# Correctness is ranked on misses; everything else is counted, not classified

- **Status:** accepted
- **Date:** 2026-09-12 (rewritten; see [History](#history-what-was-tried-and-dropped))
- **Tickets:** [#9 — Correctness metric and ground-truth format](https://github.com/henricos/extract-slides/issues/9),
  [#18 — What counts as one slide, part two](https://github.com/henricos/extract-slides/issues/18)

## Decision

### What the ground truth records

**Required contents, and nothing else.** For each distinct piece of slide content that
must appear in the output at least once: the window or windows in which a capture of it
counts, and the slide rectangle.

The question a labeller asks, once per visually distinct state, is:

> **Would I be unhappy if the output never showed this?**

If yes, it is a required content and gets a window. If no, it is not recorded at all, and
a capture there is surplus. That is the whole labelling rule.

A capture window **opens when the content is complete**, not when it starts appearing. A
five-bullet build has one window, opening at the last bullet. This is the one piece of
build-awareness the metric keeps, and it pays for itself: without it, a tool that grabbed
the slide half-built and never came back would score as correct while having lost the
content.

### The slide metric

**Primary, and the only thing that declares a winner: misses.** A miss is a required
content with no capture inside any of its windows. Silent damage.

**Secondary, a tiebreak only: surplus.** Every capture that matches no required content.
Counted, **never classified** — the metric does not care whether a surplus capture is a
duplicate, a replay, a cross-fade frame or a shot of the speaker, because all four cost
the operator the same single keystroke.

**Reported and never ranked:** timing deviation, median and p99 of the distance from each
matching capture to the start of its window.

Losing is grave; surplus is cheap. The ordering says exactly that and nothing more.

### Why capturing generously is the intended behaviour, not a tolerated accident

[ADR 0002](0002-cli-surface.md) ships `extract-slides drop DIR N...` — delete, renumber,
rewrite the manifest, and with it the generated `presentation.md`. Surplus is one command
away from gone, and removing it re-derives the slide-to-speech mapping. A detector should
therefore be tuned to over-capture, and this metric is built so that doing so costs
almost nothing.

### The crop metric

Unchanged, and the reasoning behind it still holds:

**Primary, binary:** does the crop contain 100% of the slide's content rectangle? Cutting
any slide content fails, with no partial credit.

**Secondary, among the crops that pass:** the fraction of the crop that is not slide. The
full frame passes the primary and comes last on the secondary, which is what makes the
crop stage prove it is worth having.

**Overlay is not penalised.** Where a webcam or a screen-share thumbnail overlaps the
slide, that area counts as slide area. The deliverable is a record of the slide's
information, not a re-presentable deck, so overlap is acceptable and cutting content to
remove it is not. `docs/research/slide-region-crop.md` established that no axis-aligned
crop can remove an overlapping overlay without cutting content, so a metric that penalised
the overlay would drive the crop spike to optimise for the wrong thing. **IoU was rejected**
for exactly that reason.

**Only captures that match a required content are crop-scored.** A surplus capture has no
rectangle to be scored against, and inventing one would mean labelling frames the metric
has already decided it does not care about.

### Ground truth: format and location

One file per reference video, `ground-truth/<video-id>.json`, versioned in the repo. JSON
at indent 2, matching the manifest's format, so it diffs per line and needs no new
dependency. Not in the cache: the cache holds immutable downloaded **inputs** and is not
versioned, while ground truth is hand-verified and precious.

```jsonc
{
  "video": "pJc0l2DASpo",
  "class": ["C1", "C3"],
  "role": "fixture",                  // or "target"
  "duration_s": 527.17,
  "resolution": "852x480",

  // One entry per REQUIRED content. rect is [x, y, w, h] as normalised floats,
  // the same convention as the CLI's --roi flag (ADR 0001).
  "required": [
    { "n": 1, "windows": [[0.0, 24.8]],
      "slide_rect": [0.0, 0.0, 1.0, 1.0], "note": "title card" },
    { "n": 2, "windows": [[46.13, 48.0]],
      "slide_rect": [0.0, 0.0, 1.0, 1.0], "note": "five-image build, complete at 46.13" }
  ],

  "provenance": {
    "proposed_by": "<method, deliberately not one of the spike shortlists>",
    "verified_by": "<person>",
    "verified_at": "2026-09-12"
  }
}
```

- `windows` — the intervals in which a capture of this content counts, each opening when
  the content is complete. **Usually one.** A content that leaves and comes back unchanged
  gets a second window rather than a second entry, which is all the machinery a returning
  slide needs.
- Windows may leave gaps in the timeline, and that is the point: a capture in a gap is
  surplus, and surplus is not labelled.

### How much ground truth

**Full labelling on all six sweep fixtures**, machine-proposed and human-verified. The
operator answers one binary question per candidate state rather than marking transitions
from scratch; the human signature is what makes it ground truth.

**The proposal must come from a method deliberately different from the spike shortlists**
in `docs/research/slide-change-detection.md` §10, or the ground truth is biased toward
whichever candidate a spike is about to measure. Dense frame sampling with pairwise
comparison is acceptable; reusing the shortlist's block-wise MAD, pHash or SSIM
configuration is not. `tools/groundtruth/METHOD.md` records what was built and measured.

**Slide rectangles are labelled by a human, never proposed.**
`docs/research/slide-region-crop.md` measured a multimodal model asked for crop
coordinates deviating badly, so coordinates are the one thing not worth proposing.

## Consequences

- **[#11](https://github.com/henricos/extract-slides/issues/11) should be tuned to
  over-capture.** Firing twice on an animation costs one surplus; missing a slide loses the
  comparison outright. A detector that fires once per animation loop is not penalised
  beyond the tiebreak.
- **[#12](https://github.com/henricos/extract-slides/issues/12) scores fewer captures than
  it produces**, since surplus captures are not crop-scored. Report how many were excluded
  alongside the score.
- **The manifest must record each capture's source timestamp**, since matching is by
  timestamp. A hard requirement on
  [#14](https://github.com/henricos/extract-slides/issues/14).
- **The tool may over-capture internally and reduce before finishing.** Still legitimate,
  and now clearly rewarded rather than merely permitted.
- **Reconstructing animations is out of scope**, which is what lets a build collapse to one
  window.

## What this decision does not decide

- Which detection metric or crop method wins (#11, #12, #17).
- The pairing rule between a slide and the speech said over it (#14). This ADR only makes
  it measurable, by requiring a window per required content.
- Whether an AI pass should do the duplicate elimination that `drop` does by hand. Still
  fog on the map, and it only becomes specifiable once #11 says how much surplus there
  actually is.

## History: what was tried and dropped

Two earlier versions of this decision were more elaborate, and the reason they were
dropped matters more than their contents — without it, someone will rebuild them.

**Version 1 ([#9](https://github.com/henricos/extract-slides/issues/9), 2026-09-11)**
defined a slide as a maximal run of frames in which content only accumulates, with a
mechanical pixel-subset test, and matched captures by timestamp into *miss*, *duplicate*
and *spurious*.

**Version 2 ([#18](https://github.com/henricos/extract-slides/issues/18), 2026-09-11)**
added eight decisions on top: global dedupe over information rather than adjacent frames,
a `repeats` list for content that returns, a narrowed `offscreen`, a *half-built hit*
category, a covering-wins-over-adding precedence, per-slide `rect_holds_s`, and a demotion
of the pixel test to a heuristic.

**Both were dropped after labelling the first fixture measured their cost.** Of 64
candidate states in `pJc0l2DASpo`, **21 were spent adjudicating cases where both possible
answers put the capture in the output**: an animation replaying in different colours, a
build replaying from empty, the same slide seen inside the PowerPoint window, a title card
returning unchanged, a highlight walking down a diagram. In every one, the classification
changed only what the score *called* the capture — never whether the tool produced it, and
never anything the operator could not remove with one `drop`.

Three things made that machinery not worth its price:

1. **It only ever affected the second rank.** Misses declare the winner; the classification
   of surplus never does. A taxonomy that cannot change the outcome is not a metric, it is
   bookkeeping.
2. **The product already answers it.** `drop` was decided in ADR 0002 before any of this
   was written. Building a metric that treats classifying surplus as a research problem,
   while the CLI treats it as a keystroke, was incoherent.
3. **It was not reliably applicable by hand**, which this ADR's own test rules out. The
   labeller and the model disagreed on 21 of 64 states, and the disagreements clustered
   exactly on the cases the added rules were written to settle.

**What would bring it back:** a need to *diagnose* surplus rather than count it — for
example if a spike's output were unusable in practice despite scoring zero misses, and the
shape of its surplus were the thing to fix. That is a real possibility, and the answer then
is to classify surplus **in the spike's report**, not in the ground truth, so the labelling
cost stays at zero.
