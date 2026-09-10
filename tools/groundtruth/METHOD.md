# How the ground-truth proposal is produced

Ground truth for the reference set is **machine-proposed and human-verified**
([ADR 0003](../../docs/adr/0003-correctness-metric-and-ground-truth.md)). This is
the machine half: what `propose.py` does, why it is built the way it is, and what
was measured while calibrating it. The human half — accepting or rejecting each
proposed state, grouping states into expected slides, and drawing the slide
rectangles — is what turns a proposal into ground truth.

## Why not just reuse a detector

ADR 0003 forbids proposing transitions with a metric family from the detection
shortlist in [`docs/research/slide-change-detection.md`](../../docs/research/slide-change-detection.md)
§10. Proposing with block-wise MAD, a perceptual hash or SSIM would bias the
ground truth toward whichever spike candidate uses it. What the ADR does bless is
*dense frame sampling with pairwise comparison*, and that is what this is:

| | shortlist candidates | `propose.py` |
|---|---|---|
| sample rate | 0.5–2 fps | **~4 fps** |
| working resolution | 160×90 to 360×202 | **long side 960** |
| comparison | consecutive, or last-kept frame | against the **last emitted state**, over **jointly still pixels** |
| decision | one threshold declares a slide | nothing here declares a slide; a human groups the states |

The last row is the important one. `propose.py` does not implement the
accumulation rule and has no opinion on what one slide is. It emits *states* —
visually distinct, settled frames — with deliberately high recall, and the
accumulation rule is applied by eye afterwards.

## The signal

Two stages, because decoding is the expensive part and the thresholds want
tuning:

    propose.py sample  <id>     decode once, cache grayscale samples  (9-48 s)
    propose.py propose <id>     emit candidate states from the cache   (7-40 s)
    propose.py frames  <id>     native-resolution JPEG per state
    propose.py sheet   <id>     contact sheets of those frames

`propose` maintains two things per sample:

- **stillness** — a pixel is *still* when it has not moved by more than
  `--delta` (12 grey levels) in any of the last `--still-window-s` (1 s) of
  samples;
- **drift** — the fraction of the frame that differs from the last emitted state,
  counted only over pixels still *both* now and when that state was recorded.

A new state is recorded when drift crosses `--drift`. If less than
`--min-still-frac` of the frame is holding still, drift is not evaluable, and a
state is recorded anyway after `--force-after-s` so that nothing can hide in a
permanently moving frame.

Each state carries `change_after_s` (the last sample that still matched the
previous state, so the change is bracketed) and `dwell_s` (how long it survived).

## What the calibration measured

Three things went wrong on the first pass and each is worth keeping.

**1. A global activity mask does not work on real talks.** The first version
excluded pixels that changed in more than 30% of sample pairs, the shape
`larry-xue/video-slide-extractor` uses for a permanently moving region. Measured
per-pixel activity over the whole video, highest value per fixture:

| fixture | class | max per-pixel activity |
|---|---|---|
| `2AWv_nIfp-U` | `C4`, video playing inside the slide | **0.051** |
| `pJc0l2DASpo` | `C1`+`C3` | 0.064 |
| `YBH8rQv4aTQ` | `C5` | 0.200 |
| `b9dBJnQ_kpo` | `C2b` unstable | 0.303 |
| `jqpdveK2XAU` | `C2b` + speaker strip | 0.455 |
| `X3uFwLj2u7Q` | `C7` | 0.590 |

The fixture with video *inside* the slide has the **lowest** activity of the six,
because the clip runs for a small fraction of an 11-minute talk and the fraction
is diluted by duration. A statistic computed once per video cannot see a region
that is violent for one minute and still for ten, which is the shape all six
have. Replacing it with per-pixel stillness over a 1-second window cut
`jqpdveK2XAU` from 169 states to 50.

**2. Normalising drift by the still subset inflates it.** Dividing by the number
of jointly-still pixels lets a small still region produce a large quotient, and
on `YBH8rQv4aTQ` — a vision-mixed talk that cuts between stage cameras — that
produced **760 states for 11 minutes, 592 of them transient**. Normalising by the
whole frame instead removes the unstable denominator.

**3. `force` must count from the onset of the change, not from the last state.**
Counting from the last emitted state made it fire on the first frame of every
normal transition, adding a mid-fade frame before the real one: 77 states instead
of 55 on `pJc0l2DASpo`.

**4. The contrast threshold cannot be one global number.** The states left over on
the vision-mixed fixtures come from *low-contrast* accumulated change — sweeping
stage lights, a slow camera push, sensor noise in dark areas — where every single
step stays under `--delta` so the pixels never stop counting as still, but the
difference against a fixed reference keeps growing. Raising the threshold used
for the drift comparison alone (leaving stillness at 12) was measured at
`--drift 0.002`, states as *total / transient / kept*:

| fixture | class | Δ12 | Δ25 | Δ40 |
|---|---|---|---|---|
| `pJc0l2DASpo` | `C1`+`C3` builds | 64 / 8 / **56** | 36 / 0 / **36** | 35 / 0 / 35 |
| `jqpdveK2XAU` | `C2b` | 88 / 8 / 80 | 27 / 0 / 27 | 22 / 0 / 22 |
| `b9dBJnQ_kpo` | `C2b` unstable | 160 / 8 / 152 | 72 / 1 / 71 | 48 / 0 / 48 |
| `2AWv_nIfp-U` | `C4` | 77 / 4 / 73 | 73 / 1 / 72 | 72 / 2 / 70 |
| `YBH8rQv4aTQ` | `C5` | 826 / 681 / 145 | 273 / 10 / 263 | 177 / 1 / 176 |
| `X3uFwLj2u7Q` | `C7` | 207 / 36 / 171 | 90 / 3 / 87 | 63 / 2 / 61 |

Δ25 is tempting: it cuts `YBH8rQv4aTQ` from 826 states to 273 and all but removes
the transients. But on the control it takes `pJc0l2DASpo` from 56 kept states to
36, and that fixture's remaining states are exactly the progressive builds and
the walking highlight — the subtle changes a ground-truth proposal must not miss.

**A single contrast threshold trades recall on progressive builds against noise on
live-camera footage, and the two live in different videos.** So this tool keeps
one threshold at 12, accepts the higher state count, and bounds the review load in
the presentation layer instead (`sheet --min-dwell`), which discards nothing. The
finding is worth carrying into the detection spike
([#11](https://github.com/henricos/extract-slides/issues/11)): any candidate with
one global sensitivity parameter faces the same trade, on the same fixtures, and
these are the numbers it starts from.

## What the proposal actually rests on

With the parameters above, `reason` across all six fixtures is `settled` for 1419
of 1422 states: `forced` fires **three times in 46 minutes** of video, and never
on a state that survives the dwell filter. The proposal is measured, not guessed —
the escape hatch exists so a permanently moving frame cannot hide a slide, not as
a working path.

| fixture | states | kept (`dwell >= 0.5 s`) | held back |
|---|---|---|---|
| `pJc0l2DASpo` | 64 | 56 | 8 |
| `jqpdveK2XAU` | 88 | 80 | 8 |
| `b9dBJnQ_kpo` | 160 | 152 | 8 |
| `2AWv_nIfp-U` | 77 | 73 | 4 |
| `X3uFwLj2u7Q` | 207 | 171 | 36 |
| `YBH8rQv4aTQ` | 826 | 145 | 681 |
| **total** | **1422** | **677** | **745** |

`YBH8rQv4aTQ` is the vision-mixed outlier in both columns, and both numbers are the
same fact: it cuts between shot types constantly, so most of what it emits is
superseded within half a second.

## Reading a proposal

- `dwell_s` near zero marks a **transient** — a cross-fade frame that holds
  content from two slides at once, or a frame grabbed mid-animation. On
  `pJc0l2DASpo` the three states with `dwell_s == 0` were exactly the three
  frames a human review would throw out. Sort by `dwell_s` to find them.
- `reason: forced` marks a state recorded because nothing settled, not because
  anything was measured. Treat it as a place to look, not as a finding.
- `still_frac` says how much of the frame was holding still when the state was
  recorded. A low value means the state was judged on little evidence.

## Environment notes

- **`yt-dlp` must be recent.** The version installed on the host (2026.07.04)
  returns HTTP 403 for every media format on all player clients: the GVS PO-token
  gate, which is a *different* gate from the `timedtext` one measured in
  [`docs/research/youtube-captions.md`](../../docs/research/youtube-captions.md).
  2026.08.19 works via the `visionos` client. The fetch is pinned to that version.
- **No system `ffmpeg` is needed.** Video-only streams download without muxing
  (ground-truth labelling needs no audio) and the `opencv-python-headless` wheel
  decodes all six, confirming ADR 0001's measurement on 480p/720p/1080p at 25–50 fps.
- Videos and the sample cache live in `$EXTRACT_SLIDES_CACHE`
  (default: the repo's sibling `extract-slides-cache/`), never in the repo.
  The sample cache is ~4.5 GB for the six fixtures.
