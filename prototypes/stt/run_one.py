"""PROTOTYPE (issue #13) — run one STT candidate over one audio file and report the cost.

Throwaway. One candidate per process, so the peak RSS it reports is its own.

    python run_one.py --runtime fw --model medium --threads 2 --vad --audio <id>

Writes out/spike-stt/<id>/<tag>.json (transcript + metrics) and prints the metrics row
as JSON on stdout.
"""

import argparse
import json
import os
import resource
import time
from pathlib import Path

CACHE = Path("/home/developer/github/henricos/extract-slides-cache")
OUT = Path("/home/developer/github/henricos/extract-slides/out/spike-stt")


def peak_rss_mb():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def run_faster_whisper(audio, args):
    from faster_whisper import WhisperModel

    t0 = time.monotonic()
    model = WhisperModel(
        args.model,
        device="cpu",
        compute_type=args.compute_type,
        cpu_threads=args.threads,
        download_root=str(CACHE / "models" / "faster-whisper"),
    )
    load_s = time.monotonic() - t0

    t1 = time.monotonic()
    segments, info = model.transcribe(
        audio,
        language=args.language,
        beam_size=args.beam,
        vad_filter=args.vad,
        word_timestamps=args.words,
    )
    # the generator is lazy: this loop is the actual work
    out = []
    for s in segments:
        row = {"start": round(s.start, 3), "end": round(s.end, 3), "text": s.text}
        if args.words and s.words:
            row["words"] = [
                {"w": w.word, "s": round(w.start, 3), "e": round(w.end, 3)} for w in s.words
            ]
        out.append(row)
    work_s = time.monotonic() - t1
    return out, load_s, work_s, {"detected_language": info.language, "audio_s": info.duration}


def run_sherpa(audio, args):
    import sherpa_onnx

    mdir = CACHE / "models" / "sherpa" / args.model
    t0 = time.monotonic()
    recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=str(mdir / "encoder.int8.onnx"),
        decoder=str(mdir / "decoder.int8.onnx"),
        joiner=str(mdir / "joiner.int8.onnx"),
        tokens=str(mdir / "tokens.txt"),
        num_threads=args.threads,
        model_type="nemo_transducer",
        decoding_method="greedy_search",
    )
    load_s = time.monotonic() - t0

    from faster_whisper.audio import decode_audio  # shared decoder, so the comparison is fair

    samples = decode_audio(audio, sampling_rate=16000)

    t1 = time.monotonic()
    # sherpa's offline recognizer has no internal chunking: feed it in windows so RAM stays sane
    window = int(16000 * args.sherpa_window)
    out = []
    for off in range(0, len(samples), window):
        chunk = samples[off : off + window]
        if len(chunk) < 1600:
            break
        stream = recognizer.create_stream()
        stream.accept_waveform(16000, chunk)
        recognizer.decode_stream(stream)
        r = stream.result
        base = off / 16000.0
        if r.text.strip():
            ts = list(r.timestamps) if r.timestamps else []
            out.append(
                {
                    "start": round(base + (ts[0] if ts else 0.0), 3),
                    "end": round(base + (ts[-1] if ts else len(chunk) / 16000.0), 3),
                    "text": r.text,
                }
            )
    work_s = time.monotonic() - t1
    return out, load_s, work_s, {"detected_language": "n/a", "audio_s": len(samples) / 16000.0}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--runtime", required=True, choices=["fw", "sherpa"])
    p.add_argument("--model", required=True)
    p.add_argument("--threads", type=int, default=2)
    p.add_argument("--compute-type", default="int8")
    p.add_argument("--beam", type=int, default=5)
    p.add_argument("--language", default="en")
    p.add_argument("--vad", action="store_true")
    p.add_argument("--words", action="store_true")
    p.add_argument("--sherpa-window", type=float, default=30.0)
    p.add_argument("--audio", required=True, help="video id in the fixture cache")
    p.add_argument("--tag", default=None)
    a = p.parse_args()

    os.environ.setdefault("OMP_NUM_THREADS", str(a.threads))
    audio = str(CACHE / "audio" / f"{a.audio}.m4a")

    tag = a.tag or f"{a.runtime}-{a.model}-t{a.threads}-{'vad' if a.vad else 'novad'}" + (
        "-words" if a.words else ""
    )

    runner = run_faster_whisper if a.runtime == "fw" else run_sherpa
    t_all = time.monotonic()
    segs, load_s, work_s, info = runner(audio, a)
    total_s = time.monotonic() - t_all

    text = " ".join(s["text"].strip() for s in segs)
    metrics = {
        "tag": tag,
        "runtime": a.runtime,
        "model": a.model,
        "threads": a.threads,
        "compute_type": a.compute_type if a.runtime == "fw" else "int8",
        "vad": a.vad,
        "words": a.words,
        "audio_id": a.audio,
        "audio_s": round(info["audio_s"], 1),
        "load_s": round(load_s, 1),
        "work_s": round(work_s, 1),
        "total_s": round(total_s, 1),
        "rtf": round(work_s / info["audio_s"], 3),
        "min_per_hour_audio": round(work_s / info["audio_s"] * 60, 1),
        "peak_rss_mb": round(peak_rss_mb()),
        "segments": len(segs),
        "words_out": sum(len(s.get("words", [])) for s in segs),
        "chars": len(text),
    }

    d = OUT / a.audio
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{tag}.json").write_text(
        json.dumps({"metrics": metrics, "segments": segs}, ensure_ascii=False, indent=1)
    )
    (d / f"{tag}.txt").write_text(text)
    print(json.dumps(metrics))


if __name__ == "__main__":
    main()
