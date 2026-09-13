# The crop cuts the presenter away, and nothing else

- **Status:** accepted
- **Date:** 2026-09-12
- **Ticket:** [#12 — Crop to the slide region without ever cutting content](https://github.com/henricos/extract-slides/issues/12)
- **Implements:** [ADR 0004](0004-capture-generously-delete-afterwards.md)

## Decision

The crop stage **starts from the whole frame and removes only what the presenter
occupies.** It never tries to find the slide.

**The signal is time, in two resolutions.** Sampling the video twice a second, as pass 1
already does, separates three populations of pixels:

| population | between two samples ½ s apart | between two captures |
|---|---|---|
| chrome — branding, background, furniture | still | still |
| **slide** | still | changes |
| presenter — a speaker, a webcam tile, an embedded video | **moves** | moves |

A pixel that moves in more than **6 %** of consecutive samples is the presenter. A pixel
that changes by more than 45 grey levels in more than **8 %** of consecutive captures is
slide content.

**The region is computed once per layout.** A layout is a cluster of captures that agree
on at least **half** their pixels: two captures of the same composed layout share their
chrome, two captures either side of a layout change share nothing. A layout with fewer
than three captures gets no rectangle. This is what makes a mid-video layout change work
without a segmentation pass.

**A side is cut only when the presenter is on it.** Take the bounding box of the content
blobs (specks under 10 % of the largest one ignored). For each side, look at the strip
between the frame edge and that box: if **80 %** of a blob of continuous movement lies in
it, that side is cut, **halfway between the presenter's edge and the content's**. If not,
that side stays at the frame edge. The result is then grown outward by 1.5 %.

**The fallback chain has two steps, not four**: this rectangle, then the whole frame. A
layout that is too thin, that yields no content, or that produces a rectangle under 10 %
or over 98 % of the frame gets the whole frame. The stage never returns "no crop", and
`--no-crop` and `--roi` from [ADR 0002](0002-cli-surface.md) remain the operator's escape
hatches.

**The duplicate test runs again after the crop, and the later of two duplicates
survives.** Same 256-bit perceptual hash and same 0.02-of-bits threshold as
[ADR 0005](0005-pass-1-pinned-anchor-edge-signal-watchdog.md), applied to the cropped
images.

## Why

**Because "find the slide" has no safe answer, and "remove the presenter" does.** Every
attempt to locate the slide positively — by its border, by its aspect ratio, by where its
content is — cut real content on at least one fixture. Cutting away continuous movement
never did. The asymmetry is the whole decision: a slide is *defined* by being still
between changes, and there is nothing else in a talk recording that both moves
continuously and is worth keeping.

**The prior art's recipe was adopted, measured and rejected.**
`docs/research/reference-implementations.md` §B.7 read `AutoSlides-Extractor`'s
`AutoCropDetector` — 552 lines of tuned, `cv2`-only slide-bbox detection — and recommended
it as candidate 1.5, above plain letterbox removal, singling out its aspect prior as "a
strong, cheap prior". Reimplemented at its own constants and run on this project's
fixtures, it fails on exactly the two the crop stage exists for:

- On `jqpdveK2XAU` it returns **nothing on all 19 captures**. The dilated edge map merges
  the slide's border with its own text and with the surrounding conference chrome, so no
  contour survives the four-vertex and 0.85-fill gates.
- On `b9dBJnQ_kpo` it returns something worse than nothing. Its highest-scoring rectangle
  is `(12, 273, 940, 532)`: four vertices, fill 1.00, aspect **1.77**. That is the
  **speaker's video panel**. In a composed layout the webcam feed is a cleaner 16:9
  rectangle than the slide is, so **the aspect prior actively prefers the presenter** —
  and had this shipped, the crop would have thrown the slide away and kept the speaker.

This reproduces first-hand the one negative result the research had already recorded, from
`sumerene`'s own notes: *"meeting decorations (logos, title bars, separator lines) have
brightness/edge characteristics similar to PPT content, so they cannot be
distinguished."* It is now measured, on this project's own fixtures, against the best
implementation of that family in the field.

**Cropping to the content's bounding box is the trap inside the right idea.** The first
working version of the activity recipe did exactly that, and it sliced the title off every
slide of `pJc0l2DASpo` — because a header that is identical on every slide never registers
as content that changes. **Static slide furniture is indistinguishable from static chrome
by any temporal signal**, and no amount of tuning fixes that. The box can only ever say
how far a cut *could* go; the frame edge is where a side stays unless something is proven
to be in the way.

**Black-bar removal is not recall-safe, and the research's claim that it is "by
construction" is wrong.** `docs/research/slide-region-crop.md` §9 ranked it first precisely
because "it can only ever remove uniformly black margins". On `YBH8rQv4aTQ` — white text on
near-black slides — the inward walk hit its 10 % cap on all four sides of **77 of 78
images** and cut content out of four of them: the titles of the *Spacing*, *Learning
requires a productive struggle*, *Euphoria/Chatbot Journey* and mind-map slides. A
letterbox bar and a dark slide's margin are the same pixels, and a mean-brightness test
cannot tell them apart. Keeping a letterbox bar costs nothing under
[ADR 0004](0004-capture-generously-delete-afterwards.md); cutting a title costs
everything. The step is gone.

**The cut lands at the midpoint because both ends of that interval were tried.** Cutting at
the content's edge shaved the first letter off four titles on `b9dBJnQ_kpo`. Cutting at the
presenter's edge left a sliver of him in shot and weakened the second duplicate test —
`jqpdveK2XAU` went 19 → 13 instead of 19 → 9. The midpoint is the margin a person would
leave, and it costs nothing either way.

**The later duplicate survives because the earlier rule would delete the finished slide.**
Pass 1 keeps the first of a duplicate pair, which is right when it compares whole frames.
After the crop the test finally bites on a progressive build, and "keep the first" would
keep the half-built state and delete the complete one. That is content loss, the only
failure ADR 0004 says costs anything. A build's last state is the complete one, and a
camera cutting away and back returns an identical image either way, so "keep the later"
is never worse.

**No aspect-ratio gate.** It was the one piece of the prior art's recipe worth wanting, and
it is the piece that picked the webcam. A rectangle is accepted for what it excludes, not
for what shape it is.

## What this produced

Over the six sweep fixtures in [`docs/reference-set.md`](../reference-set.md), from the 241
images [ADR 0005](0005-pass-1-pinned-anchor-edge-signal-watchdog.md) produced:

| fixture | class | in → out | rectangle | outcome |
|---|---|---|---|---|
| `pJc0l2DASpo` | C1+C3 | 38 → 38 | full frame | no presenter in shot, nothing to cut |
| `jqpdveK2XAU` | C2b | 19 → 9 | 73 % of frame, cut right | speaker strip gone, 9 distinct slides |
| `b9dBJnQ_kpo` | C2b unstable | 31 → 17 | **3 layouts, 3 rectangles** | cuts bottom, bottom, left |
| `2AWv_nIfp-U` | C4 | 53 → 53 | full frame | corner webcam not cuttable without loss |
| `YBH8rQv4aTQ` | C5 | 78 → 78 | full frame | whole frame moves, no separable region |
| `X3uFwLj2u7Q` | C7 | 22 → 21 | full frame | screen filmed at an angle, no straight cut |

**241 images in, 216 out**, about 3 minutes of wall clock for 45m55 of video — one decode
pass at the same rate as pass 1.

**Verified the way ADR 0004 says to verify: by looking.** Every cut was checked against the
source frame side by side, and the operator reviewed the same pages and accepted the
result: *"pegar mais é melhor que pegar menos"*. Nothing was cut from a slide, and every
image the second duplicate test deleted was a repeat of a slide that survived.

Two observations came out of that review, neither of them a defect in this stage:

- **A moving camera that cuts to the audience is a half-failure and will stay one.**
  `YBH8rQv4aTQ` and `X3uFwLj2u7Q` are the cases; the full frame is the safe answer and the
  only one available. This is inherent to the input, not to the recipe. The operator also
  said he will rarely ask for that kind of video, which is worth knowing before anyone
  spends effort on those two classes: **C5 and C7 are the cheapest fixtures to disappoint.**
- **Some captures are mid-fade, almost entirely dark.** That is pass 1's doing, not the
  crop's, and [ADR 0005](0005-pass-1-pinned-anchor-edge-signal-watchdog.md) predicted it:
  at two samples a second a slow cross-fade can plateau long enough to be emitted washed
  out. The clean state is captured too, so it is surplus, and surplus is
  [#21](https://github.com/henricos/extract-slides/issues/21)'s business. Worth recording
  that the prediction was confirmed by eye rather than left theoretical.

The honest reading of that table is that **the crop fires on two of six fixtures and
declines on four**, and declining is the correct answer on all four: two have no presenter
to remove, one has a corner webcam that cannot be removed by a straight line without taking
slide with it, and one is a camera in an auditorium where nothing is separable. A stage
that does nothing four times out of six is not a weak stage; it is a stage that refuses to
guess.

## Consequences

- **The second duplicate test is where the deck actually shrinks.** 241 → 216 overall, and
  all but one of those come from the two fixtures that got a crop: `jqpdveK2XAU` 19 → 9 and
  `b9dBJnQ_kpo` 31 → 17. Pass 1's first test dropped 27 on `jqpdveK2XAU` and still kept the
  same slide five times over; after the crop it collapses correctly.
- **The crop stage needs the video, not only pass 1's images.** The movement map cannot be
  built from the captures alone — they are seconds or minutes apart. That is one extra
  decode pass at 2 samples/s, the same cost as detect, and it lands on
  [#14](https://github.com/henricos/extract-slides/issues/14) as a constraint on what the
  stage may assume is on disk when `extract-slides crop DIR` runs on its own.
- **A layout of fewer than three captures gets no rectangle.** Title cards, end cards and
  one-off interruptions come out as full frames, which is correct and also means a very
  short video may get no crop at all.
- **No AI, and the question of whether the crop needs it is closed.** The learned option
  measured in `docs/research/reference-implementations.md` §B.7.2 — a single-class YOLOv8
  at 89.6 ms/frame, shipped with no licence statement — is not needed. It was also trained
  to do the thing this ADR rejects: find the slide.
- **Perspective is not corrected.** `X3uFwLj2u7Q`'s screen is filmed at an angle and comes
  out as a full frame. Nobody in the field warps, and warping moves content pixels.

## What this decision does not decide

- Which of the 216 surviving images get deleted, and by whom
  ([#21](https://github.com/henricos/extract-slides/issues/21)).
- Whether the manifest records the rectangle and the rule that produced it, and what
  `crop DIR` may assume is still on disk ([#14](https://github.com/henricos/extract-slides/issues/14)).
- Whether any constant here becomes a CLI flag. The prototype exposes seven; the production
  surface is [ADR 0002](0002-cli-surface.md)'s business.

## The prototype

Branch [`prototype/crop`](https://github.com/henricos/extract-slides/tree/prototype/crop),
`prototypes/crop/crop.py`, with `--recipe panel` preserving the rejected prior-art recipe
so the comparison can be re-run. Throwaway, as ADR 0004 requires of spikes in this map: it
is evidence for this decision, not the start of the implementation.
