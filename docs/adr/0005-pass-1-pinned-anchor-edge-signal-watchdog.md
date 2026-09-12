# Pass 1: a pinned anchor, an edge signal, and a watchdog against silence

- **Status:** accepted
- **Date:** 2026-09-12
- **Ticket:** [#11 — Pass 1: capture the screens, drop the easy duplicates](https://github.com/henricos/extract-slides/issues/11)
- **Implements:** [ADR 0004](0004-capture-generously-delete-afterwards.md)

## Decision

Pass 1 samples the video **twice a second**, analyses each sample **at 480 px wide**, and
holds the full-resolution colour frame of the current anchor in memory so that an export
costs no second decode and no re-seek.

**The change signal is the edge difference.** Auto-Canny with thresholds derived per frame
from the luma median, dilate both edge maps, take the mean absolute difference, expressed
as the percentage of pixels whose edge state differs. **Fire at ≥ 0.5.**

**The capture rule is the pinned anchor.** Every sample is compared against a held anchor,
not against its predecessor. When a sample differs, the anchor is emitted if it had held
for **≥ 1.5 s**, and the anchor then advances to the current sample. Three rules complete
it:

- **The first frame is always emitted.**
- **The pending anchor is flushed at EOF**, or the closing slide of every talk is lost.
- **The watchdog:** if 10 s pass with no emission while the anchor keeps advancing, emit
  the current frame anyway. Under continuous churn the anchor never settles, and without
  this rule the whole span — including the slide underneath the churn — produces nothing.

**An easy duplicate is a near-identical image already emitted.** A 256-bit DCT perceptual
hash of each emitted image is compared against every image already kept, and the new one
is dropped below **0.02 of differing bits**. Threshold as a fraction of bits, never a raw
Hamming count. Comparing against *all* kept images, not just the previous one, is what
absorbs a camera cutting away from the slide and back.

Nothing else. No activity mask, no detection ROI, no persisted exclusion list, no second
hash, no feature cache, no burst suppression, no slide-frame gate.

## Why

**Edges, not `max(blur(|a−b|))`.** Both were on the table and both are measured in
`docs/research/reference-implementations.md`. The edge difference sits at exactly 0.0 on a
static frame and at 1.18–1.83 on a one-bullet reveal, so any threshold in (0.01, 1.18)
catches every build and every hard cut (§C.2). Its Canny thresholds come from the frame's
own median, which makes it immune to the projector gain ramps that trip a pixel
difference, and the dilation absorbs the 1–2 px wobble of a filmed screen. The alternative,
`max(blur(|a−b|)) > 10`, is the more recall-biased reduction in isolation (§G.4), but it
fires on 16×16 codec blocks at an amplitude of 2 grey levels and misses Δ8-contrast
light-on-dark text. **Under a pinned anchor a trigger-happy signal does not produce
surplus, it produces silence** — the anchor never settles, so nothing is emitted. Choosing
the signal that *separates* best, and putting its threshold at the low end, is what
over-capture means here.

**The watchdog is the load-bearing decision, and the fixtures proved it.** On
`X3uFwLj2u7Q` — a camera filming a screen in a dark auditorium, so the frame is never
still — the ordinary dwell rule fired **once in 5 minutes 19**. The other 21 images came
from the watchdog. Without it that video yields one image. This is exactly the failure
`perelman/slide-detector` exhibits on four of its seven hard cases (§G.9): not surplus,
**silence**, which is the only outcome ADR 0004 says costs anything. The watchdog converts
it into surplus, which is free.

**And it made a detection region unnecessary.** [#20](https://github.com/henricos/extract-slides/issues/20)
left this ticket the question of whether pass 1 needs a region of its own so that a
burned-in subtitle or a moving webcam cannot silence it. The watchdog answers the same
question in three lines, without a region, without a mask, and without the coupling to the
crop stage that a detection ROI would create. The activity mask from
`larry-xue/video-slide-extractor` stays on the shelf: it would reduce how often the
watchdog fires, which is an efficiency, not a correctness argument.

**No burst suppression.** `min_scene_len` and its relatives merge an animation and a
progressive build with one scalar, and a burst shorter than the window yields only its
emptiest state (§C.3). It is a miss generator. There is none.

**Re-running is cheaper than not having to re-run.** The whole sweep set, 45 min 55 s of
video, runs in **2 min 45 s**. A persisted per-sample feature file, which would let a
threshold be re-swept without decoding, was designed and then cut: it is machinery to
avoid a cost that turned out to be three minutes.

## What this produced

Measured over the six sweep fixtures in [`docs/reference-set.md`](../reference-set.md),
at the constants above:

| fixture | class | kept | dwell | watchdog | dupes dropped | time |
|---|---|---|---|---|---|---|
| `pJc0l2DASpo` | C1+C3 | 38 | 34 | 2 | 14 | 10 s |
| `jqpdveK2XAU` | C2b | 19 | 13 | 4 | 27 | 9 s |
| `b9dBJnQ_kpo` | C2b unstable | 31 | 15 | 14 | 20 | 32 s |
| `2AWv_nIfp-U` | C4 | 53 | 49 | 2 | 33 | 38 s |
| `YBH8rQv4aTQ` | C5 | 78 | 37 | 39 | 3 | 45 s |
| `X3uFwLj2u7Q` | C7 | 22 | 1 | 20 | 12 | 31 s |

**241 images from 45 min 55 s**, roughly five per minute of video, at 6 % of real time.

**Verified the way ADR 0004 says to verify: by looking.** The operator reviewed
`pJc0l2DASpo` capture by capture against the video and found **nothing missing**. The
hardest false-positive fixture, `2AWv_nIfp-U` — rendered footage playing inside the slide
plus a step-by-step algorithm animation — produced every step of the animated build and
every slide of the deck, with the embedded video contributing a handful of captures rather
than a flood.

## Consequences

- **Pass 2 receives about five images per minute of video**, and that is the number
  [#21](https://github.com/henricos/extract-slides/issues/21) is designed against. On a
  vision-mixed talk (`YBH8rQv4aTQ`) roughly half of them are shots of the speaker, because
  there is no slide-frame gate and, per ADR 0004, there must not be one.
- **Partial states of a progressive build are output, by design and with the operator's
  agreement.** An *n*-step build yields each step plus the complete slide. Telling the
  complete state from a partial one is the judgement call ADR 0004 hands to pass 2; the
  operator confirmed he is content to make it there, by hand or by AI.
- **The duplicate test is nearly inert before the crop.** It compares whole frames, so a
  presenter moving in shot makes two captures of one slide look different: 27 dropped on
  `jqpdveK2XAU` but the same slide still kept five times over. This is the measured case
  for running the same test again **after** the crop, where the moving part of the frame is
  gone (`docs/research/reference-implementations.md` §B.8). It belongs to
  [#12](https://github.com/henricos/extract-slides/issues/12), not here.
- **The emitted frame is settled, but not guaranteed to be.** The pinned anchor cannot
  export a frame from the middle of a change, but at two samples per second a slow
  cross-fade that plateaus can hold still long enough to be emitted washed out. The clean
  state is captured too, so this is surplus, not loss.
- **The detect stage costs ~6 % of the video's duration.** For the runtime question still
  open on the map, decode is the whole of it: the analysis itself is 0.56 ms per sample.

## What this decision does not decide

- Which of the surplus images get deleted, and by whom
  ([#21](https://github.com/henricos/extract-slides/issues/21)).
- The crop, and the second duplicate pass that runs after it
  ([#12](https://github.com/henricos/extract-slides/issues/12)).
- The manifest that records a capture's timestamp and survives deletion
  ([#14](https://github.com/henricos/extract-slides/issues/14)).
- Whether any constant here becomes a CLI flag. The prototype exposes all six; the
  production surface is [ADR 0002](0002-cli-surface.md)'s business.

## The prototype

Branch [`prototype/pass1-detect`](https://github.com/henricos/extract-slides/tree/prototype/pass1-detect),
`prototypes/pass1-detect/pass1.py`. Throwaway, as ADR 0004 requires of spikes in this map:
it is evidence for this decision, not the start of the implementation.
