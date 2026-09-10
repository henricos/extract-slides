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

> **Amended.** This section is superseded in four ways — the comparison is global rather
> than against the previous frame, it is judged on information rather than pixels, covering
> takes precedence over adding, and a distant return after other slides is a repeat rather
> than a gap. See [Amendments](#amendments) below; do not apply the pixel test literally.

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

> **Amended.** The schema below is superseded: `layout_segments` is replaced by a rectangle
> per expected slide, and a `repeats` list is added. See
> [The amended ground-truth format](#the-amended-ground-truth-format) below.

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

> **Amended.** The cost estimate is wrong and the unit changed: rectangles are labelled per
> expected slide, roughly 40 per video, and the segment model does not survive a
> vision-mixed talk. See decision 4 in [Amendments](#amendments).

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

## Amendments

### 2026-09-11 — Expected slides are deduped on information, not on adjacent frames

From [#18](https://github.com/henricos/extract-slides/issues/18). Hand-labelling the six
sweep fixtures for [#10](https://github.com/henricos/extract-slides/issues/10) hit six
cases the rule above does not decide, four of which change what the *score* means. This
amendment revises the decision; it is not a correction of a consequence.

Each decision below records **why** and **what was rejected**, because the reason is the
part a future reader needs. Reading a rule and reconstructing a plausible-but-wrong
motive for it is the failure mode this section exists to prevent.

#### 1. An expected slide is deduped against every earlier expected slide, not just the previous frame

**Decision.** An expected slide is a maximal accumulation run whose final content is **not
already contained in the content of an earlier expected slide**, compared over the whole
video. A run that only replays or revisits content already expected is not a new expected
slide; it is recorded as a `repeats` entry (decision 7).

**Why.** The rule above is deliberately local — "does the later frame contain everything
the earlier frame had?" — and locality is what breaks. In `pJc0l2DASpo` the presenter
builds the "build outs" diagram from an empty header to a full diagram (364 → 374 s), then
**rebuilds the same diagram from the same empty header** (396 → 438 s), ending in the same
final state. Read locally, the second pass is a second expected slide, so a tool that
captured the first is charged a **miss** — the metric's most expensive error — having
captured every pixel of information the deck contains. `2AWv_nIfp-U` does the same in a
loop, dozens of times, with an animated sampling diagram.

The map's standing preference is recall over precision. The point of that preference is
never to lose *information*; charging a miss for information already captured inverts it.
So the unit of recall is the information, not the frame.

**Rejected: keeping the local rule and accepting the extra expected slides.** It would
push [#11](https://github.com/henricos/extract-slides/issues/11) to capture every replay
of every animation to avoid misses, which is the opposite of the deliverable — and the
duplicates it would generate are counted anyway, so the spike would be optimising against
a metric nobody wants satisfied.

#### 2. A slide that returns after other slides is a repeat, not one slide with a gap

**Decision.** `offscreen` is for gaps **inside** a slide's own life, when the slide is not
visible and **no other expected slide appeared** in the gap — the camera cut to the
speaker and came back. A slide that reappears **after other expected slides** is a
`repeats` entry instead.

**Why.** Two reasons, and the second is the load-bearing one. First: in `pJc0l2DASpo` the
title card returns unchanged at 510.7 s after appearing at 0.0 s. Written as one slide
with a gap that reads `from_s: 0.0, to_s: 527.2` with `offscreen: [[24.8, 509.1]]` — an
interval that contains every other slide in the video. Second: the `slides` list then
stops being orderable in time, and the timestamp match in the metric above depends on
intervals being disjoint to be unambiguous. The original example in this ADR uses
`offscreen` for a seven-second cut-away; it was never contemplated for a return eight
minutes and twenty slides later.

The test between the two is mechanical, which is the point: **did another expected slide
appear in the gap?** If yes it is a repeat, if no it is `offscreen`.

**Rejected: dropping `offscreen` entirely** and making every gap a repeat. The cut-away
case is genuinely one slide interrupted, and collapsing it into a repeat would lose the
distinction the crop and pairing stages need — a capture during a cut-away is spurious,
which is a different fact from a capture during a revisit.

#### 3. Covering wins over adding

**Decision.** A step that covers, dims or removes anything starts a new expected slide,
**even if the same step also adds** content.

**Why.** The rule above ends a run when content is "replaced, covered or removed" and
names highlight-then-different-highlight as two slides, but says nothing about a step that
does both at once — and real decks do both at once. `pJc0l2DASpo` at 85.6 → 101.6 s dims
part of a thumbnail grid *and* adds a subtitle in one step. Given the precedence, the
mechanical test already answers it: what was dimmed is no longer legible, so the later
frame does **not** contain what the earlier frame had, so the run ends. Without the
precedence stated, two labellers reading the same rule reach opposite answers on the same
frame, which is exactly the condition this ADR calls unmeasurable.

The accepted cost is visible and was accepted knowingly: the walking highlight at
310.4 → 333.1 s turns one authored slide into five expected slides, because each step
dims what the previous step showed. Capturing only the last is a miss under decision 1 as
well, since the last does not contain the earlier states.

**Rejected: adding wins, so a dim-and-add step continues the run.** It reads more
forgiving, but it silently loses the highlight sequence — the tool would be scored correct
having recorded only the final state, in which everything the presenter walked through is
greyed out. That is information loss scored as success.

#### 4. One slide rectangle per expected slide, not per layout segment

**Decision.** `layout_segments` is removed. Each expected slide carries its own
`slide_rect`, plus `rect_holds_s` (decision 8).

**Why.** A layout segment was only ever a compression device — the crop research's
"compute the region once per layout-stable segment" — and this ADR budgeted "roughly 12 to
15 layout-stable segments between them" for the six fixtures on that basis. The premise
does not survive a vision-mixed talk. `YBH8rQv4aTQ` alternates three shot types every few
seconds: the full-frame slide feed (24.6 s), a wide stage shot with the slide keystoned on
a screen behind the speaker (404.7 → 409.2 s), and a speaker close-up with no slide at all
(398.7 s). That is dozens of segments on one video, not two or three. (`b9dBJnQ_kpo`
confirms mid-video layout change is real — auditorium-wide at 72 s, speaker-left /
slide-right at 182 s — but there the segment model does fit.)

The metric does not need segments. It needs a rectangle for **each thing it scores**, and
what it scores is an expected slide.

**Rejected: keeping segments and labelling dozens of them.** It multiplies the hand-drawn
rectangles — the one thing this ADR decided must never be machine-proposed — with no gain,
since the crop metric never consults a segment the tool did not capture from. Note the
labelling cost moves from ~2–4 rectangles per video to ~40, which is only affordable
because the review instrument offers "same rectangle as the previous slide"; the real cost
is the number of *distinct* rectangles, which is small.

#### 5. The authoring tool's canvas is slide content

**Decision.** Frames where the presenter is showing the deck inside an authoring
application are expected slides, with the rectangle drawn around the **slide canvas**, not
the application window. Annotations drawn on the canvas are additive content on the same
slide.

**Why.** `pJc0l2DASpo` spends 446.9 → 462.4 s in the PowerPoint window — ribbon, thumbnail
rail, canvas — and the presenter draws annotation circles on the slide. `docs/reference-set.md`
rejected three *candidates* for being editor screencasts, which is a statement about what
makes a useful fixture, not about what counts as a slide. The deliverable is a record of
the slide's information, and there the presenter is showing slide content; the rectangle
around the canvas is literally the `C2b` crop case.

**Rejected: treating those frames as non-slide.** It would make the fixture's ground truth
depend on the *application* a presenter happens to be showing rather than on what is on
screen, and the same argument would exclude a slide shown inside a browser or a PDF
reader.

#### 6. Content is compared as information, and the pixel-subset test is a heuristic

**Decision.** "Contains everything the earlier had" is judged on **information**, by eye.
The pixel-subset test stated in the original decision is demoted to a labelling heuristic
for the common case, not the definition.

**Why.** Decision 1 already moved the unit of recall from frames to information; this
states the consequence rather than leaving it to be discovered. It has to be stated because
the two readings disagree on real frames: the "build outs" slide inside the PowerPoint
canvas (decision 5) is the same *information* as the full-frame version captured earlier,
but in pixels it is not a subset of anything — different scale, different surroundings.
Same in `YBH8rQv4aTQ`, where a slide appears keystoned on the stage screen and later as a
full-frame cut.

**The cost is real and is accepted knowingly:** this ADR originally valued the mechanical
test precisely because it is "far more consistent to apply by hand". Decision 1 traded
that away. Saying so plainly is better than leaving a pixel test in place that no longer
defines the rule, because a future reader who finds the pixel test and applies it literally
will produce ground truth that contradicts the metric.

**Rejected: deduping only within a shot type**, keeping the pixel test exact. It is
mechanical, but it charges a miss for the PowerPoint-canvas revisit and for every
full-frame cut of a slide already seen on the stage screen — decision 1's failure mode,
reintroduced.

#### 7. Repeats are a sibling list, not a field on a slide

**Decision.** A new top-level `repeats` list: `[{of_n, from_s, to_s, note}]`.

**Why.** Under decision 1 a replay is not an expected slide, but the matcher still has to
know the window exists — otherwise a capture there falls in no expected slide's interval
and is scored **spurious**, which is wrong twice over: the tool captured a real slide, and
it may be the only capture it made of that slide. A sibling list keeps `slides` clean and
orderable in time, which is what decision 2 set out to protect.

**Rejected: a field inside the slide entry.** A repeat has an interval of its own and one
slide can have several, so it would have to be a list of intervals inside a slide — which
is `offscreen`'s shape and would be confused with it, given that decision 2 turns on
telling those two apart.

#### 8. A rectangle is scored only where it holds

**Decision.** Each slide carries `rect_holds_s: [from_s, to_s]`, the interval over which
its `slide_rect` is valid. A capture outside that interval is scored on the slide metric
normally and **excluded from the crop metric**, reported separately and never ranked.

**Why.** Decision 4 draws each rectangle on one specific frame. If a tool captures that
slide from a different shot — the wide stage shot rather than the full-frame cut — the
labelled rectangle simply does not describe that frame, and scoring the crop against it
would be measuring nothing. Excluding it is right on the merits, not just convenient: on a
vision-mixed talk, capturing from the wide shot when a full-frame cut exists is a
**detection** choice, and the crop metric should neither reward nor punish it.

`rect_holds_s` is the "layout-stable segment" idea reduced to the scope of one slide, where
it costs one interval instead of a partition of the whole video.

**Rejected: a rectangle per shot type.** That is exactly the cost decision 4 removed, and
it would require labelling shot boundaries across the whole video — including stretches
containing no slide at all, which nothing scores.

### What the amended metric matches

Restated in full, because four of the eight decisions touch it:

- A capture **matches** expected slide *n* if its timestamp falls in
  `[complete_from_s, to_s]` minus any `offscreen` gap, or inside a `repeats` window whose
  `of_n` is *n*.
- **miss** — expected slide *n* has no matching capture anywhere, its repeats included.
- **duplicate** — more than one capture matches slide *n*.
- **half-built hit** — a capture in `[from_s, complete_from_s)`: the slide was on screen
  but not yet complete, which is where a cross-fade frame and a mid-animation grab land.
  Counted with spurious and duplicates at the second level, never as a match.
- **spurious** — a capture matching nothing, including one inside an `offscreen` gap.

Ranking is unchanged: lexicographic on misses, then on
`spurious + duplicates + half-built hits`. Timing deviation is still reported and never
ranked.

The half-built category is what closes the sixth case from #18. `pJc0l2DASpo` state 012
(73.6 s) holds the outgoing slide with the incoming header ghosted over it; before this
amendment its timestamp fell inside the outgoing slide's interval, so a tool exporting that
frame scored a clean hit. `docs/research/slide-change-detection.md` §10 records half-faded
export as the one failure four independent systems each fix, and the metric could not see
it. It needed no new field: `complete_from_s` already existed for exactly this purpose.

### The amended ground-truth format

```jsonc
{
  "video": "pJc0l2DASpo",
  "class": ["C1", "C3"],
  "role": "fixture",
  "duration_s": 527.17,
  "resolution": "852x480",

  // One entry per EXPECTED slide: an accumulation run whose content is not
  // already contained in an earlier entry. rect is [x, y, w, h] as normalised
  // floats, the same convention as the CLI's --roi flag (ADR 0001).
  "slides": [
    { "n": 1, "from_s": 0.0, "to_s": 24.8, "complete_from_s": 0.0,
      "slide_rect": [0.0, 0.0, 1.0, 1.0], "rect_holds_s": [0.0, 24.8],
      "note": "title card" },
    { "n": 2, "from_s": 24.8, "to_s": 47.73, "complete_from_s": 46.67,
      "slide_rect": [0.02, 0.05, 0.96, 0.9], "rect_holds_s": [24.8, 47.73],
      "offscreen": [[31.0, 33.4]],
      "note": "five-image additive build; camera cut away mid-slide" }
  ],

  // Windows where content already expected above comes back. Not expected
  // slides: a capture here matches `of_n`.
  "repeats": [
    { "of_n": 1, "from_s": 509.07, "to_s": 527.17,
      "note": "title card returns unchanged at the end" }
  ],

  "provenance": {
    "proposed_by": "tools/groundtruth/propose.py + human grouping",
    "verified_by": "<person>",
    "verified_at": "2026-09-11"
  }
}
```

`layout_segments` is gone (decision 4). `offscreen` survives with the narrowed meaning from
decision 2. Everything else keeps the meaning stated earlier in this ADR.

### Consequences of the amendment

- **[#10](https://github.com/henricos/extract-slides/issues/10)'s spec changed** while it
  was in progress: grouping is now global over the video rather than a single pass over
  adjacent states, and rectangles are per slide rather than per segment. The machine
  proposal in `ground-truth/proposals/` is unaffected — it emits *states* and takes no
  position on what a slide is, which is why it survived the change.
- **[#11](https://github.com/henricos/extract-slides/issues/11) must not be tuned to
  capture replays.** Under decision 1 a replayed build is a duplicate at worst, never a
  miss, so a detector that fires once per animation loop is losing on the second level for
  nothing. The over-capture-then-reduce strategy this ADR already permits is still fine;
  what changed is that recall is now measured over information, so reducing across the
  whole video is not just permitted, it is what the metric rewards.
- **[#12](https://github.com/henricos/extract-slides/issues/12) scores fewer captures than
  it produces.** Decision 8 excludes any capture taken outside its slide's `rect_holds_s`
  from the crop metric. On the vision-mixed fixture that may exclude a lot, and the count
  of excluded captures should be reported alongside the score, not hidden.
- **[#17](https://github.com/henricos/extract-slides/issues/17) gains a fixture it did not
  have.** Decision 5 makes the PowerPoint-window frames in `pJc0l2DASpo` expected slides,
  which turns that stretch into a real test for the slide-frame gate — a frame that is
  mostly application chrome and must still be recognised as carrying slide content.
- **The half-built category needs no new field in the manifest**, only the source
  timestamp already required above.
