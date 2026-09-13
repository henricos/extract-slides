# PROTOTYPE — the STT stage (issue #13)

Throwaway. Run it, read the numbers, throw it away. The decision it settles belongs in an
ADR, not here.

    ./batch.sh main b9dBJnQ_kpo      # every candidate, strictly sequential
    python wer.py b9dBJnQ_kpo        # rank them against the human caption

## The question

Which model and runtime transcribes a talk on the target host, and what does it cost?

Local speech-to-text is the **minority path**: `docs/research/youtube-captions.md` found a
ready ASR caption on 9 of 9 sampled talks, so this stage runs only when the video is not
on YouTube, has no caption at all, or the operator asks for better than YouTube gives.
That is why a slow answer is still an acceptable answer.

## What it measures

One candidate per process, so the peak RSS each one reports is its own. The batch is
strictly sequential — two physical cores, and a second job would corrupt every number.

- **Cost**: wall clock split into model load and transcription, expressed as minutes of
  work per hour of audio, plus peak RSS and model download size.
- **Quality**: word error rate against YouTube's **manual** caption, which costs the
  operator nothing to have. A human caption is edited for reading rather than transcribed
  verbatim, so these numbers rank candidates against each other; they are not absolute WER.
- **Timestamps**: whether the winner's word times are good enough to pair speech with
  slides, and what asking for them costs.

## Fixtures

English only — settled with the operator while resolving the ticket, because the reference
set has no pt-BR video and his own corpus is entirely in English.

| id | length | why |
|---|---|---|
| `b9dBJnQ_kpo` | 5m00 | Has a **manual** caption: the quality reference. Conference stage audio. |
| `X3uFwLj2u7Q` | 5m19 | **No caption at all** — the real reason this stage exists. Dark auditorium, hard audio, no reference to score against: read it. |
| `-FOCpMAww28` | 7m57 | Not a slide fixture. The only way to ask **"is local STT better than the free YouTube caption?"** — it is the one talk found carrying a human caption *and* an ASR caption, so both can be scored against the same reference. |

## Files

- `run_one.py` — one candidate, one audio file, one metrics row on stdout.
- `batch.sh` — the candidate list.
- `wer.py` — scores every transcript in `out/spike-stt/<id>/` against the human caption.
- `timing.py` — the word clock against the caption clock, for the pairing question.
- `predownload.py` — fetches the Whisper weights ahead of the timed batch, so a download
  never lands inside a measurement.

## Run over the fixtures (23 min of audio, 2026-09-13)

Cost, on the target host — `int8`, 2 threads, VAD, beam 5:

| candidate | min per hour of audio | peak RSS | on disk |
|---|---|---|---|
| `sherpa-onnx` + Parakeet TDT 0.6B int8 | 8 | 1.3 GB | 641 MB |
| **`small`** | **17–18** | **1.2–1.6 GB** | **464 MB** |
| `medium` | 43–54 | 2.7–3.4 GB | 1.5 GB |
| `large-v3-turbo` | 53–62 | 2.3–2.7 GB | 1.6 GB |

Word error rate against the human caption:

| | TED 7m57 | conference 10m59 | Danish accent 5m00 |
|---|---|---|---|
| `small` | **3.6 %** | **1.4 %** | **11.1 %** |
| `medium` | 4.4 % | 1.4 % | 11.4 % |
| `large-v3-turbo` | 10.1 % | 1.2 % | 11.3 % |
| Parakeet | 4.4 % | 2.5 % | 15.6 % |
| YouTube's own ASR | 4.3 % | — | — |

Levers: `cpu_threads=4` is 18 % *slower* than 2; VAD saves 0.8 %, which is noise; word
timestamps are free; `beam_size=1` is 40 % cheaper and 0.0–0.7 points worse.

Two things the numbers only showed after looking at the text:

- `large-v3-turbo` emitted **nine segments and 73 words past the end of the audio**, fluent
  and invented. Clipping at the audio's end takes it from 10.1 % to 4.2 %.
- `b9dBJnQ_kpo`'s **manual** caption is 676 s long for a 300 s video and contains the next
  speaker's talk from 293 s on.

Settled in [ADR 0007](../../docs/adr/0007-transcribe-with-small-and-trust-the-media-clock.md).
