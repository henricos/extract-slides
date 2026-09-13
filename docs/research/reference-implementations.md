# What the reference implementations actually do

> **Read under [ADR 0004](../adr/0004-capture-generously-delete-afterwards.md).** This
> document was written while the project still planned to rank candidates against a
> hand-labelled ground truth. That path was ended: the tool now captures generously in one
> automatic pass and the excess is deleted in a second, and there is no metric. **The facts
> and citations below stand; the verdicts that read as "measure this against that" should be
> read as "this is the technique, tune it toward over-capture".** Wherever a passage weighs
> candidates by misses and surplus, the ranking no longer happens — but the reason a
> technique loses captures is exactly what still matters.

Research for [issue #19](https://github.com/henricos/extract-slides/issues/19), gathered September 2026.
**Facts and citations only** — the choices belong to the spikes it feeds:
[#11](https://github.com/henricos/extract-slides/issues/11) (detection and dedupe),
[#12](https://github.com/henricos/extract-slides/issues/12) (crop),
[#17](https://github.com/henricos/extract-slides/issues/17) (slide-frame gate) and
[#14](https://github.com/henricos/extract-slides/issues/14) (output contract and pairing).

`docs/similar-tools.md` catalogues *which* projects exist. `docs/research/slide-change-detection.md`
and `docs/research/slide-region-crop.md` surveyed them from their documentation, published numbers
and READMEs. **This document reads their source.** Every claim below carries a file, a line, and a
permalink pinned to the commit that was cloned; where a README and its code disagree, the code wins
and the disagreement is recorded.

A finding earned its place here only by saying what to do differently in one of those four tickets.
Where a project contributes nothing to a stage, that is written down as a negative finding rather
than left out.

## What was read

Clones live in the cache, never in the repo: `extract-slides-cache/reference-implementations/`
(a sibling of the repo, per that cache's `README.md` — `~/.cache` is on the container's overlay
filesystem and is lost on rebuild).

| Repo | sha | Last commit | Licence | Read for |
|---|---|---|---|---|
| [`larry-xue/video-slide-extractor`](https://github.com/larry-xue/video-slide-extractor) | `221454d` | 2026-09-06 | MIT | Otsu calibration, activity mask, its own benchmark |
| [`larry-xue/awesome-video-to-slides`](https://github.com/larry-xue/awesome-video-to-slides) | `d1e9092` | 2026-08-29 | repo `LICENSE` | index sweep, the "product benchmark" |
| [`bit-admin/AutoSlides-Extractor`](https://github.com/bit-admin/AutoSlides-Extractor) | `e0899cd` | 2026-08-08 | MIT (weights: **none stated**) | SSIM, verification window, pHash exclusion list, ML gate, auto-crop |
| [`Breakthrough/PySceneDetect`](https://github.com/Breakthrough/PySceneDetect) | `2fa8290` | 2026-09-12 | BSD-3-Clause | edge path, FlashFilter, `--stats`, packaging |
| [`kovitking/video2slides`](https://github.com/kovitking/video2slides) | `2e16e89` | 2026-07-28 | **none** | PiP detection and masking, stability window |
| [`sumerene/video2slides`](https://github.com/sumerene/video2slides) | `65b2a77` | 2026-04-20 | MIT | dual-hash AND rule, Laplacian gate, manual ROI |
| [`binh234/video2slides`](https://github.com/binh234/video2slides) | `ceaf516` | 2024-03-15 | MIT | hysteresis settle detector |
| [`patrickmineault/vid2slides`](https://github.com/patrickmineault/vid2slides) | `6212116` | 2020-11-22 | **none** | the only surveyed attempt at a slide region |
| [`asindel/SliTraNet`](https://github.com/asindel/SliTraNet) | `994c3fa` | 2023-12-17 | **MIT** (weights: none stated) | the learned end of the space |
| [`m2kar/video2slides`](https://github.com/m2kar/video2slides) | `d3bb704` | 2024-12-01 | MIT | the only prior art for slide↔speech pairing |
| [`AnuragSingh2101/Video2Slides`](https://github.com/AnuragSingh2101/Video2Slides) | `ac298c2` | 2026-08-05 | **none** | an end-to-end pipeline with every piece |
| [`perelman/slide-detector`](https://git.aweirdimagination.net/perelman/slide-detector) (Gitea, **not** GitHub) | `93de381` | 2020-05-30 | **AGPL-3.0** | the deterministic ancestor SliTraNet failed to beat |

Three of those were not on the ticket's list. `m2kar/video2slides` and `AnuragSingh2101/Video2Slides`
are catalogued in `docs/similar-tools.md` but nobody had read their source, and `m2kar` is the only
project anywhere in the survey that pairs slide extraction with a real transcript — the open question
in #14. `perelman/slide-detector` appears in no document of this project at all; it was found in
SliTraNet's own source header, and it is the origin of the frame-differencing chain that beats
SliTraNet's CNN on recall in SliTraNet's own ablation table.

**Licence discipline.** Three of the twelve carry no licence and are therefore readable but not
copyable; they appear below as techniques and negative findings, never as code to lift. One,
`perelman/slide-detector`, is **AGPL-3.0** against this project's MIT: its techniques must be
re-implemented from the description below, never pasted — algorithms are not copyrightable, that
source is. Two repos ship model weights with no licence, model card or training-data statement at
all — usable to establish a measurement ceiling, not shippable.

## The nine findings that change a spike

Ordered by how much they change. Each links to the section that carries the evidence.

1. **One decode pass sweeps the entire detector parameter grid, and the replay is bit-exact.**
   PySceneDetect runs unlimited chained detectors per frame, a `StatsManager` forces the edge
   component to be computed even at weight 0, and the CSV stores the four *raw* components rather
   than the weighted score — so every weight vector, threshold, `min_scene_len`, filter mode and
   window width is recoverable offline. Verified rather than inferred: a 40-line replay fed only the
   CSV reproduced the library's own cut frames exactly, and `adaptive_ratio` matched on 446/446
   frames. **400 configs in 0.56 s against 107 minutes of re-decoding, for a 15-second clip.** On the
   six-video reference set, re-decoding per config is not slow, it is infeasible. This changes what
   #11 *is*: not a verdict at a handful of operating points, but the (misses, surplus) frontier as a
   function of threshold. [§C.1](#c1-one-decode-pass-sweeps-the-whole-detector-grid)

2. **The edge component is the build-recall mechanism, and it is free.** At three one-bullet reveals
   and one hard cut, measured at 1080p: `content_val` spans **814×** between a reveal and a whole-slide
   change, so no single threshold catches both — the default 27.0 is 176× too high for the build.
   `delta_edges` spans **2.4×** across the same two events and sits at exactly 0.0 on static frames.
   `--weights 0 0 0 1 --threshold 0.5` found all three builds; the defaults found none, and the
   project's own documented edge recipe (`--weights 1.0 0.5 1.0 0.2 -t 32`) also found none, because
   the `/Σ|weight|` divisor destroys the signal you turned edges on to get. The mechanism —
   auto-Canny off the luma median, dilate, mean absolute difference — is four lines, deterministic,
   and the closest thing in any surveyed repo to the TalkMiner edge superset already on the #11
   shortlist. [§C.2](#c2-the-edge-component-is-the-build-recall-mechanism)

3. **`AutoSlides-Extractor` does not use SSIM, and its famous 0.9985 is valid only for the formula it
   does use.** It is a *single-window global* correlation — one mean, variance and covariance over the
   whole 480×270 grey frame, with SSIM's C1/C2 constants. Measured on the target host, on two
   independently JPEG-encoded frames of identical content: the global formula's noise floor sits at
   0.9992–0.99996 against a weakest real signal of ≈0.96, two orders of magnitude of separation with
   0.9985 in the gap; windowed 7×7 SSIM at q50 has a noise floor of **0.9727**, *below* its own build
   signal of 0.9828. **A spike that implements SSIM as `skimage.structural_similarity` and reuses
   0.9985 because "AutoSlides uses it" measures garbage and eliminates the whole family for the wrong
   reason.** Two candidates, two sweeps. Global is also cheaper: 12.6 ms vs 23.1 ms per 1080p pair.
   [§B.2](#b2-the-change-metric)

4. **The crop stage is not greenfield after all.** `AutoSlides-Extractor` ships `AutoCropDetector`,
   552 lines: black-bar strip → Canny(20/60) → dilate → 4-vertex contours → area, margin and fill
   gates → score = `areaRatio × aspectScore` against {16:9, 4:3}, plus a single-class YOLOv8 as a
   fallback. It is `cv2`-only, deterministic, ~80 lines in Python, and a strict superset of #12's
   candidate 1. The aspect prior — *of all rectangles, prefer the large one whose aspect is closest
   to a real slide* — is a cheap, strong signal #12 did not plan for. What it lacks is the
   recall-first fallback: when no contour passes all five gates it returns nothing, where this
   project must fall back to the letterbox rect and then to the full frame.
   [§B.7](#b7-auto-crop-12-is-not-greenfield)

5. **The learned end of the space loses on the axis that declares the winner — by its authors' own
   ablation.** SliTraNet falsifies "nobody learns the change" (all three of its networks operate on
   the change; none is a slide-frame gate), and then hands over the argument against itself. Paper
   Table I, 190 minutes and 380 transitions: Gaussian-blurred frame differencing misses **15**, the
   2-D ResNet18 misses **25** — the CNN misses 67% more, buying +2.2 precision points, which under
   ADR 0003 cannot declare anything. Full pipeline: `Diff + 3-D` misses 16, the shipped all-learned
   config misses 26. SliTraNet wins only on F1, the averaging ADR 0003 refuses. Cost closes the
   question: **507 TFLOPs per 60-minute video against a host that peaks at 145 GFLOP/s** — 2.4 to 7
   hours per hour of video — with 82% of it in the stage that loses to differencing.
   [§E.2](#e2-the-authors-own-ablation-beats-their-own-cnn)

6. **The dwell-frame choice is a free fifth axis that nobody measured.** Five projects give five
   answers: middle of the run (`kovitking`), first of the run (`sumerene`), first frame after motion
   settles (`binh234`), largest JPEG in the neighbourhood (`vid2slides`), and
   `end_of_dwell − clamp(5% of dwell, 0.05 s, 0.5 s)` (`m2kar`). On a static slide all five are
   identical; on a build, a cross-fade or a slide with embedded video they pick visibly different
   images. Under (misses, surplus) they change the *content* of a capture rather than its count, and
   ADR 0003's window opens when the content is complete — which makes the tail-of-dwell answers
   structurally safer than the head-of-dwell ones. All five are computable from the same cached
   per-sample features, so measuring the axis is nearly free. [§D.6](#d6-the-hard-cases-across-all-four)

7. **Cropping changes what counts as a duplicate, which couples #11 to #12.** `AutoSlides-Extractor`
   crops and then **re-hashes and dedupes a second time**, with a code comment recording that someone
   shipped the bug of comparing cropped files against their pre-crop hashes. Two frames of the same
   slide with the speaker moved are different full-frame images and survive pHash dedupe; crop both
   to the slide region and they are identical. This project's planned order is `detect → crop → pair`,
   so it inherits exactly that surplus. #11 should measure dedupe twice — on raw frames and on frames
   cropped by #12's winner. The two spikes are currently specced as independent.
   [§B.8](#b8-crop-then-re-dedupe)

8. **The pinned anchor is the change detector and the answer to "which frame do I export", at once.**
   `perelman/slide-detector` compares every frame against a pinned anchor that advances on every
   *differing* frame, and exports **the anchor that survived the dwell** — so the exported frame is by
   construction the first settled frame after the picture stopped changing, and on a slow fade it is
   the clean pre-fade slide. No look-ahead, no re-seek, no second pass, no "grab 95 % into the scene".
   SliTraNet kept this control flow verbatim and replaced only the comparator with a CNN: the state of
   the art validated the architecture, not just the metric. Its reduction is also unmeasured here —
   `max(blur(|a−b|)) > τ` rather than the changed-pixel *fraction* every other project uses, which is
   the most recall-biased reduction available at a given τ. Two mandatory modifications before it is
   trusted: flush the pending anchor at end of file (as written it silently drops the closing slide of
   every talk — one guaranteed miss per input), and add a downscale and a stride, neither of which the
   original has. [§G.5](#g5-the-anchor-logic)

9. **The pairing rule has exactly one piece of prior art, it is 27 lines, and it is MIT.** `m2kar`
   assigns each transcript cue **whole** to the slide whose **full dwell interval** it overlaps most —
   never to the capture timestamp, never split, ties to the earlier slide. Image time and text time
   are deliberately decoupled, which is the design decision #14 should copy. Its three defects are
   what #14 must decide beyond it: an unmatched cue is silently dropped with no counter, the per-cue
   timestamps are destroyed by a `join` before reaching the output, and word timestamps are never
   requested so splitting is impossible. A fourth case it never faces: max-overlap is robust to
   over-capture, but `drop`ping a surplus slide afterwards **orphans** the cues it had won.
   [§F.1](#f1-the-pairing-rule)

## Corrections to documents already in `docs/`

The source disagrees with five things this project has written down. Each is corrected in place in
the section cited; they are collected here because they are load-bearing.

| Document | What it says | What the source says |
|---|---|---|
| `slide-change-detection.md` §9.2 | `AutoSlides-Extractor` uses SSIM at 0.999 / 0.9985 / 0.998, with a 3-sample verification window and a MobileNetV4 gate via OpenCV DNN | Not SSIM (global-statistics correlation); the presets are real but meaningless for windowed SSIM; "3 samples" is an all-must-agree look-ahead over 2 subsequent scores, not a vote; the gate runs through ONNX Runtime, on exported JPEGs in post-processing, never on video frames ([§B.0](#b0-corrections)) |
| `slide-change-detection.md` §9.4 | SliTraNet has no licence file, treat as unlicensed | It carries an **MIT** `LICENSE`, © 2022 asindel. The code is liftable; the Google-Drive weights are not covered ([§E](#group-e--asindelslitranet)) |
| `slide-change-detection.md` §9.6 | Across four systems, no prior work learns the *change*; SliTraNet is "the exception, which does classify transitions" | Far too weak: **every** SliTraNet network operates on the change and none is a slide-frame gate. The correct statement is that the one system which pointed models at the change needed three networks and a GPU, and its own ablation shows the learned front end losing on recall ([§E.1](#e1-it-does-falsify-nobody-learns-the-change)) |
| `slide-region-crop.md` (premise) | No surveyed project actually crops to the slide region | Holds for every project the crop research read, and is now confirmed against the learned state of the art too — but **`AutoSlides-Extractor` is a counter-example**: a complete, tuned, two-backend slide-bbox detector nobody had read ([§B.7](#b7-auto-crop-12-is-not-greenfield)) |
| `adr/0001-python-runtime-for-the-cli.md` | records installing `scenedetect` 0.7.1 | `scenedetect` declares the **GUI** `opencv-python`; **`scenedetect-headless`** is published on PyPI (0.7, 0.7.1), declares `opencv-python-headless`, and installs in 6 wheels with no compilation and no ffmpeg. Same `cv2` import name, two distributions, on a headless host ([§C.7](#c7-dependencies-the-video-backend-and-ffmpeg)) |

Two further corrections are smaller but worth carrying: PySceneDetect's `FlashFilter` in `MERGE`
mode emits **both** ends of a long burst rather than only the last ([§C.3](#c3-flashfilter)), and
pHash is not structurally blind to a bullet reveal — measured at 0.109–0.141 on builds against 0.242
on a hard cut, it is simply tuned about 4× too coarse ([§C.2](#c2-the-edge-component-is-the-build-recall-mechanism)).

## Measured on the target host

Several claims below were not read but run — and the machine they were run on **is** the target host:
`/proc/cpuinfo` reports `Intel(R) Core(TM) i3-4170 CPU @ 3.70GHz`, 4 threads, no GPU. They are
collected here because they are the numbers a spike would otherwise have to re-derive.

| What | Measured |
|---|---|
| Global-statistics SSIM, 1080p pair incl. both downscales | **12.6 ms** |
| Windowed 7×7 SSIM, same input | **23.1 ms** |
| `GaussianBlur(21,21)` + `absdiff` + reduce, 1080p | **4.15 ms/frame** |
| the same at 480×270 | **0.56 ms/frame** (7.4× cheaper, ~10× margin still on a bullet) |
| MobileNetV4 3-class slide gate, 256×256, via `cv2.dnn` | **22.5 ms/frame** → 61 s to gate a 45-min video at 1 fps |
| YOLOv8 single-class slide detector, 640×640, via `cv2.dnn` | **89.6 ms/frame** → ~3.6 s over ~40 exported slides |
| Peak sustained sgemm (the ceiling any learned model competes against) | **145 GFLOP/s** |
| SliTraNet, one 60-minute 1080p video | **507 TFLOPs** → 2.4–7 h |
| PySceneDetect, 1080p at `-d 1`, `detect-content` alone | 28.0 FPS |
| the same with five detectors chained and `--stats` | 10.6 FPS (~2.6×, mostly the forced Canny) |
| Offline replay of 400 detector configs from one stats CSV | **0.56 s**, against ~107 min of re-decoding |

**Two things the target host can now be said to run.** Both of `AutoSlides-Extractor`'s ONNX models
load and run correctly through `cv2.dnn`, with no ONNX Runtime and no new dependency, and the
classifier's semantics were verified rather than just its tensor shapes (synthetic slide →
`slide` 1.000; black frame → `not_slide` 0.876; noise → `may_be_slide` 0.781). That removes cost as
an argument in #17: a MobileNetV4 inference costs about the same as one windowed-SSIM comparison.
What remains against a learned gate is determinism, licensing and explicability — and the licence
question is real, because those weights carry no statement at all.

## What each ticket should do differently

The per-project verdict tables are in each section. This is the consolidated version, written as
changes to the tickets rather than as a catalogue.

### #11 — detection and dedupe

**Change the shape of the spike.** Day one is one decode pass per fixture with every detector
chained and `--stats` written, CSVs committed; from then on every threshold question is a query, not
a run ([§C.1](#c1-one-decode-pass-sweeps-the-whole-detector-grid)). Extend the same idea past
PySceneDetect's own metrics: `kovitking`'s two-pass architecture is the general form — extract every
per-sample feature once (pHash, dHash, Laplacian variance, JPEG byte size, edge density, intensity
histogram), persist a per-video feature file, and run every candidate and every threshold offline
against it ([§D.5](#d5-kovitking)). The decode is the only expensive part.

**Add to the candidate list.** The edge-only weight vector with a threshold near 1 rather than 30
([§C.2](#c2-the-edge-component-is-the-build-recall-mechanism)); global-statistics SSIM as a candidate
*separate from* windowed SSIM, each with its own sweep ([§B.2](#b2-the-change-metric)); the dual-hash
AND rule, which needs pHash-alone and dHash-alone measured beside it to mean anything
([§D.2](#d2-sumerene)); Gaussian blur (21,21) before absolute differencing, the constant from the
lineage that beat a CNN on recall ([§E.2](#e2-the-authors-own-ablation-beats-their-own-cnn)).

**Measure the pinned-anchor architecture as a candidate in its own right**, not just its metric:
compare against the anchor rather than the previous frame, advance the anchor on every differing
frame, emit the anchor that survived the dwell ([§G.5](#g5-the-anchor-logic)). Measure its reduction
separately from its comparator — `max(blur(|a−b|)) > τ` is a distinct operating point from the
changed-pixel fraction already characterised in `slide-change-detection.md` §5.3, and it is one line
of difference ([§G.4](#g4-the-differencing-core)). Its two constants come with measured caveats: the
(21,21) blur annihilates i.i.d. noise to σ=8 but **not** spatially-correlated codec blocks, which trip
τ=10 at an amplitude of 2 grey levels, and τ=10 **misses** Δ8-contrast light-on-dark text. That is one
scalar doing two jobs; a downscale to 480×270 keeps a 10× margin on bullet-scale changes at 7.4× less
cost and is the tuning axis the original lacks ([§G.4.1](#g41-constants-and-what-they-actually-do)).

**Sweep downward, and at more than one resolution.** `video-slide-extractor`'s own published numbers,
re-scored by (misses, surplus), invert its own recommendation: coverage is monotone in `changedRatio`
across all six of its fixtures, 0.02 beats 0.10 every time, and the 0.10 it prescribes is fitted to
one synthetic overlay's 9.1 %-of-blocks footprint. **Nobody has measured below 0.02**, and even there
coverage is 0.900–0.935 on the cleanest possible input, because at 160×90 a one-bullet difference sits
near the trigger floor. Working resolution is a recall parameter ([§A.4](#a4-the-published-numbers-re-scored)).
The counterweight from the same lineage: bare 0.02 with no mask kept 809 of 1,293 samples on a real
lecture, ~17× over-capture — recall-first does not mean threshold-free, it means the mask and the
dedupe absorb the camera, not the threshold ([§A.7.1](#a71-the-product-benchmark-has-no-labels)).

**Add a fifth axis: which frame of the run.** Five prior answers, none measured, all computable from
the cached features ([§D.6](#d6-the-hard-cases-across-all-four)). ADR 0003's window opening at content
completion favours the tail; `m2kar`'s `end − clamp(5 %, 0.05 s, 0.5 s)` is the most defensible
starting formula and its clamps are tuned constants ([§F.4](#f4-which-frame-of-the-dwell)).

**Set `min_scene_len` to 0 and keep it there.** One scalar controls both animation suppression and
build merging, there is no content-aware variant, and a burst shorter than the window yields only the
burst's *emptiest* state — a miss under ADR 0003, not a surplus ([§C.3](#c3-flashfilter)). Whatever
burst suppression this project needs belongs downstream, where content identity exists.

**Adopt outright, cheaply.** The activity mask as a count-of-changes per block with a refusal above
35 % of the frame — cheaper than `kovitking`'s median variant and structurally immune to a one-off
whole-frame change ([§A.2](#a2-the-activity-mask)). Dilating edge maps before differencing, as
tolerance for wobble and filmed screens ([§C.2](#c2-the-edge-component-is-the-build-recall-mechanism)).
The Otsu **bimodality guard** — refuse to act on a split that is really just noise — without the
calibrated threshold it guards, which is broken at 45–60 minutes by a stride that makes calibration
measure an 18-second time-scale while detection measures a 1-second one
([§A.1](#a1-what-the-otsu-calibration-is-run-over)). All-pairs dedupe that re-links the timeline event
to the first-kept file, which is the "returns" answer ([§B.5](#b5-phash-and-the-exclusion-list)). The
first-frame-always rule and the two end-of-video guards, without which the first and last slide of
every talk are lost ([§B.4](#b4-the-verification-window)). Hash thresholds expressed as a fraction of
bits, never as a raw Hamming count ([§D.1](#d1-the-three-video2slides-side-by-side)). **Flush any
pending capture at end of file**: `perelman/slide-detector` has no flush after its decode loop, so a
slide held to the end of the recording — the closing or Q&A slide of essentially every talk — is never
written ([§G.8](#g8-defects-the-readme-does-not-mention)).

**Measure, do not assume.** The K-sample all-must-agree verification window, noting that its recall
bias runs against this project's and that under continuous motion it walks an entire segment saving
nothing ([§B.4](#b4-the-verification-window)). The persisted pHash exclusion list, whose shipped
default entries are two HDMI capture-card "No Signal" screens — a pure field artefact, and the whole
mechanism is ~40 lines ([§B.5](#b5-phash-and-the-exclusion-list)). Hysteresis on changed-area as a
dwell-frame chooser, without `binh234`'s background model, which needs `opencv-contrib`
([§D.3](#d3-binh234)). Dedupe **twice**, once on raw frames and once post-crop
([§B.8](#b8-crop-then-re-dedupe)).

**Guard any dwell threshold with a spatial-extent test.** Three seconds is a genuinely convergent
constant — TalkMiner and `perelman/slide-detector` arrive at it independently — but unguarded it
converts continuous motion into **silence**: while anything moves the anchor advances every frame, the
dwell never completes, and nothing is emitted for the whole animated span, *including the slide
underneath it*. Four of that tool's seven hard cases fail in the miss direction for this reason
([§G.9](#g9-hard-cases)). TalkMiner's bounding-box-extent filter is the published fix, and their
recall rose when they added it.

**Reject.** GPU-accelerated SSIM — 5,166 lines of never-called stubs, deleted upstream. The
monotonic left-to-right HMM, which makes a return structurally impossible
([§D.4](#d4-vid2slides)). `HistogramDetector`, except as a control: a one-bullet reveal measured a
luma-histogram correlation of **0.99999955** ([§C.2](#c2-the-edge-component-is-the-build-recall-mechanism)).
I-frame-only sampling as a default, which silently couples recall to the source encoder's GOP — worth
exactly one row for its decode cost ([§B.3](#b3-frame-sampling)).

### #12 — crop

**Re-scope from greenfield to "one tuned deterministic recipe exists, and it has no fallback".**
**Reversed — see the note at [§B.7](#b7-auto-crop-12-is-not-greenfield); the aspect prior picks the
webcam.** `AutoCropDetector` is candidate 1.5, above plain letterbox removal, and its aspect-prior scoring is
the part this project did not plan for. Its limitation is the one recall-first must fix: five gates
and no fall-back rectangle ([§B.7](#b7-auto-crop-12-is-not-greenfield)). Everything else in the
survey still confirms the original premise, now including the learned state of the art, which
hand-labels one box per video in a text file ([§E.5](#e5-crop-the-greenfield-assumption-survives)).

**Build the activity map once and use it twice.** `video-slide-extractor`'s mask returns a
block-resolution binary map of *where this recording never stops moving* — the exact input an
activity-complement projection-profile crop needs, 22 lines, MIT ([§A.2](#a2-the-activity-mask)).
SliTraNet's paper states the same signal from the other end: slides do not fill the screen while
memes and speaker views do, so activity **outside** the rectangle against activity **inside** it
discriminates cutaway, embedded video and mixer cut. They trained a 46 M-parameter network to learn
a two-number comparison ([§E.5](#e5-crop-the-greenfield-assumption-survives)).

**Detection needs a region of its own, decided before detect runs.** In `perelman/slide-detector` the
crop is not cosmetic, it is load-bearing for recall: the detector only ever sees the cropped region,
and without it a 60×40 station bug, a subtitle strip or a webcam box changing while the slide is static
trips the predicate on every frame and the tool emits **nothing for the entire video**
([§G.6](#g6-the-crop-ui)). This is a coupling between #11 and #12 that neither ticket states, and it
does not require reordering the stages — the output crop can still be computed later.

**Order.** Two further independent reasons to consider crop before detect: `lectures-2-slides` applies its
manual rectangle before diffing ([§A.7.2](#a72-new-candidates)), and PySceneDetect's auto-downscale
factor is computed from the *post-crop* frame, so cropping is a free recall win on top of everything
else ([§C.5](#c5-downscale-frame_skip-and-what-breaks)).

**Carry a first-hand negative result.** `sumerene`'s skill notes record edge/brightness/Sobel-projection
crop detection failing on branded conference chrome — logos, title bars and separator lines have the
same edge characteristics as slide content — and a multimodal LLM asked for coordinates deviating
badly. That is one practitioner on one class of video, but the failure mode is specific enough to
test, and at least one reference video should have decorated chrome or #12 gets measured on the easy
case only ([§D.2](#d2-sumerene)).

**The greenfield premise now holds at both ends of the lineage.** The deterministic ancestor takes
`x y w h` on argv — its "UI" is a keyboard nudger that prints four numbers for you to retype, behind a
source constant rather than a flag — and the learned state of the art reads its rectangle from a
hand-authored `*_bounding_box_list.txt`. Neither infers anything
([§G.6](#g6-the-crop-ui), [§E.5](#e5-crop-the-greenfield-assumption-survives)).

**Nobody does perspective correction.** Confirmed across all eleven repos: no `getPerspectiveTransform`,
no `warpPerspective`, no quadrilateral fitting anywhere. The angled-screen case has zero prior art.

### #17 — slide-frame gate

**Cost is no longer an argument.** The MobileNetV4 gate runs at 22.5 ms/frame through `cv2.dnn` with
no new dependency — 61 s for a whole 45-minute video at 1 fps, about the cost of one windowed-SSIM
comparison per frame. Bench Laplacian variance and the intensity-histogram SVM *against it*, so the
comparison is empirical rather than theoretical; do not ship weights that carry no licence
([§B.6](#b6-the-mobilenetv4-slide-frame-gate)). Distrust the 99.27 % figure: best validation accuracy
at epoch 4 of a planned 50, on an unnamed dataset with no held-out description.

**Adopt the decision shape whatever wins.** Every failure path keeps the image; a medium-confidence
"not a slide" is deleted only if the *slide* probability is also low — a veto, not a second opinion;
and the third class is an explicit "I don't know" bucket routed to *more processing* rather than to
deletion ([§B.6](#b6-the-mobilenetv4-slide-frame-gate)). SliTraNet's combinator generalises it:
**require unanimity to suppress** ([§E.4](#e4-the-recall-safe-combination-rule)).

**Measure Laplacian variance as a score, not as a gate.** `sumerene` runs it at `< 300` on the
full-resolution ROI *before* hashing, where a false reject is a silent miss — and a title slide, a few
large words on a plain background, is exactly the low-Laplacian case. It is neither
resolution-independent nor ROI-size-independent, so any value must be pinned to a stated working
resolution. Record the score for every sampled frame beside the ground-truth label and ask whether
*any* threshold separates the classes with zero misses; if none does, #17 is answered in the negative
without wiring anything into the pipeline ([§D.2](#d2-sumerene)).

**One negative finding worth reading carefully.** `perelman/slide-detector` has no gate of any kind —
no Laplacian, no histogram, no blank-frame test — and still beat SliTraNet's CNN on recall. That is not
evidence a gate is unnecessary: it ran on clean lecture capture with a human-drawn ROI already applied,
which is the ROI doing the gate's job ([§G.7](#g7-gate-export-choice-naming-audio)).

**A labelled dataset for this question now exists.** MaViLS labels *no slide on screen* explicitly,
at a 10.5 % rate on one lecture, across twenty ([§A.7.3](#a73-mavils)).

**The deterministic churn track is free.** SliTraNet's two-anchor video track accumulates short runs
into a "video segment" emitted with `slide_id = -1` — separating a region of constant churn from a
slide change, deterministically, before any network sees anything
([§E.3](#e3-the-deterministic-skeleton)).

### #14 — output contract and pairing

**Adopt max-overlap against the full dwell interval**, cue never split, ties to the earlier slide —
then fix its three defects: an explicit `unassigned` bucket instead of a silent drop, per-cue rows
retained in the manifest with the joined blob as a *view* of them, and word-level splitting available
as an opt-in for near-50/50 straddles ([§F.1](#f1-the-pairing-rule)). Decide what `drop` does to a
dropped slide's cues; no prior art faces the question.

**Store the interval, not the instant.** A slide row needs `(dwell_start, dwell_end, capture_ts)`
distinct. Anurag's single-`int` `timestamp` is precisely what made temporal pairing impossible and
forced an ordinal join of an LLM-invented deck onto detected keyframes, labelled *"if timing matches"*
([§F.1.2](#f12-anurag-has-no-temporal-pairing)).

**Adopt the immutable-event / mutable-resolution split.** `timeline.json` keeps capture events
append-only and changes only their *resolution* — canonical, duplicate with a `duplicateOf`, or gap
with a reason. That gives `drop` its shape for free and handles returns. Keep two timestamps per
slide, and align transcript on the transition, not on the confirmation
([§B.10](#b10-timelinejson)).

**Two cautionary patterns.** Never let a downstream enrichment decide membership in the output set:
`vid2slides` filters every consumer on `el['title']`, so a detected slide whose heading Tesseract did
not read confidently is silently absent from the PDF, the GIF and the chapters — advertised as a
feature, implemented as a filter ([§D.4](#d4-vid2slides)). And emit a row for *every* slide: `m2kar`
writes a notes entry even when a slide has no speech, so an empty-speech slide stays visible rather
than vanishing ([§F.5](#f5-output-naming-numbering-and-the-manifest)).

**Naming.** Fixed-width zero padding with a floor of three digits that widens past 999, and the
capture's source timestamp in the manifest. Do not copy `m2kar`'s adaptive pad width, which changes
every filename when the scene count crosses a power of ten ([§C.6](#c6-which-frame-of-a-dwell-gets-exported),
[§F.5](#f5-output-naming-numbering-and-the-manifest)).

### #15 — packaging

`scenedetect-headless` is the correct distribution name if PySceneDetect is used for anything, even
just the spike harness: 6 packages, all wheels, no compilation, no ffmpeg
([§C.7](#c7-dependencies-the-video-backend-and-ffmpeg)). One line worth taking regardless of that
decision: `cap.set(cv2.CAP_PROP_ORIENTATION_AUTO, 1.0)`, without which a phone-recorded talk carrying
rotation metadata decodes sideways and breaks both detection and crop.

### The transcribe stage

Not one of this ticket's three targets, but the survey produced a first-hand field verdict worth
recording: `kovitking` built CPU `faster-whisper` transcription, then removed it — *"CPU
transcription of long recordings was impractically slow"* — for a project whose entire purpose
(NotebookLM ingestion) required the transcript. Same hardware class, same 45–60 minute inputs
([§D.5](#d5-kovitking)). It does not overturn `docs/research/stt-cpu.md`, whose shortlist is built
for exactly this constraint, and it does reinforce why the YouTube caption path is the primary one.
Free and worth taking: 64 kbps mono audio for STT — Whisper resamples to 16 kHz mono regardless
([§F.2](#f2-transcript-acquisition)).

## What this does to the measuring instrument

One finding lands on neither a candidate nor a stage but on `tools/groundtruth/`, which is what every
later number is scored against. It is recorded here rather than in a project section because the
reading surfaced it and a local measurement settled it.

**The observation.** `kovitking`'s run detector drifts its reference hash to the latest frame —
`candidateHash = h`, with the comment *"drift slowly with the evolving look of the slide"*
([`app.js:269`](https://github.com/kovitking/video2slides/blob/2e16e894d6bab283a35505c390f5f8888695261f/video2slides/webapp/static/app.js#L269)) —
so a run can walk arbitrarily far from where it started as long as no single step crosses the
threshold. `tools/groundtruth/runs.py` has the same structure: it ends its loop with `prev = reg`
and compares each state only against its immediate predecessor
([`tools/groundtruth/runs.py:70`](../../tools/groundtruth/runs.py)). The lineage that SliTraNet was built on does
the opposite and says why — comparing against a fixed **anchor** lets drift accumulate until it trips,
where frame-to-frame differencing sees each step as sub-threshold and never fires
([§G.5](#g5-the-anchor-logic), kept verbatim at [§E.3](#e3-the-deterministic-skeleton)). `sumerene` reaches the same place with two layers: a fast
adjacent check, then a re-check against every saved anchor ([§D.2](#d2-sumerene)).

**Why it matters here specifically.** `runs.py` decides how many questions the ground-truth review
asks — one per run, not per state — and the run's `from_s` is what seeds a required content's
window. ADR 0003 says a capture window **opens when the content is complete**. So a run that
collapses a slow accumulation opens its window too early, and a capture of an incomplete state
scores as a hit where it should score a miss. The bias is in the instrument, in the direction of
**under-counting misses**, which is the one number the metric says declares a winner.

**What the measurement says.** Re-grouping the states of the labelled fixture three ways — against
the previous state, against the run's anchor, and against both — on `jqpdveK2XAU` with its own
rectangle:

| mode | runs | max drift within a run |
|---|---|---|
| previous state (what `runs.py` does) | 9 | **0.14 %** |
| run anchor | 9 | — |
| either | 9 | — |

Identical, and not marginally: the largest drift inside any of the nine runs is 0.14 % of the
rectangle, against a 1 % threshold. **The defect did not fire on the one fixture that is labelled.**

Probed at full frame on four more fixtures, anchor mode does split more runs — 160 states go 69 → 80,
207 states go 76 → 104 — but at full frame the thing that moves is the presenter, which is precisely
what the rectangle exists to exclude. Those splits are not evidence of the defect; they are evidence
that the comparison must stay inside the rectangle.

**Verdict.** Real, structural, and so far inert. The exposure is not the additive build — ADR 0003
deliberately collapses one into a single window — but slow *replacement*: a cross-fade held over
several states, a highlight that walks, a dimming ramp. Switch the comparison to `max(prev, anchor)`
inside the rectangle before the remaining fixtures are labelled; it costs extra review questions only
where the rectangle still contains motion, and an extra question is cheap in exactly the way a
missed one is not. Worth sanity-checking `delta=25 / threshold=0.01` against a real build at the same
time: one bullet line on a 1080p slide inside a 0.6-area rectangle is well under 1 % of that
rectangle.

## Fixtures and datasets this surfaced

The index sweep and the SliTraNet read turned up material the reference set does not have.

**`andererka/MaViLS`** (Apache-2.0, Interspeech 2024) is the find. Twenty real lectures with
human-labelled alignment in git — transcripts as `.srt`, 22 source decks as PDF, videos on Kaggle.
One ground-truth file decoded directly: 421 labelled instants over 3,249 s, 38 slides, 51 derived
transitions, **14 revisit events**, and `Slidenumber = -1` meaning *no slide on screen* on **10.5 %**
of rows. That is a labelled slide-frame-gate dataset — training and test data for #17's SVM
candidate, and a real measurement of the cutaway/revisit case for #11, which no reference
implementation handles. Two caveats decide how it can be scored: labels are at transcript-sentence
granularity (~7.7 s), so a derived transition lags the visual cut by an unknown amount, and a
"slide" is a PDF page, so builds are invisible. It cannot support ±2 s transition matching and it
can support a coverage-style metric — which is ADR 0003's, almost exactly.
[§A.7.3](#a73-mavils)

**MIT OCW 6.0001 Lecture 1** — CC BY-NC-SA 4.0, pinned by SHA-256, 2,585.964 s of real lecture,
with a 46-slide product extraction available as a labelling accelerant (explicitly *not* ground
truth). A free, byte-identical 43-minute fixture. [§A.7.1](#a71-the-product-benchmark-has-no-labels)

**Two smaller index results.** `sidharth-anand/lectures-2-slides` (MIT) applies a **manual**
`slide_bounds` rectangle *before* diffing — the fourth project to need a slide region, the first to
ask the user to type it in, and an argument for crop-before-detect that the current pipeline order
does not make. `Wangxs404/video2ppt` has 239 stars and no change detection at all: grepping its
single file for `similar|dedup|compare|hash|ssim` returns zero hits. [§A.7.2](#a72-new-candidates)

**What is *not* reusable.** SliTraNet's dataset is private and undistributed, and even if it were,
its labels emit a run per build step — re-importing the taxonomy ADR 0003's History section records
dropping. `video-slide-extractor`'s own "manually-labelled product benchmark" has no labels: the
ground-truth template is one header row and a blank line, and the README's first blocker is that
the intervals have not been labelled. Its generated fixtures are worth having as a pre-flight sanity
gate — any candidate that cannot reach coverage 1.0 on the clean synthetic cut should be considered
broken — and worth nothing as a reference set. [§A.5](#a5-the-benchmark-harness)

---

## Group A — larry-xue/video-slide-extractor and awesome-video-to-slides

Repos read, pinned:

| Repo | HEAD sha | Date | License | Language |
|---|---|---|---|---|
| [`larry-xue/video-slide-extractor`](https://github.com/larry-xue/video-slide-extractor) | `221454d1cc296e75a2ddf83cd3ed587d5922c232` | 2026-09-06 | MIT (`Copyright (c) 2026 Video2Any`) | JavaScript (ESM, zero runtime deps; CLI shells to ffmpeg/ffprobe) |
| [`larry-xue/awesome-video-to-slides`](https://github.com/larry-xue/awesome-video-to-slides) | `d1e90923a955ed3894ca91ac19a565deed8fea51` | 2026-08-29 | see repo `LICENSE` (list content CC-style; code snippets in-repo) | Markdown + JSON + a Node runner |

Everything below was read from source at those shas. Permalinks are pinned to them.
Whole surface read: `index.js` (261 L), `cli.js` (362 L), `bench/run.mjs` (215 L),
`bench/generate-fixtures.mjs` (127 L), `bench/README.md`, `bench/RESULTS.md`, `bench/results.json`,
`docs/evaluation.md`, `test/index.test.js`, `test/cli.test.js` — plus the whole of
`awesome-video-to-slides`, whose `benchmarks/2026-07-mit-60001/` is the "manually-labelled product
benchmark" that `docs/research/slide-change-detection.md` §7.2 left as an open question.

---

### A.1 What the Otsu calibration is run over

`docs/research/slide-change-detection.md` §6.1 already records the knobs. The source answers the
question the doc did not: **which distribution, sampled how.** It matters, because the answer
contains a defect that is fatal for this project's input lengths.

**The distribution.** `calibrateThreshold(ratios)`
([`index.js:130-153`](https://github.com/larry-xue/video-slide-extractor/blob/221454d1cc296e75a2ddf83cd3ed587d5922c232/index.js#L130-L153))
is a hand-rolled 1-D Otsu over **`frameDiff.ratio` values — the fraction of 8×8 blocks whose mean
|ΔRGB| exceeded `blockDelta=14`**. It is *not* OpenCV's `THRESH_OTSU`, and it is not over pixel
intensities, so none of `docs/research/slide-region-crop.md` §"Otsu needs a bimodal histogram"
transfers directly. Implementation details worth knowing:

- It runs on the **sorted sample list itself**, not a histogram — every sample is its own bin of
  weight 1, so there is no quantisation error. Split index `i` maximises
  `n0·n1·(m1−m0)²` ([`index.js:139-145`](https://github.com/larry-xue/video-slide-extractor/blob/221454d1cc296e75a2ddf83cd3ed587d5922c232/index.js#L139-L145)),
  the standard between-class-variance objective. Cost is `O(n log n)` for the sort, `O(n)` after.
- Threshold is the midpoint of the two straddling samples, clamped to `[0.005, 0.15]`
  ([`index.js:151-152`](https://github.com/larry-xue/video-slide-extractor/blob/221454d1cc296e75a2ddf83cd3ed587d5922c232/index.js#L151-L152)).
- **Bimodality guard:** `if (m1 < m0 * 3 + 0.004) return null`
  ([`index.js:149`](https://github.com/larry-xue/video-slide-extractor/blob/221454d1cc296e75a2ddf83cd3ed587d5922c232/index.js#L149))
  — the upper cluster mean must be ≥ 3× the lower cluster mean plus 0.004 absolute. Otherwise the
  caller falls back to the fixed default. This is the "refuse to act on a split that is really just
  noise" device and it is the piece worth lifting wholesale; it is what makes an automatic
  per-video threshold safe to ship at all.
- Minimum 6 samples ([`index.js:132`](https://github.com/larry-xue/video-slide-extractor/blob/221454d1cc296e75a2ddf83cd3ed587d5922c232/index.js#L132)).

**The sampling.** `collectCalibrationFrames`
([`cli.js:163-173`](https://github.com/larry-xue/video-slide-extractor/blob/221454d1cc296e75a2ddf83cd3ed587d5922c232/cli.js#L163-L173))
decodes the *entire* video at `fps`/`--width` and keeps every `stride`-th frame, where
`stride = ceil(expectedFrames / MAX_CALIBRATION_FRAMES)` and `MAX_CALIBRATION_FRAMES = 150`
([`cli.js:36`](https://github.com/larry-xue/video-slide-extractor/blob/221454d1cc296e75a2ddf83cd3ed587d5922c232/cli.js#L36)).
The header comment's rationale is sound and worth copying verbatim: *"Calibration needs to see the
whole recording, not just its opening, or a deck that starts on a title card calibrates against the
title card."*

#### A.1.1 The defect: calibration measures a different time-scale than detection

`analyzeSamples`'s `pairRatios` diffs **consecutive calibration frames**
([`index.js:203-204`](https://github.com/larry-xue/video-slide-extractor/blob/221454d1cc296e75a2ddf83cd3ed587d5922c232/index.js#L203-L204)),
but `createSlideDetector` diffs against the **last kept** frame at the full sampling cadence
([`index.js:231`](https://github.com/larry-xue/video-slide-extractor/blob/221454d1cc296e75a2ddf83cd3ed587d5922c232/index.js#L231)).
Because of `stride`, those are not the same time-scale once the video exceeds
`MAX_CALIBRATION_FRAMES / fps` = **150 seconds** at the default `--fps 1`:

| Input length @ `--fps 1` | `expectedFrames` | `stride` | Calibration pair spacing | Detection pair spacing |
|---|---|---|---|---|
| 2.5 min | 150 | 1 | 1 s | 1 s |
| 10 min | 600 | 4 | 4 s | 1 s |
| **45 min** | 2700 | **18** | **18 s** | 1 s |
| **60 min** | 3600 | **24** | **24 s** | 1 s |

This project's declared inputs are 45–60 min, i.e. `stride` 18–24. The consequence runs through the
regime decider: `staticFrac` is the fraction of pairs with ratio < 0.02, and `>= 0.6` selects the
deck-like branch ([`index.js:174-176`](https://github.com/larry-xue/video-slide-extractor/blob/221454d1cc296e75a2ddf83cd3ed587d5922c232/index.js#L174-L176)).
At 18 s spacing, the probability that a calibration pair straddles a slide change is roughly
`18 / mean_slide_duration`. A talk averaging 20 s per slide puts ~90% of pairs across a change →
`staticFrac ≈ 0.1` → **the `motion` branch fires on a pure slide deck**, and the threshold becomes
`median + 2·MAD` clamped to `[0.25, 0.65]`
([`index.js:182-185`](https://github.com/larry-xue/video-slide-extractor/blob/221454d1cc296e75a2ddf83cd3ed587d5922c232/index.js#L182-L185))
— **12.5× to 32.5× the default 0.02**. Under this project's metric that is a mass-miss event, the
one failure class the metric says decides the winner.

Two secondary effects of the same `stride`:

- `buildActivityMask` is built from the same strided frames
  ([`index.js:209`](https://github.com/larry-xue/video-slide-extractor/blob/221454d1cc296e75a2ddf83cd3ed587d5922c232/index.js#L209)),
  so "a block that changes in >50% of pairs" is measured over 18-s-apart pairs. On a fast deck
  nearly every block qualifies, the mask would exceed `maxMaskFrac = 0.35`, and
  [`index.js:117`](https://github.com/larry-xue/video-slide-extractor/blob/221454d1cc296e75a2ddf83cd3ed587d5922c232/index.js#L117)
  discards it → `null`. The 0.35 guard is load-bearing exactly here and silently saves the run.
- The regime cut `r < 0.02` at
  [`index.js:174`](https://github.com/larry-xue/video-slide-extractor/blob/221454d1cc296e75a2ddf83cd3ed587d5922c232/index.js#L174)
  is a **hardcoded literal**, not `DEFAULTS.changedRatio` and not the caller's `defaultRatio`.
  Lowering the detection threshold does not move the regime decider with it.

**Fix if lifted:** sample calibration in *contiguous bursts* — e.g. 15 runs of 10 consecutive
frames spread across the video — so pair spacing equals detection spacing while still covering the
whole recording. Same memory bound, same coverage rationale, correct distribution. This is a
~10-line change and it is the difference between the calibration being usable and being a hazard.

#### A.1.2 Cost: the CLI decodes the video twice

The `cli.js` header comment (L11-19) claims *"Three ffmpeg passes, so memory stays flat no matter
how long the recording is."* That is true and honest about **memory**. What neither the comment nor
the README says is that pass 2 (calibration) reads the stream to the end whenever `stride > 1` —
the 150-frame cap is a cap on *retention*, not on *decoding*. So on a 45-min input the detect stage
pays **two full decode passes** before any export. On the i3-4170 target that roughly doubles the
stage's wall time. Adopt the calibration idea, but seek the calibration bursts (`-ss`) rather than
streaming the whole file, or fold calibration into a single pass with a deferred decision.

---

### A.2 The activity mask

`buildActivityMask`
([`index.js:98-119`](https://github.com/larry-xue/video-slide-extractor/blob/221454d1cc296e75a2ddf83cd3ed587d5922c232/index.js#L98-L119)):

| Element | Value / behaviour |
|---|---|
| Input | ordered sample frames, RGBA |
| Accumulator | `Uint16Array(rows*cols)` — per **block**, count of consecutive pairs in which that block's mean \|ΔRGB\| > `blockDelta` (14) |
| Decision | `counts[b] / pairs > activeFrac (0.5)` → masked |
| Refusals | `frames.length < 8` → `null`; `masked === 0` → `null`; `masked / (rows*cols) > maxMaskFrac (0.35)` → `null` |
| Output | `Uint8Array`, one byte per block, 1 = ignore |
| Application | masked blocks leave **both numerator and denominator** ([`index.js:58-59`](https://github.com/larry-xue/video-slide-extractor/blob/221454d1cc296e75a2ddf83cd3ed587d5922c232/index.js#L58-L59)) |

Three things this adds to what the project already recorded:

1. **It is a count-of-changes mask, not a median-of-differences mask.** `kovitking` takes the
   *median* of per-pixel consecutive differences so a single whole-frame slide change cannot enter
   the mask. `larry-xue` gets the same immunity differently and more cheaply: a slide change makes
   *every* block change *once*, and `activeFrac = 0.5` requires a block to change in over half of
   all pairs, so one-off whole-frame events are structurally excluded without any robust statistic.
   Cheaper (integer counts, no per-pixel sort) and just as safe. **This is the version to lift.**
2. **The output is already block-resolution.** `maxMaskFrac` aside, the returned array *is* a
   coarse binary map of "where does this recording never stop moving", at `width/8 × height/8` —
   e.g. 40×22 = 880 cells at the CLI default 320×180
   ([`cli.js:35`, `cli.js:267`](https://github.com/larry-xue/video-slide-extractor/blob/221454d1cc296e75a2ddf83cd3ed587d5922c232/cli.js#L267)).
   That is directly the input a row/column projection profile needs for the **activity-complement
   crop** that `docs/research/slide-region-crop.md` §"Candidate 2" says nobody has built. The
   primitive exists, MIT-licensed, in 22 lines. Nothing in this repo crops — `--width` is a
   *detector working width*, not a crop, and the export at
   [`cli.js:213`](https://github.com/larry-xue/video-slide-extractor/blob/221454d1cc296e75a2ddf83cd3ed587d5922c232/cli.js#L213)
   writes the full source frame. **Negative finding: this repo does not address #12 at all**, but it
   hands #12 its missing input for free.
3. **The `maxMaskFrac = 0.35` refusal is the same plausibility gate `kovitking` uses** (`area <
   0.35·frameArea`), arrived at independently. Two projects converging on 0.35 is the closest thing
   to a tuned constant in this area. Neither justifies the number.

**A load-bearing gap: the mask is never evaluated.** `bench/run.mjs`'s `blockDetector`
([`bench/run.mjs:68-73`](https://github.com/larry-xue/video-slide-extractor/blob/221454d1cc296e75a2ddf83cd3ed587d5922c232/bench/run.mjs#L68-L73))
calls `createSlideDetector(W, H, opts)` with **no mask and no calibration**. The two headline
mechanisms of the package — the thing the package README leads with — are absent from the package's
own benchmark, which measures only raw block-diff at two fixed thresholds. `bench/README.md` is
straightforward that it compares "Block diff (this package) — defaults and a tuned `changedRatio`",
so this is an omission, not a false claim; but every number in `RESULTS.md` describes a
configuration the library does not recommend.

---

### A.3 Constants: what was actually tuned, and against what

On constants someone already tuned, the honest answer from the source is
**almost none of them were.**

| Constant | Where | Tuned against |
|---|---|---|
| `blockSize 8`, `blockDelta 14` | [`index.js:27-31`](https://github.com/larry-xue/video-slide-extractor/blob/221454d1cc296e75a2ddf83cd3ed587d5922c232/index.js#L27-L31) | nothing in-repo. No test asserts them; no benchmark varies them. |
| `changedRatio 0.02` | same | the only constant with published evidence — `bench/RESULTS.md`, on synthetic hard-cut fixtures only |
| `activeFrac 0.5`, `maxMaskFrac 0.35` | [`index.js:99`](https://github.com/larry-xue/video-slide-extractor/blob/221454d1cc296e75a2ddf83cd3ed587d5922c232/index.js#L99) | hand-built 32×32 unit fixtures (`test/index.test.js:107-143`). No real footage. |
| Otsu clamp `[0.005, 0.15]`, guard `m1 < 3·m0 + 0.004` | [`index.js:130`, `:149`](https://github.com/larry-xue/video-slide-extractor/blob/221454d1cc296e75a2ddf83cd3ed587d5922c232/index.js#L149) | unit fixtures with synthetic ratio arrays (`test/index.test.js:148-156`) |
| `motion` clamp `[0.25, 0.65]`, `median + 2·MAD` | [`index.js:184`](https://github.com/larry-xue/video-slide-extractor/blob/221454d1cc296e75a2ddf83cd3ed587d5922c232/index.js#L184) | nothing |
| `MAX_CALIBRATION_FRAMES 150`, `DIFF_WIDTH 320`, `--fps 1` | [`cli.js:35-36`](https://github.com/larry-xue/video-slide-extractor/blob/221454d1cc296e75a2ddf83cd3ed587d5922c232/cli.js#L35-L36) | nothing |

31 tests across `test/index.test.js` and `test/cli.test.js`, all on synthetic 32×32 frames. Treat
every constant here as a *starting point for a sweep*, never as a tuned value — including the ones
this project's own `docs/research/slide-change-detection.md` §6.1 table reproduces without that
caveat.

#### A.3.1 `changedRatio 0.10` is fitted to one fixture's overlay footprint

`bench/RESULTS.md` recommends raising `changedRatio` to 0.10 to fix the overlay flood. The fixture
overlay is a `testsrc` box `176×99` at `960×540`, positioned `x=W-w-24, y=H-h-24+8*sin(t*3)`
([`bench/generate-fixtures.mjs:99-105`](https://github.com/larry-xue/video-slide-extractor/blob/221454d1cc296e75a2ddf83cd3ed587d5922c232/bench/generate-fixtures.mjs#L99-L105)).
At the benchmark's 160×90 / `blockSize 8` grid (20×11 = 220 blocks; the bottom 2 px rows are never
scored, see A.6) that box covers ~29×17 px = 3.4% of area but touches ~5×4 = 20 blocks = **9.1% of
blocks**, once its ±1.3 px vertical wobble is included.

So `0.10` sits **0.9 percentage points above this specific overlay's block footprint**. It is a
value fitted to one synthetic artefact, not a slide-domain constant. A real webcam bubble that is
slightly larger, positioned nearer a block boundary, or moving more, crosses 0.10 and the flood
returns. **Reject `0.10` as a transferable default; the activity mask is the mechanism that
generalises, and the benchmark never ran it.**

---

### A.4 The published numbers, re-scored

Raw table from [`bench/results.json`](https://github.com/larry-xue/video-slide-extractor/blob/221454d1cc296e75a2ddf83cd3ed587d5922c232/bench/results.json)
(Node v22.22.3, FFmpeg 6.1.1, 160×90 every 2 s, ±2.5 s 1:1 matching). `coverage` = fraction of
ground-truth slides receiving ≥1 capture; `duplicateRate` = extra captures ÷ all captures
([`bench/run.mjs:110-113`](https://github.com/larry-xue/video-slide-extractor/blob/221454d1cc296e75a2ddf83cd3ed587d5922c232/bench/run.mjs#L110-L113)).

Their scoring maps onto ADR-0003 almost exactly: **misses = 1 − coverage**, **surplus ≈ duplicateRate**.
Re-ranking their own results lexicographically by `(misses, surplus)`:

| Fixture | Method | captures | coverage | **misses** | **surplus** | their verdict | **(misses, surplus) rank** |
|---|---|---:|---:|---:|---:|---|---|
| synthetic clean | block 0.02 | 27 | 0.900 | 0.100 | 0 | best F1 | **1** |
| synthetic clean | block 0.10 | 21 | 0.700 | 0.300 | 0 | — | 3 |
| synthetic clean | pixel diff | 21 | 0.700 | 0.300 | 0 | — | 3 |
| synthetic clean | interval 10 s | 27 | 0.800 | 0.200 | 0.111 | worst | 2 |
| synthetic noisy | block 0.02 | 27 | 0.900 | 0.100 | 0 | best F1 | **1** |
| synthetic noisy | block 0.10 | 18 | 0.600 | 0.400 | 0 | — | 4 |
| synthetic **overlay** | block 0.02 | 81 | **1.000** | **0.000** | 0.630 | **"floods", P=0.37** | **1** |
| synthetic overlay | block 0.10 | 26 | 0.867 | 0.133 | 0 | **recommended** | 3 |
| synthetic overlay | pixel diff | 33 | 1.000 | 0.000 | 0.091 | — | **1 (better surplus)** |
| mit clean | block 0.02 | 43 | 0.935 | 0.065 | 0 | best F1 | **1** |
| mit clean | block 0.10 | 37 | 0.804 | 0.196 | 0 | — | 3 |
| mit **overlay** | block 0.02 | 125 | **1.000** | **0.000** | 0.632 | **"floods", P=0.368** | **1** |
| mit overlay | block 0.10 | 40 | 0.870 | 0.130 | 0 | **recommended** | 3 |

Two things fall out, and they are the reason this section exists:

1. **`coverage` is monotone in `changedRatio` across all six fixtures** — 0.02 ≥ 0.10 every single
   time (0.900≥0.700, 0.900≥0.600, 1.000≥0.867, 0.935≥0.804, 0.935≥0.804, 1.000≥0.870). Lowering
   the threshold buys misses at the price of surplus, which is precisely the trade this project has
   already decided it wants. **Nobody in the reference set has measured *below* 0.02.**
2. **The reference project's own recommended configuration is the losing one under ADR-0003.** Its
   prose calls the `0.02` overlay rows a failure (precision 0.37) and prescribes `0.10`; ranked by
   `(misses, surplus)`, `0.02` wins those exact rows 0.000 → 0.130 on misses. This is an
   optimisation-target disagreement, not a disagreement about facts, and it means **every threshold
   recommendation in this repo must be inverted before use.**

**The residual misses are the headline risk.** At `0.02`, on the *cleanest possible* input — hard
cuts, no crossfade, no camera, no build — coverage is still 0.900 (synthetic) and 0.935 (MIT). That
is 10% and 6.5% of slides missed on the easy case. `bench/RESULTS.md` L205-208 names the cause:
*"a few consecutive slides differ by roughly one bullet line, and at 160x90 that change stays near
the trigger floor"*. Measured, not inferred, and it confirms `docs/research/slide-change-detection.md`
§9's instinct: **working resolution is a recall parameter.** This project's own floor must be
established at ≥2 resolutions and at thresholds below 0.02.

---

### A.5 The benchmark harness

**Ground truth by construction.**
[`bench/generate-fixtures.mjs`](https://github.com/larry-xue/video-slide-extractor/blob/221454d1cc296e75a2ddf83cd3ed587d5922c232/bench/generate-fixtures.mjs)
renders videos from known slide sequences, so transitions are exact. Slide durations come from a
seeded mulberry32 PRNG (4–12 s, `SEED = 60001`, L27-38, L78) so every machine gets byte-identical
timelines. Ground truth is written as
`{dataset, seed, slideCount, durations, transitions, totalSeconds}` (L107-110) — **a flat array of
transition seconds, no `type`, no `parent_slide`.**

**Reproducibility, verified today:** `https://video2any.com/decks/mit-what-is-computation/slide-{1..46}.jpg`
returns HTTP 200 (34 KB and 9 KB for slides 1 and 46), and `DejaVuSans-Bold.ttf` is present at the
path the script hardcodes (L23). `bench/fixtures/` is gitignored, so the fixtures are *regenerable*,
not *downloadable* — two scripts plus ffmpeg. Cheap to stand up, ~630 s of video total.

**Scoring** (`score()`,
[`bench/run.mjs:75-124`](https://github.com/larry-xue/video-slide-extractor/blob/221454d1cc296e75a2ddf83cd3ed587d5922c232/bench/run.mjs#L75-L124)):
greedy nearest-first 1:1 matching within ±2.5 s, then precision/recall/F1, then the pair this
project actually wants. Note the definition detail at
[`bench/run.mjs:106-108`](https://github.com/larry-xue/video-slide-extractor/blob/221454d1cc296e75a2ddf83cd3ed587d5922c232/bench/run.mjs#L106-L108):
an **unmatched** detection is attributed to the slide whose *dwell window contains it*
(`slideOf(t)`), not discarded. So a capture taken 4 s into slide 7 credits slide 7 with coverage
even though it is a false positive against the transition. **That is the correct behaviour for this
project and the wrong behaviour for theirs** — a mid-dwell capture is a perfectly usable slide
image. It is why `coverage` tracks misses while `recall` does not, and why the two columns diverge
only on the flooding rows. Lift `coverage`/`duplicateRate` as defined; do not lift precision/recall.

**Negative finding — the `count_builds` protocol is documented but never exercised.**
[`docs/evaluation.md`](https://github.com/larry-xue/video-slide-extractor/blob/221454d1cc296e75a2ddf83cd3ed587d5922c232/docs/evaluation.md)
§1-§3 specifies event-granularity CSV labels typed `slide`/`build` with `parent_slide`, and three
`count_builds` policies with an explicit rule (§4) to discard build-window detections under
`collapse-ignore`. **None of that exists in code.** The generator emits no `build` events (hard cuts
only, L80-81), the ground-truth JSON has no `type` field, and `score()` contains no build handling
whatsoever. The protocol this project's research proposed adopting *verbatim* has never been run by
its author. The design is still worth adopting — the argument at
[`docs/evaluation.md:23-27`](https://github.com/larry-xue/video-slide-extractor/blob/221454d1cc296e75a2ddf83cd3ed587d5922c232/docs/evaluation.md#L23-L27)
(*"encoding it into the labels forces a relabel whenever the task changes, and hides the decision
from anyone reading your numbers"*) is correct — but adopt it as an untested design, and budget for
writing the scorer.

**Verdict on fixtures:** *adopt as a sanity gate, reject as a reference set.* Hard cuts, synthetic
overlay, no crossfade, no camera motion, no builds, no revisits — `bench/README.md` says so itself.
Any candidate that cannot reach coverage 1.0 on `*-clean` is broken; passing tells you nothing
about the six real videos.

---

### A.6 Smaller source-only findings

- **`grabPoint` is a fixed absolute offset, not a proportional one.**
  [`cli.js:204-209`](https://github.com/larry-xue/video-slide-extractor/blob/221454d1cc296e75a2ddf83cd3ed587d5922c232/cli.js#L204-L209):
  grab at `seconds + 1/fps`, capped at the midpoint to the next detection and at `duration - 0.05`.
  At the default `--fps 1` that is **+1 second**. A 1.5 s crossfade still yields a half-faded
  export. `m2kar`'s 0.95-of-scene and `kovitking`'s middle-of-run are proportional and strictly
  better for the crossfade hard case. Lift the *idea* (never grab at the detected timestamp — the
  change happened somewhere inside the preceding sample interval, so seeking to `t` can land on the
  last frame of the *previous* slide), not the formula. Suggested: `min(t + max(1/fps, 0.25·dwell),
  midpoint)`.
- **No clean-frame selection of any kind.** No Laplacian variance, no sharpness ranking, no
  multi-candidate comparison within a dwell. One frame, one offset, exported. **Nothing in this repo
  addresses #17**; `docs/evaluation.md:109-112` says so explicitly: *"It does not collapse
  transitions, perform global perceptual deduplication, crop the slide region, or choose a clean
  high-resolution export frame."*
- **No dedupe beyond hysteresis.** The reference is the last *kept* frame
  ([`index.js:228-236`](https://github.com/larry-xue/video-slide-extractor/blob/221454d1cc296e75a2ddf83cd3ed587d5922c232/index.js#L228-L236)),
  so slow drift never accumulates — but there is no hash set, so **the camera-cutaway and
  slide-revisit hard cases are entirely unhandled**, by design.
- **Output naming.**
  [`cli.js:309-314`](https://github.com/larry-xue/video-slide-extractor/blob/221454d1cc296e75a2ddf83cd3ed587d5922c232/cli.js#L309-L314):
  `slide-001.png`, sequential detection order, zero-padded to `max(3, digits(count))` so it widens
  past 999. **The filename carries no timestamp** — timestamps survive only in `--json`
  (`index`, `seconds`, `timecode`, `ratio`, `grabbedAt`, `file`,
  [`cli.js:325-333`](https://github.com/larry-xue/video-slide-extractor/blob/221454d1cc296e75a2ddf83cd3ed587d5922c232/cli.js#L325-L333)).
  For this project's `pair` stage, a sidecar is mandatory or the transcript alignment is lost.
- **Nothing about audio or transcripts.** Grepping the whole repo for
  `audio|transcript|subtitle|whisper|srt` returns exactly one hit: the marketing outro string at
  [`cli.js:43`](https://github.com/larry-xue/video-slide-extractor/blob/221454d1cc296e75a2ddf83cd3ed587d5922c232/cli.js#L43).
  `ffprobe` is called with `-select_streams v:0`. Negative finding, cleanly.
- **A latent aliasing bug the CLI's own contract warns about.**
  [`cli.js:118-120`](https://github.com/larry-xue/video-slide-extractor/blob/221454d1cc296e75a2ddf83cd3ed587d5922c232/cli.js#L118-L120)
  states *"Yielded buffers are views into a shared read buffer and are only valid until the next
  frame: a consumer that retains one must copy it."* `collectCalibrationFrames` honours it
  (`Buffer.from(frame)`, L168). `createSlideDetector` does **not**: it retains via `frame.slice()`
  ([`index.js:228`, `:233`](https://github.com/larry-xue/video-slide-extractor/blob/221454d1cc296e75a2ddf83cd3ed587d5922c232/index.js#L228)).
  Verified in Node: `Uint8Array.prototype.slice()` copies, but **`Buffer.prototype.slice()` returns
  a view** (deprecated alias for `subarray`). The library is correct for its documented browser
  input type and silently unsafe for the Node `Buffer` its own CLI feeds it. It survives today only
  because `rawFrames` reallocates via `Buffer.concat` each chunk rather than overwriting in place
  ([`cli.js:139`](https://github.com/larry-xue/video-slide-extractor/blob/221454d1cc296e75a2ddf83cd3ed587d5922c232/cli.js#L139)).
  Not a technique to lift — a reminder that this code has not been run against adversarial buffering.
- **Edge rows and columns are never scored.** `frameDiff` uses
  `Math.floor(width / blockSize)` / `Math.floor(height / blockSize)`
  ([`index.js:49-50`](https://github.com/larry-xue/video-slide-extractor/blob/221454d1cc296e75a2ddf83cd3ed587d5922c232/index.js#L49-L50)),
  silently dropping up to 7 px at the right and bottom. At the CLI default 320×180 that is the
  bottom 4 px; at the benchmark's 160×90, the bottom 2 px. Irrelevant for slide bodies, relevant for
  **burned-in subtitles**, which live exactly there.
- **`extractSlideIndices(… {calibrate:true})` honours the caller's `changedRatio` over the
  calibrated one** ([`index.js:255`](https://github.com/larry-xue/video-slide-extractor/blob/221454d1cc296e75a2ddf83cd3ed587d5922c232/index.js#L255)),
  and the CLI documents the same precedence in a comment:
  *"An explicit `--changed-ratio` is the user overriding the calibration, so it wins; the mask is
  still worth keeping either way"*
  ([`cli.js:291-295`](https://github.com/larry-xue/video-slide-extractor/blob/221454d1cc296e75a2ddf83cd3ed587d5922c232/cli.js#L291-L295)).
  **This is the exact adoption recipe for a recall-first pipeline: take `analyzeSamples().mask`,
  discard `analyzeSamples().choice.changedRatio`, and pin your own low threshold.** It is already a
  supported code path, not a fork.
- **ffmpeg plumbing worth copying verbatim**: raw RGBA over a pipe with
  `-vf fps=N,scale=W:H -f rawvideo -pix_fmt rgba -` and manual frame reassembly
  ([`cli.js:121-156`](https://github.com/larry-xue/video-slide-extractor/blob/221454d1cc296e75a2ddf83cd3ed587d5922c232/cli.js#L121-L156));
  `-ss` **before** `-i` for the full-resolution re-extraction
  ([`cli.js:213`](https://github.com/larry-xue/video-slide-extractor/blob/221454d1cc296e75a2ddf83cd3ed587d5922c232/cli.js#L213));
  even-height forcing for yuv420p, `max(2, round(w·h/w/2)·2)`
  ([`cli.js:267`](https://github.com/larry-xue/video-slide-extractor/blob/221454d1cc296e75a2ddf83cd3ed587d5922c232/cli.js#L267));
  and an ENOENT handler that prints the three platform install commands
  ([`cli.js:92`](https://github.com/larry-xue/video-slide-extractor/blob/221454d1cc296e75a2ddf83cd3ed587d5922c232/cli.js#L92)).

---

### A.7 `awesome-video-to-slides` used as an index

#### A.7.1 The product benchmark has no labels

`bench/README.md` and `docs/research/slide-change-detection.md` §7.2 both point at a *"separate,
manually-labeled product benchmark protocol"* in this repo. It exists, and it is empty of labels.

[`benchmarks/2026-07-mit-60001/ground-truth-template.csv`](https://github.com/larry-xue/awesome-video-to-slides/blob/d1e90923a955ed3894ca91ac19a565deed8fea51/benchmarks/2026-07-mit-60001/ground-truth-template.csv)
is one header row (`slide_id,start_seconds,end_seconds,build_group,visual_description,notes,reviewer`)
plus a blank row. The README's own blockers list leads with *"Ground-truth intervals have not yet
been manually labeled"*
([`README.md:161-170`](https://github.com/larry-xue/awesome-video-to-slides/blob/d1e90923a955ed3894ca91ac19a565deed8fea51/benchmarks/2026-07-mit-60001/README.md#L161-L170)),
and it is explicit that the Video2Any 46-frame extraction *"is a product output, **not independent
ground truth**"*. **Question closed: there is nothing to reuse here.**

Two things in it *are* worth having:

- **A fully pinned real-lecture fixture**, free and licensed: MIT OCW 6.0001 Fall 2016 Lecture 1,
  `https://archive.org/download/MIT6.0001F16/MIT6_0001F16_Lecture_01_300k.mp4`, CC BY-NC-SA 4.0,
  101,137,401 bytes, SHA-256 `06236664b370ca2309aa5e74918a36a39512fad690ad9938d50b776217c02dcf`,
  2,585.964 s. A 43-minute real recording with byte-level identity, and the Video2Any 46-slide
  extraction available as a *labelling accelerant* (not as truth).
- **A real-footage flood measurement.** The smoke run
  ([`results/video-slide-extractor-default.md`](https://github.com/larry-xue/awesome-video-to-slides/blob/d1e90923a955ed3894ca91ac19a565deed8fea51/benchmarks/2026-07-mit-60001/results/video-slide-extractor-default.md))
  sampled 1,293 frames at 160×90 every 2 s and the detector **kept 809** — 62.6% of all samples.
  The runner calls `extractSlideIndices(frames, width, height)` with no `calibrate` and no mask
  ([`scripts/run-video-slide-extractor.mjs:30`](https://github.com/larry-xue/awesome-video-to-slides/blob/d1e90923a955ed3894ca91ac19a565deed8fea51/benchmarks/2026-07-mit-60001/scripts/run-video-slide-extractor.mjs#L30)),
  i.e. bare `changedRatio 0.02`. **This is the essential counterweight to A.4**: against a plausible
  ~46-slide truth that is ~17× over-capture. On synthetic hard cuts, `0.02` had duplicate rate 0; on
  a real lecture it keeps two frames in three. Recall-first does not mean threshold-free — it means
  the *mask and the dedupe*, not the threshold, must absorb the camera.

#### A.7.2 New candidates

The index lists 12 tools in `data/video-tools.json` (last reviewed 2026-08-28) — all SaaS/browser
products, no source. Cross-referencing every GitHub URL in the repo against
`docs/similar-tools.md` yields **three genuinely new repos**. (`szanni/slideextract`,
`binh234/video2slides`, `patrickmineault/vid2slides`, `tesseract`, `whisper.cpp` are already in the
survey. `OpenIGI/OpenIGI` and `adolfintel/weltendaemmerung` are unrelated — they appear only inside
a draft PR review of an unrelated game-preservation list.)

| Repo | License | Last push | Lang | Technique (from source skim) | Source read later? |
|---|---|---|---|---|---|
| [`andererka/MaViLS`](https://github.com/andererka/MaViLS) | Apache-2.0 | 2024-09-25 | Jupyter/Python | Video↔slide-PDF alignment by dynamic programming over merged OCR + sentence-embedding + image-feature matrices with a **slide-transition jump penalty** (default 0.1), plus a SIFT baseline. Interspeech 2024 paper. | **Yes — but for its dataset first** (see below) |
| [`sidharth-anand/lectures-2-slides`](https://github.com/sidharth-anand/lectures-2-slides) | MIT | 2021-10-17 | Python | SSIM (`skimage.structural_similarity`) on greyscale, `--threshold` default **0.82**, multiprocess over a directory of videos. Crucially applies a **manual `slide_bounds` rectangle crop before diffing** (`main.py:71-72`). | No — one number (SSIM 0.82) is the whole finding |
| [`Wangxs404/video2ppt`](https://github.com/Wangxs404/video2ppt) | MIT | 2025-11-03 | Python | 239 stars, single 201-line `main.py`. `extract_frames` is a **bare fixed-interval `cv2.imwrite` dump** — grepping the file for `similar|dedup|compare|hash|ssim|prev` returns **zero hits**. No change detection, no dedupe. | No |

Three notes on those:

- **`lectures-2-slides` confirms the #12 premise from a new angle.** It is the fourth project to
  need a slide region and the first to *ask the user to type it in* — `slide_bounds` is a
  `[x0,y0,x1,y1]` CLI argument applied to every frame of every video in the batch. Nobody computes
  it. And note *where* it is applied: **before** the SSIM comparison, i.e. the crop is a detection
  input, not just an export step. That is an argument for ordering crop before detect, which the
  current pipeline (`detect → crop`) does not do.
- **`video2ppt` is a clean "README claims X, code does Y".** Its README (and the `video2ppt.com`
  product it shares a name with) says "Convert videos to Slides"; the code screenshots every
  `fps_interval` seconds and stuffs the images into a PPTX. 239 stars is not evidence of technique.
- **`MaViLS` is the find.** Detailed below.

#### A.7.3 MaViLS

`docs/research/slide-change-detection.md` §10 concludes *"there is no public labelled slide-transition
dataset covering the three hard cases — the two public datasets that exist label frames, not
transitions."* MaViLS is a third one and it is materially better than that framing suggests.

Contents (Apache-2.0, sha `d1e909…` index entry; repo tree read via API):

- `data/audioscripts/*.srt` — **20 real lecture transcripts**, preprocessed with faster-whisper
  (MIT OCW ML-for-health / cognitive robotics / theory of computation / psychology / visual system,
  Goodfellow's deep learning, Silver's RL, Hennig's numerics, phonetics, cryptocurrency, …).
- `data/ground_truth_files/ground_truth_*.xlsx` — **human-labelled** alignment, one file per lecture.
- 22 source decks as PDF; `results/` holds 803 xlsx result sheets from the paper's runs.
- Videos are **not** in the repo — they are on Kaggle (link in README), so obtaining them needs an
  account. The labels, transcripts and decks are in git.

I decoded `ground_truth_deeplearning.xlsx` directly (3 columns: `Key`, `Slidenumber`, `Value`):

| Property | Value |
|---|---|
| Rows | 421 labelled instants over **3,249 s** (54 min — squarely this project's target length) |
| `Key` | timestamp in seconds of a transcript sentence |
| `Value` | the transcript sentence itself |
| `Slidenumber` | the slide PDF page visible at that instant, **or `-1` for "no slide on screen"** |
| Distinct slides | 38 |
| Derived transitions (`Slidenumber` changes) | 51 |
| **Revisit events** (a slide id reappearing after leaving) | **14** |
| **`-1` rows (no slide visible)** | 44 = **10.5%** |

What that buys, per ticket:

- **#11 — transitions and revisits on real footage.** 51 transitions and, critically, **14 revisit
  events in a single lecture**. The camera-cutaway / slide-revisit hard case has a labelled instance
  count here, across 20 videos. No reference implementation in the survey handles it; now it can be
  *measured*.
- **#17 — this is a labelled slide-frame gate dataset.** `Slidenumber = -1` is literally "this
  moment is not showing a slide", at a 10.5% positive rate on one lecture, with
  `evaluation/analyse_videos.py` computing *"the ratio between no slide and slide view"* across the
  set. That is exactly the label #17 needs to answer both of its questions — is a gate needed (what
  fraction of a real lecture is non-slide?) and must it be learned (can Laplacian variance or an
  intensity-histogram SVM separate the `-1` class?). **Training and test data for the SVM candidate
  already exists, human-labelled, Apache-2.0.**
- **`pair` stage** — the labels are keyed *by transcript sentence*, so slide↔transcript alignment is
  labelled too.

**Two caveats that decide how it can be scored.** Labels are at **transcript-sentence granularity**
(~7.7 s mean spacing in this file), not frame granularity, so a derived transition timestamp is the
first sentence spoken *while the new slide was already up* — it lags the visual cut by an unknown
amount. And a "slide" is a **PDF page**, so progressive builds are invisible (one page = one label).

Which means: MaViLS is **unusable for ±2 s transition matching** and **well-suited to a
coverage-style metric** — did the pipeline capture something during slide N's labelled span, and
how many extra captures did it produce. That is `(misses, surplus)` almost exactly. ADR-0003's
metric happens to be the one metric this dataset can support.

---

### A.8 Verdicts

| # | Technique | Source | Verdict | Ticket |
|---|---|---|---|---|
| 1 | Block-wise MAD diff (8 px, `blockDelta` 14) against the **last kept** frame | `index.js:47-82`, `:224-238` | **adopt** as the #11 baseline detector; sweep `changedRatio` **downward from 0.02** | #11 |
| 2 | `buildActivityMask` — count-of-changes per block, `activeFrac 0.5`, refuse if > `maxMaskFrac 0.35` | `index.js:98-119` | **adopt**; cheaper and as safe as `kovitking`'s median variant, and it is the deterministic answer to moving webcam overlay + embedded video | #11 |
| 3 | The same mask's block grid as the input to an activity-**complement** projection-profile crop | `index.js:112-118` | **measure in the spike** — this is #12's missing primitive, MIT-licensed, 22 lines. Nothing in the repo crops. | **#12** |
| 4 | Otsu bimodality **guard** (`m1 < 3·m0 + 0.004` → fall back) | `index.js:149` | **adopt the guard**; it is what makes any auto-threshold shippable | #11 |
| 5 | The Otsu **threshold itself**, and `chooseThreshold`'s `motion` regime | `index.js:130-186` | **reject as shipped.** Broken at 45–60 min by the `stride` time-scale mismatch (A.1.1), and it optimises precision. Use `analyzeSamples().mask`, discard `.choice.changedRatio` — a supported path (`index.js:255`, `cli.js:291-295`) | #11 |
| 6 | `changedRatio = 0.10` | `bench/run.mjs:130` | **reject.** Fitted to a 9.1%-of-blocks synthetic overlay; loses on misses in all 6 fixtures | #11 |
| 7 | `coverage` + `duplicateRate`, with unmatched detections credited to the containing dwell | `bench/run.mjs:100-113` | **adopt the scoring shape** — it is `(misses, surplus)` with different names | #11 |
| 8 | `count_builds` event-granularity labelling protocol | `docs/evaluation.md` §1-§4 | **adopt as design, budget the implementation** — it has never been run; no code implements it | #11 |
| 9 | Generated-fixture harness (seeded PRNG, three degradation variants) | `bench/generate-fixtures.mjs` | **adopt as a pre-flight sanity gate only** — verified regenerable today | #11 |
| 10 | `grabPoint` — never export at the detected timestamp | `cli.js:204-209` | **adopt the principle, replace the formula** with a proportional offset | #11 |
| 11 | Calibration-frame sampling (whole-video stride) | `cli.js:163-173` | **adopt the "see the whole recording" rationale, redesign as contiguous bursts** so calibration and detection share a time-scale; seek rather than stream to avoid a second full decode | #11 |
| 12 | MaViLS dataset — 20 lectures, human labels, `-1` = no slide, srt transcripts | `andererka/MaViLS`, Apache-2.0 | **adopt as a reference set**, scored by coverage not transition-matching | **#11 + #17** |
| 13 | MIT 6.0001 L1 fixture (SHA-256 pinned, CC BY-NC-SA 4.0, 2,585.964 s) | `awesome-video-to-slides` benchmark README | **adopt as one of the six real videos** | #11 |
| 14 | SSIM @ 0.82 with a manual `slide_bounds` crop applied **before** diffing | `sidharth-anand/lectures-2-slides:71-82` | **measure** the 0.82 SSIM point; note the crop-before-detect ordering, which the current pipeline does not do | #11, #12 |
| 15 | Clean-frame selection / slide-frame gate | — | **negative finding**: nothing here, stated explicitly at `docs/evaluation.md:109-112` | #17 |
| 16 | Audio / transcript | — | **negative finding**: zero handling; `ffprobe -select_streams v:0` | — |

---

## Group B — bit-admin/AutoSlides-Extractor

**Cloned:** `git clone --depth 1 https://github.com/bit-admin/AutoSlides-Extractor.git`
**HEAD sha:** `e0899cdc643937e06fb4e45220a18ffd8de10639` (v2.0.0 line, CHANGELOG dated 2026-08-08)
**Licence:** MIT, `Copyright (c) 2025 bit-admin` ([LICENSE](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/LICENSE)). Code is freely liftable.
**Language:** C++17 / Qt 6 / OpenCV / FFmpeg / ONNX Runtime — ~21 kLOC in `src/`. Not Python; the value is the design and the two shipped model files, not the dependency.
**Bundled weights:** `resources/models/slide_classifier_mobilenetv4_v1.onnx` (33.7 MB) and `resources/models/slide_detector_yolov8_v1.onnx` (12.3 MB). **Neither has any stated licence, model card, training-data provenance or attribution anywhere in the repo** — see §7.3.

All permalinks below are pinned to `e0899cdc643937e06fb4e45220a18ffd8de10639`.

---

### B.0 Corrections

Five of the claims recorded there do not survive contact with the source. Two of them invalidate a spike design.

| Claim in our §9.2 | What the code does | Where |
|---|---|---|
| "SSIM as the change metric" | **Not SSIM.** A *single-window global* correlation using SSIM's C1/C2 constants — one mean/variance/covariance over the whole 480×270 grey image. No 7×7 or 11×11 window, no per-pixel SSIM map, no mean-of-map. | §2.1 |
| presets 0.999 / 0.9985 / 0.998 | Correct (`Strict`/`Normal`/`Loose`), **but they are calibrated to the global formula and are meaningless for windowed SSIM** — measured in §2.4. | §2.2 |
| "3-sample verification window" | It is a *look-ahead over SSIM scores*, not a majority vote and not 3 frames. With `verificationCount=3` it requires the **next 2 consecutive scores** also to be ≥ threshold — i.e. 4 consecutive samples of identical content. Any single dip **aborts and restarts from the dip**. | §4 |
| "3-class MobileNetV4 gate **via OpenCV DNN**" | Runs through the **ONNX Runtime C++ API** (`Ort::Session`), not `cv::dnn`. The checkpoint filename `…_opencv.pth` refers to the *resize convention* (INTER_AREA), not the runtime. The README says ONNX Runtime; our note got this wrong, not theirs. *(Good news: I verified the model also loads and runs correctly under `cv2.dnn` — §6.4.)* | §6.1 |
| implied: gate runs during detection | The gate runs **only in post-processing, over already-exported slide JPEGs on disk** — never on video frames. Batch size is 1 (`classifyBatch` is a `for` loop with a `TODO: Implement true batch processing`). | §6.2 |

Also worth correcting the framing in `docs/research/slide-region-crop.md`: **this repo is a counter-example to "no surveyed project actually crops to the slide region".** It ships a complete, tuned, two-backend slide-bbox detector (`AutoCropDetector`) plus a trained YOLOv8 slide-region model. #12 is not greenfield. See §7.

---

### B.1 Pipeline shape

```
FFmpeg decode (I-frames only)  →  chunk of 100 frames
   → global-SSIM between adjacent samples  → threshold + 3-sample verification → write slide_<video>_NNN.jpg + timeline.json event
   → POST: pHash all-pairs dedupe → pHash exclusion list → MobileNetV4 gate
          → may_be_slide: try auto-crop (Canny→YOLO); keep if it succeeds, else trash
          → re-hash the cropped files and dedupe AGAIN
```

Nothing is ever deleted: everything goes to `.extractorTrash/` with a reason tag, and `timeline.json` keeps the event and rewrites only its *resolution*. There is **no audio, transcript, subtitle or speech handling anywhere in the repo** (grep for `audio|transcript|subtitle|srt|whisper` over `src/` returns zero hits) — negative finding for our `pair` stage.

---

### B.2 The change metric

#### B.2.1 Exact implementation

[`src/ssimcalculator.cpp#L560-L601`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/ssimcalculator.cpp#L560-L601):

```cpp
processedImg1 = downsampleImage(img1, downsampleWidth, downsampleHeight); // 480x270, INTER_AREA
gray1 = convertToGrayscale(processedImg1);                                 // COLOR_BGR2GRAY
double mean1 = calculateMean(gray1);  double var1 = calculateVariance(gray1, mean1);
double covariance = calculateCovariance(gray1, gray2, mean1, mean2);
double numerator   = (2 * mean1 * mean2 + C1) * (2 * covariance + C2);
double denominator = (mean1 * mean1 + mean2 * mean2 + C1) * (var1 + var2 + C2);
```

- **Window:** none. Four scalars over the entire image. Identical formula in the SIMD path, [`ssimcalculator.cpp#L171-L173`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/ssimcalculator.cpp#L171-L173) (comment there literally says *"Calculate SSIM using the global formula"*).
- **Channels:** 1, BGR→grey, Rec.601 luma.
- **Downscale:** forced `cv::resize(..., cv::Size(480,270), INTER_AREA)` — [`#L621-L636`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/ssimcalculator.cpp#L621-L636). **Aspect ratio is not preserved**; a 4:3 capture is squashed. Skipped entirely if the source is already ≤480×270.
- **Constants:** `C1 = 6.5025`, `C2 = 58.5225` = `(0.01·255)²`, `(0.03·255)²` — [`ssimcalculator.h#L106-L107`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/ssimcalculator.h#L106-L107).
- Result clamped to [0,1] in the SIMD path but **not** in `calculateGlobalSSIM` — the production path can return values slightly outside [0,1]. Degenerate case `denominator == 0` returns `1.0` ("both images uniform") — so **two consecutive pure-black frames score a perfect 1.0 and never fire.**

#### B.2.2 Presets and where they live

[`src/configmanager.cpp#L167-L181`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/configmanager.cpp#L167-L181):

| Preset | Threshold | README's stated tuning target ([README.md#L217-L228](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/README.md#L217)) |
|---|---:|---|
| Strict | `0.999` | "Videos where small slide changes are being missed" |
| Normal | `0.9985` | "Typical lecture recordings and screen captures" — the default |
| Loose | `0.998` | "Videos with animations, cursor movement, or noisy compression" |

Change fires when `score < threshold` ([`slidedetector.cpp#L184`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/slidedetector.cpp#L184)), so **higher preset = more captures**. The naming is counter-intuitive but the README is consistent with the code. There is no evidence in the repo that these were tuned against a labelled corpus — no test set, no benchmark, no fixtures. Treat them as field-tuned defaults, not measured optima.

Other defaults, [`src/configmanager.h#L103-L130`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/configmanager.h#L103-L130): `downsample 480×270` on, `chunkSize 100`, `jpegQuality 95`, `hammingThreshold 10`, `verificationCount 3`, `frameInterval 2.0` (**dead — see §3**).

#### B.2.3 Cost, measured on the target host

Measured on this machine, which **is** the #11 target host (`Intel(R) Core(TM) i3-4170 CPU @ 3.70GHz`, 4 threads), via a NumPy/OpenCV transliteration of the C++ (the C++ SIMD path will be faster; these are upper bounds):

| operation (1080p input pair) | median |
|---|---:|
| `cv2.resize` 1080p → 480×270 INTER_AREA | 3.3 ms |
| **global SSIM** (incl. both downscales) | **12.6 ms/pair** |
| **windowed SSIM, 7×7 uniform** (incl. both downscales) | **23.1 ms/pair** |

#### B.2.4 The measurement that should change the #11 spike

I compared the AutoSlides global formula against standard windowed SSIM (7×7 uniform, mean-of-map — the `skimage.metrics.structural_similarity` shape) on synthetic 1080p slides pushed through JPEG at several qualities to simulate two independently-encoded I-frames of the *same* static slide.

| case (480×270 grey, both metrics) | global | windowed 7×7 |
|---|---:|---:|
| **noise floor** — same slide, 2 I-frames @ q90 | 0.999876 | 0.995634 |
| **noise floor** — same slide, 2 I-frames @ q75 | 0.999956 | 0.999081 |
| **noise floor** — same slide, 2 I-frames @ q50 | 0.999207 | **0.972660** |
| signal — +1 bullet on a 12-item agenda (any step) | 0.83 – 0.96 | ≈0.9828 (flat) |
| signal — burned-in subtitle line changes, slide static | 0.9818 | 0.9890 |
| signal — webcam overlay moves 40 px | 0.9597 | 0.9652 |
| signal — cut to speaker | 0.0289 | 0.3648 |
| non-signal — whole frame dimmed 3 % (AGC) | 0.998980 | 0.999384 |

**The two metrics are not interchangeable at these thresholds.** For the global formula the noise floor sits at 0.9992–0.99996 and the weakest real signal at ≈0.96 — two orders of magnitude of separation, and `0.9985` sits cleanly in the gap. For windowed SSIM at q50 the noise floor (0.9727) falls *below* its own build signal (0.9828): at `0.9985` it fires on **every** pair and the detector degenerates to "every sample is a slide".

> **If the #11 spike implements SSIM as `skimage.metrics.structural_similarity` and reuses 0.999 / 0.9985 / 0.998 because "AutoSlides uses those", it will measure garbage and wrongly eliminate SSIM from the shortlist.** The spike must treat *global-statistics SSIM* and *windowed SSIM* as **two separate candidates**, each with its own threshold sweep. The global variant is also the cheaper one (12.6 ms vs 23.1 ms/pair).

Note also the shape difference: windowed SSIM's response to a progressive build is **flat** (~0.9828 whether it is step 1→2 or 11→12), while global degrades monotonically (0.833 → 0.957) as the slide fills up. Global is more discriminative early and converges towards its floor late — so on a very dense slide with a tiny reveal it will eventually stop firing, whereas windowed will not. That trade-off is exactly what the spike should measure.

#### B.2.5 GPU SSIM was ripped out as dead code

CHANGELOG 1.2.2 (2026-06-06): *"Deleted the entire GPU-SSIM optimization layer (~5,166 lines) … The CUDA/OpenCL/Metal/DirectX SSIM backends were incomplete stubs (empty `createGPUCalculators()`, undefined CUDA kernel, wrong OpenCL math…)"*. Five thousand lines of GPU SSIM that were never once called. **Verdict: reject any GPU/accelerated-SSIM ambition for our no-GPU host.** Their live acceleration is a SIMD path plus a `cv::Mat` buffer pool ([`ssimcalculator.cpp#L22-L94`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/ssimcalculator.cpp#L22-L94)) — that part is worth copying in spirit (reuse buffers, downscale once per frame not once per pair).

---

### B.3 Frame sampling

The production path is `HardwareDecoder::extractFramesInChunks` ([`hardwaredecoder.cpp#L502-L611`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/hardwaredecoder.cpp#L502-L611)). It walks packets and **decodes only key packets**:

```cpp
bool isIFrame = (m_packet->flags & AV_PKT_FLAG_KEY);
if (isIFrame) { ... shouldDecode ... }
```

The `double targetInterval` parameter is **never read** in that function body. And the only caller hardcodes it anyway — [`processingthread.cpp#L454-L459`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/processingthread.cpp#L454-L459):

```cpp
int totalFrames = decoder.extractFramesInChunks(chunkCallback, progressCallback, chunkSize,
                                                2.0  // Use 2 seconds as the ideal target interval
                                                );
```

`m_config.frameInterval` (default 2.0, [`configmanager.h#L105`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/configmanager.h#L105)) never reaches the decoder. **The sampling cadence is the encoder's GOP, not a time grid, and the user cannot change it.**

The only cadence control is a GOP-length heuristic, [`hardwaredecoder.cpp#L364-L377`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/hardwaredecoder.cpp#L364-L377), driven by a measured average I-frame interval over the first N packets ([`#L272-L317`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/hardwaredecoder.cpp#L272-L317)):

| measured avg GOP | strategy | effective sample interval |
|---|---|---|
| ≥ 4.0 s | `UseAllIFramesWarn` | ≥ 4 s |
| 1.6 – 1.9 s | `UseAllIFrames` | ~1.75 s |
| 1.0 – 1.5 s | `SkipEveryOtherI` | ~2 – 3 s |
| everything else (incl. < 1.0 s) | `UseAllIFrames` | = GOP |

**Consequence for #11, and it is severe.** The verification window (§4) is counted in *samples*, so the dwell a slide must survive is `verificationCount × GOP`, which varies per file and is unbounded. On a source with a 5-second GOP (common for re-encoded/streamed lecture recordings), a slide must be on screen ~15 s to be captured at all; anything shorter is a **silent miss**, and the tool has no way to know. There is a `UseAllIFramesWarn` enum value but grepping shows it is never surfaced to the user.

**Verdict — adopt the inverse, #11.** We control ingestion (we re-encode/normalise at `fetch`), so we should sample on an explicit fixed time grid and make the interval a first-class spike variable. Keyframe-only sampling is a decode-cost optimisation that silently couples detection recall to the source encoder. Worth one row in the #11 matrix nonetheless: "sample at I-frames only" is the cheapest possible decode and the measurement will show what it costs in misses.

---

### B.4 The verification window

[`src/slidedetector.cpp#L181-L308`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/slidedetector.cpp#L181-L308). The loop walks the score array `scores[i] = ssim(frame[i], frame[i+1])`:

```cpp
if (result.ssimScores[i] < ssimThreshold) {                 // transition detected
    int potentialSlideLocalIndex = i + 1;
    for (int j = 0; j < currentVerificationCount - 1; ++j) { // 2 more scores for count==3
        int checkIndex = potentialSlideLocalIndex + j;
        if (checkIndex >= scores.size())      { isStable = false; verificationFailedAt = checkIndex; break; }
        if (scores[checkIndex] < ssimThreshold) { isStable = false; verificationFailedAt = checkIndex; break; }
    }
    if (isStable) {
        int newStableLocalIndex = potentialSlideLocalIndex + currentVerificationCount - 1;  // = i + 3
        state.savedSlideIndices.push_back(newStableGlobalIndex);
        i = newStableLocalIndex;                            // jump past
    } else if (verificationFailedAt != -1) {
        i = verificationFailedAt;                           // restart AT the instability
    }
}
```

Precisely:
- **Not** a majority vote, **not** 3 frames — it is **all-must-agree over `verificationCount − 1 = 2` subsequent scores**, i.e. frames `i+1, i+2, i+3` must be mutually stable. Four frames total participate.
- **Latency:** confirmation lands `verificationCount − 1 = 2` samples after the change. At the observed ~1.75–2 s cadence that is **~4 s**; at a 5 s GOP, **10 s**.
- **Cost in missed builds:** a change is dropped entirely if *any* of the two following scores dips. During an embedded video, an animated transition, a moving webcam overlay or a hand-held camera, **every** window fails and `i` restarts at the failure point — the detector can walk an entire animated segment and save nothing. This is the repo's dominant miss mode and it is silent. The README's "The App Misses Slides" advice ([README.md#L905-L912](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/README.md#L905)) is *"Check whether the video contains long animations or transition effects"* — an acknowledgement without a fix.
- `verificationCount` **is** configurable in the struct (and `enableVerification` exists) but there is no CLI flag and no GUI control for it — effectively hardcoded to 3, which matches our prior note.
- The state machine survives chunk boundaries: `VerificationState::VERIFICATION_1OF3 / 2OF3 / 3OF3` is carried in `ProcessingState` and the remaining count is resumed at `i == 0` of the next chunk ([`#L218-L235`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/slidedetector.cpp#L218-L235)), with a one-frame overlap (`workingFrames = [lastFrame] + newFrames`, [`#L145-L161`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/slidedetector.cpp#L145-L161)). Worth copying if we ever chunk; ignorable if we hold the score array in memory (a 60-min video at 1 fps is 3600 doubles).

**Edge handling** ([`#L170-L177`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/slidedetector.cpp#L170-L177), [`#L311-L349`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/slidedetector.cpp#L311-L349)): the **first frame is always saved unconditionally**, and at EOF there are two special cases (if the last stable index was `n-2`, save the final frame regardless; if it was `n-3`, save it only if the last pair is similar). Both exist because the verification look-ahead cannot complete near the end — otherwise the final slide of every talk is lost. **Adopt: our detector needs the same two guards, and the first-frame and last-slide cases belong in the #11 ground truth explicitly.**

**Verdict — measure in the spike (#11).** "Require the next K samples to agree, restart at the first dip" is a cheap, deterministic stabiliser worth one axis in the matrix, with K swept — but note its recall bias runs *against* our stated preference. Recall-over-precision argues for K=1 (fire on every change, let `drop` clean up), or for restarting *after* the dip rather than at it.

---

### B.5 pHash and the exclusion list

#### B.5.1 The hash

[`src/phashcalculator.cpp#L17-L82`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/phashcalculator.cpp#L17-L82) — a **256-bit** pHash, wider than the usual 64-bit:

1. `COLOR_BGR2GRAY`; 2. `cv::resize` to **64×64** with `INTER_LINEAR` (note: *not* INTER_AREA, unlike the SSIM and ML paths); 3. `cv::dct` on CV_32F; 4. keep the top-left **16×16** low-frequency block; 5. **drop the DC term**; 6. median of the remaining **255** AC coefficients; 7. bit = `coeff >= median`, MSB-first into 32 bytes.

Constants at [`phashcalculator.h#L71-L72`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/phashcalculator.h#L71-L72): `HASH_SIDE_DIM = 16`, `DCT_SIDE_DIM = 64` (*"4x hash dimension"*). Only 255 of the 256 bits are ever set; the last bit is always 0. Hamming via Brian Kernighan popcount ([`#L113-L130`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/phashcalculator.cpp#L113-L130)). Serialised as a 64-char hex string.

**The radius is 10 bits out of 255** (`hammingThreshold`, default 10) — i.e. ~3.9 % of bits, a *much* tighter relative radius than the usual "≤10 of 64" (15.6 %) rule of thumb quoted for 64-bit pHash. Anyone porting the constant without porting the hash width will be ~4× too permissive. README tuning guidance ([#L275-L285](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/README.md#L275)): *"Start with small changes such as 8, 10, 12, and review results."*

#### B.5.2 Dedupe is all-pairs, not adjacent

[`postprocessor.cpp#L154-L211`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/postprocessor.cpp#L154-L211) is an O(n²) double loop over every exported image, keeping the **first** and trashing every later match. So a slide the speaker **returns to** 20 minutes later is removed as a duplicate — and crucially the timeline is *re-linked*, not erased:

```cpp
TimelineMetadata::markDuplicate(dir, QFileInfo(file2).fileName(), QFileInfo(file1).fileName());
// "Keep event; re-link later span to first-kept basename"
```

**This is the right answer to the "returns" case in ADR-0003 and we should adopt the pattern**: dedupe the *image*, keep the *event*, point the second occurrence's transcript span at the first-kept file. Our `pair` stage then emits two transcript spans against one screenshot, which is what a reader actually wants.

#### B.5.3 The exclusion list

- **Structure:** `ExclusionEntry { remark, hashHex, hashBytes }` ([`postprocessor.h#L15-L23`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/postprocessor.h#L15-L23)).
- **Persistence:** `QSettings` (platform-native: registry / plist / INI), flattened as `exclusionListSize` + `exclusionRemark_<i>` / `exclusionHash_<i>` — [`configmanager.cpp#L214-L268`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/configmanager.cpp#L214-L268). Note the careful three-state load: key absent → ship the defaults; `size == 0` → the user deliberately cleared it, return empty; otherwise load.
- **How entries get added: manually, by the user only.** README [#L291-L294](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/README.md#L291): *"Add from Image"* (pick a file, the app hashes it) or paste 64 hex chars. There is **no code path anywhere that learns or auto-appends an entry.** Our prior note's "a persisted pHash exclusion list nothing else offers" is accurate; the implied automation is not there.
- **Radius:** the *same* `hammingThreshold` (10) as the dedupe pass — not separately tunable ([`postprocessor.cpp#L233`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/postprocessor.cpp#L233)).
- **When consulted:** post-processing only, after dedupe, before the ML gate; first match wins (`break`) and the file is trashed as `phash_excluded` with the timeline event marked `gap / "exclusion"`.
- **On a false positive:** nothing is lost. The file is in `.extractorTrash/` with the reason and the Hamming distance in the message; Slides Review can filter by reason and **Restore Selected** ([README #L923-L929](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/README.md#L923)), which flips the timeline resolution back to `canonical`.
- CLI can also pass ad-hoc hashes for one run without persisting: `--phash-exclusion-hashes <hex>,<hex>` ([README #L637-L640](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/README.md#L637)).

#### B.5.4 Field-failure workaround not in the README

[`postprocessor.cpp#L531-L549`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/postprocessor.cpp#L531-L549) ships **two hardcoded hashes by default**, and the README never mentions that the list is non-empty on first run:

```cpp
ExclusionEntry entry1("No_Signal_1", "99c799ce6638663399c799ce6638663199c799ce6638663199c799ce66386630");
ExclusionEntry entry2("No_Signal_2", "2ddb2658d224d1a72ddb2e58d264d1a7299b2f58d664d4a7299b091ad664f6e4");
```

These are the **HDMI capture-card "No Signal" screens**. That is a pure field-failure artefact: when a lecture capture rig loses the projector feed, the capture shows a perfectly static "No Signal" card, which the SSIM detector *loves* — it is maximally stable, sails through verification, and gets exported as a slide, possibly many times. Two constants in the source are the entire fix. (The ML gate's `not_slide` class covers the same case per README #L312, so they defend it twice.)

**Verdict — adopt the mechanism, not the hashes (#11).** A user-extensible, persisted "never capture this frame" list is genuinely the only such feature in the surveyed set, it is ~40 lines, and it composes perfectly with our recall-over-precision stance: capture everything, then let a per-user list suppress the known-junk recurrences across runs. Our hashes will be different (Zoom "reconnecting", Meet waiting-room, OBS "no source", desktop wallpaper).

---

### B.6 The MobileNetV4 slide-frame gate

#### B.6.1 Model facts

[`resources/models/model_info.json`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/resources/models/model_info.json):

| field | value |
|---|---|
| classes | `may_be_slide`, `not_slide`, `slide` (indices 0,1,2) |
| architecture | `mobilenetv4_conv_medium.e500_r256_in1k` (a `timm` backbone) |
| input | `[1, 3, 256, 256]`, NCHW float32 |
| normalisation | ImageNet mean `[0.485,0.456,0.406]` std `[0.229,0.224,0.225]` |
| quantisation | `"none"` — full fp32, 33.7 MB on disk |
| reported val acc | `99.2748 %` at **epoch 4** of 50, batch 64, lr 1e-3, wd 1e-4, patience 10 |
| exporter | PyTorch 2.5.1 (from the ONNX producer string) |

Best accuracy at epoch 4 out of a planned 50, on an unnamed `dataset` directory with no held-out description, is a number to distrust: a near-ceiling score that early usually means an easy or leaky split. **Do not carry 99.27 % into #17 as an expectation.**

#### B.6.2 Where it runs, and on what

`PostProcessor::classifyAndRemove` ([`postprocessor.cpp#L261-L415`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/postprocessor.cpp#L261-L415)) runs it over `imageHashes.keys()` — **the surviving exported JPEGs on disk**, after pHash dedupe. So it sees O(number of slides) ≈ tens of images per talk, not O(number of frames) ≈ thousands. It is a *cleanup* filter, not a detection gate. `classifyBatch` is a loop over `classifySingle`, batch size 1, with an explicit `// TODO: Implement true batch processing for better performance` ([`mlclassifier.cpp#L130-L141`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/mlclassifier.cpp#L130-L141)).

#### B.6.3 The decision rule

[`mlclassifier.cpp#L143-L190`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/mlclassifier.cpp#L143-L190). Five thresholds, two stages, conservative in every branch:

```cpp
auto shouldDelete = [&](const CategoryThresholds& t) {
    if (confidence >= t.highThreshold) return true;                     // stage 1
    if (confidence >= t.lowThreshold && slideProb <= slideMaxThreshold) // stage 2
        return true;
    return false;
};
if (predictedClass == "slide")              return true;                // never delete
if (startsWith("not_slide"))                return !shouldDelete(notSlideThresholds);
if (startsWith("may_be_slide"))             return deleteMaybeSlides ? !shouldDelete(maybeSlideThresholds) : true;
return true;                                                            // unknown class -> keep
```

Defaults: `notSlideHigh/Low = 0.9 / 0.75`, `maybeSlideHigh/Low = 0.9 / 0.75`, `slideMax = 0.25` ([`configmanager.h#L126-L130`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/configmanager.h#L126-L130)).

Three things worth lifting verbatim:
1. **Every failure path keeps the image** — classification error keeps, unknown class keeps, `slide` always keeps. Exactly our recall-over-precision stance, expressed as code.
2. **The second stage is a veto, not a second opinion.** A medium-confidence `not_slide` is only deleted if the *slide* probability is also low (≤0.25). A frame the model calls "probably not a slide, but it does look 0.4 slide-ish" survives. This is the pattern to copy for any gate we ship.
3. **The third class is an explicit "I don't know" bucket with its own downstream route** (§8), rather than a forced binary.

#### B.6.4 Cost on the target host

`opencv-python-headless` is already a project dependency and its `cv2.dnn` module loads **both** shipped ONNX files without ONNX Runtime. Measured on the i3-4170, `DNN_BACKEND_OPENCV` / `DNN_TARGET_CPU`, median of 8 runs after warm-up:

| model | input | output | median | min |
|---|---|---|---:|---:|
| `slide_classifier_mobilenetv4_v1.onnx` | 1×3×256×256 | `(1, 3)` | **22.5 ms** | 20.8 ms |
| `slide_detector_yolov8_v1.onnx` | 1×3×640×640 | `(1, 5, 8400)` | **89.6 ms** | 85.8 ms |

And it produces correct semantics, not just correct shapes — replicating their exact preprocessing (BGR→RGB, INTER_AREA to 256×256, /255, ImageNet norm, NCHW) and softmaxing the logits:

| input | may_be_slide | not_slide | slide |
|---|---:|---:|---:|
| synthetic title+bullets slide | 0.000 | 0.000 | **1.000** |
| pure black frame | 0.051 | **0.876** | 0.073 |
| uniform RGB noise | **0.781** | 0.170 | 0.049 |
| slide letterboxed inside a black 1080p frame | 0.000 | 0.000 | **1.000** |

**What this does to #17.** The premise that a learned gate is the expensive option does not hold on this hardware. At 22.5 ms/frame:

| gate applied to | frames (45-min video) | wall time |
|---|---:|---:|
| every frame @ 1 fps | 2 700 | **61 s** |
| every frame @ 0.5 fps (2 s grid) | 1 350 | **30 s** |
| only detected slides (~40) | 40 | **0.9 s** |

61 seconds, single-threaded, for a whole-video gate on the target host — against 12.6 ms for one global-SSIM pair and 23.1 ms for one windowed-SSIM pair. **A MobileNetV4 inference costs about the same as a single windowed-SSIM comparison.** Cost is therefore not a reason to prefer a deterministic gate; only determinism, licensing and explicability are. Conversely the gate is cheap enough to be evaluated as a *detector input* (per-frame `slide` probability as a signal, not just a post-filter) — which is not how AutoSlides uses it and is not currently in the #17 plan.

**Verdict — measure in the spike (#17), with a caveat.** These weights are a ready-made, zero-training baseline runnable from `cv2.dnn` today with no new dependency. Bench Laplacian variance and the intensity-histogram SVM *against this*, and the comparison becomes meaningful rather than theoretical. The caveat is §7.3: the weights have no licence. Use them to establish the ceiling; do not ship them until that is resolved.

#### B.6.5 Preprocessing workaround not in the README

[`mlclassifier.cpp#L563-L568`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/mlclassifier.cpp#L563-L568) — a comment recording a real debugging session:

```cpp
// INTER_AREA is the correct method for downsampling to match PIL's LANCZOS and Sharp's lanczos3
// Testing confirmed: INTER_AREA produces RGB(141,55,43) vs Sharp's RGB(140,55,43) - nearly identical!
// Other methods produce significantly different results (CUBIC: 168,59,48 / LANCZOS4: 168,62,50)
```

A ~27-unit-per-channel systematic shift from picking the wrong interpolation — far more than ImageNet normalisation tolerates, and enough to move predictions. **Adopt as a rule: when running someone else's weights, the resize kernel is part of the model contract.** Our pipeline must use `INTER_AREA` for any downsample feeding these weights. Also note they squash to 256×256 without preserving aspect (unlike the YOLO path, which letterboxes) — so the classifier was trained on distorted images and we must distort identically.

---

### B.7 Auto-crop: #12 is not greenfield

`AutoCropDetector` ([`autocropdetector.h`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/autocropdetector.h), [`.cpp`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/autocropdetector.cpp), 552 lines) returns a slide bounding box in original-image pixels. Three modes ([`configmanager.h#L17-L21`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/configmanager.h#L17-L21)): `CannyThenYolo` (default), `CannyOnly`, `YoloOnly`. Fallback order at [`autocropdetector.cpp#L249-L258`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/autocropdetector.cpp#L249-L258): try Canny; if invalid, try YOLO; if both fail, return invalid (and surface Canny's error).

The header notes it *"Mirrors the Electron auto-crop worker (REFERENCE/autoCrop.worker.ts)"* — a prior JS implementation not present in this repo, so these constants have been through at least two implementations.

#### B.7.1 The Canny backend

[`autocropdetector.cpp#L266-L343`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/autocropdetector.cpp#L266-L343):

1. **Grey**, then strip black borders ([`#L24-L63`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/autocropdetector.cpp#L24-L63)): walk rows/cols inward while the row/col **mean** ≤ `blackThreshold`, capped at `maxBorderFrac` of the dimension. This is exactly our #12 candidate 1 — but note it is used only as a *preprocessing* step, never as the output.
2. `cv::Canny(inner, edges, cannyLowThreshold, cannyHighThreshold)`.
3. `cv::dilate` with a **3×3 ones** kernel (closes dashed slide borders).
4. `cv::findContours(RETR_LIST, CHAIN_APPROX_SIMPLE)`.
5. Per contour, five gates in order, then a score:
   - `approxPolyDP(cnt, 0.02 * arcLength)` must yield **exactly 4 vertices**;
   - `areaRatio = boundingRect.area / innerArea` ∈ [`areaRatioMin`, `areaRatioMax`];
   - **margin gate** — `marginTop` OR `marginBottom` ≥ `marginFrac`; this is what stops the algorithm returning the whole frame;
   - `fill = contourArea / boundingRect.area` ≥ `fillRatioMin` (rejects L-shapes and ragged blobs);
   - `aspectScore = max(0, 1 − min_over{16:9, 4:3}(|a − aᵣ|/aᵣ) / aspectTolerance)` must be > 0.
   - **score = `areaRatio × aspectScore`** → keep the max. Biggest box that is most nearly a standard slide aspect.
6. Translate back to full-image coordinates and intersect with the frame.

Tuned constants, [`configmanager.h#L23-L42`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/configmanager.h#L23-L42):

| constant | default | role |
|---|---:|---|
| `aspectTolerance` | `0.05` | ±5 % relative around 16:9 or 4:3 |
| `blackThreshold` | `20.0` | row/col mean below this is "black border" |
| `maxBorderFrac` | `0.10` | never strip more than 10 % per side |
| `cannyLowThreshold` / `High` | `20` / `60` | deliberately low — slide borders are faint |
| `areaRatioMin` / `Max` | `0.08` / `0.95` | slide occupies 8–95 % of the de-letterboxed frame |
| `marginFrac` | `0.02` | require ≥2 % margin top **or** bottom |
| `fillRatioMin` | `0.85` | contour must fill 85 % of its bounding box |
| `SUPPORTED_ASPECTS` | `{16/9, 4/3}` | hardcoded, [`autocropdetector.cpp#L20`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/autocropdetector.cpp#L20) |

> **Reversed by the crop spike ([ADR 0006](../adr/0006-crop-by-cutting-the-presenter-away.md)).**
> Reimplemented at these exact constants and run on this project's fixtures, it fails on the two
> the crop stage exists for. On `jqpdveK2XAU` it returns **nothing on all 19 captures** — the
> dilated edge map merges the slide's border with its own text and with the surrounding chrome, so
> no contour survives the four-vertex and 0.85-fill gates. On `b9dBJnQ_kpo` it returns something
> worse: its top-scoring rectangle is `(12, 273, 940, 532)`, four vertices, fill 1.00, aspect
> **1.77** — the **speaker's video panel**. The aspect prior singled out below as "a strong, cheap
> prior" is precisely what prefers it: in a composed layout the webcam feed is a cleaner 16:9
> rectangle than the slide is. Had this shipped, the crop would have kept the presenter and thrown
> the slide away. This is `sumerene`'s documented negative result, now reproduced first-hand
> against the best implementation of that family in the field.

**Verdict — adopt as #12 candidate 1.5, above plain letterbox removal.** This is `cv2`-only, deterministic, ~80 lines in Python, and it is a *superset* of our black-bar candidate. The aspect-prior scoring in particular is the piece we do not currently have planned: "of all rectangles, prefer the large one whose aspect is closest to a real slide" is a strong, cheap prior. The `fillRatioMin` and margin gates are the kind of thing that only gets added after a rectangle detector returns garbage in the field.

Important limitation to carry into the spike: **it never falls back to the stripped-black-border rectangle.** If no contour passes all five gates, the result is invalid and (in `CannyThenYolo`) control passes to YOLO. For us, recall-over-precision argues the opposite — fall back to the letterbox rect, then to the full frame, and never return "no crop".

#### B.7.2 The YOLO backend

[`autocropdetector.cpp#L455-L552`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/autocropdetector.cpp#L455-L552). Textbook Ultralytics inference: **letterbox** to 640×640 with grey `(114,114,114)` padding preserving aspect (contrast with the classifier's squash), BGR→RGB, /255, CHW; decode the `[1, C, N]` tensor as `cx,cy,w,h,conf…` with the max of any extra class channels; un-letterbox via `(x − pad)/scale`; NMS at `yoloIouThreshold = 0.45`; **take `kept.front()` — the highest-confidence box, not the largest**, with no aspect sanity check at all. `yoloConfidenceThreshold = 0.25`, `yoloInputSize = 640`.

Measured output shape is `(1, 5, 8400)` — 4 box coords + 1 confidence, **single class**, 8400 anchors: a YOLOv8 trained to detect exactly one thing, "slide". Measured cost **89.6 ms/frame** on the i3-4170 via `cv2.dnn` (§6.4). Running it once per exported slide (~40) is ~3.6 s — entirely affordable at our scale.

#### B.7.3 Licence problem with both models

The repo's MIT `LICENSE` covers the source. **There is no licence, model card, attribution, or training-data statement for either `.onnx` file** — grep for `ultralytics|timm|apache|agpl|dataset|training data` across `README.md` and `CHANGELOG.md` returns nothing. But:
- The YOLO file's tensor names are `model.0.conv.weight`, `model.1.conv.weight`, … and the output is the `(1,5,8400)` YOLOv8 export signature — this is an **Ultralytics YOLOv8** derivative, and Ultralytics YOLOv8 is **AGPL-3.0**. A model fine-tuned from Ultralytics weights, with Ultralytics code, is conventionally treated as AGPL-encumbered. `docs/research/slide-region-crop.md:1058` already flags Ultralytics as AGPL-3.0; this repo appears to ship such a derivative under an MIT umbrella without saying so.
- The classifier is a `timm` `mobilenetv4_conv_medium.e500_r256_in1k` fine-tune; timm and those weights are Apache-2.0, which is fine, but the *fine-tuned* weights still carry no statement from this author.

**Verdict — reject for shipping, adopt for measurement.** Use both models in the spikes to establish an upper bound (they run today, for free, on the target host, from `cv2.dnn`). Do not put either in a release artefact without a licence answer. For #12 the deterministic Canny recipe in §7.1 is the shippable part; if a learned crop prior proves necessary, retrain or source permissively (the `opencv_zoo` NanoDet/YOLOX route already noted in `slide-region-crop.md:1055`).

---

### B.8 Crop-then-re-dedupe

[`postprocessor.cpp#L92-L129`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/postprocessor.cpp#L92-L129) and [`#L318-L370`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/postprocessor.cpp#L318-L370). When the ML gate is about to trash a `may_be_slide`, it first tries to *rescue* it by cropping:

```cpp
if (isMaybeSlide && canAutoCrop) {
    AutoCropResult ac = autoCropDetector->detect(result.imagePath);
    if (ac.isValid() && CropManager::applyCrop(result.imagePath, baseOutputDir, ac.bbox, jpegQuality, true)) {
        outAutoCroppedKept->append(result.imagePath);
        continue;                        // keep live file
    }
    // auto-crop failed -> fall through to trash
}
```

and then, critically, **re-hashes the cropped files and dedupes a second time** (`removePostCropDuplicates`, [`#L417`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/postprocessor.cpp#L417); the comment at `#L114-L116` notes the pre-crop hashes are now stale).

The insight: **cropping changes what counts as a duplicate.** Two frames of the same slide shot with the speaker moving in a camera inset are *different* full-frame images and survive pHash dedupe; crop both to the slide region and they become identical. Our planned order is `detect → crop → pair`, so dedupe happens on uncropped frames and we inherit exactly this surplus.

**Verdict — adopt, and it changes #11's design (not just its measurement).** The #11 spike should measure dedupe **twice**: once on raw frames and once on frames cropped by the #12 winner. If post-crop dedupe removes a meaningful surplus at zero miss cost, then `crop` must move *before* the final dedupe in the pipeline, or dedupe must run in both places. This also couples #11 and #12, which are currently specced as independent spikes — worth flagging before either is run.

The GUI defaults `mlAutoCropMaybeSlides` and `mlPostCropDedup` to **true**; the CLI forces both **false** unless `--ml-autocrop-maybe` / `--ml-postcrop-dedup` are passed ([`configmanager.h#L79-L84`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/configmanager.h#L79-L84)) — deliberately never inheriting a GUI-true into a headless run. Good CLI hygiene worth copying.

---

### B.9 Which frame gets exported, and naming

- **Which frame:** the frame at `potentialSlideLocalIndex + verificationCount − 1`, i.e. the **last frame of the verified stability run** — 3 samples after the transition, ~4–6 s into the dwell ([`slidedetector.cpp#L258`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/slidedetector.cpp#L258)). Not the first frame after the change, not the middle of the dwell, not a sharpness-selected best-of. Picking the *last verified* frame rather than the first is a deliberate anti-transition choice: it is guaranteed clear of fades, wipes and mid-build states. No Laplacian/sharpness selection anywhere in the repo.
- **Naming:** `slide_<videoName>_<NNN>.jpg`, `NNN` zero-padded to 3, JPEG quality 95 — [`processingthread.cpp#L598-L607`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/processingthread.cpp#L598-L607). Numbering is a **running count of all slides saved so far**, computed as `savedSlideIndices.size() − selectedFrames.size() + 1`, so it survives chunk boundaries. In `--compatible` mode: `Slide_<videoName>_<NNN>.png`, no compression params, post-processing skipped.
- **Numbering is never re-flowed after post-processing.** A talk that exports 40 slides and trashes 7 leaves gaps in the sequence. Deliberate: the number is a stable identity for the timeline and the trash metadata, not a presentation index.

---

### B.10 timeline.json

Schema v1, [`timelinemetadata.h#L14-L41`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/timelinemetadata.h#L14-L41):

```
events:      [ { id: "evt_<unix_ms>_<alnum>", changeAt: <PTS s>, confirmedAt: <PTS s>, initialFile } ]   // immutable
resolutions: { <eventId>: { state: "canonical"|"duplicate"|"gap",
                            file | duplicateOf | gapReason: "ai_filtered"|"exclusion"|"manual_trash" } } // mutable
```

The split is the good idea: **capture events are append-only and never deleted; only the resolution changes.** pHash dedupe → `duplicate` + `duplicateOf`; exclusion or ML → `gap` + reason; manual restore → back to `canonical`.

Two timestamps per slide, not one: `changeAt` (PTS of the transition *into* the content) and `confirmedAt` (PTS of the frame actually saved, ~4 s later). Both are threaded through chunk boundaries via `ProcessingState.pendingChangeAt` ([`slidedetector.cpp#L204-L210`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/slidedetector.cpp#L204-L210), [`#L275-L282`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/slidedetector.cpp#L275-L282)).

**Verdict — adopt the schema shape for `pair` (#11-adjacent).** Our transcript alignment must use `changeAt`, not `confirmedAt`: the speech that belongs to a slide starts when the slide appears, not when we got around to confirming it. Keeping both, plus the immutable-event / mutable-resolution split, gives us the `drop` command for free (mark, don't delete) and handles the "returns" case from ADR-0003 (§5.2).

---

### B.11 The hard cases, scored against this repo

| hard case | what AutoSlides actually does |
|---|---|
| **Progressive build** | Fires reliably — measured 0.83 (1→2 items) degrading to 0.96 (11→12) on a 12-item agenda, all far below 0.9985. The global metric's sensitivity *decreases* as the slide fills, so the last reveals on a dense slide are the first to be lost. Each confirmed step is exported as its own slide; pHash then does **not** merge them (10/255 bits is far too tight for a one-bullet difference), so a 12-step build yields 12 files. Correct under recall-over-precision; noisy otherwise. |
| **Camera cutaway to speaker and back** | Detected as two changes (global SSIM 0.029 on the cut). The speaker shot is exported as a slide, then removed downstream by the ML gate's `not_slide` class. The return to the slide is exported again and then removed by the **all-pairs** pHash dedupe, with the timeline re-linked to the first copy (§5.2). Handled well, but only because all three stages exist. |
| **Embedded video / animation inside a slide** | **The dominant failure.** Every verification window fails, `i` restarts at the dip, and nothing is saved for the whole segment — a silent miss. Only mitigation offered is the `Loose` preset (README #L918). No motion masking, no region-of-interest exclusion, no "confirm anyway after N failures" escape hatch. |
| **Moving webcam overlay** | Same failure. A 40 px overlay move scores 0.9597 globally, well below threshold, so verification never completes while the presenter moves. Nothing masks the overlay region. |
| **Burned-in subtitles changing every phrase** | Fires (measured 0.9818). Each subtitle change is treated as a slide change; if the subtitle changes faster than 3 samples, verification never completes and the slide is **missed entirely**. Nothing in the repo detects or masks a subtitle band. |
| **Vision mixer cutting constantly** | Not addressed. Verification never completes. |
| **Slide filmed on a screen at an angle** | Partly addressed — and only in the **crop** stage. `AutoCropDetector`'s Canny path is built for exactly this (4-vertex contour, aspect prior against 16:9/4:3), though it returns an axis-aligned `boundingRect`, never a perspective warp — no `getPerspectiveTransform` anywhere. **In the detector it is a disaster:** a 1-px global pan scores 0.9804 and a 3-px pan 0.8500, so a hand-held or vibrating camera makes *every* sample fire and *every* verification fail. Global-statistics SSIM is far more shift-sensitive than windowed SSIM here (0.9940 / 0.9628 for the same pans) — one of the few places where windowed wins outright, and worth an explicit row in the #11 matrix. |

---

### B.12 Other workarounds in the code but not the README

| workaround | where | why it exists |
|---|---|---|
| Two shipped `No_Signal_*` pHashes | [`postprocessor.cpp#L536-L537`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/postprocessor.cpp#L536-L537) | HDMI capture "No Signal" cards are maximally stable and sail through verification. §5.4 |
| `INTER_AREA` mandated with a measured RGB diff in the comment | [`mlclassifier.cpp#L563-L566`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/mlclassifier.cpp#L563-L566) | Wrong resize kernel shifts channels ~27 units and moves predictions. §6.5 |
| First frame saved unconditionally; two EOF special cases | [`slidedetector.cpp#L170-L177`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/slidedetector.cpp#L170-L177), [`#L322-L349`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/slidedetector.cpp#L322-L349) | Look-ahead verification cannot complete at either end; without these the first and last slide of every talk are lost. |
| `denominator == 0 → return 1.0` | [`ssimcalculator.cpp#L596-L598`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/ssimcalculator.cpp#L596-L598) | Guards divide-by-zero on uniform frames — but silently means consecutive black frames score a perfect match. |
| `ImageIOHelper::imreadUnicode` / `imwriteUnicode` everywhere instead of `cv::imread` | all call sites | `cv::imread` fails on non-ASCII paths on Windows. Relevant to us: pt-BR filenames. |
| Post-crop hashes explicitly treated as stale | [`postprocessor.cpp#L114-L116`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/postprocessor.cpp#L114-L116) | Someone shipped a bug where cropped files were compared against their pre-crop hashes. |
| CLI never inherits GUI-true for any post-processing flag | [`configmanager.h#L61-L84`](https://github.com/bit-admin/AutoSlides-Extractor/blob/e0899cdc643937e06fb4e45220a18ffd8de10639/src/configmanager.h#L61-L84) | A headless run must be reproducible from its argv alone. |
| GPU-SSIM layer deleted (~5 166 lines of never-called stubs) | CHANGELOG 1.2.2 | §2.5 |

---

### B.13 Verdicts

| # | Technique | Verdict | Ticket |
|---|---|---|---|
| 1 | **Global-statistics SSIM ≠ windowed SSIM; 0.9985 is valid only for the former** | **Adopt as a spike-design constraint** — two separate candidates, two threshold sweeps | **#11** |
| 2 | Presets 0.999 / 0.9985 / 0.998 on 480×270 INTER_AREA grey | Measure as the starting sweep for the *global* variant only | #11 |
| 3 | `K`-sample all-must-agree verification, restart at the dip | Measure with K swept; note its recall bias opposes ours | #11 |
| 4 | First-frame-always + two EOF guards | **Adopt** — and put both in the ground truth | #11 |
| 5 | I-frame-only sampling, `frameInterval` dead | **Reject as default**; sample on a fixed time grid, but keep one matrix row for I-frame-only decode cost | #11 |
| 6 | 256-bit pHash (64×64 DCT → 16×16, DC dropped, median), radius 10/255 | Measure — and never port the radius without the width | #11 |
| 7 | All-pairs dedupe + re-link the timeline event to the first-kept file | **Adopt** — this is the "returns" answer for ADR-0003 | #11 / pair |
| 8 | User-curated persisted pHash exclusion list | **Adopt the mechanism** (ours: Zoom/Meet/OBS/wallpaper, not theirs) | #11 |
| 9 | **Crop, then dedupe again on the cropped pixels** | **Adopt** — and it couples #11 to #12; measure dedupe pre- and post-crop | **#11 + #12** |
| 10 | Canny + black-bar strip + 4-vertex + area/margin/fill gates + **aspect-prior scoring** | **Adopt as #12 candidate 1.5**, strictly above plain letterbox removal; add a letterbox→full-frame fallback they lack | **#12** |
| 11 | YOLOv8 single-class slide detector, 89.6 ms/frame on the target host | Measure as the #12 ceiling; **do not ship** (licence, §7.3) | #12 |
| 12 | MobileNetV4 3-class gate, **22.5 ms/frame on the i3-4170 via `cv2.dnn`, no new dependency** | **Measure as the #17 baseline**; do not ship unresolved weights | **#17** |
| 13 | Two-stage threshold logic with a `slideProb` veto; keep on every error path | **Adopt the decision shape** for whatever gate wins | #17 |
| 14 | `may_be_slide` third class routed to auto-crop rather than a binary verdict | **Adopt the idea**: "uncertain" should trigger *more processing*, not deletion | #17 + #12 |
| 15 | Match the training resize kernel (INTER_AREA), squash vs letterbox per model | **Adopt as a rule** | #17 |
| 16 | `timeline.json`: immutable events + mutable resolutions, `changeAt` vs `confirmedAt` | **Adopt the schema shape**; align transcript on `changeAt` | pair |
| 17 | Export the **last** verified frame of the run, `slide_<video>_NNN.jpg`, numbering never re-flowed | Adopt "last verified frame"; measure against a sharpness-selected alternative | #11 |
| 18 | GPU-accelerated SSIM | **Reject** — 5 kLOC of dead stubs deleted upstream | #11 |
| 19 | Audio / transcript / subtitle handling | **Nothing here.** Negative finding; `pair` gets no help from this repo | — |
| 20 | Perspective correction for an angled filmed screen | **Nothing here.** Axis-aligned `boundingRect` only, no warp | #12 |

---

### B.14 Reproducing the measurements

Host: `Intel(R) Core(TM) i3-4170 CPU @ 3.70GHz`, 4 threads, no GPU — the #11/#12/#17 target host. Python 3, `opencv-python` 5.0.0, `numpy` 2.5.3; no `onnxruntime`, no `skimage` (windowed SSIM implemented directly with `cv2.blur`, uniform 7×7, `n/(n−1)` unbiased covariance, border cropped).

Method: ONNX timing through `cv2.dnn`; classifier semantics checked against synthetic inputs; global versus windowed SSIM implemented side by side on the same arrays. Synthetic 1080p slides pushed through `cv2.imencode('.jpg', q)` with additive Gaussian noise (σ=2) at two different seeds to emulate two independently-encoded I-frames of identical content.

---

## Group C — Breakthrough/PySceneDetect

**Repo:** [Breakthrough/PySceneDetect](https://github.com/Breakthrough/PySceneDetect) ·
**Licence:** BSD-3-Clause (`LICENSE`, Copyright (C) 2014 Brandon Castellano) ·
**Cloned sha:** `2fa8290de0353d371eaae92a8a6efb69d16a1e0c` (2026-09-12, `--depth 1` of `main`).
All permalinks below are pinned to that sha.

**Vendored code:** exactly one file, `scenedetect/_thirdparty/simpletable.py` (MIT, Matheus Vieira
Portela), used only for `save-html`. `THIRD-PARTY.md` lists click / NumPy / OpenCV / PyAV / pytest /
tqdm / MoviePy as *dependencies*, not vendored source. **Nothing in the package is copyleft**, and
BSD-3-Clause imposes only attribution — no obstacle to depending on it or lifting code from it.

Prior research (`docs/research/slide-change-detection.md` §4) already covered the defaults and the
published benchmarks. This document does not repeat that. It adds: **line-pinned source**, the
**exact FlashFilter state machine** (which §4.8 gets partly wrong), the **packaging answer**
(`scenedetect-headless` exists on PyPI and §4/ADR 0001 did not know it), and a set of
**measurements taken on the installed library** that change what the #11 spike should do.

Everything marked **[measured]** was run on `scenedetect-headless==0.7.1` +
`opencv-python-headless` 5.0.0.93 + `numpy` 2.5.3, Python 3.12, against a synthetic 1920×1080 / 30 fps
15 s MP4 built for the purpose: one title slide, then three successive one-bullet reveals
(a **progressive build**, frames 91 / 181 / 271), then a hard cut to a dark slide (frame 361).
Synthetic high-contrast slides overstate every metric's separation; treat orderings as transferable
and magnitudes as an upper bound.

---

### C.1 One decode pass sweeps the whole detector grid

This is the finding that changes what #11 measures, so it goes first.

**The three facts that combine.**

1. **`SceneManager` accepts unlimited detectors, and runs all of them on each decoded frame.**
   `add_detector` appends to a list and wires the shared `StatsManager` into each detector
   ([`scene_manager.py#L337-L352`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/scene_manager.py#L337-L352));
   `_process_frame` loops over every registered detector with the same `frame_im`
   ([`#L426-L435`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/scene_manager.py#L426-L435)).
   There is no guard anywhere against multiple detectors. The CLI group is `chain=True`
   ([`_cli/__init__.py#L189`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/_cli/__init__.py#L189))
   and `CliContext.add_detector` just forwards
   ([`_cli/context.py#L119-L125`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/_cli/context.py#L119-L125)),
   so **chaining detectors works from the command line too** — undocumented, and not mentioned
   anywhere in `docs/` or on scenedetect.com.

2. **Attaching a `StatsManager` forces the edge component to be computed even at weight 0.**
   `calculate_edges = (self._weights.delta_edges > 0.0) or self.stats_manager is not None`
   ([`content_detector.py#L158`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/detectors/content_detector.py#L158)).
   §4.1 called this a "performance trap". It is the opposite: it is the thing that makes the sweep
   possible, because `delta_edges` lands in the CSV whether or not you asked for it.

3. **The CSV stores the four *raw components*, not just the weighted score.**
   `METRIC_KEYS = [content_val, delta_hue, delta_sat, delta_lum, delta_edges]`
   ([`#L88`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/detectors/content_detector.py#L88))
   and all five are written per frame
   ([`#L183-L186`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/detectors/content_detector.py#L183-L186)).
   Since `content_val = Σ(componentᵢ·weightᵢ) / Σ|weightᵢ|`
   ([`#L177-L180`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/detectors/content_detector.py#L177-L180)),
   **any weight vector's score is recoverable offline from the four columns.**

**Therefore:** one decode pass yields enough data to replay the *entire* ContentDetector and
AdaptiveDetector parameter space offline — weights × threshold × `min_scene_len` × `filter_mode` ×
`window_width` × `min_content_val` — with **no re-decoding at all**. The only parameters that need
their own pass are the ones baked into a metric key (`hash` size/lowpass, `hist` bins), and those
can be added as *extra detectors in the same pass*, because each instance's key embeds its own
parameters: `f"hash_dist [size={size} lowpass={factor}]"`
([`hash_detector.py#L63`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/detectors/hash_detector.py#L63))
and `f"hist_diff [bins={bins}]"`
([`histogram_detector.py#L57`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/detectors/histogram_detector.py#L57)),
so `HashDetector(size=8)` and `HashDetector(size=16)` write to two different columns without
colliding.

**[measured] — the single chained command, verbatim:**

```
scenedetect -i slides.mp4 -s chain.csv -d 1 \
  detect-content detect-adaptive detect-hash detect-hist detect-threshold list-scenes
```

It ran, and produced one CSV with an 11-column header:

```
Frame Number,Timecode,adaptive_ratio (w=2),average_rgb,content_val,delta_edges,
delta_hue,delta_lum,delta_sat,hash_dist [size=16 lowpass=2],hist_diff [bins=256]
```

Columns are `Frame Number` (1-based), `Timecode`, then metric keys **sorted alphabetically**
([`stats_manager.py#L190-L203`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/stats_manager.py#L190-L203)) —
so column order is not detector order and must be read by name.

**[measured] — the replay is bit-exact.** A ~40-line pure-Python port of
`_calculate_frame_score` + `FlashFilter._filter_merge`, fed only `chain.csv`, reproduces the
library's own scene counts and cut frames exactly:

| config | replayed offline from CSV | the tool, re-decoding |
|---|---|---|
| `--weights 0 0 0 1 -t 0.5 -m 1` | 5 scenes, cuts @ 91, 181, 271, 361 | 5 scenes |
| defaults (`-t 27`, `-m 0.6s`) | 2 scenes, cut @ 361 | 2 scenes, cut @ 00:00:12.000 = frame 361 |

**[measured] — `adaptive_ratio` too, for window widths the CSV never carried.** Re-deriving the
ratio from the `content_val` column with the algorithm at
[`adaptive_detector.py#L111-L128`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/detectors/adaptive_detector.py#L111-L128)
matched the CSV's `adaptive_ratio (w=2)` column on **446/446 frames, zero mismatches** (tolerance
1e-9), and the same code then produced ratios for `w=1,3,5` from the same single pass.

**[measured] — the cost difference.** 400 configs (5 weight vectors × 16 thresholds ×
5 `min_scene_len`) replayed in **0.56 s** (1.4 ms/config) over 450 frames. Re-decoding those
400 configs at this clip's measured 28.0 FPS detection rate would be **107 minutes** — for a 15-second
clip. Extrapolated to the #11 corpus (6 videos, ~50 min each, 1080p at `-d 1`), a re-decode-per-config
sweep is not slow, it is **infeasible**; the one-pass route costs one decode per video plus minutes
of CPU for the whole grid.

> **Verdict: ADOPT, for the #11 spike harness — and it changes what #11 measures.** The spike was
> scoped as "which detector wins", which under a re-decode budget means testing a handful of
> configs. With this, the unit of measurement becomes *the whole parameter surface per video*, so
> #11 can report the (misses, surplus) frontier as a function of threshold rather than a verdict at
> one operating point. The cheapest thing #11 can do on day one is `-s stats.csv` over all six
> fixtures with every detector chained, and commit the CSVs — from then on, every threshold question
> is a pandas query. Note this is a *harness* adoption; it does not commit the shipped tool to
> depending on PySceneDetect.

**Caveats that must go in the spike notes.**

- **`--stats` is a hard error with `--frame-skip`**
  ([`scene_manager.py#L498-L499`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/scene_manager.py#L498-L499);
  **[measured]** CLI message: *"Combining the -s/--stats and -fs/--frame-skip options is not
  supported."*). The stats pass must decode every frame.
- **The stats pass is ~2.6× the cost of a plain detection pass** — **[measured]** 42.3 s
  (10.64 FPS) with five chained detectors + stats, vs 16.1 s (28.0 FPS) for `detect-content` alone,
  both at `-d 1` on 450 frames of 1080p. The forced Canny is most of it.
- **Unset metrics are written as the literal string `None`**, not empty
  ([`stats_manager.py#L200-L203`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/stats_manager.py#L200-L203)
  stringifies `_get_metric`'s `None`). Frame 1 and any detector-specific warmup rows carry it.
  `pd.read_csv(..., na_values=["None"])`.
- **Do not expect `get_scene_list()` to be meaningful in a chained run.** All detectors' cuts are
  pooled into one `_cutting_list`
  ([`#L426-L428`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/scene_manager.py#L426-L428))
  and deduped by `set()`
  ([`#L403-L408`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/scene_manager.py#L403-L408)),
  so the scene list is the *union* of five detectors. In a sweep you want the CSV and should ignore
  the scene list.
- **`StatsManager.load_from_csv()` is deprecated and slated to become a no-op**
  ([`stats_manager.py#L221-L241`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/stats_manager.py#L221-L241),
  *"TODO: Make this an error, then make load_from_csv() a no-op, and finally, remove it"*).
  **The library's own "reload a stats file and skip recomputation" path is going away.** This does
  not hurt the plan above — the sweep is your code reading a CSV — but it does mean the spike must
  not build on `load_from_csv`, and §4.7's framing ("thresholds are then fitted offline") only holds
  if *you* write the fitting. Only `ThresholdDetector` still consults `metrics_exist`
  ([`threshold_detector.py#L123`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/detectors/threshold_detector.py#L123)).

---

### C.2 The edge component is the build-recall mechanism

**[measured]** at the three progressive-build boundaries and at the hard cut, `-d 1`, 1080p:

| frame | event | `content_val` | `delta_edges` | `hash_dist [size=16]` | `hist_diff [bins=256]` |
|---|---|---|---|---|---|
| 90 | static | 0.0000937 | 0.0 | 0.0 | ~1.0 |
| **91** | **+1 bullet** | **0.157** | **1.505** | **0.109** | **0.99999955** |
| **181** | **+1 bullet** | **0.202** | **1.832** | **0.141** | **0.99999891** |
| **271** | **+1 bullet** | **0.124** | **1.184** | **0.141** | **0.99999969** |
| **361** | **hard cut** | **127.86** | **4.432** | **0.242** | **−0.0040** |

Read the ratios, not the values:

- **`content_val` spans 814× between a one-bullet reveal (0.157) and a whole-slide change (127.9).**
  No single threshold catches both. The default 27.0 catches only the hard cut; it is **176× too
  high** for the build. AdaptiveDetector's `min_content_val` floor of 15.0 is **96× too high**.
- **`delta_edges` spans 2.4×** (1.18 → 4.43) across the same two events, while sitting at **exactly
  0.0** on static frames. That compression is the whole point: a text reveal is almost pure
  high-frequency edge energy, and the edge map is the only component that measures it.
  **A threshold anywhere in (0.01, 1.18) catches every build *and* every hard cut.**
- **[measured] confirmation:** `detect-content --weights 0 0 0 1 --threshold 0.5 -m 1` → **5 scenes**
  (all three builds + the hard cut). Default weights → **2 scenes**. Same decode, same `-d 1`.

**How the edge map is built** — worth lifting whether or not PySceneDetect is the dependency
([`content_detector.py#L213-L239`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/detectors/content_detector.py#L213-L239)):

```python
sigma  = 1.0 / 3.0
median = numpy.median(lum)                      # luma channel of the HSV split
low    = int(max(0,   (1.0 - sigma) * median))
high   = int(min(255, (1.0 + sigma) * median))
edges  = cv2.Canny(lum, low, high)
return   cv2.dilate(edges, self._kernel)
```

- **Canny thresholds are derived per frame from the luma median**, not fixed — this is the
  auto-Canny recipe, and it is exactly the per-video adaptivity #11 wants, at zero tuning cost. It
  costs one `numpy.median` per frame.
- **The dilation is a documented field workaround:** *"This increases edge overlap leading to
  improved robustness against noise and slow camera movement. Note that very large kernel sizes can
  negatively affect accuracy."*
  ([`#L235-L237`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/detectors/content_detector.py#L235-L237)).
  Dilating both edge maps before differencing means a 1–2 px shift (camera wobble, a filmed screen,
  re-encode ringing) stops registering as a change. That directly addresses **"a slide filmed on a
  screen at an angle"** and **"a moving webcam overlay"** — the hard cases — and is the single
  cheapest robustness trick in this repo.
- **The kernel size is an admitted guess:** `size = 4 + round(sqrt(W·H)/192)`, forced odd
  ([`#L39-L46`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/detectors/content_detector.py#L39-L46)),
  with the comment *"TODO: This equation is based on manual estimation from a few videos. Create a
  more comprehensive test suite to optimize against."* **Tuned against nothing reproducible.** For
  1080p it gives 13; at the default 7.5× downscale (256×144) it gives 5. Treat as a spike knob, not
  a constant to trust.

**Negative finding — the project's own documented edge recipe does not work for builds.**
scenedetect.com recommends `--weights 1.0 0.5 1.0 0.2 --threshold 32` as the starting point for
turning edges on. **[measured]**, that config finds **2 scenes** — it misses all three builds. The
arithmetic says why: the weighted mean divides by `Σ|weight| = 2.7`, so the build's `delta_edges` of
1.83 contributes `1.83 × 0.2 / 2.7 = 0.136` against a threshold of 32. **Mixing edges with the other
three components at a small weight destroys the very signal you turned edges on to get.** For
recall on builds the weight vector must be `(0, 0, 0, 1)` or close to it, with a threshold ~1, not
~30. The README/docs recommendation is calibrated for shot-boundary detection on broadcast footage,
which is what all of PySceneDetect's published benchmarks measure.

> **Verdict: ADOPT the mechanism (auto-Canny + dilate + mean absolute difference of dilated edge
> maps), MEASURE the constants. Changes #11.** This is a deterministic, wheels-only, ~4-line
> technique that is the best-separating metric in the table above, and it is the closest thing in
> any surveyed repo to the TalkMiner-style edge superset already on the #11 shortlist. It also
> partly answers #17: an edge-density measure is in the same family as the Laplacian-variance gate,
> so one pass can feed both.

**Also from the table, for #11's controls:**

- **`hist_diff` at a one-bullet reveal is 0.99999955** — a *perfect* luma-histogram correlation.
  The prior research's §5.2 claim ("no threshold separates the classes") is **confirmed on video, at
  1080p, against real builds**. The default threshold 0.20 means "cut when correlation ≤ 0.80"
  ([`histogram_detector.py#L52`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/detectors/histogram_detector.py#L52)),
  and no threshold short of 0.9999994 separates a build from a static frame. **Keep it as a control
  only, and expect it to score last on misses.**
- **pHash did better than §4.9 predicted.** `hash_dist` was 0.109–0.141 on the builds against 0.242
  on the hard cut — a 1.8× span, not the structural blindness predicted. At the released default
  threshold of 0.395 all four events are missed; at ~0.08 all four fire. **Correction to prior
  research: pHash is not structurally incapable of seeing a bullet reveal, it is just tuned ~4×
  too coarse.** (Caveat: synthetic slides, size=16 → 256 bits. At the post-0.7.1 default of size=8
  → 64 bits, one bullet may fall below the quantisation floor. Worth one line in the spike.)

---

### C.3 FlashFilter

Source: [`detector.py#L106-L224`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/detector.py#L106-L224).
Used by **`ContentDetector` only** — `Adaptive`, `Hash` and `Histogram` each roll their own
one-line refractory check
([`adaptive_detector.py#L140`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/detectors/adaptive_detector.py#L140),
[`hash_detector.py#L109-L111`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/detectors/hash_detector.py#L109-L111),
[`histogram_detector.py#L108-L110`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/detectors/histogram_detector.py#L108-L110)),
and `AdaptiveDetector` explicitly disables its parent's filter by passing `min_scene_len=0`
([`adaptive_detector.py#L71-L77`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/detectors/adaptive_detector.py#L71-L77)).

**`Mode.SUPPRESS`** ([`#L171-L187`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/detector.py#L171-L187)) —
emit an above-threshold frame only if `min_scene_len` has elapsed since the last above-threshold
frame; otherwise drop it permanently. No lookahead, no deferral.
**What is lost:** every reveal of a build after the first, permanently. You keep the *emptiest*
state of the slide.

**`Mode.MERGE`** (the default, [`#L189-L224`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/detector.py#L189-L224)) —
more subtle than §4.8 describes. Tracing the code:

1. A first above-threshold frame arriving *after* a quiet gap ≥ `min_scene_len` is **emitted
   immediately, at that frame** (`min_length_met` → `return [timecode]`, [`#L216-L219`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/detector.py#L216-L219)).
   It also sets `_merge_enabled = True`.
2. Subsequent above-threshold frames inside the window arm the merge (`_merge_triggered`,
   `_merge_start`) and emit nothing.
3. The merge releases **one** cut at `self._last_above` — the **last** above-threshold frame of the
   burst — and only once the signal has been quiet for `min_scene_len` **and** the burst's own span
   `(_last_above - _merge_start)` is itself ≥ `min_scene_len`
   ([`#L200-L211`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/detector.py#L200-L211)).

So **MERGE emits both ends of a long burst** (first frame and last frame), not just the last — which
is *better* for recall than §4.8 implies. But:

- **A burst whose total span is shorter than `min_scene_len` never releases its trailing cut at all.**
  The filter stays in `_merge_triggered` indefinitely, returning `[]`, until some later
  above-threshold frame drags `_last_above` far enough past `_merge_start`. **A four-bullet build
  completed inside 0.6 s yields exactly one capture, of the first state — the emptiest one.** Under
  ADR 0003 that capture lands *before* the content's window opens, so it scores as a **miss**, not a
  surplus. This is the precise mechanism by which the CLI default `-m 0.6s` converts a fast build
  into silent damage.
- **Undocumented gate — the first burst of a video is discarded, not merged.** `_merge_enabled`
  starts `False` and is only set once a cut has actually been emitted
  ([`#L141`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/detector.py#L141),
  [`#L217-L222`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/detector.py#L217-L222)).
  `_last_above` is initialised to the very first frame processed
  ([`#L163-L164`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/detector.py#L163-L164)),
  so any above-threshold activity in the **first `min_scene_len` of the video** fails
  `min_length_met`, finds `_merge_enabled == False`, and is dropped outright — neither emitted nor
  deferred. **A title-card change in the opening 0.6 s is lost with no trace.** This is in no README
  and in no doc page.

**Disabling it:** `length <= 0` short-circuits to "every above-threshold frame is a cut"
([`#L154-L162`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/detector.py#L154-L162)) —
the maximum-recall setting, and the one this project's metric wants, since ADR 0003 prices surplus
at one `drop` keystroke.

**New since §4.8: `min_scene_len` now accepts seconds and timecodes**, not just frames
([`#L117-L139`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/detector.py#L117-L139)),
and the frames↔seconds conversion is pinned from the **first frame's** framerate to avoid OpenCV's
bogus average fps on VFR input
([`#L177-L180`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/detector.py#L177-L180)) —
a field workaround for variable-frame-rate sources, which YouTube downloads frequently are.

**CLI default resolution, which the API does not share.** Per-detector `min-scene-len` defaults to
`TimecodeValue(0)` ([`_cli/config.py#L367,L375,L380,L386,L393`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/_cli/config.py#L367)),
and when it is still at its default the **global** value `"0.6s"` is substituted
([`_cli/config.py#L420`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/_cli/config.py#L420),
[`_cli/context.py#L136-L148`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/_cli/context.py#L136-L148)).
The **API** default is `15` *frames* ([`content_detector.py#L107`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/detectors/content_detector.py#L107)).
At 30 fps these coincide; at 25 or 60 fps they do not. **The spike must state which surface it used.**

> **Verdict: REJECT `min_scene_len` as a burst-suppression mechanism for this project; MEASURE it at
> 0 only. Changes #11.** The design tension §4.8 identified is real and confirmed in the code: one
> scalar controls both animation suppression and build merging, and there is no per-region or
> content-aware variant. Given ADR 0003 (misses rank, surplus is free), the correct setting here is
> `-m 0` — take every reveal and let `drop` clean up. Any burst suppression this project needs
> should be a separate downstream pass with access to content identity, which PySceneDetect does not
> have (see C.6).

---

### C.4 AdaptiveDetector: the rolling window is inert on slides

[`adaptive_detector.py#L111-L143`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/detectors/adaptive_detector.py#L111-L143).
The ratio is `min(target_score / mean(window excluding centre), 255.0)`, with a divide-by-zero
branch that forces `255.0` when the window mean is `< 1e-5` *and* `target_score >= min_content_val`
([`#L121-L128`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/detectors/adaptive_detector.py#L121-L128)).

§4.2 deduced that this degenerates to `content_val >= 15` on static content. **[measured],
confirmed and sharpened:** re-deriving the ratio offline for `window_width` 1, 3 and 5 gave
**identical cut sets at every width** — `[361]` at `min_content_val=15.0`, and
`[91, 181, 271, 361]` at `min_content_val=0.05`.

**`window_width` is a no-op on slide content.** Neighbouring scores on a static slide are ~1e-4, so
the `average_is_zero` branch fires regardless of how many neighbours you average, and the ratio is
pinned to 255.0. The only knob that moves the answer is `min_content_val` — whose default of 15.0
is, per C.2, ~96× above a one-bullet reveal.

This is a **negative finding about the per-video adaptivity the task was hoping for**: the
"adaptive" in AdaptiveDetector adapts to *sustained motion*, which is what talk video has during a
camera cutaway or an embedded clip, and it correctly does nothing during the 99% of a talk that is a
motionless slide. It is not a mechanism for auto-calibrating a threshold per video.

**Where its adaptivity *is* real:** inside an embedded video or a constantly-cutting vision mixer,
every frame in the ±window scores high, the ratio sits near 1.0, and the default 3.0 suppresses the
flood — the mechanism the project actually advertises. That is genuinely useful for the
"embedded video/animation" hard case, and it is **the only content-aware suppression anywhere in
this repo**.

**A latency detail with a correctness consequence:** cuts are emitted at `target_timecode`, which is
`window_width` frames *behind* the frame being processed
([`#L139-L143`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/detectors/adaptive_detector.py#L139-L143)).
`SceneManager` sizes its frame buffer from `event_buffer_length` to compensate
([`scene_manager.py#L352`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/scene_manager.py#L352)),
but a known-broken TODO remains against the callback path:
*"TODO(issues/283): This breaks with AdaptiveDetector as cuts differ from the frame number being
processed"* ([`#L419-L421`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/scene_manager.py#L419-L421)).
**If the spike uses `detect_scenes(callback=...)` to grab frames as cuts fire, do not use it with
AdaptiveDetector.**

> **Verdict: MEASURE `detect-adaptive` in #11 only as `--min-content-val` ≈ 0.1 with edges weighted;
> REJECT the premise that it supplies per-video threshold adaptivity.** The per-video adaptivity in
> this codebase lives in the *auto-Canny median* (C.2), not in the rolling window.

---

### C.5 Downscale, frame_skip, and what breaks

**Downscale** ([`scene_manager.py#L110`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/scene_manager.py#L110),
[`#L123-L140`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/scene_manager.py#L123-L140)):
`DEFAULT_MIN_WIDTH = 256`, factor = `frame_width / 256.0`, computed from `max(width, height)` of the
**post-crop** frame. 1080p → 7.5× → detection at 256×144. The constant carries its own disclaimer:
*"TODO: This value can and should be tuned for performance improvements as much as possible, until
accuracy falls, on a large enough dataset. **This has yet to be done**"*
([`#L107-L109`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/scene_manager.py#L107-L109)) —
**256 is not a tuned constant, it is an untested guess, by the author's own admission.** Every
published benchmark number on scenedetect.com was produced at this downscale.

Order of operations in the decode thread
([`#L666-L684`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/scene_manager.py#L666-L684)):
crop → resize (`Interpolation.LINEAR` by default, config-only) → enqueue. **Cropping to the slide
region therefore also reduces the auto-downscale factor**, which is a free recall win and a concrete
reason #12's crop could precede #11's detect rather than follow it. Worth a line in #12.

**`frame_skip`** ([`#L686-L689`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/scene_manager.py#L686-L689)):
implemented as `video.read(decode=False)` — a *grab* without decode, so it is genuinely cheap.
**[measured]** `-fs 2` ran at 82.1 FPS vs 27.0 FPS unskipped (3.0×), and still found all 5 scenes on
this clip. Two things break:

1. **It is a hard error with `--stats`** (C.1) — no sweeping while skipping.
2. The docstring's warning is the one that matters here
   ([`#L470-L474`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/scene_manager.py#L470-L474)):
   *"Not recommended except for extremely high framerate videos."* The docs elaborate that skipping
   "essentially raises the threshold between frames in the same scene … while not affecting the
   threshold between frames of different scenes". **Any threshold calibrated at `fs=0` is wrong at
   `fs>0`**, in the direction of *more* false positives — which, under this project's metric, is
   the cheap direction. Still: calibrate and run at the same skip.

---

### C.6 Which frame of a dwell gets exported

[`output/image.py`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/output/image.py).
`_generate_timecode_list` ([`#L38-L72`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/output/image.py#L38-L72))
splits each scene into `num_images` equal segments and picks:

| case | chosen time | line |
|---|---|---|
| `num_images == 1` | **`start + duration/2` — the exact midpoint** | [`#L62-L63`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/output/image.py#L62-L63) |
| first of N | `segment_start + frame_margin` (clamped) | [`#L64-L65`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/output/image.py#L64-L65) |
| last of N | `segment_end - frame_margin` (clamped) | [`#L66-L67`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/output/image.py#L66-L67) |
| middle | segment midpoint | [`#L68-L69`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/output/image.py#L68-L69) |

Defaults: `num_images=3`, `frame_margin=1`
([`#L111-L112`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/output/image.py#L111-L112)).
**[measured]** with `-n 1` on the 5-scene run: exported frames 45, 135, 225, 315, 405 — the exact
midpoints of scenes spanning 1–90, 91–180, 181–270, 271–360, 361–450.

**The midpoint rule is directly useful to this project, and the reason is ADR 0003.** A capture
window *opens when the content is complete*. Exporting the **first** frame of a dwell lands on the
half-built state — before the window — and scores as a **miss**. Exporting the midpoint lands well
inside the window for any build that completes in less than half the dwell, which is every normal
talk slide. `frame_margin` exists precisely to avoid cross-fade frames at the boundaries; the
midpoint gets that for free.

Export **re-decodes the original full-resolution video by seek**, in the main thread, one seek+read
per image ([`#L268-L280`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/output/image.py#L268-L280)),
with encode and disk-write on two background threads
([`#L298-L332`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/output/image.py#L298-L332)).
Detection resolution and export resolution are fully decoupled — the pattern every reference project
uses, confirmed here in code.

**Naming.** Default template `"$VIDEO_NAME-Scene-$SCENE_NUMBER-$IMAGE_NUMBER"`
([`#L115`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/output/image.py#L115)),
via `string.Template.safe_substitute`
([`#L200-L211`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/output/image.py#L200-L211)).
Scene numbers are **1-based**, zero-padded to `max(3, floor(log10(N)) + 1)` digits — i.e. a floor of
3 digits that widens automatically past 999 scenes
([`#L195-L196`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/output/image.py#L195-L196)).
Available variables: `$VIDEO_NAME`, `$SCENE_NUMBER`, `$IMAGE_NUMBER`, `$FRAME_NUMBER`,
**`$TIMESTAMP_MS`**, `$TIMECODE` (with `:` → `;` for Windows paths).

**[measured]** default → `slides-Scene-001-01.jpg` … `slides-Scene-005-03.jpg`;
`-f '$SCENE_NUMBER-$FRAME_NUMBER-$TIMESTAMP_MS-$TIMECODE'` → `001-45-1500-00;00;01.500.jpg`.

> **Verdict: ADOPT the midpoint rule for `num_images == 1`, and the padded-1-based naming with a
> 3-digit floor. Changes #11 (which frame to capture) and #14 (manifest).** ADR 0003 makes
> *"the manifest must record each capture's source timestamp"* a hard requirement; `$TIMESTAMP_MS`
> is that value, already computed. The zero-pad-to-3-widening-automatically rule is also the right
> answer for `drop`'s renumbering.

---

### C.7 Dependencies, the video backend, and ffmpeg

**The backend is OpenCV's `cv2.VideoCapture`, and it is the only mandatory one.**
`backends/__init__.py` imports the OpenCV backend unconditionally (comment: *"OpenCV must be
available at minimum"*, [`#L94-L98`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/backends/__init__.py#L94-L98))
and wraps PyAV and MoviePy in `try/except ImportError`
([`#L100-L108`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/backends/__init__.py#L100-L108)).
The global default is `"opencv"` ([`_cli/config.py#L412`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/_cli/config.py#L412)).

**No system ffmpeg binary is needed for detection or for `save-images`.** `opencv-python-headless`
wheels ship their own statically-linked FFmpeg libraries; `cv2.VideoCapture` calls into them. The
only code paths that shell out to a binary are:

| feature | needs | source |
|---|---|---|
| `split-video` (default) | `ffmpeg` on PATH, or the `imageio_ffmpeg` package's bundled binary | [`platform.py#L253-L280`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/platform.py#L253-L280) |
| `split-video --mkvmerge` | `mkvmerge` on PATH | [`platform.py#L297-L305`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/platform.py#L297-L305) |
| `--backend moviepy` | MoviePy, which launches ffmpeg as a subprocess | [`backends/moviepy.py`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/backends/moviepy.py) |

**This project uses none of those.** `split-video` is irrelevant (we want images, not clips), and
the OpenCV backend is the default. `THIRD-PARTY.md`'s ffmpeg/mkvmerge section applies only to
`split-video`.

**Packaging — the part that supersedes ADR 0001.** The repo now builds **three** distributions from
one source tree ([`pyproject.toml#L15-L52`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/pyproject.toml#L15-L52)
plus [`packaging/variants/`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/packaging/variants/)):

| distribution | OpenCV it pulls | published? |
|---|---|---|
| `scenedetect-core` | **none declared** (dev installs only) | **No** — *"0.7.1 was published briefly and yanked … layering the published packages over a shared core dist is unsafe with pip"* ([`pyproject.toml#L41-L49`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/pyproject.toml#L41-L49)) |
| `scenedetect` | `opencv-python` (GUI) | yes, 0.7.1 |
| **`scenedetect-headless`** | **`opencv-python-headless`** | **yes, 0.7 and 0.7.1** |

**[measured]** `pip index versions scenedetect-headless` → `0.7.1, 0.7`. The published 0.7.1 wheel's
`Requires-Dist` is exactly:

```
click!=8.3.0,~=8.0 · numpy · opencv-python-headless · platformdirs · tqdm
(extras: pyav → av>=9.2 ; moviepy → moviepy)
```

**[measured]** `pip install scenedetect-headless==0.7.1` into a clean venv installed **6 packages,
all wheels, no compilation, no ffmpeg, no `av`**: `click` 8.5.0, `numpy` 2.5.3,
`opencv-python-headless` 5.0.0.93, `platformdirs` 4.11.8, `scenedetect-headless` 0.7.1, `tqdm` 4.70.1.

> **This is a correction to `docs/adr/0001-python-runtime-for-the-cli.md`, which records installing
> `scenedetect` 0.7.1.** Plain `scenedetect` declares `opencv-python`, the **GUI** variant, which on
> a headless host pulls GUI shared-library dependencies and can collide with the project's own
> `opencv-python-headless` pin (same `cv2` import name, two distributions). **`scenedetect-headless`
> is the correct name for this project**, it satisfies the wheels-only constraint, and it needs no
> system ffmpeg. If PySceneDetect is adopted for anything — even just the #11 spike harness — this
> is the line to put in the dependency file. Worth a one-line amendment to ADR 0001.

**Threading, on a 2C/4T i3.** Exactly one background decode thread, feeding a `queue.Queue(maxsize=4)`
([`scene_manager.py#L113`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/scene_manager.py#L113),
[`#L565-L579`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/scene_manager.py#L565-L579));
detectors run in the caller's thread. No multiprocessing, no `--threads`. The only multi-core lever
is the PyAV backend's `threading-mode` (`auto`, [`_cli/config.py#L360`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/_cli/config.py#L360)),
which requires the `pyav` extra — still a wheel, but one more dependency. **Chaining five detectors
costs one decode and five serial per-frame computations in a single thread**, which is why C.1's
pass measured 10.6 FPS: the win is that it replaces hundreds of passes, not that it is fast.

**Field workarounds in the backend, none in any README:**

- `cap.set(cv2.CAP_PROP_ORIENTATION_AUTO, 1.0)` citing opencv/opencv#26795
  ([`backends/opencv.py#L367`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/backends/opencv.py#L367)).
  Honours container rotation metadata. **Directly relevant:** a phone-recorded talk with rotation
  metadata would otherwise be decoded sideways, breaking both detection and crop. One line, adopt it.
- `max_decode_attempts=5` ([`backends/opencv.py#L77`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/backends/opencv.py#L77),
  retry loop at [`#L293-L302`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/backends/opencv.py#L293-L302)) —
  continue past corrupt frames rather than aborting, with a one-shot
  *"Failed to decode some frames, results may be inaccurate"* warning.
- Codec-detection failure check (`CAP_PROP_FOURCC == 0`) with a three-option remediation message,
  citing issue #86 ([`#L341-L352`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/backends/opencv.py#L341-L352)).
- Frames whose decoded size differs from the container's reported resolution are **skipped**, with
  the error suppressed after 16 occurrences
  ([`scene_manager.py#L643-L664`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/scene_manager.py#L643-L664)).

---

### C.8 The version trap is worse than §4.0 said

§4.0 warned that released 0.7.1 and `main` disagree on `HashDetector`/`HistogramDetector` defaults.
**[measured]**, they are *indistinguishable by version string*:

| | `scenedetect.__version__` | HashDetector | HistogramDetector |
|---|---|---|---|
| PyPI `scenedetect-headless==0.7.1` | `"0.7.1"` | `size=16`, `threshold=0.395` | `bins=256` |
| this clone (`2fa8290`, post-0.7.1 `main`) | **`"0.7.1"`** | `size=8`, `threshold=0.35` | `bins=128` |

([`scenedetect/__init__.py#L83`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/__init__.py#L83),
[`hash_detector.py#L49-L52`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/detectors/hash_detector.py#L49-L52),
[`histogram_detector.py#L35-L37`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/detectors/histogram_detector.py#L35-L37).)

**The fix is free and it is already in the artefact:** the stats CSV header self-documents the
parameters (`hash_dist [size=16 lowpass=2]` vs `[size=8 lowpass=2]`). A committed stats file is
self-identifying; `__version__` is not. Record the wheel hash in the spike anyway.

---

### C.9 Negative findings

- **No dedupe, no repeat detection, no frame memory — confirmed at the source.** Every detector
  holds at most the immediately previous frame's derived data: `self._last_frame`
  ([`content_detector.py#L130`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/detectors/content_detector.py#L130)),
  `self._last_hash` ([`hash_detector.py#L62`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/detectors/hash_detector.py#L62)),
  `self._last_hist` ([`histogram_detector.py#L55`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/detectors/histogram_detector.py#L55)),
  or Adaptive's `(1 + 2·window_width)`-entry score buffer
  ([`adaptive_detector.py#L88`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/detectors/adaptive_detector.py#L88)).
  The output type is `list[tuple[FrameTimecode, FrameTimecode]]` — **scenes have no identity**.
  **The camera-cutaway-and-return case gets a second screenshot, always.** The `drop`/dedupe half of
  #11 must be built outside this library. Unchanged from §4.9, now line-pinned.
- **No slide, presentation or screencast awareness anywhere.** Confirmed by grep across
  `scenedetect/`, `docs/` and `website/`. All five detectors are generic adjacent-frame shot-boundary
  detectors, and every published benchmark is broadcast/web-clip shot-boundary data (BBC Planet
  Earth, AutoShot, ClipShots) — **no slides, no builds**. Any default in this library is tuned
  against the wrong distribution for this project, which C.2 measured concretely.
- **No crop-region detection.** `--crop` is a *manual* `CropValue`
  ([`_cli/config.py#L413`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/_cli/config.py#L413)),
  applied as a plain slice `frame_im[y0:y1, x0:x1]`
  ([`scene_manager.py#L666-L668`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/scene_manager.py#L666-L668)),
  and it affects **detection only** — `save-images` re-decodes the original and writes the
  **uncropped** frame ([`output/image.py#L268-L277`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/output/image.py#L268-L277)).
  **PySceneDetect contributes nothing to #12** beyond confirming, for the sixth time, that
  `docs/similar-tools.md` is right that slide-region cropping is greenfield. The one transferable
  note is the ordering in C.5: cropping before detection also lowers the downscale factor.
- **Nothing about audio or transcripts.** The only audio in the package is `split-video`'s
  pass-through and an OTIO export that needs an audio track
  ([`output/__init__.py#L668`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/output/__init__.py#L668)).
  Nothing for #14.
- **`transnet_v2.py` is still dead code at this sha** — present
  ([`detectors/transnet_v2.py`](https://github.com/Breakthrough/PySceneDetect/blob/2fa8290de0353d371eaae92a8a6efb69d16a1e0c/scenedetect/detectors/transnet_v2.py)),
  but grep confirms zero references from `detectors/__init__.py`, `_cli/__init__.py` or
  `_cli/config.py`. Not exported, not wired, not in the config. Irrelevant on a no-GPU host, and it
  would violate "deterministic first" anyway.

---

### C.10 Verdict table

| # | Technique | Source | Verdict | Ticket |
|---|---|---|---|---|
| 1 | **One decode pass → all detector metrics → offline sweep of the whole parameter grid** (chained detectors + `--stats`; weights/threshold/`min_scene_len`/`filter_mode`/`window_width` all replayable; **[measured]** bit-exact, 400 configs in 0.56 s vs 107 min re-decoding) | `scene_manager.py#L337-L352,L426-L435`; `content_detector.py#L88,L158,L177-L186`; `_cli/__init__.py#L189` | **ADOPT** (spike harness) | **#11** |
| 2 | **Edge component as the build-recall metric**: auto-Canny (`sigma=1/3` off the luma median) + dilate + mean abs diff. **[measured]** 2.4× span build→hard-cut vs `content_val`'s 814×; `--weights 0 0 0 1 -t 0.5` finds 3/3 builds, defaults find 0/3 | `content_detector.py#L213-L239` | **ADOPT mechanism, MEASURE constants** | **#11**, touches **#17** |
| 3 | **Dilation before differencing** as shift-tolerance for wobble / filmed screens / moving overlays | `content_detector.py#L235-L237` | **ADOPT** | **#11** |
| 4 | **Midpoint frame export** for `num_images == 1`; padded 1-based naming with a 3-digit floor; `$TIMESTAMP_MS` | `output/image.py#L62-L63,L195-L211` | **ADOPT** | **#11**, **#14** |
| 5 | **`scenedetect-headless` on PyPI** — wheels-only, 6 deps, no ffmpeg, `opencv-python-headless` | `packaging/variants/pyproject-scenedetect-headless.toml`; **[measured]** wheel metadata | **ADOPT the name** (amends ADR 0001) | packaging |
| 6 | `CAP_PROP_ORIENTATION_AUTO` for rotation metadata | `backends/opencv.py#L367` | **ADOPT** (one line) | fetch/decode |
| 7 | `HashDetector` at threshold ~0.08–0.10 (not the 0.395/0.35 default) | `hash_detector.py#L109-L111`; **[measured]** 0.109–0.141 on builds | **MEASURE** as control | **#11** |
| 8 | `AdaptiveDetector` rolling window for embedded-video suppression | `adaptive_detector.py#L111-L143` | **MEASURE** (only knob that moves: `--min-content-val`) | **#11** |
| 9 | `min_scene_len` / FlashFilter as burst suppression | `detector.py#L106-L224` | **REJECT** — set `-m 0`; merges away builds, and a sub-`min_scene_len` build yields only its emptiest state (= a **miss** under ADR 0003) | **#11** |
| 10 | `HistogramDetector` | `histogram_detector.py`; **[measured]** `hist_diff = 0.99999955` on a bullet reveal | **REJECT** except as a control | **#11** |
| 11 | Docs' recommended `--weights 1.0 0.5 1.0 0.2 -t 32` | scenedetect.com; **[measured]** finds 0/3 builds | **REJECT** — the `/Σ|weight|` divisor destroys the edge signal | **#11** |
| 12 | Anything for slide-region crop, dedupe/repeat detection, or transcripts | — | **Nothing here** | **#12**, **#14** |

---

## Group D — the video2slides family and vid2slides

Four repos, read at source. Three (`kovitking`, `sumerene`, `binh234`) are independent takes on the same
shape — sample, compare, dedupe, assemble a PDF — so they are read comparatively below. `patrickmineault/vid2slides`
is a different shape (HMM over compressibility-ranked templates) and is the only one of the four that attempts an
automatic slide-region crop.

| repo | sha cloned | last commit | licence |
|---|---|---|---|
| [`kovitking/video2slides`](https://github.com/kovitking/video2slides/tree/2e16e894d6bab283a35505c390f5f8888695261f) | `2e16e894d6bab283a35505c390f5f8888695261f` | 2026-07-28 | **none** (no `LICENSE`) — read, do not copy |
| [`sumerene/video2slides`](https://github.com/sumerene/video2slides/tree/65b2a777709cd2811282bc8700452029cb5cc64f) | `65b2a777709cd2811282bc8700452029cb5cc64f` | 2026-04-20 | MIT |
| [`binh234/video2slides`](https://github.com/binh234/video2slides/tree/ceaf516d3099d96a42ebbab742ac416717230ada) | `ceaf516d3099d96a42ebbab742ac416717230ada` | 2024-03-15 | MIT (© 2023 Binh Le) |
| [`patrickmineault/vid2slides`](https://github.com/patrickmineault/vid2slides/tree/62121168143d0576aa0990530c2af0d6dba629ec) | `62121168143d0576aa0990530c2af0d6dba629ec` | 2020-11-22 | **none** — read, do not copy |

The `kovitking` and `vid2slides` shas match the ones already pinned in `docs/research/slide-region-crop.md`, so the
verifications below are at the same commit the prior claims were made against.

---

### D.1 The three `video2slides` side by side

Every row is the same decision made three ways.

| decision | `kovitking` | `sumerene` | `binh234` |
|---|---|---|---|
| sampling | seek every **2.0 s** ([`app.js:34`](https://github.com/kovitking/video2slides/blob/2e16e894d6bab283a35505c390f5f8888695261f/video2slides/webapp/static/app.js#L34)) | seek every **1.0 s** ([`extract_slides.py:58`](https://github.com/sumerene/video2slides/blob/65b2a777709cd2811282bc8700452029cb5cc64f/scripts/extract_slides.py#L58)) | sequential decode, every Nth frame, N∈{1,2,3}, default **1** ([`video_2_slides.py:36-43`](https://github.com/binh234/video2slides/blob/ceaf516d3099d96a42ebbab742ac416717230ada/video_2_slides.py#L36-L43)) |
| working resolution for the decision | 1280-wide capture → 64×64 grey for the hash; PiP pass at 240-wide ([`app.js:33,37,39`](https://github.com/kovitking/video2slides/blob/2e16e894d6bab283a35505c390f5f8888695261f/video2slides/webapp/static/app.js#L33-L39)) | **full resolution, no downscale** ([`extract_slides.py:100-109`](https://github.com/sumerene/video2slides/blob/65b2a777709cd2811282bc8700452029cb5cc64f/scripts/extract_slides.py#L100-L109)) | 640-wide for bg-model ([`bg_modeling.py:60`](https://github.com/binh234/video2slides/blob/ceaf516d3099d96a42ebbab742ac416717230ada/bg_modeling.py#L60)); **full-res grey** for frame-diff ([`frame_differencing.py:62`](https://github.com/binh234/video2slides/blob/ceaf516d3099d96a42ebbab742ac416717230ada/frame_differencing.py#L62)) — inconsistent within the same repo |
| change metric | DCT pHash, **256 bits** (`hash_size=16`, `highfreq_factor=4`, re-implemented in JS to match `imagehash.phash`) ([`app.js:38-39,99-113`](https://github.com/kovitking/video2slides/blob/2e16e894d6bab283a35505c390f5f8888695261f/video2slides/webapp/static/app.js#L99-L113)) | `imagehash.phash` **and** `imagehash.dhash`, default `hash_size=8` → **64 bits each** ([`extract_slides.py:37-42`](https://github.com/sumerene/video2slides/blob/65b2a777709cd2811282bc8700452029cb5cc64f/scripts/extract_slides.py#L37-L42)) | GMG/KNN foreground **area %**, or thresholded `absdiff` area %; `dhash` at `hash_size=12` → **144 bits** used only in post-processing ([`config.py:18-20`](https://github.com/binh234/video2slides/blob/ceaf516d3099d96a42ebbab742ac416717230ada/config.py#L18-L20)) |
| change threshold | Hamming **≤ 10/256 = 3.9 %** joins the current run; presets sparse/default/dense = 14/10/6 ([`app.js:28-32`](https://github.com/kovitking/video2slides/blob/2e16e894d6bab283a35505c390f5f8888695261f/video2slides/webapp/static/app.js#L28-L32)) | Hamming **< 10/64 = 15.6 %** on *each* hash ([`extract_slides.py:59-60`](https://github.com/sumerene/video2slides/blob/65b2a777709cd2811282bc8700452029cb5cc64f/scripts/extract_slides.py#L59-L60)) | fg area **< 0.01 %** → capture, **≥ 0.15 %** → re-arm ([`config.py:11-12`](https://github.com/binh234/video2slides/blob/ceaf516d3099d96a42ebbab742ac416717230ada/config.py#L11-L12)); frame-diff: per-pixel δ **> 80**, dilate 7×7 ellipse, area **≥ 0.06 %** ([`frame_differencing.py:8,17,67-75`](https://github.com/binh234/video2slides/blob/ceaf516d3099d96a42ebbab742ac416717230ada/frame_differencing.py#L67-L75)) |
| dedupe **scope** | **adjacent** — compared against `confirmedHash`, the single previously emitted slide ([`app.js:272`](https://github.com/kovitking/video2slides/blob/2e16e894d6bab283a35505c390f5f8888695261f/video2slides/webapp/static/app.js#L272)) | **global** — linear scan over every slide saved so far ([`extract_slides.py:45-49,118`](https://github.com/sumerene/video2slides/blob/65b2a777709cd2811282bc8700452029cb5cc64f/scripts/extract_slides.py#L45-L49)) | **hybrid** — exact-hash match anywhere in the video via a dict, near-hash match only against a `deque(maxlen=5)` of accepted slides ([`post_process.py:11-33`](https://github.com/binh234/video2slides/blob/ceaf516d3099d96a42ebbab742ac416717230ada/post_process.py#L11-L33)) |
| non-slide gate | none | **Laplacian variance < 300 → skip frame** ([`extract_slides.py:103-107`](https://github.com/sumerene/video2slides/blob/65b2a777709cd2811282bc8700452029cb5cc64f/scripts/extract_slides.py#L103-L107)) | none |
| which frame of the dwell | **middle** of the stable run ([`app.js:273`](https://github.com/kovitking/video2slides/blob/2e16e894d6bab283a35505c390f5f8888695261f/video2slides/webapp/static/app.js#L273)) | **first** sample that differs ([`extract_slides.py:123-126`](https://github.com/sumerene/video2slides/blob/65b2a777709cd2811282bc8700452029cb5cc64f/scripts/extract_slides.py#L123-L126)) | **first frame after motion settles** (bg-model) / **fixed 85 frames after motion starts** (frame-diff) ([`bg_modeling.py:70-77`](https://github.com/binh234/video2slides/blob/ceaf516d3099d96a42ebbab742ac416717230ada/bg_modeling.py#L70-L77), [`frame_differencing.py:80-89`](https://github.com/binh234/video2slides/blob/ceaf516d3099d96a42ebbab742ac416717230ada/frame_differencing.py#L80-L89)) |
| slide region | detects the PiP box, **masks it for hashing only** | **manual** — human draws a red box, HSV finds it | none |
| output naming | `slide_{i}.png` posted to `/api/pdf`; no numbered files on disk ([`app.js:459`](https://github.com/kovitking/video2slides/blob/2e16e894d6bab283a35505c390f5f8888695261f/video2slides/webapp/static/app.js#L459)) | `slide_{n:03d}_{H-MM-SS}.png` — **index *and* timestamp** ([`extract_slides.py:124-125`](https://github.com/sumerene/video2slides/blob/65b2a777709cd2811282bc8700452029cb5cc64f/scripts/extract_slides.py#L124-L125)) | `{n:03}.jpg` ([`bg_modeling.py:75`](https://github.com/binh234/video2slides/blob/ceaf516d3099d96a42ebbab742ac416717230ada/bg_modeling.py#L75)) |
| output pixel fidelity | PNG, but **capped at 1280 px wide** — a 1080p source is downsampled ([`app.js:33,345`](https://github.com/kovitking/video2slides/blob/2e16e894d6bab283a35505c390f5f8888695261f/video2slides/webapp/static/app.js#L345)) | PNG at full ROI resolution → `img2pdf` | **JPEG quality 75** ([`bg_modeling.py:77`](https://github.com/binh234/video2slides/blob/ceaf516d3099d96a42ebbab742ac416717230ada/bg_modeling.py#L77)) |
| audio / transcript | **removed** (see D.5) | none | none |
| what the constants were tuned against | one synthetic 24 s video + one real 60-min webinar, **eyeballed, no counts recorded** | "1080P academic PPT", page turns every 5–30 s ([`SKILL.md:124`](https://github.com/sumerene/video2slides/blob/65b2a777709cd2811282bc8700452029cb5cc64f/SKILL.md#L124)) | **LearnOpenCV tutorial defaults**, demoed on 5-minute YouTube explainers ([`README.md`](https://github.com/binh234/video2slides/blob/ceaf516d3099d96a42ebbab742ac416717230ada/README.md) "References" §1) |

Two things fall out of the table that no single repo makes visible:

**Two of the three independently land on ~4 % of hash bits.** `kovitking` uses 10/256 = 3.9 %; `binh234` parameterises
the threshold as a similarity *percent* and derives the Hamming distance from it, `diff_threshold = int(hash_size² ×
(100 − sim_threshold) / 100)` — 96 % similarity is 4 % of bits by construction
([`video_2_slides.py:136`](https://github.com/binh234/video2slides/blob/ceaf516d3099d96a42ebbab742ac416717230ada/video_2_slides.py#L136)).
`sumerene` sits at 15.6 % per hash but only because it requires **two** hash families to agree. The `binh234`
formulation is the liftable one: it is the only parameterisation in the scan that survives a change of hash size without
silently retuning the detector. **Adopt** for #11 — express any hash threshold as a fraction of bits, never as a raw
Hamming count.

**The dwell-frame choice is a free axis and all three answer it differently** — middle, first, first-after-settle — with
`vid2slides` supplying a fourth (D.4). None of them measures the choice. See D.6.

---

### D.2 sumerene

The dual-hash rule is four lines
([`extract_slides.py:45-49`](https://github.com/sumerene/video2slides/blob/65b2a777709cd2811282bc8700452029cb5cc64f/scripts/extract_slides.py#L45-L49)):

```python
def is_duplicate(ph, dh, saved_hashes, p_thresh, d_thresh):
    for sp, sd in saved_hashes:
        if (ph - sp) < p_thresh and (dh - sd) < d_thresh:
            return True
    return False
```

The two hashes are `imagehash.phash` and `imagehash.dhash`, both computed on the same BGR→RGB ROI at the library default
`hash_size=8` (64 bits), and compared by `imagehash`'s `__sub__` (Hamming distance)
([`extract_slides.py:37-42`](https://github.com/sumerene/video2slides/blob/65b2a777709cd2811282bc8700452029cb5cc64f/scripts/extract_slides.py#L37-L42)).
The agreement is evaluated as **AND on the duplicate side**, both distances strictly `<` their own threshold (defaults
10 and 10), against *every* previously saved slide. Equivalently: a frame is kept as new if **either** hash disagrees.
That is precisely the "recall over precision" bias this project has, arrived at independently, and the author states the
reason ([`README.md:9`](https://github.com/sumerene/video2slides/blob/65b2a777709cd2811282bc8700452029cb5cc64f/README.md#L9),
[`SKILL.md:62-65`](https://github.com/sumerene/video2slides/blob/65b2a777709cd2811282bc8700452029cb5cc64f/SKILL.md#L62-L65)):

> pHash is sensitive to structure, but when academic PPT templates are uniform it misjudges easily; dHash is more
> sensitive to differences in text content. Both must judge it a duplicate before skipping — this avoids deleting by
> mistake. *(translated; original zh)*

The pitfall table names the rejected alternative explicitly: *"slide dedupe — wrong: SSIM alone or pHash alone; right:
pHash + dHash, both must agree"*
([`SKILL.md:115`](https://github.com/sumerene/video2slides/blob/65b2a777709cd2811282bc8700452029cb5cc64f/SKILL.md#L115)).
This is anecdotal, not measured, but it is a named failure mode the #11 spike can test directly: **a uniform deck
template is the case where pHash alone under-triggers.** Two of the six reference videos should be a uniform-template
deck for the AND rule to be worth anything.

**Verdict: measure in the spike (#11).** The shortlist currently treats "perceptual hashes" as one row. It should be at
least three: pHash alone, dHash alone, and the AND-of-both. The cost of the third is one extra 64-bit hash per sample.

Two caveats the code does not state:

- The dedupe is **global** and the author intends it that way — `SKILL.md:60` gives the purpose as *"handles the case
  where the speaker goes back to an earlier slide"*, i.e. a return is deliberately dropped. Our
  `docs/adr/0003-correctness-metric-and-ground-truth.md` decided the opposite (a `repeats` list; a returning title card
  goes in the output). Lift the AND rule, **not** the global scope.
- Layer 1 compares against the previous *sampled* frame and Layer 2 against all saved slides
  ([`extract_slides.py:112-121`](https://github.com/sumerene/video2slides/blob/65b2a777709cd2811282bc8700452029cb5cc64f/scripts/extract_slides.py#L112-L121)),
  so a run that drifts is caught by Layer 2 rather than Layer 1. This repo does **not** have the drift bug described in
  D.6, because its Layer-1 comparison is only a fast path and Layer 2 re-checks against fixed anchors.

#### D.2.1 Laplacian variance, the #17 datapoint

```python
gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
lap_var = cv2.Laplacian(gray, cv2.CV_64F).var()
if lap_var < args.laplacian:      # default 300
    sec += args.interval
    continue
```
([`extract_slides.py:102-107`](https://github.com/sumerene/video2slides/blob/65b2a777709cd2811282bc8700452029cb5cc64f/scripts/extract_slides.py#L102-L107))

Precisely: **threshold 300**, on the **variance of the 64-bit Laplacian of the greyscale ROI at full source
resolution** (no downscale), applied to the ROI *after* the crop, evaluated **before** hashing. What it is meant to
reject, per `SKILL.md:71`: *"frames below this value (speaker close-ups, transition frames) are not slides"*. The
author's generalisation note flags it as the one constant that needs retuning across resolutions:
*"if the video resolution differs a lot, fine-tune `LAPLACIAN_THRESH`"*
([`SKILL.md:124`](https://github.com/sumerene/video2slides/blob/65b2a777709cd2811282bc8700452029cb5cc64f/SKILL.md#L124)).

Three things the #17 spike must account for, none of which are in the repo:

1. **It is not resolution-independent and it is not ROI-size-independent.** The Laplacian is an unnormalised
   second-difference kernel; downscaling a frame raises per-pixel gradient magnitudes, so 300 on a 1920-wide ROI is a
   different gate from 300 on a 640-wide one. Any value we measure must be pinned to a stated working resolution, or
   normalised (e.g. compute on a fixed-height resize) before it is comparable across the reference set.
2. **It runs before everything, so a false reject is a silent miss.** A title slide — a few large words on a plain
   background — is exactly the low-Laplacian case, and it is also exactly the slide a viewer would most notice missing.
   Given the project's lexicographic (misses, surplus) metric, a gate in this position is the single most dangerous
   component in the pipeline.
3. Its stated targets — speaker close-up, transition frame — are our "camera cutaway" and "cross-fade" hard cases. So it
   is worth measuring, but the right place for it may be as a **tie-break/annotation**, not a pre-filter.

**Verdict: measure in the spike (#17), as a labelled score rather than a gate.** Record `lap_var` for every sampled
frame of the reference set alongside the ground-truth label, then ask whether *any* threshold separates slide from
non-slide with zero misses. If no threshold does, #17 is answered in the negative for this feature without ever wiring
it into the pipeline.

#### D.2.2 ROI: the human is the detector

`detect_roi.py` has no CV region detection at all. The flow is: dump a frame from **t = 10 s**
([`detect_roi.py:93`](https://github.com/sumerene/video2slides/blob/65b2a777709cd2811282bc8700452029cb5cc64f/scripts/detect_roi.py#L93)),
the human draws a red box in any paint program, HSV `inRange` over two hue bands — `[0,100,100]–[10,255,255]` and
`[160,100,100]–[180,255,255]` — recovers the red pixels, and the bounding box of **all** of them (a global `min`/`max`,
no connected components) becomes the ROI
([`detect_roi.py:31-43`](https://github.com/sumerene/video2slides/blob/65b2a777709cd2811282bc8700452029cb5cc64f/scripts/detect_roi.py#L31-L43)).

Two details are liftable regardless:

- **The ROI is stored normalised to 0–1** and re-applied to the frame dimensions at use time
  ([`detect_roi.py:42-43`](https://github.com/sumerene/video2slides/blob/65b2a777709cd2811282bc8700452029cb5cc64f/scripts/detect_roi.py#L42-L43),
  [`extract_slides.py:28-34`](https://github.com/sumerene/video2slides/blob/65b2a777709cd2811282bc8700452029cb5cc64f/scripts/extract_slides.py#L28-L34)),
  so the same rect survives a resolution change. Our `tools/groundtruth/runs.py --rect` already does this; worth keeping.
- **`--test` dumps N=5 crops spread evenly across the video** for eyeballing before committing
  ([`detect_roi.py:50-79`](https://github.com/sumerene/video2slides/blob/65b2a777709cd2811282bc8700452029cb5cc64f/scripts/detect_roi.py#L50-L79)),
  and the skill makes operator confirmation mandatory before proceeding (`SKILL.md:37`). That is the cheapest possible
  validation harness for #12 and costs nothing to build.

And the **negative result**, which is the part worth carrying into #12
([`SKILL.md:44-47`](https://github.com/sumerene/video2slides/blob/65b2a777709cd2811282bc8700452029cb5cc64f/SKILL.md#L44-L47)):

> **Unreliable methods (do not use):**
> - CV edge detection / brightness analysis / Sobel projection: conference decorations (logos, title bars, separator
>   lines) have brightness and edge characteristics similar to the PPT content, and cannot be told apart.
> - Asking a multimodal LLM for the coordinates: measured deviation is large, the region still includes decoration, not
>   reliable. *(translated; original zh)*

This is one practitioner's experience on one class of video (Chinese conference streams with heavy branded chrome), not
a benchmark — but it is a first-hand report against two approaches for #12, one of which (edge/projection) is close to
the TalkMiner-style edge superset on the #11 shortlist and to a projection-profile activity crop. **The failure mode
named is specific enough to test: branded chrome around the slide.** At least one reference video should have a
decorated frame, or #12 will be measured on the easy case only.

**Verdict for the red-box scheme itself: reject as a strategy** (this project must not require a paint program),
**adopt the normalised-rect storage and the N-sample crop dump** as spike tooling for #12.

---

### D.3 binh234

This is the LearnOpenCV "video to slides converter" pipeline, and the README says so
([References §1](https://github.com/binh234/video2slides/blob/ceaf516d3099d96a42ebbab742ac416717230ada/README.md)).
The constants in `config.py` are therefore **tutorial defaults, not independently tuned values** — provenance that
matters, because the demo material in `output_results/` is four 5-minute YouTube explainers, not a 45–60 minute talk.

The technique worth lifting is the **Schmitt trigger on foreground area**
([`bg_modeling.py:66-83`](https://github.com/binh234/video2slides/blob/ceaf516d3099d96a42ebbab742ac416717230ada/bg_modeling.py#L66-L83)):

```python
p_non_zero = (cv2.countNonZero(fg_mask) / (1.0 * fg_mask.size)) * 100
if p_non_zero < MAX_PERCENT_THRESH and not capture_frame:   # 0.01 %  -> motion stopped
    capture_frame = True
    ...save orig_frame...
elif capture_frame and p_non_zero >= MIN_PERCENT_THRESH:    # 0.15 %  -> motion resumed
    capture_frame = False
```

Two thresholds with a 15× gap between them (`MAX_PERCENT = 0.01`, `MIN_PERCENT = 0.15`;
[`config.py:11-12`](https://github.com/binh234/video2slides/blob/ceaf516d3099d96a42ebbab742ac416717230ada/config.py#L11-L12))
and a latch, so a single capture fires per quiet period and re-arms only after real motion. The naming is confusing —
`MIN_PERCENT` is the *larger* number — which is itself a warning to pick clearer names if we lift this.

Three properties matter for us:

- **It answers "which frame of a dwell" as "the first frame after the transition finishes"**, which is the only one of
  the four answers in this group that is defined by the *content* rather than by position in the run. For a progressive
  build this captures each completed build state; for an embedded video it captures the frame after playback stops.
- **It decides on a 640-wide resize but saves `orig_frame` at full resolution**
  ([`bg_modeling.py:58-60,77`](https://github.com/binh234/video2slides/blob/ceaf516d3099d96a42ebbab742ac416717230ada/bg_modeling.py#L58-L60)).
  Decide small, save big — the right shape for our host.
- **It requires a background model with a warm-up.** GMG is `cv2.bgsegm` (opencv-contrib, not in
  `opencv-python-headless`) with `initializationFrames=history=15` and `decisionThreshold=0.75`; KNN is core OpenCV with
  `history=15, dist2Threshold=100, detectShadows=False`
  ([`bg_modeling.py:21-30`](https://github.com/binh234/video2slides/blob/ceaf516d3099d96a42ebbab742ac416717230ada/bg_modeling.py#L21-L30),
  [`config.py:7-9`](https://github.com/binh234/video2slides/blob/ceaf516d3099d96a42ebbab742ac416717230ada/config.py#L7-L9)).
  **The GMG path is unavailable under the project's wheels-only, headless constraint** — it needs `opencv-contrib-python`.
  KNN is available. The default in both the CLI and the Gradio app is GMG.

Note that the hysteresis state machine does not actually need a background subtractor: a plain `absdiff` against the
previous sampled frame produces a "% of the frame that changed" signal of the same shape, with no model, no warm-up and
no contrib dependency. **Adopt the hysteresis; do not adopt the background model.**

The `Frame_Diff` alternative is cruder and worth noting as a rejected design: per-pixel `absdiff` thresholded at **80**
(0–255), dilated with a 7×7 ellipse, area ≥ **0.06 %** arms a counter, and the capture happens a fixed
**`ELAPSED_FRAME_THRESH = 85` frames** later — ~2.8 s at 30 fps — regardless of whether motion has actually stopped
([`frame_differencing.py:8,67-89`](https://github.com/binh234/video2slides/blob/ceaf516d3099d96a42ebbab742ac416717230ada/frame_differencing.py#L67-L89)).
A fixed delay, not a settle detector. It does however **always save the first frame of the video unconditionally**
([`frame_differencing.py:34-48`](https://github.com/binh234/video2slides/blob/ceaf516d3099d96a42ebbab742ac416717230ada/frame_differencing.py#L34-L48)) —
a one-line recall guarantee for the opening slide that the bg-model path lacks, and that `kovitking` reimplements as
`if (chosen.length === 0) chosen.push(samples[0])`.

**Hard case acknowledged in the README, not solved**
([`README.md:11`](https://github.com/binh234/video2slides/blob/ceaf516d3099d96a42ebbab742ac416717230ada/README.md)):

> For slide videos with full background animation similar to [this video], the algorithm cannot extract the right frames
> after the animation ends. In that case, using Frame Differencing (`--type Frame_Diff`) will yield better results, but
> the results are still decent.

A full-frame animation never lets the foreground area fall below 0.01 %, so the settle detector never fires. This is our
"embedded video / animation playing inside a slide" hard case, and the repo's answer is "switch detectors and accept
worse results". The complementary observation is useful: **an area-based settle detector fails open (captures nothing)
under continuous motion, while a hash-based change detector fails closed (captures constantly).** Under a (misses,
surplus) metric, failing closed is strictly better. That argues for hashing as the primary and hysteresis as a refiner
of *which* frame, not as the change detector itself.

**Workaround present but undocumented:** the two thresholds that actually control capture (`MIN_PERCENT`, `MAX_PERCENT`)
are **not exposed** in either the CLI or the Gradio UI, while `hash_size`, `queue_len` and `frame_buffer_history` — which
barely matter — get sliders
([`app.py:139-184`](https://github.com/binh234/video2slides/blob/ceaf516d3099d96a42ebbab742ac416717230ada/app.py#L139-L184)).
The advertised tuning surface is not the real one.

**Verdicts.** Hysteresis settle detector: **measure in the spike (#11)**, as a dwell-frame chooser. Similarity-as-percent
threshold: **adopt (#11)**. Sliding-window-of-5 dedupe: **measure (#11)** — it is the middle option between `kovitking`'s
adjacent-only and `sumerene`'s global, and it is the one that matches ADR-0003's `repeats` treatment most closely (a
return after >5 distinct slides is re-emitted). JPEG quality 75 output: **reject** — `sumerene`'s insistence on PNG +
`img2pdf` with an explicit "never use PIL, `Image.save()` re-encodes even at `quality=100`"
([`generate_pdf.py:7-8`](https://github.com/sumerene/video2slides/blob/65b2a777709cd2811282bc8700452029cb5cc64f/scripts/generate_pdf.py#L7-L8),
[`SKILL.md:107`](https://github.com/sumerene/video2slides/blob/65b2a777709cd2811282bc8700452029cb5cc64f/SKILL.md#L107))
is the right call for a deliverable meant to be read.

---

### D.4 vid2slides

Both claims in `docs/research/slide-region-crop.md` §1.1 **hold at the cloned sha**.

**Claim 1 — "contour detection" is a near-pure-black letterbox-bar remover. VERIFIED.**
[`vid2slides.py:269-293`](https://github.com/patrickmineault/vid2slides/blob/62121168143d0576aa0990530c2af0d6dba629ec/vid2slides/vid2slides.py#L269-L293)
is the whole detector. `ims` is built from `cv2.imread(el['source'])` (line 276) — `cv2.imread` returns **uint8 0–255**,
so `im.mean(axis=2)` is on a 0–255 scale, and line 280's `(A.mean(axis=0) > .2)` is *"mean intensity above 0.2 out of
255"*, i.e. "not essentially pure black". The mask is 1 almost everywhere; the largest contour's `boundingRect` therefore
strips only what is near-black in every slide keyframe. The prior research's reading is exactly right, including the
`cv2.imread` scale argument that the whole claim rests on.

**Claim 2 — `pip_location` is computed and read by nothing. VERIFIED.** `grep -rn "pip_location"` over the repo returns
exactly two hits, both writes: the return of `detect_faces`
([`vid2slides.py:197`](https://github.com/patrickmineault/vid2slides/blob/62121168143d0576aa0990530c2af0d6dba629ec/vid2slides/vid2slides.py#L197))
and the JSON assembly
([`vid2slides.py:408`](https://github.com/patrickmineault/vid2slides/blob/62121168143d0576aa0990530c2af0d6dba629ec/vid2slides/vid2slides.py#L408)).
`slides2pdf.py`, `slides2gif.py` and `slides2chapters.py` read `sequence['crop']` and nothing else. The KMeans is
`sklearn.cluster.KMeans()` at its default `n_clusters=8`, guarded by `if len(small_faces) > 8`
([`vid2slides.py:189-194`](https://github.com/patrickmineault/vid2slides/blob/62121168143d0576aa0990530c2af0d6dba629ec/vid2slides/vid2slides.py#L189-L194)).
The face detector's only load-bearing use is the *temporal* `has_full_face` filter (a face wider than 25 % of the
thumbnail **height**, line 181), not a spatial one. Claim stands unchanged.

#### D.4.1 How it picks keyframes

Not covered by the prior research, and the most interesting idea in the repo
([`vid2slides.py:62-81`](https://github.com/patrickmineault/vid2slides/blob/62121168143d0576aa0990530c2af0d6dba629ec/vid2slides/vid2slides.py#L62-L81)):

```python
def heuristic_frames(sizes, ban_time=5):
    """Pick the images which are least compressible, and ban surrounding images."""
```

`sizes` is literally `os.stat(filename).st_size` of each JPEG thumbnail
([`vid2slides.py:210`](https://github.com/patrickmineault/vid2slides/blob/62121168143d0576aa0990530c2af0d6dba629ec/vid2slides/vid2slides.py#L210)).
Greedy non-maximum suppression over JPEG file size: take the largest file, ban ±`ban_time` indices around it, repeat.
**JPEG byte size is a free proxy for visual complexity** — ffmpeg has already computed it, at zero marginal cost, and it
correlates with "how much is on this slide". For a progressive build, the *most complete* build state is the largest
file. That is a directly liftable dwell-frame chooser and a fourth distinct answer to the question:

> **Export the frame of the run whose JPEG encodes largest** — the most-built, least-blurred, least-cross-faded moment.

Cheap enough to measure for free in the #11 spike (encode each sampled frame once to JPEG in memory, record `len(buf)`).

Three constants and their consequences:

- `ban_time=5` at `thumb_interval=2` s means **±10 s of exclusion**, so `vid2slides` structurally **cannot emit two
  slides less than 12 s apart**. On a talk with 5-second slides that is a guaranteed miss, with no diagnostic.
- `has_full_face` frames get `sizes[i] = 0`
  ([`vid2slides.py:214-216`](https://github.com/patrickmineault/vid2slides/blob/62121168143d0576aa0990530c2af0d6dba629ec/vid2slides/vid2slides.py#L214-L216)),
  banning a speaker close-up from ever becoming a template — a **camera-cutaway** handler, and a clean one: the cutaway
  frames are also excluded from the HMM's observation sequence entirely (`to_select`,
  [`vid2slides.py:348-354`](https://github.com/patrickmineault/vid2slides/blob/62121168143d0576aa0990530c2af0d6dba629ec/vid2slides/vid2slides.py#L348-L354))
  and the whole cutaway becomes one `type: 'speaker'` segment in the output JSON. **Adopt the pattern** (a gate that
  labels a segment rather than deleting a frame), even if the Haar cascade is not the detector we would use.
- The HMM is **left-to-right with no backward transitions**:
  `T = arange(n)[:,None] < arange(n)[None,:]`, `A = 0.8·I + 0.2·T/rowsum`, absorbing final state
  ([`vid2slides.py:256-261`](https://github.com/patrickmineault/vid2slides/blob/62121168143d0576aa0990530c2af0d6dba629ec/vid2slides/vid2slides.py#L256-L261),
  `jump_probability=0.2`). **A return to an earlier slide is structurally impossible** — the model assigns it zero
  probability. This is the strongest form of the "returns are deduped away" decision in the scan: not a policy, an
  axiom. Directly incompatible with ADR-0003's `repeats`. **Reject** the monotonic HMM for #11.

#### D.4.2 A silent ordering bug

`detect_faces` iterates `sorted(glob.glob(...))`
([`vid2slides.py:167`](https://github.com/patrickmineault/vid2slides/blob/62121168143d0576aa0990530c2af0d6dba629ec/vid2slides/vid2slides.py#L167));
`get_delta_images` iterates **unsorted** `glob.glob(...)`
([`vid2slides.py:201`](https://github.com/patrickmineault/vid2slides/blob/62121168143d0576aa0990530c2af0d6dba629ec/vid2slides/vid2slides.py#L201)).
`glob` returns `os.scandir` order, which on ext4 is hash order, not lexical. So `has_face[i]` is indexed by sorted order
while `images[i]` and `sizes[i]` are in directory order — the face mask lands on the wrong frames — and, worse, the
`images` array fed to the left-to-right HMM is **not in time order at all**. The monotonicity the whole model depends on
is not guaranteed to hold on the data it is given. Whatever the demo output shows, it is not evidence that this
architecture works. (It happens to work when `glob` returns sorted order, which small directories on some filesystems
do.) **Negative finding: do not cite `vid2slides`' demo as validation of the HMM approach.**

#### D.4.3 An OCR gate that silently drops slides

All three consumers filter on `el['type'] == 'slide' **and el['title']**`
([`slides2pdf.py:17`](https://github.com/patrickmineault/vid2slides/blob/62121168143d0576aa0990530c2af0d6dba629ec/vid2slides/slides2pdf.py#L17),
[`slides2gif.py:9`](https://github.com/patrickmineault/vid2slides/blob/62121168143d0576aa0990530c2af0d6dba629ec/vid2slides/slides2gif.py#L9),
[`slides2chapters.py:19`](https://github.com/patrickmineault/vid2slides/blob/62121168143d0576aa0990530c2af0d6dba629ec/vid2slides/slides2chapters.py#L19)).
`el['title']` comes from `get_slide_title`, which keeps only Tesseract blocks with **confidence > 80** and then returns
the first text block from the top that is **more than 30 pixels high and at least 5 characters long**
([`vid2slides.py:296-323`](https://github.com/patrickmineault/vid2slides/blob/62121168143d0576aa0990530c2af0d6dba629ec/vid2slides/vid2slides.py#L296-L323)).
A detected slide with no confidently-OCR'd large heading — a full-bleed diagram, a photo, a chart, a slide in a script
Tesseract handles poorly — **is silently absent from the PDF, the GIF and the chapter list**. The README says nothing
about it; it advertises OCR as a feature, not as a filter. This is the exact failure shape the project's metric is built
to punish, in the one surveyed project that is also the closest to our output format. **Reject, and treat as a cautionary
pattern: never let a downstream enrichment step decide membership in the output set.**

Corroborating evidence that the crop is a no-op, from the project's own shipped demo
([`demo/91004320940_1_out.txt`](https://github.com/patrickmineault/vid2slides/blob/62121168143d0576aa0990530c2af0d6dba629ec/demo/91004320940_1_out.txt)):
line 4 of the chapter listing is `00:01:06 - Adobe Acrobat Reader DC Anzeige Unterschreiben Fenster Hilfe` — the Acrobat
menu bar survived the crop *and* was strong enough to become a slide title, in the showcase output.

#### D.4.4 Audio and transcript

**Nothing.** `vid2slides` never touches the audio stream. Its text output is OCR of the slide images
([`vid2slides.py:415-419`](https://github.com/patrickmineault/vid2slides/blob/62121168143d0576aa0990530c2af0d6dba629ec/vid2slides/vid2slides.py#L415-L419)),
and its "chapters" feature is slide titles plus start timestamps, aimed at YouTube chapter markers. Of all four repos in
this group, **none produces a speech transcript in its current code.** Our `pair` stage has no prior art here.

Still dead on a modern stack, unchanged at this sha: `np.int` ([line 54] — removed in NumPy 1.24), `moviepy.editor`
(removed in MoviePy 2.x), and `environment.yml` pinning Python 3.8.5, `decord==0.4.2`, `opencv-python==4.4.0.46`.

---

### D.5 kovitking

**Claim: it detects the PiP box well but masks it only for hashing and saves the UNMASKED full frame. VERIFIED, verbatim.**
The mask is applied inside pass 1 only, as a black `fillRect` on the hashing canvas
([`app.js:235-238`](https://github.com/kovitking/video2slides/blob/2e16e894d6bab283a35505c390f5f8888695261f/video2slides/webapp/static/app.js#L235-L238)).
Pass 2 carries the comment *"Saves the UNMASKED frame — the PiP mask is only used for hashing."*
([`app.js:291`](https://github.com/kovitking/video2slides/blob/2e16e894d6bab283a35505c390f5f8888695261f/video2slides/webapp/static/app.js#L291))
and `captureSlideImages` calls `drawVideoFrame(video, canvas, detectW, detectH)` with no `fillRect`
([`app.js:302`](https://github.com/kovitking/video2slides/blob/2e16e894d6bab283a35505c390f5f8888695261f/video2slides/webapp/static/app.js#L302)).
The exported PDF contains the webcam overlay. There is no crop anywhere in the repo. Every numeric detail in
`slide-region-crop.md` §1.2 also checks out at this sha: `PIP_DIFF_THRESHOLD = 4.0`, `PIP_SAMPLE_N = 60`,
`PIP_WORK_WIDTH = 240`, `n = clamp(floor(duration/2.0), 2, 60)`, pair spacing `SAMPLE_INTERVAL_SEC * 0.5` = 1.0 s,
exact per-pixel median, single global min/max scan, the `0.01`/`0.35`/`0.6` plausibility gate, 6 px pad, and `return null`
(proceed unmasked, no warning) on failure
([`app.js:162-220`](https://github.com/kovitking/video2slides/blob/2e16e894d6bab283a35505c390f5f8888695261f/video2slides/webapp/static/app.js#L162-L220)).

The prior research covered the PiP detector thoroughly. What it did not cover — because it was a crop investigation — is
`detectSlides`, which is the piece that matters for #11.

#### D.5.1 The stability window, and the drift that hides progressive builds

[`app.js:252-287`](https://github.com/kovitking/video2slides/blob/2e16e894d6bab283a35505c390f5f8888695261f/video2slides/webapp/static/app.js#L252-L287):

```js
if (hammingDistance(h, candidateHash) <= hashThreshold) {
  stableCount++;
  candidateHash = h; // drift slowly with the evolving look of the slide
} else {
  if (stableCount >= minStableFrames &&
      (confirmedHash === null || hammingDistance(candidateHash, confirmedHash) > hashThreshold)) {
    chosen.push(samples[candidateStartIdx + Math.floor(stableCount / 2)]);
    confirmedHash = candidateHash;
  }
  ...
}
```

Four decisions in nine lines:

1. **The run's reference hash drifts to the latest frame** (line 269), deliberately, with a comment. Consequence: a run
   can walk arbitrarily far from where it started as long as no single 2-second step exceeds the threshold. A
   progressive build that adds one bullet every few seconds is absorbed into one run and emits **one** slide. The
   project states this as a feature — the README calls it *"this throws out mid-transition / build-animation frames
   instead of capturing them as extra false slides"*
   ([`video2slides/README.md:29-31`](https://github.com/kovitking/video2slides/blob/2e16e894d6bab283a35505c390f5f8888695261f/video2slides/README.md)).
   **That is precision-first, the exact opposite of our bias.** Under our metric it is a miss generator.
2. **Dedupe against `confirmedHash` only** — the single previously emitted slide, so a return to an earlier slide *is*
   re-emitted, and an A→B→A→B vision-mixer alternation emits every alternation. Recall-friendly, surplus-heavy; the
   right default for us, and the opposite of `sumerene`'s.
3. **The exported frame is the middle of the run**, `candidateStartIdx + floor(stableCount/2)` (line 273). Combined with
   drift, "middle" on a progressive build means a half-built slide: neither the empty state nor the finished one.
4. **The minimum-dwell gate is inert at two of the three presets.**
   `minStableFrames = max(1, round(minStableSeconds / 2.0))`
   ([`app.js:254`](https://github.com/kovitking/video2slides/blob/2e16e894d6bab283a35505c390f5f8888695261f/video2slides/webapp/static/app.js#L254)) →
   **default** `round(1.5/2.0) = round(0.75) = 1`; **dense** `round(0.25) = 0 → max(1,·) = 1`; **sparse**
   `round(1.5) = 2`. So the headline feature — *"a slide is only confirmed once its hash has stayed put for a minimum
   stable duration"* — does nothing at all unless the user picks "sparse". Undocumented, and not the kind of thing a
   README would ever reveal. If we build a dwell gate, express it in **samples**, not in seconds divided by a sampling
   interval that may not divide evenly.

#### D.5.2 The two-pass architecture

The file's header comment (lines 15–24) states the design: pass 1 seeks the whole video once and retains **only a
256-bit hash per sample** (~a few hundred bytes), never holding more than one full-resolution frame; pass 2 re-seeks
only the chosen timestamps to capture PNGs, cached by timestamp. The payoff is stated explicitly: *"changing sensitivity
re-runs the stability window over already-computed hashes instantly, no reseeking needed."*

For the #11 spike on a 6-video reference set on an i3-4170, this is the difference between a threshold sweep that takes
an afternoon and one that takes seconds. **Adopt as spike-harness architecture: extract every per-sample feature once
(pHash, dHash, Laplacian variance, JPEG byte size, edge density, intensity histogram), persist to a per-video
feature file, and run every candidate detector and every threshold offline against that file.** The decode/seek pass is
the only expensive part, and the existing `docs/research/slide-region-crop.md` §3.3 measurements already say the pixel
math is free by comparison. This also makes the ground truth and the detector sweeps reproducible from one artefact.

#### D.5.3 Transcription: removed, and why

`PLAN.md` is stale relative to the shipped code. It is titled *"video → slides.pdf + transcript.srt for NotebookLM"* and
its architecture diagram shows an `ffmpeg -vn → faster-whisper (local, CPU, int8) → transcript.srt` branch
([`PLAN.md:1,28-29`](https://github.com/kovitking/video2slides/blob/2e16e894d6bab283a35505c390f5f8888695261f/video2slides/PLAN.md#L28-L29)).
`grep -rn "whisper|srt|transcript"` over the current tree returns exactly one hit: `app.py`'s docstring saying *"No
transcription"*. The reason is recorded in two places:

> Both the CLI and transcription were removed — **CPU transcription of long recordings was impractically slow**, and
> once transcription was gone there was no reason to keep decoding video server-side either.
> ([`video2slides/README.md:74-78`](https://github.com/kovitking/video2slides/blob/2e16e894d6bab283a35505c390f5f8888695261f/video2slides/README.md),
> same in [`CLAUDE.md:17-22`](https://github.com/kovitking/video2slides/blob/2e16e894d6bab283a35505c390f5f8888695261f/CLAUDE.md))

Not one of our three tickets, but it is a first-hand field verdict on `faster-whisper` int8 on CPU for long recordings,
from a project whose entire purpose (NotebookLM ingestion) required the transcript — and it still got cut. Our
`transcribe` stage targets the same hardware class and the same 45–60 minute inputs. Worth a line in whatever ticket
owns transcription: **the one surveyed project that tried CPU Whisper on hour-long talks abandoned it.**

#### D.5.4 What the repo does and does not have as validation

`PLAN.md:54-64` records the only numbers in the repo: a **synthetic 24 s video**, 4 visually distinct slides held 6 s
each, plus a top-right box with a circle moving on every frame. Masked → **4/4** (captured at t=3/9/15/21 s, the run
midpoints, consistent with the `floor(stableCount/2)` rule); `--no-pip` → **1/4**. The README additionally claims
validation *"and a real 60-minute 1080p webinar recording"*
([`video2slides/README.md:39-41`](https://github.com/kovitking/video2slides/blob/2e16e894d6bab283a35505c390f5f8888695261f/video2slides/README.md)),
but `CLAUDE.md:112-116` describes that as *"confirmed via direct browser testing"* and `CLAUDE.md:14` states *"No test
suite"*. **There are no recorded slide counts on real footage anywhere in this repo.** The 4/4-vs-1/4 number is from a
synthetic worst case and should be cited as such.

Open problem the repo names and no longer has code for: *"Multiple PiP boxes: some webinar tools show two presenters
side by side … hasn't been tested against two separated boxes on opposite corners"*
([`PLAN.md:104-109`](https://github.com/kovitking/video2slides/blob/2e16e894d6bab283a35505c390f5f8888695261f/video2slides/PLAN.md#L104-L109)) —
and, as the crop research already noted, the merge logic `PLAN.md` credits with handling it lives only in the deleted
Python version.

One unbuilt suggestion is worth recording because it is a cheap #11 variant nobody in the scan implemented:
*"OCR-based confirmation: run pytesseract on the masked region and require both hash-distance AND text-content to differ
before confirming a new slide. Helps on slides with subtle background motion (e.g. an animated brand watermark) that
isn't confined to a clean rectangular PiP box"*
([`PLAN.md:93-97`](https://github.com/kovitking/video2slides/blob/2e16e894d6bab283a35505c390f5f8888695261f/video2slides/PLAN.md#L93-L97)).
Note the direction: requiring **both** to differ is a precision-first AND — the mirror image of `sumerene`'s
recall-first AND. For our bias the useful form is the OR: **either** the hash moved **or** the OCR text changed.
Tesseract on every sample is too slow for our host, but OCR on the frames of a *single run* is affordable and is the
only technique in the scan that would split a progressive build. **Measure in the spike (#11) as a run-splitter, not as
a frame-level detector.**

---

### D.6 The hard cases, across all four

| hard case | `kovitking` | `sumerene` | `binh234` | `vid2slides` |
|---|---|---|---|---|
| progressive build | **absorbed into one run** by the drifting reference; stated as intended | likely over-captures — a bullet changes dHash more than pHash, and the AND rule needs both to agree to skip | bg-model: captures each settled build state (good); frame-diff: fixed 85-frame delay may land mid-build | absorbed — one template per ±10 s window; the largest-JPEG rule at least favours the most-built state |
| camera cutaway to speaker | not handled; the speaker shot becomes a slide | Laplacian < 300 skips it (if the gate fires) | not handled | **handled** — `has_full_face` excludes the frames from templates *and* from the model, emitting a `type: 'speaker'` segment |
| embedded video / animation in a slide | hash churns → many surplus captures (fails closed) | churns → surplus | **fails open, captures nothing** — README admits it | churns; the moving region also has high JPEG size, so it attracts templates |
| moving webcam overlay | **the repo's whole reason to exist** — median-diff PiP detect + mask for hashing | only if the human's red box excludes it | not handled | `pip_location` computed and discarded; face frames filtered temporally only |
| burned-in subtitles changing per phrase | not handled — every phrase is a hash change → surplus (acceptable under our metric) | not handled — likely a new "slide" per phrase | bg-model: subtitle motion keeps fg% above 0.01 %, so **captures may never fire** | not handled |
| vision mixer cutting constantly | adjacent-only dedupe → every alternation emitted | global dedupe → each distinct shot emitted once | queue-of-5 → emitted unless within the last 5 | left-to-right HMM → the second visit is **structurally impossible**; the cut collapses |
| slide filmed on a screen at an angle | nothing | nothing | nothing | nothing |

**No project in group D contains any perspective-correction code.** Confirmed by inspection of every source file in all
four repos: no `getPerspectiveTransform`, no `warpPerspective`, no quadrilateral fitting. The angled-screen hard case has
zero prior art here.

**The dwell-frame question has four answers and nobody measured it.** Middle of run (`kovitking`), first of run
(`sumerene`), first after motion settles (`binh234` bg-model), largest JPEG in the neighbourhood (`vid2slides`). On a
static slide all four are identical; on a progressive build, a cross-fade, or a slide with an embedded video they pick
visibly different images, and under a lexicographic (misses, surplus) metric they change the *content* of the captures
rather than their count. This is a fifth axis the #11 spike should sweep and currently does not name — it is free to
measure, because all four choices are computable from the same cached per-sample features.

---

### D.7 The finding that should change the spike

`kovitking`'s drifting run reference (`candidateHash = h`, [`app.js:269`](https://github.com/kovitking/video2slides/blob/2e16e894d6bab283a35505c390f5f8888695261f/video2slides/webapp/static/app.js#L269))
is not just a property of their detector. **This project's own ground-truth tooling has the same structure.**
`tools/groundtruth/runs.py` ends its loop with `prev = reg` and compares each state only against the immediately
preceding one:

```python
frac = count_nonzero(abs(reg - prev) > delta) / reg.size   # delta=25
if frac > args.threshold:                                  # threshold=0.01
    runs.append(cur); cur = [k]
else:
    cur.append(k)
prev = reg
```

A progressive build whose each step changes less than 1 % of the slide rectangle collapses into **one run**, exactly as
it does in `kovitking`. Because `runs.py` is what decides *how many questions the ground-truth review page asks* — "one
question per run, not per state", per its own docstring — a collapsed build becomes **one ground-truth entry instead of
several**. Every detector then scores zero misses on that build, including detectors that genuinely missed the
intermediate states. The bias is in the measuring instrument, not in the candidates, and it biases the one number
(`misses`) that the correctness metric says declares the winner.

The fix is cheap and worth making before any spike runs: compare each state against the **anchor** of the current run —
the first state in it — rather than against the previous state, or against both and end the run if either exceeds the
threshold. `sumerene` shows the two-layer version of this (a fast adjacent check plus a re-check against fixed saved
anchors), which is why that repo does not have the bug.

Second-order, same theme: the `delta=25 / threshold=0.01` pair in `runs.py` is doing the same job as
`binh234`'s `MIN_PERCENT`/`MAX_PERCENT` and should be sanity-checked against a real build. One bullet line on a 1080p
slide inside a 0.6-area rectangle is well under 1 % of that rectangle's pixels.

---

## Group E — asindel/SliTraNet

**Cloned:** `extract-slides-cache/reference-implementations/SliTraNet`, HEAD
`994c3faca9615619926efcb7613af87331f9928b` (2023-12-17, the repo's *only* commit — it was
pushed as a single squashed drop). Permalink base:
`https://github.com/asindel/SliTraNet/blob/994c3faca9615619926efcb7613af87331f9928b/`.

**Size:** 1358 lines of Python in 7 files. Inference only — no training code, no dataset,
no frame export.

**Licence — correction to prior research.** `docs/research/slide-change-detection.md` §9.4
says "no licence file, so treat as unlicensed". That is now **wrong**: the repo carries
[`LICENSE`](https://github.com/asindel/SliTraNet/blob/994c3faca9615619926efcb7613af87331f9928b/LICENSE),
**MIT, Copyright (c) 2022 asindel**. The code *is* liftable. The pretrained weights are a
separate matter: they are distributed from a Google Drive folder linked in the README and
carry **no stated licence at all** — MIT covers "the Software" in the repo, and the weights
are not in the repo.

---

### E.1 It does falsify "nobody learns the change"

`docs/research/slide-change-detection.md` §9.6 concludes that four systems over sixteen
years all put a learned model at the same place — the slide-*frame* gate — and that
SliTraNet is "the exception, which *does* classify transitions". That hedge is correct but
far too weak. **All three of SliTraNet's networks operate on the change. Not one of them is
a slide-frame gate.**

| net | file:line | input | output |
|---|---|---|---|
| `net2d`, 2-D ResNet18 | [`test_SliTraNet.py:47-51`](https://github.com/asindel/SliTraNet/blob/994c3faca9615619926efcb7613af87331f9928b/test_SliTraNet.py#L47-L51) | **a pair** `(anchor_frame, current_frame)` stacked on the channel axis — 2 ch grayscale or 6 ch RGB, 256×256 | `n_class=1` + sigmoid: `pred<0.5` ⇒ **the two frames are different** ([`test_slide_detection_2d.py:89-93`](https://github.com/asindel/SliTraNet/blob/994c3faca9615619926efcb7613af87331f9928b/test_slide_detection_2d.py#L89-L93)) |
| `net1`, 3-D ResNet50 | [`test_SliTraNet.py:53-57`](https://github.com/asindel/SliTraNet/blob/994c3faca9615619926efcb7613af87331f9928b/test_SliTraNet.py#L53-L57) | an **8-frame clip** of the **raw full frame** | `n_class=3`: `0: slide-video transition, 1: slide, 2: video` ([`test_SliTraNet.py:186`](https://github.com/asindel/SliTraNet/blob/994c3faca9615619926efcb7613af87331f9928b/test_SliTraNet.py#L186)) |
| `net2`, 3-D ResNet50 | [`test_SliTraNet.py:59-63`](https://github.com/asindel/SliTraNet/blob/994c3faca9615619926efcb7613af87331f9928b/test_SliTraNet.py#L59-L63) | an **8-frame clip** of the **ROI crop** | `n_class=4`: `0: hard transition, 1: gradual transition, 2: slide, 3: video` ([`test_SliTraNet.py:185`](https://github.com/asindel/SliTraNet/blob/994c3faca9615619926efcb7613af87331f9928b/test_SliTraNet.py#L185)) |

The 2-D net is **a learned frame-difference function** — a Siamese/channel-concat pairwise
similarity, which the weight filename confirms: `Frame_similarity_ResNet18_gray.pth`
([`test_SliTraNet.py:212`](https://github.com/asindel/SliTraNet/blob/994c3faca9615619926efcb7613af87331f9928b/test_SliTraNet.py#L212)).
The paper is explicit: *"We train a 2-D ResNet18 for the discrimination task whether two
images are from the same slide (class 1) or not (class 0). For this task, we concatenate
both images along the color channel dimension"* (arXiv:2202.03540 §III.B). The 3-D nets
classify the transition **type** over a temporal window. `slide` vs `video` appears only as
one *class among four* inside a clip classifier used to **suppress** transition candidates —
it is a segment classifier, never a per-frame gate.

**Verdict on the falsification:** confirmed, and §9.6 should be rewritten. The correct
statement is not "nobody learns the change" but: *every system that put its model at the
slide-frame gate did so to stay cheap; the one system that pointed a model at the change
itself needed three networks and a GPU, and its own ablation shows the learned change
detector loses on recall to Gaussian-blurred frame differencing.* Which is E.2.

---

### E.2 The authors' own ablation beats their own CNN

Paper Table I (test set = 14 videos, 190 min, 380 ground-truth transitions). Reproduced
with the columns this project actually ranks by:

| method | #pred | **FN** | **Recall** | Precision | F1 |
|---|---|---|---|---|---|
| Ground truth | 380 | 0 | 100.00 | 100.00 | 100.00 |
| **`Diff-RGB-blur`** (stage 1, deterministic) | 992 | **15** | **96.05** | 36.79 | 53.21 |
| `Diff-gray-blur` (stage 1, deterministic) | 1011 | 15 | 96.05 | 36.10 | 52.48 |
| `2-D ResNet18-RGB` (stage 1, learned) | 1188 | 22 | 94.21 | 30.13 | 45.66 |
| `2-D ResNet18-gray` (stage 1, learned) | 911 | 25 | 93.42 | 38.97 | 55.00 |
| `ResNets-Reverse` (3-D first) | 366 | 77 | 79.74 | 82.79 | 81.23 |
| **`Diff-RGB-blur` + 3-D ResNet50** | 435 | **16** | **95.79** | 83.68 | 89.33 |
| `Diff-gray-blur` + 3-D ResNet50 | 442 | 16 | 95.79 | 82.35 | 88.56 |
| `SliTraNet-RGB-RGB` (full learned) | 453 | 23 | 93.95 | 78.81 | 85.71 |
| **`SliTraNet-gray-RGB`** (the shipped config) | 408 | **26** | **93.16** | 86.76 | 89.85 |

Read this against ADR 0003 (`docs/adr/0003-correctness-metric-and-ground-truth.md`), which
ranks lexicographically by **(misses, surplus)** and calls surplus "one keystroke away from
gone":

- **Stage 1 alone.** Deterministic Gaussian-blurred frame differencing: 15 misses. Learned
  2-D ResNet18: 25 misses (gray) / 22 (RGB). **The CNN misses 67% more transitions.** All
  it buys is +2.2 precision points (36.79 → 38.97) — i.e. it removes surplus, the axis that
  by ADR 0003 *cannot declare a winner*.
- **Full pipeline.** `Diff + 3-D` scores 16 misses; the all-learned `SliTraNet-gray-RGB`
  scores 26. Under this project's metric **the deterministic front end beats the learned one
  outright**, and it is not close: 10 fewer misses out of 380. SliTraNet wins only on F1
  (89.85 vs 89.33), a metric that averages misses with surplus — exactly the averaging ADR
  0003 refuses.
- The authors, optimising F1, chose the config that loses on recall. Their own numbers,
  re-ranked by this project's metric, say: **keep the heuristic front end, drop the 2-D
  CNN.** That is a peer-reviewed, 190-minute, 380-transition ablation validating this
  project's "deterministic first" preference at the exact point where the temptation to
  learn is strongest.

**Constants the authors tuned, and against what.** The `Diff-*-blur` baseline is Gaussian
blur with **kernel size (21,21)** before absolute differencing (paper §IV.C), attributed to
Perelman [23]. Tuned against 1080p / 25 fps / 6–33 min university lecture recordings with
4:3 and 16:9 slide formats. This is a directly liftable starting constant for **#11**'s
frame-differencing candidate — and note the blur is what makes differencing recall-safe
here: it suppresses compression noise and sub-pixel jitter without suppressing a new bullet.

> **#11 / #17 verdict: the strongest single result in this whole survey.** Adopt the
> conclusion, not the code. `Diff + blur(21,21)` at the anchor stage, measured against the
> shortlist. A learned change detector is not merely expensive — it is *measurably worse on
> the axis that declares the winner*.

---

### E.3 The deterministic skeleton

The thing worth stealing from this repo is not a network. It is the **anchor-based run
segmentation with a two-anchor video track**, in
[`test_slide_detection_2d.py:53-118`](https://github.com/asindel/SliTraNet/blob/994c3faca9615619926efcb7613af87331f9928b/test_slide_detection_2d.py#L53-L118).
It is entirely deterministic apart from one call — line 89 — and **any similarity function
drops into that slot**: pHash, SSIM, block-MAD, or the blurred difference. The paper says so:
*"we plug the neural network into a heuristic-based approach… This general idea is borrowed
from Perelman [23], which uses the absolute difference of the blurred grayscale versions of
the frames."*

The algorithm, from the source:

```
anchor = None; video_idx = None; prev_video_idx = None
for i in range(N_frames):
    frame = decode_at_reduced_size(i)          # L55
    frame = gray(frame); frame = crop(frame, roi)   # L59-64
    if anchor is None: anchor = frame; anchor_idx = i
    if SAME(anchor, frame):  continue          # L93: keep the anchor, extend the run
    # --- differs ---
    if (i - anchor_idx) > slide_thresh:        # L94  the run was long enough
        if video_idx is not None and (video_idx - prev_video_idx) > video_thresh:  # L96
            emit(slide_id=-1, prev_video_idx+1, video_idx+1)   # a VIDEO segment
        video_idx = prev_video_idx = None
        emit(slide_id=next_id, anchor_idx+1, i)                # a STATIC SLIDE run
    else:                                      # L110-114  run too short
        video_idx = anchor_idx                 # remember it as churn, not a slide
        if prev_video_idx is None: prev_video_idx = anchor_idx
    anchor = frame; anchor_idx = i             # L116-117
```

Three things in here are worth having:

1. **Compare against the *anchor*, not the previous frame.** Drift accumulates against a
   fixed anchor, so a slow cross-fade or a progressive build eventually trips the
   comparison, where frame-to-frame differencing would see each step as below threshold and
   never fire. This is the single most important structural choice in the file and it costs
   nothing.
2. **The two-anchor video track** (`video_frame_idx` / `prev_video_frame_idx`, L95-114).
   Short runs are not discarded — they are accumulated into a *video segment* that is
   emitted with `slide_id = -1` when the next real static slide arrives. This is how the
   pipeline separates "a region of constant churn" (speaker cutaway, embedded video, vision
   mixer) from "a slide changed", **deterministically, before any network sees anything.**
   For #11 this is a free hard-case handler: a run of sub-threshold runs is a churn region.
3. **The hard-vs-gradual split is a one-line deterministic rule**, not a model output:
   [`data/data_utils.py:90-95`](https://github.com/asindel/SliTraNet/blob/994c3faca9615619926efcb7613af87331f9928b/data/data_utils.py#L90-L95) —
   a transition is the *gap* between the end of run *i* and the start of run *i+1*, and
   `slide_transition_types = (gap > 1)` ⇒ `0: hard, 1: gradual`. The 3-D net's much fancier
   4-class output is used *instead of* this at inference; `slide_transition_types` and
   `frame_types` are computed, returned, and **never read** in `test_SliTraNet.py`. Dead
   code that documents the cheap version of the idea.

**Tuned constants** ([`test_slide_detection_2d.py:177-178`](https://github.com/asindel/SliTraNet/blob/994c3faca9615619926efcb7613af87331f9928b/test_slide_detection_2d.py#L177-L178),
same defaults at [`test_SliTraNet.py:213-214`](https://github.com/asindel/SliTraNet/blob/994c3faca9615619926efcb7613af87331f9928b/test_SliTraNet.py#L213-L214)):

| constant | value | at 25 fps | in the paper? |
|---|---|---|---|
| `slide_thresh` — min length of a static run to count as a slide | **8 frames** | 0.32 s | Yes (§IV.B), with its cost stated: *"slides of one frame length cannot be detected by our method"* |
| `video_thresh` — min length of a churn region to be recorded as video rather than a gradual transition | **13 frames** | 0.52 s | **No. Code only.** |
| `patch_size` — network input canvas | 256 | — | Yes |
| `clip_length` — 3-D net temporal window | 8 frames | 0.32 s | Yes |
| `temporal_sampling` | 1 (every frame) | — | No |

`video_thresh = 13` is an **undocumented field constant** — it exists nowhere in the paper
and its only job is to stop a half-second cross-fade from being misfiled as an embedded
video. That is the shape of a constant that exists because something failed in the field.

**A decode-time optimisation worth copying regardless of everything else.** The video is
*never decoded at 1080p*:
[`test_slide_detection_2d.py:31`](https://github.com/asindel/SliTraNet/blob/994c3faca9615619926efcb7613af87331f9928b/test_slide_detection_2d.py#L31)
and [`data/test_video_clip_dataset.py:61`](https://github.com/asindel/SliTraNet/blob/994c3faca9615619926efcb7613af87331f9928b/data/test_video_clip_dataset.py#L61)
pass `width=`/`height=` into `decord.VideoReader`, pushing the downscale into the decoder.
`determine_load_size_roi`
([`data/data_utils.py:30-58`](https://github.com/asindel/SliTraNet/blob/994c3faca9615619926efcb7613af87331f9928b/data/data_utils.py#L30-L58))
computes the scale from the **ROI width**, `f = patch_size / (x2-x1)` (L40), so the *slide
region* lands at exactly 256 px wide whatever the frame size — and a separate factor
`f2 = patch_size / W1` (L52) for the full-frame path, so 1920×1080 → 256×144. The ROI
rectangle is scaled by the same factor (L48) so it stays valid against the reduced decode.
The equivalent in this project is `ffmpeg -vf scale` at decode rather than `cv2.resize`
after — the same trick, and for #11 it is most of the decode budget.

**Resampling choice, deliberate and unusual.** Both resize paths use
`interpolation = cv2.INTER_NEAREST`
([`test_slide_detection_2d.py:69`](https://github.com/asindel/SliTraNet/blob/994c3faca9615619926efcb7613af87331f9928b/test_slide_detection_2d.py#L69),
[`data/test_video_clip_dataset.py:118`](https://github.com/asindel/SliTraNet/blob/994c3faca9615619926efcb7613af87331f9928b/data/test_video_clip_dataset.py#L118)).
Nearest-neighbour for *downscaling* is normally a mistake — it aliases. Here it is almost
certainly intentional: `INTER_AREA` averages, and averaging is exactly what erases a single
thin new line on a slide (precisely the failure the paper documents in Fig. 5b). For #11,
**how you downscale before comparing is a spike variable, not an implementation detail**:
INTER_AREA is recall-hostile for thin-stroke slide content.

**Normalisation** is `x/255 - 0.5`, not ImageNet mean/std
([`data/test_video_clip_dataset.py:40-42`](https://github.com/asindel/SliTraNet/blob/994c3faca9615619926efcb7613af87331f9928b/data/test_video_clip_dataset.py#L40-L42)) —
consistent with the paper's *"We trained all networks from scratch"* (§IV.B). Grayscale is
the Rec.601 luma `0.299R + 0.587G + 0.114B` hand-rolled in torch
([`test_slide_detection_2d.py:60`](https://github.com/asindel/SliTraNet/blob/994c3faca9615619926efcb7613af87331f9928b/test_slide_detection_2d.py#L60)).

**There is no deterministic pre-filter in front of the network.** Stage 1 runs the CNN on
**every frame at batch size 1** (`for i in range(N_frames)` → `net(imgs.unsqueeze(0))`,
L53/L89). No sampling, no skip, no cheap gate. This is the opposite of the "cheap
deterministic pre-filter in front of a network" pattern, and it is why the thing costs what
it costs (E.6). A negative finding: the state of the art here did not do the obvious cheap
thing.

---

### E.4 The recall-safe combination rule

[`test_SliTraNet.py:176-196`](https://github.com/asindel/SliTraNet/blob/994c3faca9615619926efcb7613af87331f9928b/test_SliTraNet.py#L176-L196):

```python
if all(slide_transition_pred==3) and all(slide_video_pred==2):
    neg_indices.append(key)     # DROP this candidate
else:
    ... emit it ...
```

A transition candidate is discarded **only if both 3-D networks agree it is video, and only
if every clip sampled from that candidate agrees**. Two `all()`s and an `and`. Anything
short of unanimity and the candidate survives to the output.

This is this project's recall-over-precision preference expressed as code, and the pattern
generalises past SliTraNet: **when combining suppressors, require unanimity to suppress.**
If #11 ends up with two independent "this is not a slide change" signals (say a churn
detector and a slide-frame gate), this is the combinator to use — and the paper's Table I
shows what it buys: recall only drops 96.05 → 93.16 while precision goes 36.79 → 86.76.

Note the two 3-D nets are **deliberately given different views of the same clip**: `net1`
sees the **raw full frame** ([`test_SliTraNet.py:105-113`](https://github.com/asindel/SliTraNet/blob/994c3faca9615619926efcb7613af87331f9928b/test_SliTraNet.py#L105-L113), no `roi=` argument),
`net2` sees the **ROI crop** ([`test_SliTraNet.py:141-149`](https://github.com/asindel/SliTraNet/blob/994c3faca9615619926efcb7613af87331f9928b/test_SliTraNet.py#L141-L149), `roi=roi`).
That is not redundancy — see E.5.

**Clip sampling around a candidate** is also deterministic and worth noting
([`data/test_video_clip_dataset.py:66-90`](https://github.com/asindel/SliTraNet/blob/994c3faca9615619926efcb7613af87331f9928b/data/test_video_clip_dataset.py#L66-L90)):
gap ≤ 1 → **1** clip centred on the boundary; gap ≤ 8 → **3** clips (midpoint, start, end);
gap > 8 → `k = gap//4 + 1` clips evenly spaced across the gap. More evidence goes to longer,
more ambiguous transitions. Cheap idea, applicable to any verification stage.

---

### E.5 Crop: the greenfield assumption survives

**SliTraNet does not detect the slide region. At all.** The ROI is a hand-labelled,
per-video, **constant** axis-aligned rectangle read from a text file:
[`data/data_utils.py:60-70`](https://github.com/asindel/SliTraNet/blob/994c3faca9615619926efcb7613af87331f9928b/data/data_utils.py#L60-L70)
parses `videos/<phase>_bounding_box_list.txt` in the format `Videoname,x0,y0,x1,y1`, and
[`crop_frame`](https://github.com/asindel/SliTraNet/blob/994c3faca9615619926efcb7613af87331f9928b/data/data_utils.py#L24-L25)
is a bare numpy slice `frame[y1:y2, x1:x2]`. The README's own example is
`Architectures_1,38,57,1306,1008`. One box, whole video, absolute pixels, no perspective
correction, no per-frame adaptation, no detection.

> **This is the strongest confirmation yet that #12 is greenfield.** The deep-learning state
> of the art for this exact problem, with three CNNs and a GPU budget, **hand-labels the
> slide rectangle** rather than detect it. `docs/research/slide-region-crop.md`'s finding
> that no surveyed project crops to the slide region holds, and now holds against the
> learned end of the space too.

**But** the paper states the reason the two 3-D nets get different views, and it is a
technique, not an implementation accident (§III.C):

> *"The slides of lecture videos are not necessarily filling the full screen, but can be
> placed on top of some background. In our particular lecture video dataset, the memes,
> animations and speaker video sequences are **full screen in contrast to the slides**.
> Using this knowledge, we use the raw video input to train our second 3-D ResNet50."*

Restated deterministically: **compare the activity inside the slide rectangle against the
activity outside it.** Change confined to the rect ⇒ slide change. Change across the whole
frame, rect and background alike ⇒ camera cutaway, full-screen video, or a mixer cut. The
authors needed a whole 46 M-parameter network to learn this because they fed it raw pixels;
the *signal* is a two-number comparison of differencing energy inside vs outside a known
rect, and this project already has `--roi` (ADR 0001).

> **#12 / #11 verdict: measure in the spike, and it bridges two tickets.** This is #12's
> "activity-complement crop" candidate running in reverse — the complement region used as a
> *detector* signal rather than as a crop target. Two payoffs from one measurement: the
> outside-rect activity discriminates hard cases 2, 3 and 6 (cutaway, embedded video, vision
> mixer) for near-zero cost, and the same per-region activity map is the input the
> activity-complement crop needs. Worth building the activity map once and using it twice.

---

### E.6 Cost on the target host

The benchmark below was run **on the target host itself** (`Intel(R) Core(TM) i3-4170 CPU @
3.70GHz`, 2 cores / 4 threads): sustained `numpy` sgemm at 1200×1200 fp32 reaches
**145 GFLOP/s** across all 4 threads. That is the optimistic ceiling; PyTorch convolution on
Haswell realistically sustains 20–40% of peak sgemm for these shapes.

FLOPs computed analytically from the layer shapes in the cloned source; the 3-D count independently
reproduces the 46.21 M parameter figure commonly cited for 3-D ResNet-50, which validates the counter:

| network | shape | GFLOPs per call | params | fp32 weights |
|---|---|---|---|---|
| 2-D ResNet18, 2 ch | 256×256 | **4.63** / frame-pair | 11.17 M | 42.6 MB |
| 3-D ResNet50, 4-class | 8×256×256×3 | **86.8** / clip | 46.21 M | 176.3 MB |
| 3-D ResNet50, 3-class | 8×256×256×3 | **86.8** / clip | 46.21 M | 176.3 MB |
| | | | | **395 MB to ship** |

The 3-D net is this expensive because the authors **removed temporal downsampling** from
`conv1` and `maxpool` — `stride=(1,2,2)` at
[`backbones/resnet3d.py:126`](https://github.com/asindel/SliTraNet/blob/994c3faca9615619926efcb7613af87331f9928b/backbones/resnet3d.py#L126)
and [`:131`](https://github.com/asindel/SliTraNet/blob/994c3faca9615619926efcb7613af87331f9928b/backbones/resnet3d.py#L131),
flagged in the comment *"changed from stride = 2 to (1,2,2)"* — so all 8 frames survive to
`layer1` at 64×64. `conv1` alone (7×7×7 over 8×128×128×64) is 8.6 GMACs.

For one **60-minute 1080p video at 25 fps = 90,000 frames**:

```
stage 1 (2-D, EVERY frame, batch size 1):  90,000 × 4.63 GFLOPs  = 417 TFLOPs   (82%)
stage 2+3 (3-D):  ~287 candidates × ~1.8 clips × 2 nets ≈ 1,035 clips
                                   1,035 × 86.8 GFLOPs =  90 TFLOPs   (18%)
                                                  TOTAL = 507 TFLOPs
```

(Candidate count scaled from the paper's own test run: `2-D ResNet18-gray` produced 911
candidates over 190 min ⇒ 4.79/min.)

| sustained throughput | time per 60-min video |
|---|---|
| 58 GFLOP/s (40% of measured peak — optimistic) | **2.4 h** |
| 45 GFLOP/s (31%) | **3.1 h** |
| 30 GFLOP/s (21%) | **4.7 h** |
| 20 GFLOP/s (batch-size-1 reality) | **7.0 h** |

**2.4 to 7 hours of CPU per hour of video, i.e. 2.4–7× realtime, before decode.** The paper
reports *"SliTraNet takes less than 90 min to process the 190 min test data"* (§IV.C) — 0.47×
realtime **on a GPU**. The ~6× gap between that and my CPU estimate is consistent: stage 1
runs at batch size 1, so the GPU run was launch-latency bound rather than FLOP bound, which
means the GPU figure *understates* the FLOP count and my estimate is the right bound.

**The cost is in the wrong place.** 82% of it is stage 1 — the dense per-frame 2-D net that
Table I says is *beaten on recall by Gaussian-blurred frame differencing*. Blur(21,21) +
absdiff on a 256×144 grayscale ROI is ~0.003 GFLOPs/frame against 4.63 — **roughly 1500×
cheaper, for 10 fewer misses out of 380.** Prior research guessed the 3-D CNN was the
blocker; it is not, it is 18% of the bill and the only part that earns its keep.

> **#17 verdict: reject, and the rejection is now quantitative.** Not "probably out of
> budget" — 507 TFLOPs, 2.4–7 h/hour of video, 395 MB of unlicensed weights, on a host that
> peaks at 145 GFLOP/s. And the part that would be affordable (the 3-D refinement) is a
> *surplus reducer*, which ADR 0003 ranks second and `drop` deletes with one keystroke.

**Practical blockers on top of the arithmetic**, all from the source:

- **`.cuda()` is hardcoded, with no CPU fallback and no `--device` flag** —
  [`test_SliTraNet.py:49`](https://github.com/asindel/SliTraNet/blob/994c3faca9615619926efcb7613af87331f9928b/test_SliTraNet.py#L49),
  [`:56`](https://github.com/asindel/SliTraNet/blob/994c3faca9615619926efcb7613af87331f9928b/test_SliTraNet.py#L56),
  [`:62`](https://github.com/asindel/SliTraNet/blob/994c3faca9615619926efcb7613af87331f9928b/test_SliTraNet.py#L62),
  [`:121`](https://github.com/asindel/SliTraNet/blob/994c3faca9615619926efcb7613af87331f9928b/test_SliTraNet.py#L121),
  [`:156`](https://github.com/asindel/SliTraNet/blob/994c3faca9615619926efcb7613af87331f9928b/test_SliTraNet.py#L156),
  [`test_slide_detection_2d.py:87`](https://github.com/asindel/SliTraNet/blob/994c3faca9615619926efcb7613af87331f9928b/test_slide_detection_2d.py#L87).
  Cannot be run on the target host without patching.
- **`np.float` crashes on any NumPy ≥ 1.24** —
  [`data/data_utils.py:80`, `:82`, `:84`](https://github.com/asindel/SliTraNet/blob/994c3faca9615619926efcb7613af87331f9928b/data/data_utils.py#L80-L84).
  The code is unmaintained and cannot run as-is on a 2026 stack.
- **`decord` is dead.** Latest PyPI release is 0.6.0 (2021); the only Linux artefact is
  `decord-0.6.0-py3-none-manylinux2010_x86_64.whl`, a manylinux2010 binary bundling an
  ancient ffmpeg. Against this project's "Python 3.12, wheels-only" constraint that is a
  wheel that installs and then may or may not decode.
- **`np.hstack(neg_indices)` raises on an empty list**
  ([`test_SliTraNet.py:193`](https://github.com/asindel/SliTraNet/blob/994c3faca9615619926efcb7613af87331f9928b/test_SliTraNet.py#L193))
  — a video where no candidate is suppressed crashes at the last line.
- **`cv2.resize` is called on a torch tensor**
  ([`test_slide_detection_2d.py:69`](https://github.com/asindel/SliTraNet/blob/994c3faca9615619926efcb7613af87331f9928b/test_slide_detection_2d.py#L69));
  dead path only because `scaling_factor` is normally exactly 1.

---

### E.7 Dataset and label shape vs ADR 0003

**The dataset (paper §IV.A):** a private subset of lecture videos from two FAU
Erlangen-Nuremberg courses (deep learning; medical image processing). **30 videos** — 12
train / 4 val / 14 test — Full HD, **25 fps**, 6 to 33 min each, test split = 190 min. Both
4:3 and 16:9 slide formats. It contains speaker views and deliberately inserted "memes"
(embedded YouTube clips, credited in the figure captions).

**Not downloadable. No link in the repo, no link in the paper, no licence.** Only the
pretrained weights ship, via Google Drive. `docs/research/slide-change-detection.md`'s note
that "the labelled videos themselves are not distributed" is confirmed at HEAD — the README
defines the expected *folder structure* and nothing more. **Unusable as fixtures.**

**How the labels were produced (§IV.A), verbatim:**

> *"The ground truth slide transitions were obtained semi-automatically. Based on the
> difference of the frames, static slides were roughly detected and were manually corrected
> at frame level and split into hard and gradual transitions."*

This is **the same workflow ADR 0003 adopted** — machine-proposed, human-corrected, one
binary decision per candidate state. Independent confirmation that the process is the right
one. With one sharp caveat: they proposed with **frame differencing**, which is on this
project's own #11 shortlist, so their procedure would **violate ADR 0003's anti-bias rule**
("the proposal must come from a method deliberately different from the spike shortlists").
Their Table I therefore has a structural bias *toward* `Diff-*-blur`, which is worth stating
plainly — though it does not rescue the CNN, since the bias would have to account for a
10-miss gap and the labels were hand-corrected at frame level.

**Label shape compatibility — incompatible in the way that matters.**

| | SliTraNet | ADR 0003 |
|---|---|---|
| unit | a **transition**: `Transition No, FrameID0, FrameID1`, 1-based frame indices ([`test_SliTraNet.py:171`, `:191`](https://github.com/asindel/SliTraNet/blob/994c3faca9615619926efcb7613af87331f9928b/test_SliTraNet.py#L191)) | a **required content**: `{n, windows: [[t0,t1]], slide_rect}`, seconds |
| stage-1 intermediate | a **run**: `Slide No, FrameID0, FrameID1`, `slide_id = -1` marking a video segment ([`test_slide_detection_2d.py:126-131`](https://github.com/asindel/SliTraNet/blob/994c3faca9615619926efcb7613af87331f9928b/test_slide_detection_2d.py#L126-L131)) | — |
| progressive build | **every build step is its own transition** — the anchor fires per bullet, and their GT splits them | **one window**, opening at the last bullet |
| returning slide | a fresh transition | a **second window** on the same content |
| slide rect | one box per **video**, absolute px, hand-labelled | one rect per **content**, normalised floats |
| matching | euclidean distance of transition start/end ≤ **20 frames** (0.8 s), bidirectional, mutual (§IV.C) | capture timestamp inside a window |

The stage-1 *run* format converts cleanly to a window (`[FrameID0/fps, FrameID1/fps]`) — the
arithmetic is trivial. The problem is semantic: SliTraNet emits a run **per build step**,
so a five-bullet build becomes five required contents, which is exactly the collapse ADR
0003 exists to perform and its History section records dropping two metric versions to
achieve. Converting their labels would re-import the taxonomy the ADR deleted.

> **Verdict: not reusable as fixtures** — the data is not distributed, and even if it were,
> the label shape re-introduces per-build-step contents. The *proposal workflow* is
> confirmatory, and their ±20-frame bidirectional matching tolerance is a useful reference
> point for how loose a transition match needs to be (0.8 s at 25 fps).

---

### E.8 Hard cases

| hard case | what SliTraNet does |
|---|---|
| **Progressive build** | **Documented failure.** Paper Fig. 5b, a false negative in an animated slide: *"A plausible reason for the failure of the network… is the small difference of the two frames as only thin lines appear that connect the nodes."* The 2-D net cannot see a thin new line. Note the asymmetry: this is fatal for them (each build step is a GT transition) and **near-harmless here** — ADR 0003 collapses a build to one window opening at the *last* bullet, and the anchor loop fires generously on the way there. Their weakness is not this project's weakness. |
| **Camera cutaway to speaker** | **Handled, twice.** Deterministically by the two-anchor video track (E.3), then by the 3-D nets' `video` class. Full-screen speaker view vs non-full-screen slide is the explicit discriminator (E.5). |
| **Embedded video / animation in a slide** | **The entire reason stages 2–3 exist.** Paper: *"The frame to anchor comparison detects many false positive transitions for video frames, where short static sequences alternate with motions."* And still **not solved**: Fig. 5c is a documented false positive — *"The meme… has a similar color distribution as the lecture slides and thus the transition within the meme is falsely detected as a slide transition."* Even a 46 M-parameter 3-D CNN does not close this. Sobering for #11's expectations. |
| **Moving webcam overlay** | **Not handled.** The intro acknowledges *"the lecture slides can be full screen with the lecturer screen inserted as a small window on top"*, but nothing in the code addresses it: if the overlay falls inside the hand-drawn ROI, its motion is indistinguishable from slide motion. |
| **Burned-in subtitles changing every phrase** | **Nothing. Not mentioned in paper or code.** The anchor loop would fire on every phrase change and `slide_thresh=8` (0.32 s) would not suppress it. A clean gap. |
| **Vision mixer cutting constantly** | Not addressed as such; the two-anchor video track would classify a constantly-cut region as video churn, which is the right behaviour by accident. |
| **Slide filmed on a screen at an angle** | **Not handled.** `crop_frame` is an axis-aligned numpy slice; no homography, no perspective correction anywhere in the repo. |
| **Fast consecutive slide changes** | **Documented failure.** Fig. 5d, and the paper states the limit outright: *"we defined that a static slide has to be at least eight frames long, hence slides of one frame length cannot be detected by our method, but for the most applications these limitations are acceptable."* A hard floor of `slide_thresh` frames on dwell time. |

---

### E.9 Negative findings

- **It does not extract slides.** Despite the paper's framing (*"automatic slide extraction…
  to give a brief overview of the main content"*), the code **never writes an image**. The
  only outputs are two text files of frame indices
  ([`test_SliTraNet.py:169-172`](https://github.com/asindel/SliTraNet/blob/994c3faca9615619926efcb7613af87331f9928b/test_SliTraNet.py#L169-L172),
  [`test_slide_detection_2d.py:124-132`](https://github.com/asindel/SliTraNet/blob/994c3faca9615619926efcb7613af87331f9928b/test_slide_detection_2d.py#L124-L132)).
  **Which frame of a dwell to export: the question is never asked.** No representative-frame
  selection, no sharpness check, no "last frame of the run" rule — nothing. The repo stops
  one step before the problem this project has to solve.
- **Output naming/numbering:** a 1-based sequential counter `s` incremented per surviving
  transition ([`test_SliTraNet.py:188-191`](https://github.com/asindel/SliTraNet/blob/994c3faca9615619926efcb7613af87331f9928b/test_SliTraNet.py#L188-L191)),
  written as `"{s}, {FrameID0+1}, {FrameID1+1}"`. Note the `+1`: internal indices are
  0-based, output is 1-based. Nothing else.
- **Nothing about audio or transcripts.** Zero audio handling in the code. The paper
  mentions the AutoBlog transcript pipeline only as motivation and future work: *"using our
  slide transition detection method, the software could be extended"*. The slide↔speech
  pairing problem (#14) is untouched by the learned end of the space.
- **No dedupe of any kind.** A returning slide is a new transition; identical content
  appearing twice is two transitions. No hashing, no clustering, no global comparison. The
  "dedupe" half of #11 has no prior art here at all.
- **`frame_types`** (which side of a transition was a video segment) is computed at
  [`data/data_utils.py:92`](https://github.com/asindel/SliTraNet/blob/994c3faca9615619926efcb7613af87331f9928b/data/data_utils.py#L92),
  returned, and never used. So is `slide_transition_types`. The cheap deterministic answers
  are computed and then thrown away in favour of the networks.

### E.10 A lead this survey has not covered

[`test_slide_detection_2d.py:5`](https://github.com/asindel/SliTraNet/blob/994c3faca9615619926efcb7613af87331f9928b/test_slide_detection_2d.py#L5)
credits `https://git.aweirdimagination.net/perelman/slide-detector` (paper ref [23]) as the
source of the anchor heuristic *and* of the `Diff-*-blur` baseline that beats the CNN on
recall in Table I. **It appears nowhere in `docs/`** — not in `slide-change-detection.md`,
not in `similar-tools.md`, not in `slide-region-crop.md`. It is pure Python, licensed, and
from its project page it (a) detects slides as "frames that stay the same for several frames
in a row" with a default **3-second** minimum dwell, and (b) ships an **interactive crop UI**
with 10-px/1-px nudge keys and a frame-by-frame debug view of the analysis stages. Given
that #12 is greenfield on slide-region cropping and #11's shortlist includes frame
differencing, the direct ancestor of the method that won SliTraNet's own ablation deserves a
read — it is the deterministic system this whole paper was built on top of and failed to beat
on recall.

---

## Group F — m2kar/video2slides and AnuragSingh2101/Video2Slides

The two end-to-end projects the survey catalogues but whose source nobody had read. Both were
cloned with `git clone --depth 1` into `extract-slides-cache/reference-implementations/`.

| Repo | HEAD sha | Last commit | License | Size of the part that matters |
|---|---|---|---|---|
| [`m2kar/video2slides`](https://github.com/m2kar/video2slides) | `d3bb704b914b0e97dc5661caae6d39ee9f9c2ace` | 2024-12-01 | **MIT** (`LICENSE`, "Copyright (c) 2024 @m2kar") | one file, 263 lines |
| [`AnuragSingh2101/Video2Slides`](https://github.com/AnuragSingh2101/Video2Slides) | `ac298c28df08b75aacf24694035f47abf6793baf` | 2026-08-05 | **none — no LICENSE file, no license field anywhere in the repo** | ~950 lines of backend Python, of which ~250 are in scope |

> **Licence warning for #14/#11.** `AnuragSingh2101/Video2Slides` ships **no licence at all**. Under
> GitHub's default terms that is all-rights-reserved: its code may be *read and described* but not
> copied into this project. Everything below from that repo is recorded as a technique or a
> negative finding, never as code to lift. `m2kar` is MIT and is safe to copy from with attribution.

---

### F.1 The pairing rule

#### F.1.1 m2kar: max-overlap, winner-take-all, cue never split

This is the only real prior art found for issue #14's open question, and it is 27 lines long.
[`video2slides/main.py#L100-L131`](https://github.com/m2kar/video2slides/blob/d3bb704b914b0e97dc5661caae6d39ee9f9c2ace/video2slides/main.py#L100-L131):

```python
srt_notes = [""] * len(scene_infos)
for seg in segments:
    seg_start = seg["start"];  seg_end = seg["end"];  seg_text = seg["text"]

    max_intersection = 0
    assigned_scene_index = -1

    for idx, scene in enumerate(scene_infos):
        scene_start = float(scene[3])   # Start Time (seconds)
        scene_end   = float(scene[6])   # End Time (seconds)

        overlap_start = max(seg_start, scene_start)
        overlap_end   = min(seg_end, scene_end)
        overlap = max(0, overlap_end - overlap_start)

        if overlap > max_intersection:
            max_intersection = overlap
            assigned_scene_index = idx

    if assigned_scene_index != -1:
        if srt_notes[assigned_scene_index]:
            srt_notes[assigned_scene_index] += "\n" + seg_text
        else:
            srt_notes[assigned_scene_index] = seg_text
```

Answering #14's questions exactly as the code answers them:

| #14's question | m2kar's answer, read from the code |
|---|---|
| What is the slide's time anchor? | **The whole dwell interval `[scene_start, scene_end)`**, taken from PySceneDetect's `list-scenes` CSV — *not* the capture timestamp, *not* the transition instant. The screenshot is taken at ~95% of the dwell (§4) but plays no part in pairing. Image time and text time are deliberately decoupled. |
| Is a cue split at a slide boundary? | **No.** The cue is an atom. It is assigned whole. |
| A cue that spans two slides? | Goes **entirely to the slide it overlaps most** (`overlap > max_intersection`). A cue split 60/40 across a transition puts 100% of its words on the 60% side and 0% on the other. |
| Speech that starts before the slide changes? | Resolved by the same majority rule. The typical lead-in ("…and now let's look at the architecture") is spoken while the *old* slide is still up, so most of that cue lies in the old dwell and the whole sentence lands on the old slide. This is the *correct* outcome by accident of majority, not by an explicit rule. |
| Tie-breaking? | Strict `>` against a running max initialised to `0`, scanning scenes in order ⇒ **an exact tie goes to the earlier scene**. |
| Cue matching nothing? | `assigned_scene_index` stays `-1` and the cue is **silently dropped, with no warning and no counter**. Because PySceneDetect's scenes tile `[0, duration]` contiguously, this only fires for a zero-duration cue or one that starts past the last scene's end — i.e. exactly Whisper's trailing-silence hallucinations. An accidental but real filter. |
| Cue-level resolution in the output? | **Destroyed.** The per-slide note is `"\n".join(texts)` with no per-cue timestamps (L124-127). Only the slide-level aggregate survives into the deliverable. |
| Cost | O(cues × scenes), a full rescan of every scene for every cue. Fine at this scale (~500 cues × ~80 scenes) but there is no sort/merge, no early exit, no use of the fact that both sequences are monotonic. |

**Verdict: adopt the max-overlap rule as the baseline for #14, and fix its three known defects.**
It is the right default — it is deterministic, needs no word timestamps, is trivially explainable
to a user ("this slide gets the sentences mostly said while it was on screen"), and it degrades
gracefully. Its defects, all visible above, are what #14 must decide beyond it:

1. **Silent drop.** `-1` must become a diagnosable outcome (an `unassigned` bucket in the
   manifest), not a `continue`. A recall-first project cannot silently lose speech.
2. **No cue-level record.** The pairing is collapsed into a blob of joined text. #14's manifest
   should keep `(cue_start, cue_end, text, slide_id)` rows and let the joined blob be a *view* of
   them, so a mis-paired cue can be re-attributed by a `move` command without re-running anything.
3. **No splitting option.** Word-level resolution is in scope for #14. Whisper's
   `word_timestamps=True` would let a straddling cue be split at the transition instant; m2kar
   never asks for it. Note the trade: splitting mid-sentence produces two fragments that each read
   as broken prose, which is why whole-cue assignment is the sane default and splitting should be
   opt-in (or applied only when the straddle is near 50/50 and the cue is long).

A fourth observation worth carrying into #14: **max-overlap makes pairing robust to
over-capture, which is exactly what this project's recall-first policy produces.** If detection
emits a surplus slide, that slide's dwell is a short sub-interval and it simply wins the cues
spoken inside it; the neighbours keep theirs. Dropping the surplus slide afterwards, however,
*orphans* its cues — so the `drop` command in #14 must specify whether a dropped slide's cues
merge into the previous slide or are lost. m2kar never faces this because it has no drop command.

#### F.1.2 Anurag has no temporal pairing

The repo the survey describes as "a concrete example of every piece implemented together" does
not, in fact, associate speech with slides by time. The entire association is this, at
[`backend/app/workers/tasks.py#L125-L131`](https://github.com/AnuragSingh2101/Video2Slides/blob/ac298c28df08b75aacf24694035f47abf6793baf/backend/app/workers/tasks.py#L125-L131):

```python
# Link slide keyframe images if timing matches
for s in slides:
    s["video_id"] = video_id
    # Simple heuristic: match slide number with OpenCV extracted frames
    ocr_match = next((item for item in ocr_slides if item["slide_number"] == s["slide_number"]), None)
    if ocr_match:
        s["image_path_storage"] = ocr_match["storage_path"]
```

The comment says "if timing matches"; the code matches **ordinals from two unrelated sequences**.
`slides` is a deck *invented by Gemini* from the transcript
([`llm_analysis.py#L122-L162`](https://github.com/AnuragSingh2101/Video2Slides/blob/ac298c28df08b75aacf24694035f47abf6793baf/backend/app/services/llm_analysis.py#L122-L162)),
whose prompt hard-codes *"Design a comprehensive presentation deck (at least 6-10 slides)"*
(L153) regardless of how many keyframes the detector found. `ocr_slides` is the list of histogram
changes. So the Nth LLM-authored slide is handed the image of the Nth histogram change. On a
45-minute talk that detects ~120 changes and yields 8 LLM slides, slides 1-8 get the images of the
first 8 detected changes — all from the first few minutes — and the other ~112 images are orphaned.

Two corroborating reads confirm this is not a mis-reading:

- The `slides` table has **no time column at all** —
  [`supabase/migrations/20260801000000_init_schema.sql#L83-L93`](https://github.com/AnuragSingh2101/Video2Slides/blob/ac298c28df08b75aacf24694035f47abf6793baf/supabase/migrations/20260801000000_init_schema.sql#L83-L93)
  is `(id, video_id, slide_number, title, bullet_points, presenter_notes, diagram_code,
  image_path_storage, created_at)`. `chapters` and `transcript_embeddings` both carry
  `start_seconds`/`end_seconds`; `slides` does not. The timing simply has nowhere to live.
- `presenter_notes` is **LLM-written prose, not transcript**. The deck contains no speech the
  speaker actually said.

**Verdict: reject, and record as the cautionary negative finding for #14.** Its value is as proof
that the pairing question is easy to *skip* and that skipping it silently produces an artifact
that looks complete. It also argues directly for #14 storing `(start, end)` on the slide row: the
schema omission is what made the wrong join unavoidable.

#### F.1.3 The README-vs-code gap in the same repo

The README (L11) claims the AI Slide Generator "creat[es] slide presentations with summary
bullets and presenter notes, **extracting slide change images directly from the video**." The
PPTX exporter
[`backend/app/services/ppt_gen.py#L62-L83`](https://github.com/AnuragSingh2101/Video2Slides/blob/ac298c28df08b75aacf24694035f47abf6793baf/backend/app/services/ppt_gen.py#L62-L83)
**never reads `image_path_storage`.** Its own comment says "Add Diagram/Graphic Placeholder or
Frame Image on the right", but the branch only writes a text box reading
`"[Flowchart / Architectural Diagram]"`. `image_path_storage` is consumed in exactly one place in
the whole codebase — the web UI at
[`frontend/src/app/project/[id]/page.tsx#L400-L404`](https://github.com/AnuragSingh2101/Video2Slides/blob/ac298c28df08b75aacf24694035f47abf6793baf/frontend/src/app/project/%5Bid%5D/page.tsx#L400-L404).
**The exported `.pptx` from a project named "Video2Slides" contains none of the video's slides.**

---

### F.2 Transcript acquisition

| | m2kar | Anurag |
|---|---|---|
| Engine | `openai-whisper` (PyTorch) | `faster-whisper` (CTranslate2) |
| Model | **`"turbo"`** hard-coded, [main.py#L88](https://github.com/m2kar/video2slides/blob/d3bb704b914b0e97dc5661caae6d39ee9f9c2ace/video2slides/main.py#L88) | `settings.WHISPER_MODEL`, default **`"base"`**, [config.py#L25](https://github.com/AnuragSingh2101/Video2Slides/blob/ac298c28df08b75aacf24694035f47abf6793baf/backend/app/core/config.py#L25) |
| CPU handling | `fp16=False` passed explicitly, [L91](https://github.com/m2kar/video2slides/blob/d3bb704b914b0e97dc5661caae6d39ee9f9c2ace/video2slides/main.py#L91) — silences the "FP16 is not supported on CPU" fallback | `device = "cuda" if torch.cuda.is_available() else "cpu"`, `compute_type = "float16" if cuda else **"int8"**`, [transcription.py#L19-L27](https://github.com/AnuragSingh2101/Video2Slides/blob/ac298c28df08b75aacf24694035f47abf6793baf/backend/app/services/transcription.py#L19-L27) |
| Input | **the video file itself** — `model.transcribe(video_path)`; Whisper shells out to ffmpeg internally | 64 kbps **mono MP3** extracted by yt-dlp's `FFmpegExtractAudio`, [youtube.py#L43-L57](https://github.com/AnuragSingh2101/Video2Slides/blob/ac298c28df08b75aacf24694035f47abf6793baf/backend/app/services/youtube.py#L43-L57) |
| Word timestamps | not requested | **explicitly disabled**, with the comment `# Sentence-level is perfect for chapters and slides`, [transcription.py#L63](https://github.com/AnuragSingh2101/Video2Slides/blob/ac298c28df08b75aacf24694035f47abf6793baf/backend/app/services/transcription.py#L63) |
| Other params | none | `beam_size=5`; no VAD filter, no language hint |
| Missing ffmpeg | **no check anywhere.** Failure surfaces as an opaque Whisper/ffmpeg error | **no check either**, but a post-hoc `if not os.path.exists(expected_output_path): raise FileNotFoundError("Failed to extract audio…")`, [youtube.py#L63-L64](https://github.com/AnuragSingh2101/Video2Slides/blob/ac298c28df08b75aacf24694035f47abf6793baf/backend/app/services/youtube.py#L63-L64) — a workaround for yt-dlp exiting 0 after a postprocessor failed |
| YouTube captions | **neither project uses them.** `grep -ri 'writesubtitles\|caption\|\bsrt\b\|vtt'` over Anurag's whole tree returns **zero hits**; m2kar takes a local file and has no downloader at all | |

Two liftable details:

- **`preferredquality: "64"` + `postprocessor_args: ["-ac", "1"]`** — 64 kbps mono, commented
  *"sufficient for Whisper, 75% smaller"*
  ([youtube.py#L50-L54](https://github.com/AnuragSingh2101/Video2Slides/blob/ac298c28df08b75aacf24694035f47abf6793baf/backend/app/services/youtube.py#L50-L54)).
  Whisper resamples to 16 kHz mono regardless, so this is free. Worth adopting for the fetch stage.
- **m2kar's lazy `import whisper` *inside* `srt_info()`**
  ([L85](https://github.com/m2kar/video2slides/blob/d3bb704b914b0e97dc5661caae6d39ee9f9c2ace/video2slides/main.py#L85))
  while `setup.py` lists `openai-whisper` as a hard `install_requires`
  ([setup.py#L21](https://github.com/m2kar/video2slides/blob/d3bb704b914b0e97dc5661caae6d39ee9f9c2ace/setup.py#L21)).
  The README hedges with "(需正确安装 openai-whisper库)" — "requires openai-whisper to be correctly
  installed". A torch dependency that is declared required, imported lazily, and hedged in the
  README is a fair description of how badly that install goes in the field. Direct support for
  this project's wheels-only, no-compile constraint.

**Verdict for the model choice, against the i3-4170/no-GPU target:** m2kar's `"turbo"` on stock
PyTorch CPU is the wrong end (large-v3-turbo, ~809M params, fp32 on 2 cores). Anurag's
`faster-whisper` + **`compute_type="int8"`** is the right shape for our host; only its `"base"`
default is too small for a technical talk. Neither is a finding this project doesn't already have,
but the CPU `int8` selection line is the concrete precedent.

---

### F.3 Detection metric and thresholds

| | m2kar | Anurag |
|---|---|---|
| Metric | PySceneDetect **`detect-hash`** — pHash: grayscale → resize to `size*lowpass` = **32×32** → DCT → keep low 16×16 → threshold on median → normalised Hamming distance `hash_dist / 256` | **HSV 2-D histogram correlation**: `cv2.calcHist([hsv],[0,1],None,[180,256],...)`, `NORM_MINMAX` to 0..1, then `cv2.compareHist(..., HISTCMP_CORREL)` |
| Invocation | `os.system("scenedetect …")`, [main.py#L188-L198](https://github.com/m2kar/video2slides/blob/d3bb704b914b0e97dc5661caae6d39ee9f9c2ace/video2slides/main.py#L188-L198) | in-process OpenCV, [video_proc.py#L82-L92](https://github.com/AnuragSingh2101/Video2Slides/blob/ac298c28df08b75aacf24694035f47abf6793baf/backend/app/services/video_proc.py#L82-L92) |
| Threshold | `0.1` — **vs PySceneDetect's own default of `0.395`** (verified in `scenedetect/detectors/hash_detector.py`, `HashDetector.__init__`, v0.6.4 and v0.7.1). ~4× more sensitive: a cut at >25.6 of 256 bits instead of >101 | `hist_threshold = 0.92`; change when `correl < 0.92` |
| Tuned against? | Unknown. The inline comment reads `# 提高阈值以减少误切` ("raise the threshold to reduce mis-cuts") sitting next to a value **below** the library default, so the comment describes movement from some earlier private value, not from the default. No test set, no example beyond `examples/example.mp4` | **Nothing.** The comment is folklore: `# Histogram comparison threshold for scene changes (0.85 to 0.95 is standard for slide decks)` ([L68](https://github.com/AnuragSingh2101/Video2Slides/blob/ac298c28df08b75aacf24694035f47abf6793baf/backend/app/services/video_proc.py#L68)) — unsourced, no measurement |
| Sampling rate | `-fs {skip_frames}`, `skip_frames = int((fps-1) * 0.15)` ⇒ compare a frame every ~0.15 s ≈ **6.7 fps** | `interval_frames = int(fps)` ⇒ **1.0 fps**, via `cap.set(CAP_PROP_POS_FRAMES, idx)` seeks |
| Min dwell | `--min-scene-len 1.0` (s) — vs library default 15 frames (~0.5 s at 30 fps) | **none.** Two consecutive seconds both below 0.92 ⇒ two slides |
| Dedupe | **none** | **none** |

Notes that bear on #11 directly:

- **`detect-hash` at `size=16, lowpass=2` downsamples the frame to 32×32 grayscale before the
  DCT** (`imsize = hash_size * factor`, `hash_frame()`). One bullet appearing on a 1080p slide
  moves a 32×32 DCT almost not at all. This detector will **miss progressive builds** — a
  first-order failure under a (misses, surplus) metric. If `detect-hash` enters the spike, it
  needs `--size`/`--lowpass` raised, and that should be measured, not assumed.
- **PySceneDetect discards, rather than defers, a cut inside `min_scene_len`**: the cut is dropped
  and `_last_scene_cut` is not advanced. Three bullets revealed within 1.0 s collapse to one
  scene. Another miss source.
- **Neither project dedupes.** Camera cutaway to the speaker and back produces, in both, two extra
  slides and no recognition that the second is a return to the first. m2kar's README TODO admits
  it: `优化包含摄像头的视频的分割准确率` ("improve segmentation accuracy for videos containing a
  camera"), alongside `优化有幻灯片过渡的分割准确率` (slide transitions) and
  `优化PPT内嵌视频的分割准确率` (video embedded in the slide). **Three of this project's named hard
  cases are listed as unsolved by the author of the closest prior art.**
- **Neither project crops.** Confirms `docs/research/slide-region-crop.md`: nothing in either
  repo touches #12. Anurag's saved frame is a raw `cv2.imwrite(frame)` of the full downloaded
  frame; m2kar's is a raw full-frame ffmpeg grab. **#12 remains greenfield.**
- Anurag **seeks per sample** (`cap.set(CAP_PROP_POS_FRAMES)` in a loop) rather than reading
  sequentially and skipping. On a long H.264 file that is a keyframe seek plus re-decode per
  second, and is slower and less timestamp-accurate than a sequential decimated read. Do not copy.

---

### F.4 Which frame of the dwell

The two projects make opposite choices, and m2kar's is the defensible one.

**m2kar shoots near the END of the dwell.**
[`main.py#L143-L152`](https://github.com/m2kar/video2slides/blob/d3bb704b914b0e97dc5661caae6d39ee9f9c2ace/video2slides/main.py#L143-L152):

```python
default_screenshot_seconds = start_seconds + Config.screenshot_position*(end_seconds-start_seconds)
screenshot_margin = max(Config.min_screenshot_margin,
                        min(Config.max_screenshot_margin, end_seconds - default_screenshot_seconds))
screenshot_seconds = round(end_seconds - screenshot_margin, 3)
screenshot_cmd = f"ffmpeg -ss {screenshot_seconds} -i '{video_path}' -frames:v 1 -q:v 2 -y '{dst_path}'"
```

with `screenshot_position = 0.95`, `min_screenshot_margin = 0.05`, `max_screenshot_margin = 0.5`
([Config, L27-L36](https://github.com/m2kar/video2slides/blob/d3bb704b914b0e97dc5661caae6d39ee9f9c2ace/video2slides/main.py#L27-L36)).
Reduced, given `min_scene_len = 1.0 s`, the capture instant is:

| dwell length | capture point |
|---|---|
| 1 s – 10 s | `end − 0.05·len` (the 5 % clamp binds at the low end: exactly `end − 0.05 s` at 1 s) |
| > 10 s | **`end − 0.5 s`** (the max-margin clamp binds) |

So: **always inside the last half-second of the dwell, never within 50 ms of the next
transition.** Two things fall out of that, and both are worth lifting:

1. **Skipping the *head* of the dwell dodges the incoming transition animation** (fade, wipe,
   push). The head of a dwell is where a cross-fade is still resolving; the tail is settled.
   Sampling the tail is the cheap, deterministic answer to "embedded transition" — one of the
   three cases the README's TODO admits are unsolved for *detection*, silently mitigated in
   *capture*.
2. **The tail of a dwell is the superset of a progressive build.** Within a run of same-content
   states, the last state has the most bullets revealed. If #11's run-grouping (already
   implemented per commit `501b953`) picks one frame per run, picking it from the **tail of the
   run, backed off by a margin** is strictly more complete than picking the head or the midpoint.

The 50 ms floor and 500 ms ceiling are the tuned constants: enough to clear a typical
PowerPoint/Keynote transition (~0.3–0.7 s) on long dwells, without walking outside a short one.

**The export is decoupled from the analysis pass.** Detection runs decimated (~6.7 fps) through
PySceneDetect; the *image* is a fresh `ffmpeg -ss … -frames:v 1 -q:v 2` against the **original
file at full resolution**, with `-ss` before `-i` (fast input seek). Analysis resolution and
export resolution are independent. **Adopt this separation.** It is the right shape for the
i3-4170 budget and it is the direct opposite of Anurag, who downloads
`"worstvideo[ext=mp4]/worst[ext=mp4]"`
([video_proc.py#L35](https://github.com/AnuragSingh2101/Video2Slides/blob/ac298c28df08b75aacf24694035f47abf6793baf/backend/app/services/video_proc.py#L35),
commented *"360p is perfect for OCR and layout analysis"*) and then **saves that same 360p frame
as the deliverable slide image** (L104). Cheap analysis is right; shipping the cheap frame is not.

**Anurag shoots the FIRST sampled frame of the new state** (`is_slide_change` → `cv2.imwrite`
immediately, L99-L104). With 1 fps sampling, that frame is 0–1 s after the true transition, i.e.
frequently mid-fade, and for a progressive build it is the *least* complete state. Reject.

---

### F.5 Output naming, numbering, and the manifest

**m2kar — adaptive zero-padding, and no manifest at all.**
[`main.py#L137`](https://github.com/m2kar/video2slides/blob/d3bb704b914b0e97dc5661caae6d39ee9f9c2ace/video2slides/main.py#L137):

```python
img_basename_template = "scene{scene_number:0"+str(len(str(len(scene_infos))))+"d}.jpg"
```

Pad width = digit count of the scene total: 8 scenes → `scene1.jpg`, 12 → `scene01.jpg`, 120 →
`scene001.jpg`. Numbering is PySceneDetect's 1-based contiguous scene number. **Do not copy this.**
It makes filenames unstable across reruns — nudge a threshold, cross a power-of-ten boundary, and
every filename changes width. #14 should fix the width (`slide-0001.png`).

The manifest situation is the sharper finding:

- The only machine-readable pairing table is PySceneDetect's `list-scenes` CSV
  (`Scene Number, Start Frame, Start Timecode, Start Time (seconds), End Frame, End Timecode,
  End Time (seconds), Length (frames), Length (timecode), Length (seconds)`, header transcribed at
  [L64-L66](https://github.com/m2kar/video2slides/blob/d3bb704b914b0e97dc5661caae6d39ee9f9c2ace/video2slides/main.py#L64-L66)).
- That CSV and every JPEG live in `./tmp-v2s-{timestamp}-{fname}/` and are **`shutil.rmtree`'d on
  exit** by an `atexit` hook, unless `DEBUG` is set
  ([L201-L219](https://github.com/m2kar/video2slides/blob/d3bb704b914b0e97dc5661caae6d39ee9f9c2ace/video2slides/main.py#L201-L219)).
- **The single surviving artifact is the `.pptx`.** The pairing result is embedded in the
  PowerPoint speaker-notes field
  ([L58-L60](https://github.com/m2kar/video2slides/blob/d3bb704b914b0e97dc5661caae6d39ee9f9c2ace/video2slides/main.py#L58-L60)),
  formatted as the joined cue texts, then `"\n\n"`, then
  `f"Time Info: scene {n}, {start_tc}-{end_tc} ({len_s}s)"`
  ([L129-L130](https://github.com/m2kar/video2slides/blob/d3bb704b914b0e97dc5661caae6d39ee9f9c2ace/video2slides/main.py#L129-L130)).

That `Time Info` line is the whole idea in miniature and it is instructive: the author clearly
felt the need for provenance, and had nowhere to put it, so he **stringified the manifest into a
notes field**. **Strong support for #14's separate-manifest design.** Everything a user would need
to re-run, audit, drop or re-pair is computed and then deleted; the deliverable is
non-reconcilable by construction. One nice property to keep: the notes are written for *every*
scene, so a slide with no speech gets a note that is just `"\n\n" + time_info` — an empty-speech
slide stays visible rather than vanishing.

**Anurag — a real schema, wrong keys.** `extracted_slides` rows are
`{"slide_number", "timestamp", "storage_path", "ocr_text"}`
([video_proc.py#L128-L133](https://github.com/AnuragSingh2101/Video2Slides/blob/ac298c28df08b75aacf24694035f47abf6793baf/backend/app/services/video_proc.py#L128-L133)) —
note `timestamp` is a single `int` second (`int(frame_idx / fps)`, L80), **a point, not an
interval**, so a dwell has no end and no duration anywhere in the system. That single choice is
what makes overlap-based pairing impossible and forces §1.2's ordinal join. Naming is
`slides/{video_id}/slide_{slide_count}.jpg`, unpadded (`slide_9`, `slide_10` sort wrong).

**Lift for #14:** store the **interval**, not the instant. A slide row needs at minimum
`(slide_id, dwell_start, dwell_end, capture_ts, source_frame, image_path)` — `capture_ts` distinct
from `dwell_start` precisely because §4 shows they should differ.

---

### F.6 Workarounds in the code but absent from the README

**m2kar:**

| Where | What | Why it's there |
|---|---|---|
| [L91](https://github.com/m2kar/video2slides/blob/d3bb704b914b0e97dc5661caae6d39ee9f9c2ace/video2slides/main.py#L91) | `fp16=False` | CPU-only run; suppresses Whisper's fp16→fp32 fallback warning |
| [L85](https://github.com/m2kar/video2slides/blob/d3bb704b914b0e97dc5661caae6d39ee9f9c2ace/video2slides/main.py#L85) | lazy `import whisper` despite a hard `install_requires` | torch install fragility (§2) |
| [L144](https://github.com/m2kar/video2slides/blob/d3bb704b914b0e97dc5661caae6d39ee9f9c2ace/video2slides/main.py#L144) | the 0.05 s / 0.5 s capture margin clamp | slide transition animations (§4) — README mentions none of this, only lists transitions as an unsolved *detection* TODO |
| [L174](https://github.com/m2kar/video2slides/blob/d3bb704b914b0e97dc5661caae6d39ee9f9c2ace/video2slides/main.py#L174) | `fps = get_video_fps(video_path) - 1` before computing skip | **looks like a bug**, not a workaround — a misremembered "n−1 gaps between n frames". At 30 fps it changes `int(4.5)=4` to `int(4.35)=4`; harmless in practice, but it is unexplained arithmetic on a rate |
| [L196](https://github.com/m2kar/video2slides/blob/d3bb704b914b0e97dc5661caae6d39ee9f9c2ace/video2slides/main.py#L196) | `scenedetect_cmd += " 2>&1"` when not DEBUG | **a broken silencer.** `2>&1` merges stderr into stdout; it does not suppress it. The intent (visible at [L150](https://github.com/m2kar/video2slides/blob/d3bb704b914b0e97dc5661caae6d39ee9f9c2ace/video2slides/main.py#L150), where the ffmpeg call correctly uses `> /dev/null 2>&1`) was to hide the output |
| [L213](https://github.com/m2kar/video2slides/blob/d3bb704b914b0e97dc5661caae6d39ee9f9c2ace/video2slides/main.py#L213) | `print(f"Signal {signum} received…")` inside `def signal_handler(sig, frame)` | **`NameError` on every Ctrl+C.** The temp dir is still cleaned (the `atexit` hook is separate), but the interrupt path is noisy and untested |
| L149, L159, L189 | `os.system(f"… '{video_path}' …")` | shell interpolation of a user-supplied path: breaks on any path containing a `'`, and is a command-injection hole. We use `subprocess` with a list |

**Anurag:**

| Where | What | Why it's there |
|---|---|---|
| [youtube.py#L36-L38](https://github.com/AnuragSingh2101/Video2Slides/blob/ac298c28df08b75aacf24694035f47abf6793baf/backend/app/services/youtube.py#L36-L38) | temp dir under `os.getcwd()/scratch/` with the comment *"avoid root /tmp restriction"* | container `/tmp` is read-only or too small |
| [youtube.py#L66](https://github.com/AnuragSingh2101/Video2Slides/blob/ac298c28df08b75aacf24694035f47abf6793baf/backend/app/services/youtube.py#L66) + [transcription.py#L38-L39](https://github.com/AnuragSingh2101/Video2Slides/blob/ac298c28df08b75aacf24694035f47abf6793baf/backend/app/services/transcription.py#L38-L39) | `audio_path_storage` holds a **local FS path**, not a storage key, to dodge Supabase's 50 MB limit; the consumer then branches `if os.path.exists(path)` to handle both meanings | a field-driven hack that made one DB column polymorphic |
| [llm_analysis.py#L19-L27](https://github.com/AnuragSingh2101/Video2Slides/blob/ac298c28df08b75aacf24694035f47abf6793baf/backend/app/services/llm_analysis.py#L19-L27) | stripping ` ```json ` fences from a response already requested with `response_mime_type="application/json"` | Gemini returns fenced JSON anyway |
| [llm_analysis.py#L8](https://github.com/AnuragSingh2101/Video2Slides/blob/ac298c28df08b75aacf24694035f47abf6793baf/backend/app/services/llm_analysis.py#L8) | method still named `_query_ollama_json` but calls Gemini; `OLLAMA_URL`/`OLLAMA_MODEL="phi4"` remain in `config.py` and are dead | the local-LLM path was abandoned for a cloud API. Relevant to this project's "deterministic first / local" stance: the one surveyed project that tried local LLM inference gave up on it |
| [llm_analysis.py#L41](https://github.com/AnuragSingh2101/Video2Slides/blob/ac298c28df08b75aacf24694035f47abf6793baf/backend/app/services/llm_analysis.py#L41), L65, L95, L128 | `segments[:300]`, `full_text[:12000]`, `full_text[:10000]` | context caps. A 45–60 min talk is 60–90k characters, so **~85 % of the transcript is discarded before slides are generated** |
| [video_proc.py#L19](https://github.com/AnuragSingh2101/Video2Slides/blob/ac298c28df08b75aacf24694035f47abf6793baf/backend/app/services/video_proc.py#L19) | `easyocr.Reader(['en'], gpu=True)` hard-coded | inconsistent with `transcription.py`'s `torch.cuda.is_available()` check; on a CPU-only host easyocr warns and falls back |

---

### F.7 Hard cases, scored

| Hard case (from `docs/idea.md`) | m2kar | Anurag |
|---|---|---|
| Progressive build | **Misses** (32×32 pHash + 1.0 s min-scene-len). *But* its tail-of-dwell capture makes each detected state the most complete one | Misses (HSV histogram barely moves for one bullet) |
| Camera cutaway and back | Two surplus slides, no dedupe. Author lists it as an open TODO | Two surplus slides, no dedupe |
| Embedded video / animation in a slide | Storm of surplus scenes; `min_scene_len 1.0` caps it at ~1/s. Author lists it as an open TODO | Storm of surplus slides, uncapped (no min dwell) |
| Moving webcam overlay | Not addressed | Not addressed |
| Burned-in subtitles changing per phrase | Not addressed. The 32×32 pHash is *accidentally* robust here — a subtitle line is a small fraction of a 32×32 DCT — which is the same coarseness that loses progressive builds. One knob, both effects | Not addressed; HSV hist over a small text region also barely moves |
| Vision mixer cutting constantly | Not addressed | Not addressed |
| Slide filmed on a screen at an angle | Not addressed (no rectification, no crop) | Not addressed |
| Transition animation contaminating the capture | **Solved, in the capture stage** — the 0.05/0.5 s tail margin (§4) | Made worse — captures the first frame after the change |

---

### F.8 Verdicts

| # | Finding | Ticket | Verdict |
|---|---|---|---|
| F1 | **Max-overlap winner-take-all cue→slide assignment against the full dwell interval, cue never split, ties to the earlier slide** ([m2kar L100-L131](https://github.com/m2kar/video2slides/blob/d3bb704b914b0e97dc5661caae6d39ee9f9c2ace/video2slides/main.py#L100-L131), MIT) | **#14** | **Adopt as the baseline rule**, with three fixes: an explicit `unassigned` bucket instead of the silent `-1` drop; per-cue rows retained in the manifest instead of a joined blob; word-level splitting available as an opt-in for near-50/50 straddles |
| F2 | **Capture at `end_of_dwell − clamp(5 % of dwell, 0.05 s, 0.5 s)`** ([m2kar L143-L146](https://github.com/m2kar/video2slides/blob/d3bb704b914b0e97dc5661caae6d39ee9f9c2ace/video2slides/main.py#L143-L146)) | **#11** | **Adopt** as the which-frame-of-the-run rule. Deterministic, dodges transition animations, and is the most complete state of a build. The 0.05/0.5 s clamps go into the spike as tuned starting constants |
| F3 | **Analysis stream ≠ export stream**: detect on a decimated pass, export via `ffmpeg -ss … -q:v 2` against the original at full resolution | **#11, #14** | **Adopt.** Correct for the i3 budget; Anurag's counter-example (ship the 360p analysis frame) shows the failure |
| F4 | **Store the dwell as an interval, not an instant.** Anurag's single-`int` `timestamp` is what made temporal pairing impossible ([video_proc.py#L128-L133](https://github.com/AnuragSingh2101/Video2Slides/blob/ac298c28df08b75aacf24694035f47abf6793baf/backend/app/services/video_proc.py#L128-L133), no licence) | **#14** | **Adopt as a schema constraint.** `(dwell_start, dwell_end, capture_ts)` distinct |
| F5 | `detect-hash --size 16 --lowpass 2 --threshold 0.1 --min-scene-len 1.0`, vs library defaults `0.395` / 15 frames | **#11** | **Measure in the spike**, but expect it to lose on misses: the 32×32 downsample before the DCT is too coarse for progressive builds, and `min_scene_len` *discards* rather than defers suppressed cuts. If it runs, vary `--size`/`--lowpass` too |
| F6 | HSV 2-D histogram correlation, `< 0.92`, sampled at 1 fps, no min dwell, no dedupe | **#11** | **Reject as tuned.** The threshold is unsourced folklore (`"0.85 to 0.95 is standard"`) and the per-sample `cap.set()` seek is the wrong access pattern. The 2-D `(H,S)` histogram itself may still be worth a row in the comparison table |
| F7 | **Ordinal join of an LLM-invented deck onto detected keyframes, labelled "if timing matches"** ([tasks.py#L125-L131](https://github.com/AnuragSingh2101/Video2Slides/blob/ac298c28df08b75aacf24694035f47abf6793baf/backend/app/workers/tasks.py#L125-L131)) | **#14** | **Reject**; keep as the cautionary example of an output that looks complete and is not reconcilable |
| F8 | **No manifest survives** in m2kar: the CSV and frames are `rmtree`'d at exit and provenance is stringified into a PPTX notes field | **#14** | **Negative finding — supports a first-class manifest.** Also worth keeping: emit a row for *every* slide, so a slide with no speech stays visible |
| F9 | 64 kbps mono MP3 for STT (`preferredquality: "64"`, `-ac 1`) | fetch stage | **Adopt.** Free — Whisper resamples to 16 kHz mono regardless |
| F10 | **Neither project crops, and neither uses YouTube captions** (`grep` for `writesubtitles`/`caption`/`srt`/`vtt` over Anurag's tree: zero hits) | **#12** | Confirms `docs/research/slide-region-crop.md`. **#12 stays greenfield**; no new prior art from this slice |
| F11 | m2kar's author lists slide transitions, in-frame camera, and slide-embedded video as **unsolved** in his own README TODO | #11, #17 | Corroborates the hard-case list from the closest prior art's author |

---

### F.9 Reproduction notes

```
extract-slides-cache/reference-implementations/m2kar-video2slides                 d3bb704b914b0e97dc5661caae6d39ee9f9c2ace
extract-slides-cache/reference-implementations/AnuragSingh2101-Video2Slides       ac298c28df08b75aacf24694035f47abf6793baf
```

PySceneDetect defaults quoted in §3 were verified by reading
`scenedetect/detectors/hash_detector.py` from the published wheels of **0.6.4** (the version
contemporaneous with m2kar's Dec-2024 commit) and **0.7.1**; `HashDetector.__init__` is
`threshold=0.395, size=16, lowpass=2, min_scene_len=15` in both. m2kar pins no version
([setup.py#L17](https://github.com/m2kar/video2slides/blob/d3bb704b914b0e97dc5661caae6d39ee9f9c2ace/setup.py#L17)
is a bare `"scenedetect"`), so which defaults it inherited depends on install date.

---

## Group G — perelman/slide-detector

### G.1 Provenance: not on GitHub, and AGPL-3.0

| | |
|---|---|
| Canonical URL | `https://git.aweirdimagination.net/perelman/slide-detector` (self-hosted **Gitea**, not GitHub) |
| GitHub mirror | **None.** `git ls-remote` on `perelman/slide-detector`, `dperelman/slide-detector`, `perelman/slide_detector` → all 404. The GitHub-permalink convention used everywhere else in this document cannot be honoured for this group; permalinks below use the Gitea form `…/src/commit/<sha>/<path>#L<n>`. |
| HEAD sha | `93de3818f1dc090a4fc49c35afe12bb619b69f12` |
| Last commit | **2020-05-30 01:06:35 -0700** — "Fix wording in README." |
| Author | Daniel Perelman `<perelman@cs.washington.edu>` |
| Licence | **AGPL-3.0** (`LICENSE`, 614 lines, "GNU AFFERO GENERAL PUBLIC LICENSE, Version 3") |
| Size | **One file, 144 lines.** `slide-detector.py`, plus `README.md` (35 lines) and a stock Python `.gitignore`. No tests, no data, no requirements file. |
| Local clone | `extract-slides-cache/reference-implementations/perelman-slide-detector` (unshallowed to full history) |

Permalink base used throughout:
`https://git.aweirdimagination.net/perelman/slide-detector/src/commit/93de3818f1dc090a4fc49c35afe12bb619b69f12/slide-detector.py#L<n>`
*(HTTP verification of that URL was not possible from this sandbox — outbound HTTPS is blocked to everything except the git proxy; the form is canonical Gitea and the sha is the one actually cloned.)*

**Why this repo matters despite its size.** SliTraNet — the learned SOTA — credits it in its own source header: `test_slide_detection_2d.py:5`, *"Code is partly based on https://git.aweirdimagination.net/perelman/slide-detector"*. SliTraNet's paper Table I benchmarks its 2-D CNN against a Gaussian-blur frame-differencing baseline derived from this file, and **the deterministic baseline wins on recall** (15 FN vs 25 over 380 transitions). Under this project's lexicographic `(misses, surplus)` metric, misses declare the winner — so this 144-line file is the thing the state of the art failed to beat at the only axis that declares.

**It appears nowhere in this project's `docs/`.** `grep -rniE 'perelman|aweirdimagination|slide-detector' docs/ README.md` → zero hits. Genuinely new lead.

### G.2 Licence incompatibility: read before lifting a line

The project is **MIT** (`/home/developer/github/henricos/extract-slides/LICENSE`, "MIT License, Copyright (c) 2026 Henrico Scaranello"). This reference is **AGPL-3.0**. Copying any of these 144 lines relicenses the project. Every technique below is described so it can be **re-implemented from the description** (algorithms are not copyrightable); do not paste the source. This is the only repo in the survey so far where the licence forces that distinction — the SliTraNet lineage is otherwise permissive.

### G.3 Nobody tuned these constants

Full history is **5 commits, all on 2020-05-29/30** — a single evening. `git log -- slide-detector.py` returns **exactly one commit**: `b4514b6 "Working first draft of slide-detector.py."` The other four are the initial commit and three README edits.

> **Negative finding, and it reframes the brief.** The task asked for "constants someone already tuned, and what they were tuned against". **Nothing here was tuned.** `(21,21)`, `10`, `3000` are first-draft values that were never revised, never measured, and have no test set, no ground truth and no benchmark in the repo. Their authority comes entirely from *downstream*: SliTraNet reproduced this chain, measured it on 380 hand-labelled transitions, and it beat their CNN on recall. Cite the chain via SliTraNet's Table I, never via this repo's own (non-existent) evidence.

---

### G.4 The differencing core

Per-frame, at **full source resolution, every frame, no stride, no downscale**:

| Step | Line | Permalink | Code |
|---|---|---|---|
| crop (optional, **before** everything) | L40 | [#L40](https://git.aweirdimagination.net/perelman/slide-detector/src/commit/93de3818f1dc090a4fc49c35afe12bb619b69f12/slide-detector.py#L40) | `frame = crop(frame)` |
| colour space | L47 | [#L47](https://git.aweirdimagination.net/perelman/slide-detector/src/commit/93de3818f1dc090a4fc49c35afe12bb619b69f12/slide-detector.py#L47) | `cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)` |
| blur | L48 | [#L48](https://git.aweirdimagination.net/perelman/slide-detector/src/commit/93de3818f1dc090a4fc49c35afe12bb619b69f12/slide-detector.py#L48) | `cv2.GaussianBlur(gray, (21, 21), 0)` |
| difference | L62 | [#L62](https://git.aweirdimagination.net/perelman/slide-detector/src/commit/93de3818f1dc090a4fc49c35afe12bb619b69f12/slide-detector.py#L62) | `cv2.absdiff(anchor_gray, gray)` — **anchor**, not previous frame |
| threshold | L65 | [#L65](https://git.aweirdimagination.net/perelman/slide-detector/src/commit/93de3818f1dc090a4fc49c35afe12bb619b69f12/slide-detector.py#L65) | `cv2.threshold(deltaframe, 10, 255, cv2.THRESH_BINARY)[1]` |
| dilate | L66 | [#L66](https://git.aweirdimagination.net/perelman/slide-detector/src/commit/93de3818f1dc090a4fc49c35afe12bb619b69f12/slide-detector.py#L66) | `cv2.dilate(threshold, None)` |
| **reduction** | L70 | [#L70](https://git.aweirdimagination.net/perelman/slide-detector/src/commit/93de3818f1dc090a4fc49c35afe12bb619b69f12/slide-detector.py#L70) | **`if threshold.any():`** |

**The reduction is `any()`, not `countNonZero()/total`.** Every other project in `docs/research/slide-change-detection.md` reduces the difference image to a *fraction* of changed pixels and compares it to a percentage (binh234 `MIN_PERCENT=0.15`, TalkMiner "> 1% of total"). This one reduces it to **existence**: `max(blur(|a−b|)) > 10`. Sigma is `0`, i.e. OpenCV derives σ ≈ 0.3·((21−1)·0.5 − 1) + 0.8 = **3.8 px** from the kernel.

That is the **most recall-biased reduction possible** for a given τ, and it is exactly the shape this project's metric rewards: it cannot miss a change that any pixel registers; it pays for that in anchor thrash, not in misses. `docs/research/slide-change-detection.md` §5.3 measures `absdiff + threshold + countNonZero` but never measures the `max`/`any` reduction. **It is a distinct operating point and it is currently unmeasured.**

**The `dilate` at L66 is dead code for the decision. [verified]** Dilation cannot turn an all-zero image non-zero, and cannot zero a non-zero one, so `.any()` is invariant under it (confirmed: `cv2.dilate(zeros,None).any() → False`; a 1-px blob goes 1 px → 9 px but stays non-zero). With `UI=False` it costs a full-frame morphological pass per frame and buys nothing — it exists only to thicken the `'threshold'` debug window at L68. **A lifted implementation drops it.** (It *would* be load-bearing under a `countNonZero > n` reduction, which is presumably where it came from.)

#### G.4.1 Constants, and what they actually do

The exact chain was run to characterise the operating point, since the repo supplies no evidence of its own. Measured on the target host (see [Measured on the target host](#measured-on-the-target-host)).

| Probe | Result | Meaning |
|---|---|---|
| One **1×1 black pixel** on a white 1080p frame | maxdiff **13** → **fires** | The predicate is extraordinarily sensitive. A single pixel of change trips it. |
| 24/40/64 px bullet line appears | maxdiff **155 / 199 / 228** → fires | Progressive builds are detected with a ~15–20× margin over τ=10. |
| i.i.d. Gaussian sensor noise σ=1,2,3,5,**8** | maxdiff 1,1,1,2,**3** → **never fires** | The (21,21) blur is a noise annihilator: averaging over ~441 px divides i.i.d. σ by ~21. This is *why* the kernel is that large — it is what makes `any()` survivable at all. |
| **Blocky (DCT-like) residual**, 16×16 blocks, amplitude **2** grey levels | maxdiff **12** → **fires** | ❗ Realistic codec noise is spatially correlated and **survives the blur**. 8×8 blocks need amplitude 3. On a real compressed 1080p stream this chain will trip on encoder noise alone. **This is the actual field failure mode, and the blur does not cover it.** |
| Global luma shift +5 / +11 (auto-exposure, projector AGC) | 5 → no; 11 → **fires, 2.07 M px** | Any camera gain ramp resets the anchor on every frame. |
| **Dark-theme text**, fg 40 on bg 32 (Δ8) | maxdiff **7** → **does not fire** | ❗ τ=10 post-blur is **not free**: a low-contrast bullet on a dark slide is a **silent miss**. Δ16 fires. Thin light-grey text on dark backgrounds is a known real slide style. |
| Localized distractor: 320×290 webcam box / subtitle strip / 60×40 station bug changing while slide is static | maxdiff 143 / 142 / **140** → all fire | See §2 — this is the catastrophic case. |
| Downscale **before** the chain (perelman does not) | 1.0 → 199, 0.5 → 140, **0.25 → 96** → all fire | A 480×270 downscale keeps a ~10× margin on bullet-scale changes while killing sub-bullet sensitivity. **Downscale is a free tuning axis the original lacks.** |
| Blur kernel sweep, bullet vs σ=3 i.i.d. noise | k=1: bullet 235 / noise **16 (fires)**; k=5: 235 / 5; k=11: 231 / 3; **k=21: 199 / 1**; k=31: 161 / 1 | k=21 is comfortably past the knee. k=11 already suppresses i.i.d. noise; k=21 is conservative, not magic. **Verified: the `(21,21)` figure another agent attributed to this lineage is real and is at L48.** |
| Cost: `GaussianBlur(21,21)+absdiff+reduce` | **4.15 ms/frame @1080p**, **0.56 ms @480×270** — measured on the target host itself | Full-res every-frame is the dominant avoidable cost. At 0.25 scale it is 7.4× cheaper with no loss of bullet sensitivity. |

**Tuning verdict on the constants:** `(21,21)` is justified and transferable; `τ=10` is *too high* for dark low-contrast slides and *too low* for blocky codec noise — it is a single scalar being asked to do two jobs, which is the argument for a downscale + a spatial-extent test rather than a different τ.

---

### G.5 The anchor logic

State is four globals ([#L23–L28](https://git.aweirdimagination.net/perelman/slide-detector/src/commit/93de3818f1dc090a4fc49c35afe12bb619b69f12/slide-detector.py#L23)): `anchor_frame`, `anchor_gray`, `anchor_frame_num`, `anchor_time`. `set_anchor()` ([#L50](https://git.aweirdimagination.net/perelman/slide-detector/src/commit/93de3818f1dc090a4fc49c35afe12bb619b69f12/slide-detector.py#L50)) snapshots the **colour cropped frame**, the blurred grey, the frame number and `CAP_PROP_POS_MSEC`.

The entire decision is six lines ([#L70–L79](https://git.aweirdimagination.net/perelman/slide-detector/src/commit/93de3818f1dc090a4fc49c35afe12bb619b69f12/slide-detector.py#L70)):

```
if threshold.any():                                  # this frame differs from the anchor
    if time - anchor_time > STATIC_THRESHOLD_MSECS:  # the anchor was held ≥ 3 s
        write anchor_frame                           # export the ANCHOR, not the current frame
    set_anchor()                                     # anchor advances to the current frame
```

**Every frame is compared to a pinned anchor, and the anchor advances on *every* differing frame** — not on a "transition confirmed" event. That produces four behaviours worth naming:

1. **Continuous motion emits nothing.** While anything moves, the anchor advances each frame, the dwell gap is one frame time (~33 ms), `3000` is never reached. The failure under motion is **silence, not surplus** — a pure miss under this project's metric. This is the inverse of the failure mode the project is designed around.
2. **The exported frame is always a settled frame, for free.** During a dissolve the anchor chases the transition frame by frame; the anchor that finally *survives* 3 s is the first frame after the picture stopped changing. No look-ahead, no re-seek, no "grab 95% into the scene". `docs/research/slide-change-detection.md:925` lists four independent implementations of "capture from inside the dwell, not at the transition" (`larry-xue` `grabPoint`, `kovitking` mid-run, `m2kar` 0.95, TalkMiner "last frame in segment"). **This is a fifth, and it is the only one that costs nothing** — the anchor mechanism self-selects a clean frame as a side effect of its own state machine.
3. **Slow fades export the *old* slide cleanly.** Because the reference is pinned, a fade whose per-frame delta is below τ accumulates against the anchor; when it finally crosses, the emitted `anchor_frame` is the last clean frame *before* the fade. Correct content, no half-dissolve. (`docs/research/slide-change-detection.md:139` derives the same property from ffmpeg `freezedetect`/`mpdecimate`; this is an independent instance and the only one that also solves *which* frame to export.)
4. **A progressive build emits one image per reveal.** Bullet appears → fires → anchor held ≥3 s → the **pre-bullet** state is written → anchor becomes the post-bullet state. So an *n*-bullet build yields *n* images, each showing 1…n−1 bullets, and the complete slide is emitted only when the *next* slide arrives. This is exactly the over-capture the project declares intentional — **but note the off-by-one: you get every partial state and the complete state, which is the superset the dedupe stage is supposed to collapse.**

**Animation flood vs progressive build — the asymmetry.** A build is a step function (change, then 3+ s of stillness → emit). An animation/embedded video is a continuous function (change every frame → anchor never held → **emit nothing at all** for the whole duration, including the slide that is underneath it). The 3-second dwell does not merely under-sample an animated slide; it **erases** it. This is the identical observation TalkMiner published (`docs/research/slide-change-detection.md:754`: *"missed slides due to continuous small motion"*) and it is why their spatial-extent filter exists. **perelman has no such filter — the manual crop is the entire mitigation.**

---

### G.6 The crop UI

**The user does not draw anything.** There is no mouse handler, no `cv2.selectROI`, no drag rectangle. `grep -n 'setMouseCallback\|selectROI' slide-detector.py` → nothing. The "UI" is a **keyboard nudger** ([#L95–L142](https://git.aweirdimagination.net/perelman/slide-detector/src/commit/93de3818f1dc090a4fc49c35afe12bb619b69f12/slide-detector.py#L95)): `w/a/s/d` move the top-left by 10 px, `W/A/S/D` by 1 px, `i/j/k/l` and `I/J/K/L` resize by 10/1 px, each `print()`ing the new scalar. `z`/`x` seek ±100 frames and reset the anchor ([#L86](https://git.aweirdimagination.net/perelman/slide-detector/src/commit/93de3818f1dc090a4fc49c35afe12bb619b69f12/slide-detector.py#L86)).

**It does not produce a crop — it produces four numbers you retype.** The rectangle is never saved. You read `x=…`, `y=…`, `w=…`, `h=…` off stdout and pass them as `argv[2:6]` on a second, non-UI run ([#L10–L13](https://git.aweirdimagination.net/perelman/slide-detector/src/commit/93de3818f1dc090a4fc49c35afe12bb619b69f12/slide-detector.py#L10)). The UI is a *calibration* mode, not a crop stage.

**`UI` is a source constant, not a flag.** `UI = False` at [#L7](https://git.aweirdimagination.net/perelman/slide-detector/src/commit/93de3818f1dc090a4fc49c35afe12bb619b69f12/slide-detector.py#L7). The README admits it: *"There's no command-line option for it, but at the top of the file…"*. You edit the file to calibrate, then edit it back.

**Nothing is ever inferred automatically. → Issue #12's greenfield premise is CONFIRMED, and now confirmed at both ends of the lineage.** The descendant does the same thing: SliTraNet reads its ROI from a hand-authored annotation file, `test_SliTraNet.py:74` — `roi_path = os.path.join(opt.dataset_dir,"videos", opt.phase+'_bounding_box_list.txt')`, parsed by `data/data_utils.py:62–70` into `x1,y1,x2,y2` per video basename. **The deterministic ancestor takes the rectangle on argv; the learned SOTA takes it from a text file a human wrote. Neither computes it.**

**But the crop here is not cosmetic — it is load-bearing for recall, and it is applied BEFORE detection.** L40 crops, L47 converts, L62 diffs. The detector only ever sees the cropped region. Given §2's "continuous motion emits nothing" and my probe 9 (a 60×40 station bug or a subtitle strip changing while the slide is static → maxdiff 140 → fires every frame → anchor never held → **zero slides for that entire video**), the manual rectangle is the *only* thing standing between this tool and total failure on any recording with a webcam overlay, burned-in subtitles, or a broadcast bug.

> **Architectural consequence for this project.** The declared pipeline is `detect → crop`. perelman's ordering is `crop → detect`, and that ordering is what makes his detector work at all. This does not mean reordering the stages — it means **detection needs its own region of interest, decided before or during detect**, even if the *output* crop is computed later. That is a new coupling between #11 and #12 that neither ticket currently states.

---

### G.7 Gate, export choice, naming, audio

| Question | Answer in this repo |
|---|---|
| Slide-frame gate / non-slide rejection (**#17**) | **None.** No Laplacian, no histogram, no SVM, no blank/black-frame test, no aspect test. The only filters are (a) the manual crop and (b) the 3 s dwell. Grep for `Laplacian\|calcHist\|SVM` → zero hits. |
| Which frame of the dwell is exported | **The first settled frame** (`anchor_frame`), written at the moment the dwell *ends* ([#L78](https://git.aweirdimagination.net/perelman/slide-detector/src/commit/93de3818f1dc090a4fc49c35afe12bb619b69f12/slide-detector.py#L78)). Colour, cropped, un-blurred. See §2.2. |
| Output naming | `static_at_%s.jpg % msec_to_human_readable(anchor_time)` → **`static_at_MM:SS.jpg`**, timestamp of the *start* of the dwell. No sequence number. Written to the **current working directory** with no output-dir option. Quality is OpenCV's JPEG default (95). |
| Audio / transcript | **Nothing.** No ffmpeg, no ASR, no subtitle handling anywhere in the repo. |
| Dedupe / "have I seen this slide before?" | **Nothing.** No hashing, no revisit detection. A cutaway to the speaker and back re-exports the same slide. Under `(misses, surplus)` that is the cheap direction, but it means this tool contributes **nothing** to the dedupe half of #11. |

---

### G.8 Defects the README does not mention

1. **The last slide of every video is silently dropped. [code-verified]** The emit test at [#L70](…#L70) only runs *inside* `if threshold.any():`. The loop exits at [#L38–L39](https://git.aweirdimagination.net/perelman/slide-detector/src/commit/93de3818f1dc090a4fc49c35afe12bb619b69f12/slide-detector.py#L38) when `frame is None` and there is **no flush after the loop** (L143 is `cap.release()`). A slide held from its appearance to the end of the recording — i.e. the closing/thank-you/Q&A slide of essentially every talk — is never written. **One guaranteed miss per video**, which under a lexicographic `(misses, surplus)` metric is the worst possible kind of bug. Any lifted implementation must flush the pending anchor at EOF.
2. **Resizing the crop in UI mode crashes the tool. [verified]** `i/j/k/l/I/J/K/L` change `w`/`h` but do **not** reset `anchor_frame`, so the next iteration computes `cv2.absdiff(anchor_gray, gray)` on arrays of different shapes → `cv2.error: (-209:Sizes of input arguments do not match)`. Only `z`/`x` reset the anchor (L89, L93). Moving the corner (`w/a/s/d`, size preserved) is safe; resizing is not. The README documents all sixteen keys as equals.
3. **Negative crop origin silently produces an empty frame. [verified]** `x`/`y` are unclamped; `frame[-10:-10+500]` on a 1080-row frame yields shape `(0, 800, 3)` → the same `absdiff` crash. Nudging the rectangle off the top or left edge kills the run.
4. **`MM:SS` filenames are illegal on Windows/exFAT** (`:`), and truncate to whole seconds, so two dwells starting in the same second **overwrite each other**.
5. **The CLI cannot take `slide_time_millis` without also taking a crop** — `if len(sys.argv) > 5` at L10 gates both, so `argv[6]` is unreachable unless four crop values are supplied.
6. **Progress printing is frame-count modular, not time-based** ([#L44](https://git.aweirdimagination.net/perelman/slide-detector/src/commit/93de3818f1dc090a4fc49c35afe12bb619b69f12/slide-detector.py#L44), `% 2000 == 0`) and is suppressed entirely in UI mode.
7. **No stride, no downscale, no seek.** Every frame is decoded and blurred at source resolution. For a 60-min 30 fps 1080p input that is 108,000 full-res `GaussianBlur(21,21)` passes. Given the dwell threshold is 3 s, a stride of 5–10 frames would lose nothing and cost 5–10× less — the tool's own parameters prove the sampling is 100× denser than its decision needs.

### G.9 Hard cases

| Hard case | Behaviour |
|---|---|
| Progressive build | ✅ Handled, and over-captures by design: one image per reveal (§2.4). |
| Camera cutaway to speaker and back | ⚠️ Emits the slide, emits the speaker shot, re-emits the slide. No dedupe → duplicate. Surplus, not miss — acceptable direction. |
| Embedded video / animation in a slide | ❌ **Silent total miss** for the whole animated span, including the underlying slide (§2). |
| Moving webcam overlay | ❌ **Silent total miss for the entire video** unless a manual crop excludes it (probe 9: a 320×290 box → maxdiff 143 every frame). |
| Burned-in subtitles changing every phrase | ❌ Same — maxdiff 142, anchor never held, **zero output**. |
| Vision mixer cutting constantly | ❌ Same class of failure. |
| Slide filmed on a screen at an angle | ❌ No rectification, no perspective handling; and the projector AGC / auto-exposure that such recordings exhibit trips the chain globally (probe 8: +11 grey levels → fires). |

Four of seven hard cases fail in the **miss** direction — the direction this project's metric punishes hardest. That is the honest counterweight to the SliTraNet recall headline: the baseline wins recall **on SliTraNet's dataset**, which is clean lecture-capture with a hand-drawn ROI already applied.

---

### G.10 Verdicts

| Technique | Verdict | Ticket |
|---|---|---|
| **Pinned anchor + emit-the-anchor-on-break** — the reference frame advances on every differing frame; the frame you export is the anchor that survived the dwell | **ADOPT.** It is simultaneously the change detector *and* the answer to "which frame of the dwell do I export", at zero extra cost and with no second pass, no re-seek, no `0.95`-into-the-scene heuristic. It provably never exports a transition frame, and on slow fades it exports the clean pre-fade slide. It is also the exact control flow SliTraNet kept when it replaced the comparator with a CNN (`test_slide_detection_2d.py:75–115`, `anchor_frame` / `anchor_frame_idx` / `slide_thresh`) — the SOTA validated the *architecture*, not just the metric. | **#11** |
| **`max(blur(absdiff)) > τ` (the `any()` reduction)** as a distinct operating point alongside `countNonZero/total > frac` | **MEASURE — first-class, and cheap to add.** It is one line of difference from the `absdiff` baseline already in `docs/research/slide-change-detection.md` §5.3, and it is the most recall-biased reduction available, which is the direction the metric declares. Measure it **with a 480×270 downscale and a stride**, both of which the original lacks and both of which my probes show cost nothing in bullet sensitivity (maxdiff 96 at 0.25 scale) while removing 7.4× of the cost and most of the sub-bullet false triggers. | **#11** |
| `(21,21)` Gaussian σ≈3.8 as the pre-diff blur | **ADOPT as the default blur.** Verified at L48 [measured]: it annihilates i.i.d. noise to σ=8 while leaving a 40 px bullet at maxdiff 199. k=11 is already past the knee; k=21 is the conservative side of it. | **#11** |
| `τ = 10` post-blur | **MEASURE, do not adopt blind.** Two documented failures: it **misses** Δ8-contrast dark-theme text, and it **fires** on 16×16 codec blocks at amplitude 2. It is one scalar doing two jobs. | **#11** |
| `dilate(threshold, None)` | **REJECT — verified no-op** under an `any()` reduction; pure per-frame cost. | **#11** |
| 3 s dwell (`STATIC_THRESHOLD_MSECS = 3000`) | **MEASURE, with a spatial-extent guard mandatory.** Note the number is independently arrived at by TalkMiner ("stable for at least three seconds", `docs/research/slide-change-detection.md:743`) — three seconds is a real convergent constant. But unguarded, the dwell converts continuous motion into **silence**, which is the metric's worst outcome. TalkMiner's bounding-box-extent test is the published fix and their numbers show recall *rising* when they added it. | **#11**, feeds **#17** |
| Flush the pending anchor at EOF | **ADOPT as a requirement.** The original loses the final slide of every video. | **#11** |
| Crop-before-detect / detection ROI | **ADOPT the ordering insight, REJECT the manual rectangle.** The crop is load-bearing for recall here, not cosmetic. Detection needs a region decided before detect runs. | **#12** ↔ **#11** |
| Manual `x y w h` on argv + keyboard-nudge calibration mode | **REJECT as a UX, RECORD as evidence.** Confirms #12 is greenfield at both ends of the lineage: ancestor takes argv, SOTA takes `train_bounding_box_list.txt`. **Nobody in this lineage infers the slide region.** | **#12** |
| Slide-frame gate | **Nothing here.** Negative finding for **#17**: the deterministic ancestor has no gate of any kind, and still beat the CNN on recall — on a dataset where a human had already drawn the ROI. That is not evidence a gate is unnecessary; it is evidence the ROI was doing the gate's job. | **#17** |
| Dedupe / revisit detection | **Nothing here.** No hashing, no memory. Contributes zero to the dedupe half of #11. | **#11** |
| Audio / transcript | **Nothing here.** | — |
