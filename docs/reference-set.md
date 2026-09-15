# The reference set

A fixed, small set of real videos spanning the difficulty classes, assembled for
[issue #4](https://github.com/henricos/extract-slides/issues/4).

**These are videos to watch the tool against, not a measured benchmark.**
[ADR 0004](adr/0004-capture-generously-delete-afterwards.md) ended the ground-truth and
correctness-metric path: nothing is scored against these, and the way to know a stage is
not losing captures is to watch one of them and compare it with the output. They were
chosen to span the cases that break naive detectors, and that is exactly what still makes
them worth having.

The method that found it, and the rules for finding more, are in
[`tools/candidates/CALIBRATION.md`](../tools/candidates/CALIBRATION.md) and
[`docs/reference-set-method.md`](reference-set-method.md).

## Difficulty classes

Six classes, revised from the eight originally sketched. Two revisions matter:

- **`C2a` and `C2b` are different problems.** `C2a` is the speaker's webcam overlaid on
  a full-frame slide; `C2b` is the slide genuinely inset in a smaller box. The operator
  ruled that **overlap by the presenter is acceptable in the output** — the deliverable
  is a record of the slide's information, not a re-presentable deck — so `C2a` is a
  *detection* problem (the moving webcam causes false transitions), not a crop problem.
  Only `C2b` requires cropping.
- **`C6` (pt-BR audio) was dropped as a composition criterion.** Portuguese is a
  high-resource language for Whisper and beats English on Common Voice from `small`
  upward (`docs/research/stt-cpu.md`), so it sets no floor worth designing the set
  around.

| Class | What it stresses |
|---|---|
| `C1` | Slide fills the frame, no speaker. The baseline: a detector that fails here is broken. |
| `C2a` | Webcam overlaid on the slide. Detection: the moving overlay causes false transitions. |
| `C2b` | Slide inset in a smaller box. The case that motivates the crop stage. |
| `C3` | Progressive build. Dedupe: a five-bullet build is how many distinct slides? |
| `C4` | Video or animation inside the slide. The detector's worst case for false positives. |
| `C5` | Camera cuts between speaker and slide feed. The slide leaves the screen and returns. |
| `C7` | A camera films the scene; the slide is on a screen in the background, at an angle. |

`C7` is **in scope without perspective correction**. The bar is "captured the slide's
content legibly, even keystoned, even dirty". Dewarping is not required.

## Tier 1 — sweep fixtures

Short, cheap, re-run on every spike iteration and every parameter sweep. Every entry was
verified frame-by-frame by a strong model, not by the cheap screening pass.

| Class | id | Duration | Best ≤1080p | Subject | Why it is in the set |
|---|---|---|---|---|---|
| `C1` + `C3` | `pJc0l2DASpo` | 8m47 | 480p30 | software architecture | Full-frame slides, no speaker at all, and the diagrams build element by element. 480p is a free low-resolution stress case. |
| `C2b` | `jqpdveK2XAU` | 4m16 | 720p30 | containers | Slide left, speaker as a vertical strip right, conference branding, **plus letterbox bars** — the recall-safe crop floor from `docs/research/slide-region-crop.md`. |
| `C2b` unstable | `b9dBJnQ_kpo` | 5m00 | 1080p50 | DevOps | **The layout changes mid-video** — speaker-left/slide-right, then slide alone, at different sizes. Attacks "compute the region once per layout-stable segment" directly. |
| `C4` | `2AWv_nIfp-U` | 11m34 | 1080p30 | graphics research | Rendered result footage plays *inside* the slide, plus a step-by-step algorithm animation, plus a tiny corner webcam. The most severe false-transition case found. |
| `C5` | `YBH8rQv4aTQ` | 10m59 | 1080p30 | AI in education | Cuts between stage camera angles and full-frame slides, and the slides build. |
| `C7` | `X3uFwLj2u7Q` | 5m19 | 1080p50 | DevOps | Dark auditorium, camera on the stage, slide on a large screen behind — and **legible**, unlike every other `C7` candidate found. |

**Total 45m55, ≈209 MiB** at best ≤1080p.

### The transcript paths are covered by accident

Not designed, but measured and worth keeping. All three branches appear in tier 1:

| Path | Videos |
|---|---|
| ASR `-orig` caption | `pJc0l2DASpo`, `jqpdveK2XAU`, `2AWv_nIfp-U` |
| **Manual caption only, no ASR** | `b9dBJnQ_kpo` (`en`), `YBH8rQv4aTQ` (14 human tracks) |
| **No caption at all → local STT** | `X3uFwLj2u7Q` |

`X3uFwLj2u7Q` closes a gap nobody had ticketed: without a caption-less *talk*, the STT
fallback in `docs/research/stt-cpu.md` is never exercised end to end. The negative
controls in `docs/research/youtube-captions.md` were music videos, useless for slides.

The manual-only pair matters because manual tracks carry **no word timings**
(`docs/research/youtube-captions.md`), only cue-level, so these two exercise the
coarse-timing branch of the pairing rule owned by
[#14](https://github.com/henricos/extract-slides/issues/14).

## Tier 2 — final validation

Run once, at the end, to confirm the result is actually useful. Not swept.

| Role | id | Duration | Best ≤1080p | Note |
|---|---|---|---|---|
| Target corpus, and the `C2a` fixture | `4Z4ie_MQOTw` | 11m46 | 1080p30 | Full-frame slide, circular webcam overlaid bottom-right, **plus burned-in subtitles** that change every phrase while the slide is still — an unforeseen dedupe hazard. |
| Target corpus | `YDAxITCNcko` | 5m04 | 1080p30 | Manual `en`+`ko`, **zero** automatic captions. |
| Target corpus | `VGN22pPpb-8` | 11m06 | 1080p60 | 21 `-orig` tracks (see below). |
| Target corpus | `Sir59K8ZDPU` | 21m18 | 1080p60 | 21 `-orig` tracks. |
| Target corpus | `VH9uBxLJx30` | 83m59 | 1080p25 | The long one. Excluded from sweeps on cost. |
| `C1` + `C3`, accessible subject | `N7bb3iUp1aI` | 24m57 | 480p30 | Pathology webinar. Clean full-frame medical deck with clear bullet-and-image builds, on a subject a non-specialist can follow, which is what makes it usable for checking the output by eye. |

**Total 158m10.** The five target-corpus videos are the operator's real material, chosen
for subject, not as difficulty fixtures. Those two jobs conflict, so each row above says
which it is.

## PO-token exposure baseline

Required by this ticket. Every video in both tiers whose ASR track could be probed
returned `exp=none` in its `timedtext` URL — **0 of the set is in the PO-token rollout**
as of 2026-09-10. `docs/research/youtube-captions.md` measured the gate as a partial
rollout; this set is entirely outside it. Re-check if caption fetches start failing.

## Correction to the caption research

`docs/research/youtube-captions.md` §"Track selection: the `-orig` handle" assumes one
real ASR track per video, identified by its `-orig` suffix, plus machine translations.
**Two videos here carry 21 different `-orig` tracks** (`ar-orig`, `bn-orig`, `en-orig`,
`pt-BR-orig`, …): `VGN22pPpb-8` and `Sir59K8ZDPU`.

This is YouTube multi-language audio — each dubbed audio track gets its own ASR — so
`-orig` is **not a unique handle**. Picking "the `-orig` track" is ambiguous on such a
video, and the choice has to be driven by the video's audio language rather than by the
suffix. This lands on [#14](https://github.com/henricos/extract-slides/issues/14).

### It did not reproduce, five days later

**Re-measured 2026-09-15**, same host and the same `yt-dlp` 2026.07.04: both videos now
carry **one** `-orig` track (`en-orig`) out of 157 automatic captions, no manual track, a
top-level `language` of `en`, and a single audio format marked `en-US` /
*"English (US) original (default)"*. Either YouTube withdrew the dubbing from these two, or
the reading above came from a different extractor client.

The observation is kept because it may well come back, and because of what looking again
exposed: **`yt-dlp` states which audio track is the original**, at the top level and on the
format. That is a handle `docs/research/youtube-captions.md` never used, and it is what
[ADR 0009](adr/0009-the-output-contract-a-table-of-instants.md) selects on — with local STT
as the fall-through when it is absent or ambiguous.

## Rejected candidates worth remembering

| id | Why rejected |
|---|---|
| `Z-PA3Pohp7Q`, `CRQSrIWX81k` | `C7`, but the projection screen is blown out by stage lighting. Illegible. |
| `3TLjFhv9IRk`, `cDdLZO7ET_I`, `74YwR4EFdYk` | Editor screencasts, not presentations. Ribbon, thumbnail rail, "Click to add title". |
| `l8xiNOCIdLY`, `VTxJbUPhRJw` | Slide rendered too small inside a composed layout. Illegible. |
| `kQ_LaoWYsyw`, `q7R8VUhbzQs`, `bxDObdH2YSc` | No slides: meetup vlog, bare terminal demo, interview. |
| `w9suOaHITtk` | Good `C4`-like live browser demo on an accessible subject, but the content panel is ~40% of the frame. Kept as the `C4` runner-up. |
