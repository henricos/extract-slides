# Transcription: the small model, and the media clock as the authority

- **Status:** accepted
- **Date:** 2026-09-13
- **Ticket:** [#13 — Spike: choose the STT model and runtime on the target host](https://github.com/henricos/extract-slides/issues/13)
- **Builds on:** [ADR 0001](0001-python-runtime-for-the-cli.md) (Python, wheels only), [ADR 0002](0002-cli-surface.md) (the `transcribe` stage)

## Decision

**The runtime is `faster-whisper` on CTranslate2**, `device="cpu"`, `compute_type="int8"`,
`cpu_threads=2`, `vad_filter=True`, `beam_size=5`, `word_timestamps=True`.

**The model is `small`.** Not `medium`, which the research named as the quality knee.
`medium` stays reachable through a `--model` flag as the quality opt-in, and pt-BR is the
case most likely to need it — see *What this decision does not decide*.

**Two guards, one rule: the media's own duration is the authority on time.**

- **Discard any transcript segment that starts at or after the end of the audio.** A model
  can emit fluent, grammatical, entirely invented speech past the end of the media, with
  plausible timestamps.
- **Reject a caption track whose last cue ends past the end of the video**, by more than a
  couple of seconds. A caption file is not guaranteed to belong to the video it is attached
  to — including a *manual* one.

**Local transcription is allowed to overrule the YouTube caption** (`--force-stt`, per
ADR 0002), because it measured better than YouTube's own ASR on the one talk where both
exist.

Rejected: `large-v3-turbo`, `sherpa-onnx` + Parakeet TDT 0.6B v3, `whisper.cpp`, `tiny`,
`base`, greedy decoding as the default, and `cpu_threads=4`.

## Why

### `small` is not a compromise on this host — `medium` simply did not buy anything

Word error rate against YouTube's **manual** caption, three English talks, 23 minutes:

| | TED, studio (7m57) | conference, clear (10m59) | conference, Danish accent (5m00) | cost |
|---|---|---|---|---|
| `small` | **3.6 %** | **1.4 %** | **11.1 %** | **18 min/h** |
| `medium` | 4.4 % | 1.4 % | 11.4 % | 48–54 min/h |
| `large-v3-turbo` | 10.1 % | 1.2 % | 11.3 % | 53–62 min/h |
| Parakeet TDT 0.6B | 4.4 % | 2.5 % | 15.6 % | 8 min/h |
| YouTube's own ASR | 4.3 % | — | — | free |

`medium` is **three times the cost of `small` and never once better than it**. That is the
whole argument. `docs/research/stt-cpu.md` ranked `medium` first on the strength of
Whisper's published pt/en benchmark tables, which are read and prepared speech; on
spontaneous talk audio scored against an edited human caption, the gap the tables promise
does not appear. The research's own §8.9 predicted exactly this blind spot — *"no pt-BR WER
on spontaneous speech for any Whisper size"* — and the same hole turns out to exist for
English.

**Read these as a ranking, not as absolute WER.** A human caption is edited for reading, so
part of every number above is the caption's own paraphrasing, which is why the three
columns differ so much more than the rows do. That is also the point: **the fixture
dominates the model.** Choosing a model buys tenths of a point; the audio decides the rest.

### The most expensive model invented 73 words after the audio ended

`large-v3-turbo` on the TED talk emitted **nine segments past the 476.6 s end of the
audio**, running to 498 s — fluent, punctuated, and wholly fabricated:

> `490.3` *If we've missedTodd estimate, we have the potential ved scholar to advise.*
> `497.3` *Teresa V ridden.*

Clipping the output at the end of the audio takes its error from **10.1 % to 4.2 %**:
*every* bit of its quality deficit was hallucination past the end. Its substitution count
inside the audio is the best of the field (9, against `small`'s 15) — the model hears well
and then keeps talking.

**VAD did not prevent it.** That run had `vad_filter=True`. The research called VAD the
largest documented CPU saving; on this evidence its real value is neither speed (measured
at 0.8 % here, below noise) nor hallucination safety, and it is kept only because it costs
nothing.

`small` did it once, for two words. `medium` never did it. But no model is trusted on this
point, which is why the guard is a pipeline rule rather than a reason to prefer one model.

### A human caption lied about which talk it was

`b9dBJnQ_kpo` is a 300-second lightning talk. Its **manual** English caption track runs to
**676 seconds**, and from 293 s onward it contains *the next speaker's talk*. Nothing in
the file says so.

This is the more serious of the two findings, because it hits the **primary** transcript
path rather than the fallback: `docs/research/youtube-captions.md` found a ready caption on
9 of 9 sampled talks and the pipeline prefers it over transcribing. Here a caption that is
not machine-generated, not translated, and not flagged in any way silently carries six
minutes of a different talk. Of the four caption files fetched for this spike, three agree
with their video's duration to within 2 seconds and one overruns by 376.

Both failures — the model's and the caption's — are the same shape and take the same
three-line guard: **the media's duration is the authority, and anything stamped past it is
not real.** That symmetry is why this ADR states it once as a rule rather than twice as a
workaround.

### Local transcription earns the right to overrule the free caption

Only one talk could answer this, because it needs a video carrying a human caption *and* an
ASR caption, and no fixture in the reference set has both. On the TED talk: YouTube's ASR
scores **4.3 %**, local `small` scores **3.6 %**. Slim, one data point, and enough to say
`--force-stt` is not a placebo.

### Parakeet is six times faster and still loses

`sherpa-onnx` + Parakeet TDT 0.6B v3 int8 transcribes an hour of audio in **8 minutes** —
better than twice as fast as `small`, in 1.3 GB. It is genuinely good: on the hard
auditorium fixture its text is indistinguishable from Whisper's by eye, and it alone caught
the opening *"Hi,"*. It is rejected anyway, on three counts that compound:

- **It is consistently the worst of the field on quality**, and the gap widens exactly where
  it hurts: 15.6 % against `small`'s 11.1 % on the accented speaker.
- **Its Portuguese is unmeasured and flagged European** by NVIDIA's own model card, and this
  spike measured no pt-BR at all. Adopting it would take a documented risk on a language
  nobody has tested here.
- **It would need its own segmentation built.** It exposes per-token timestamps, but no
  segments; the spike windowed the audio at 30 s and got 10–22 blocks for a whole talk,
  against Whisper's 200-plus native segments with word times.

Cost is not the binding constraint here — 18 minutes per hour of audio sits far inside the
operator's stated ceiling of two hours. Parakeet is the documented answer if that ever
changes, and the note about its Portuguese travels with it.

### `whisper.cpp` never reached the starting line

It reads WAV and nothing else, and Docker — which would have supplied the official image
with `ffmpeg` — is not available inside the working container. Entering the comparison would
have meant compiling it, which is what [ADR 0001](0001-python-runtime-for-the-cli.md) exists
to avoid. `faster-whisper` reads YouTube's DASH m4a directly through the PyAV wheel it
already ships, in about a second for five minutes of audio. The floor candidate lost to
plumbing, not to accuracy.

### The two cheap levers, measured

- **`cpu_threads=4` is 18 % slower than `cpu_threads=2`** (63.5 vs 53.7 min/h on `medium`).
  CTranslate2's "do not exceed physical cores" guidance, confirmed on this CPU.
- **Greedy decoding (`beam_size=1`) is 40 % cheaper and slightly worse**: `small` drops from
  18 to 11 min/h, and loses 0.0 / 0.5 / 0.7 points on the three fixtures. It won on the
  first fixture tried, which is why it was measured on all three — that win was noise. Both
  fit the time budget, so quality takes it. This is the lever to pull if a long video ever
  needs to finish sooner.

## What this produced

On the target host (i3-4170, 2 cores / 4 threads, no GPU), `small` int8, 2 threads, VAD,
beam 5:

| | measured |
|---|---|
| Transcription cost | **17–18 minutes per hour of audio** (RTF 0.28–0.30), stable across all four fixtures |
| A 45-minute talk | about **13 minutes** |
| Peak RSS | **1.2–1.6 GB** (`medium` 2.7–3.4 GB, `turbo` 2.3–2.7 GB) |
| Model on disk | **464 MB** (`medium` 1.5 GB, Parakeet 641 MB) |
| Offline | **Yes** — verified with `HF_HUB_OFFLINE=1`; downloads once into a cache directory |
| Word timestamps | **Free** — 17.5 vs 18.1 min/h, within noise |
| Install | 23 wheels, **no compilation, 6 seconds** |

**The word clock is good enough for pairing, by a wide margin.** Against the human caption's
own cue times, matching on the opening trigram of each cue: median offset **−0.01 s** and
**−0.08 s** on the two fixtures, with **96–99 % of cues within half a second**. Slides are
tens of seconds apart. Timestamp quality is not a constraint on the pairing rule that
[#14](https://github.com/henricos/extract-slides/issues/14) owns.

**One packaging defect, for [#15](https://github.com/henricos/extract-slides/issues/15):**
`faster-whisper` 1.2.0 imports `requests` and does not declare it. A clean install fails on
first use. It must be pinned explicitly alongside.

## Consequences

- The transcript stage costs **a fifth of real time**, so a talk transcribes in a fraction of
  its length and resumability is a convenience rather than a necessity for this stage. The
  detect stage runs at 6 % of real time ([ADR 0005](0005-pass-1-pinned-anchor-edge-signal-watchdog.md));
  together they put a 45-minute talk at roughly **16 minutes end to end**, on the path where
  no caption exists. Where a caption exists, the pipeline is dominated by detection alone.
- **Peak memory is 1.6 GB**, against ~10 GB free on the host. Nothing about this choice
  strains the machine, and both `medium` (3.4 GB) and the rejected candidates would also
  have fit — memory never entered the decision.
- **Two duration guards enter the pipeline**, one on the caption path and one on the STT
  path. They are cheap, and the caption one protects the path the tool takes most often.
- **`--force-stt` has a measured basis**, and the number to beat is YouTube's, not zero.
- **The model is a flag, not a lock-in.** `small` is the default; `medium` is one flag away
  and costs three times as much for no measured English gain.

## What this decision does not decide

- **Portuguese is unmeasured.** The operator ruled pt-BR out of this spike: the reference set
  has no pt-BR video and his own corpus is entirely English. The exposure is narrow but real
  — Whisper is one multilingual model, so choosing `small` for English chooses it for
  Portuguese too, and `docs/research/stt-cpu.md` §1 puts `small` at the pt **floor** (CV9
  12.5) with `medium` at the **knee** (8.1). English measured no difference between the two;
  Portuguese, on published numbers, would. **If a pt-BR video ever disappoints, `--model
  medium` is the first thing to try**, and the quality claim for it there is untested here.
  This is the one place where the rejected candidate might still be right.
- **Whether Parakeet's Portuguese is usable.** Untested, and flagged European by its vendor.
- **Which caption track to pick** on a video with 21 `-orig` tracks, and what the transcript
  looks like in the output — [#14](https://github.com/henricos/extract-slides/issues/14).
- **The pairing rule itself.** This ADR only establishes that the clock is accurate enough
  not to constrain it.
- **How the model is fetched and cached in a shipped install** — [#15](https://github.com/henricos/extract-slides/issues/15).

## The prototype

[`prototype/stt`](https://github.com/henricos/extract-slides/tree/prototype/stt) —
`prototypes/stt/`, throwaway. `run_one.py` (one candidate, one audio file, one metrics row),
`batch.sh` (the candidate list), `wer.py` (scoring, with the caption-overrun clip),
`timing.py` (word clock against the caption clock). Raw transcripts and metrics under
`out/spike-stt/`.
