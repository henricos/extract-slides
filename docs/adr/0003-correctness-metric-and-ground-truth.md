# Correctness is ranked lexicographically on misses, then on everything droppable

- **Status:** accepted
- **Date:** 2026-09-11
- **Ticket:** [#9 — Correctness metric and ground-truth format](https://github.com/henricos/extract-slides/issues/9)

## Decision

### What counts as one slide

> A slide is a **maximal run of frames in which content only accumulates**. The expected
> capture is the last frame of that run. The run ends when content is **replaced, covered
> or removed** — and then the states before and after are two distinct expected slides.

So a five-bullet additive build is **one** expected slide, captured at its final state.
But a slide where a diagram element is highlighted and then a different one is
highlighted, or where something is covered by an overlay that arrives later, is **two or
more** expected slides, even though the original deck had one.

The test a labeller applies is mechanical: *does the later frame contain everything the
earlier frame had?* If yes, the earlier is redundant. If no, both are needed. That is far
more consistent to apply by hand than "is this the same slide?".

A slide that **leaves the screen and returns unchanged** is still one slide, with a gap in
its visibility. Returning **changed** starts a new slide, by the rule above.

### The slide metric: two levels

**Primary, and the only thing that declares a winner** — lexicographic on:

1. **misses** — an expected slide with no capture. Silent damage, decides everything.
2. **spurious + duplicates** — everything the operator can see and delete.

**Secondary, reported and never used to rank**: timing deviation. Median and p99 of the
distance from each matched capture to the window in which that slide was complete.

No F-measure, no pair of thresholds. A single miss loses to any number of duplicates,
which is the map's standing recall-over-precision preference stated as an ordering.

**Matching is by timestamp.** The manifest records the source timestamp of every capture,
so a capture matches the expected slide whose interval contains it. From that:

- **miss** — an expected slide with no capture in its interval.
- **duplicate** — an expected slide with more than one.
- **spurious** — a capture whose timestamp falls in no expected slide's interval, e.g. a
  frame grabbed while the camera had cut to the speaker.

Spurious and duplicate are counted separately for diagnosis but ranked together, because
both are visible and cheap to drop. Timing deviation is zero for any capture that lands
inside the slide's complete window.

### The crop metric: two levels, same shape

**Primary, binary and unforgiving**: does the crop contain **100% of the slide's content
rectangle**? Cutting any slide content fails, with no partial credit.

**Secondary, among the crops that pass**: the fraction of the crop that is not slide.
The full frame passes the primary and comes last on the secondary, which is precisely what
makes the crop stage prove it is worth having.

**Overlay is not penalised.** Where the presenter's webcam or a screen-share thumbnail
overlaps the slide, that area counts as slide area. This follows the scoping decision that
the deliverable is a *record of the slide's information*, not a re-presentable deck, so
overlap is acceptable and cutting content to remove it is not. `docs/research/slide-region-crop.md`
established that no axis-aligned crop can remove an overlapping overlay without cutting
content, so any metric that penalised the overlay would drive the crop spike to optimise
for the wrong thing.

**IoU was rejected** for exactly that reason: it punishes keeping the overlay.

### Ground truth: format and location

One file per reference video, `ground-truth/<video-id>.json`, versioned in the repo.
JSON at indent 2, matching the manifest's format, so it diffs per line and needs no new
dependency. Not in the cache: the cache holds immutable downloaded **inputs** and is not
versioned, while ground truth is hand-verified and precious.

```jsonc
{
  "video": "pJc0l2DASpo",
  "class": ["C1", "C3"],
  "role": "fixture",                  // or "target"
  "duration_s": 527,
  "resolution": "854x480",

  // One entry per layout-stable segment. rect is [x, y, w, h] as normalised
  // floats, the same convention as the CLI's --roi flag (ADR 0001).
  "layout_segments": [
    { "from_s": 0.0, "to_s": 527.0, "slide_rect": [0.0, 0.0, 1.0, 1.0],
      "note": "full frame, no speaker" }
  ],

  // One entry per EXPECTED slide, i.e. per accumulation run.
  "slides": [
    { "n": 1, "from_s": 4.2, "to_s": 31.8, "complete_from_s": 4.2, "note": "" },
    { "n": 2, "from_s": 31.8, "to_s": 74.0, "complete_from_s": 68.5,
      "offscreen": [[52.0, 59.5]],
      "note": "three-step build; camera cut away mid-slide" }
  ],

  "provenance": {
    "proposed_by": "<method, deliberately not one of the spike shortlists>",
    "verified_by": "<person>",
    "verified_at": "2026-09-11"
  }
}
```

- `from_s` / `to_s` — the slide's whole life, gaps included.
- `complete_from_s` — the earliest instant at which a capture would contain **all** of
  that slide's content. Equal to `from_s` for a slide that is not a build. This is the
  field the timing metric measures against, and it is what makes the build rule
  computable rather than a matter of opinion.
- `offscreen` — optional, the intervals during which the slide was not on screen. A
  capture inside one of these is spurious, not a duplicate.

### How much ground truth

**Full transition labelling on all six sweep fixtures**, machine-proposed and
human-verified. The operator reviews a proposal instead of marking 60 to 140 transitions
from scratch; the human signature at the end is what makes it ground truth.

**The proposal must come from a method deliberately different from the spike shortlists**
in `docs/research/slide-change-detection.md` §10. Proposing transitions with the same
metric family a spike will be measured against biases the ground truth in that spike's
favour. Dense frame sampling with pairwise comparison is acceptable; reusing the
shortlist's block-wise MAD, pHash or SSIM configuration is not.

**Slide-content rectangles are labelled by a human, not proposed.**
`docs/research/slide-region-crop.md` measured a multimodal model asked for crop
coordinates deviating badly, so coordinates are the one thing not worth proposing. The
cost is small: the six fixtures have roughly 12 to 15 layout-stable segments between them.

## Consequences

- **[#10](https://github.com/henricos/extract-slides/issues/10) has its spec**: produce
  `ground-truth/<id>.json` for the six sweep fixtures, machine-proposed, human-verified,
  rectangles by hand.
- **[#11](https://github.com/henricos/extract-slides/issues/11) and
  [#12](https://github.com/henricos/extract-slides/issues/12) have their scoreboard**, and
  neither can declare a winner on a number this ADR does not define.
- **The manifest must record each capture's source timestamp.** The slide metric matches
  by timestamp, so this is now a hard requirement on
  [#14](https://github.com/henricos/extract-slides/issues/14), not a nice-to-have.
- **The tool may over-capture internally and reduce before finishing.** Capturing every
  intermediate state and discarding the ones that a later frame supersedes is a legitimate
  strategy, and it is the recall-first principle applied inside the pipeline. It is
  [#11](https://github.com/henricos/extract-slides/issues/11)'s choice; this metric judges
  only the final output.
- **Reconstructing animations is out of scope**, which is what lets the build rule collapse
  an additive build to its final state at no cost.

## What this decision does not decide

- Which detection metric or crop method wins (#11, #12, #17).
- The pairing rule between a slide and the speech said over it (#14). This ADR only makes
  it measurable, by requiring per-slide intervals in the ground truth.
- What `review` renders. Still fog on the map.
