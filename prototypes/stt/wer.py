"""PROTOTYPE (issue #13) — word error rate of each candidate against a human caption.

Throwaway. The reference is YouTube's *manual* caption track, so it costs the operator
nothing to have (ADR 0004: no hand-built ground truth). It is not perfect either — a human
caption is edited for reading, not a verbatim transcript — so read these numbers as a
ranking between candidates, not as an absolute WER.

    python wer.py <video-id>
"""

import json
import re
import sys
from pathlib import Path

CACHE = Path("/home/developer/github/henricos/extract-slides-cache")
OUT = Path("/home/developer/github/henricos/extract-slides/out/spike-stt")

# Whisper writes "16", Parakeet writes "sixteen", and a human caption picks whichever it
# likes. Without folding the two spellings together the comparison scores a formatting
# convention as a transcription error.
UNITS = "zero one two three four five six seven eight nine ten eleven twelve thirteen \
fourteen fifteen sixteen seventeen eighteen nineteen".split()
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
        "seventy": 70, "eighty": 80, "ninety": 90}
WORD_TO_NUM = {w: i for i, w in enumerate(UNITS)}
WORD_TO_NUM.update(TENS)


def norm(text):
    text = text.lower()
    text = text.replace("’", "'").replace("‐", "-").replace("–", " ").replace("—", " ")
    text = re.sub(r"\[[^\]]*\]", " ", text)      # [Music], [Applause]
    text = re.sub(r"<[^>]*>", " ", text)
    text = re.sub(r"[^a-z0-9'\s]", " ", text)
    words = []
    for w in text.split():
        w = w.strip("'")
        if not w:
            continue
        words.append(str(WORD_TO_NUM[w]) if w in WORD_TO_NUM else w)
    # "twenty five" and "25" should also agree
    fused = []
    for w in words:
        if fused and fused[-1].isdigit() and w.isdigit():
            a, b = int(fused[-1]), int(w)
            if a in TENS.values() and 1 <= b <= 9:
                fused[-1] = str(a + b)
                continue
        fused.append(w)
    return fused


def caption_text(path, limit_s=None):
    """Text of a json3 caption, clipped to limit_s.

    The clip is not paranoia. `b9dBJnQ_kpo` is a 300 s lightning talk whose *manual*
    caption runs to 676 s and carries the next speaker's talk from 293 s on — a human
    caption that does not belong to the video it is attached to.
    """
    d = json.loads(Path(path).read_text())
    parts, last = [], 0.0
    for ev in d.get("events", []):
        if "segs" not in ev:
            continue
        t = ev.get("tStartMs", 0) / 1000.0
        last = max(last, t + ev.get("dDurationMs", 0) / 1000.0)
        if limit_s is not None and t > limit_s:
            continue
        for seg in ev.get("segs", []) or []:
            parts.append(seg.get("utf8", ""))
    return " ".join(parts), last


def wer(ref, hyp):
    # Levenshtein over words, O(len(ref) * len(hyp)) with a rolling row
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h))
        prev = cur
    return prev[-1] / max(1, len(ref))


def audio_seconds(vid):
    """Duration of the candidates' own view of the audio, from any metrics row."""
    for f in sorted((OUT / vid).glob("*.json")):
        return json.loads(f.read_text())["metrics"]["audio_s"]
    return None


def main():
    vid = sys.argv[1]
    ref_path = CACHE / "captions" / f"{vid}.en.json3"
    if not ref_path.exists():
        print(f"no human caption for {vid}")
        return
    audio_s = audio_seconds(vid)
    text, caption_end = caption_text(ref_path, limit_s=audio_s)
    ref = norm(text)
    print(f"reference: {ref_path.name}, {len(ref)} words")
    print(f"audio {audio_s:.0f} s, caption ends {caption_end:.0f} s", end="")
    print(f"  — OVERRUN {caption_end - audio_s:+.0f} s, clipped\n" if caption_end - audio_s > 5 else "\n")
    rows = []
    # YouTube's own ASR, where the video carries both tracks: the bar local STT has to beat
    asr_path = CACHE / "captions" / f"{vid}.asr.en-orig.json3"
    if asr_path.exists():
        asr_text, _ = caption_text(asr_path, limit_s=audio_s)
        asr = norm(asr_text)
        rows.append((wer(ref, asr), "** YouTube ASR caption **", len(asr)))
    for f in sorted((OUT / vid).glob("*.txt")):
        hyp = norm(f.read_text())
        rows.append((wer(ref, hyp), f.stem, len(hyp)))
    for w, tag, n in sorted(rows):
        print(f"{w*100:6.1f} %   {tag:42s} {n} words")


if __name__ == "__main__":
    main()
