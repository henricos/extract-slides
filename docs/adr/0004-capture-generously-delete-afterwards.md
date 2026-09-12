# Capture generously in one pass, delete in a second

- **Status:** accepted
- **Date:** 2026-09-12
- **Supersedes:** [ADR 0003](0003-correctness-metric-and-ground-truth.md)
- **Tickets:** [#11](https://github.com/henricos/extract-slides/issues/11),
  [#21](https://github.com/henricos/extract-slides/issues/21)

## Decision

The tool works in **two passes**, and only the first one is automatic.

**Pass 1 — simple and coarse.** Capture the screens on its own, and discard only the
duplicates that are *easy* to detect. Leaving too much is the expected outcome, not a
tolerated one. The single failure this pass must avoid is **losing a capture**.

**Pass 2 — deletion.** The excess is removed afterwards: by the operator, with
`extract-slides drop` ([ADR 0002](0002-cli-surface.md)), or by an AI pass that deletes for
him. That decision is [#21](https://github.com/henricos/extract-slides/issues/21); either
way it operates on the ~100 images pass 1 produced, not on the ~20,000 frames of a video.

## What this decision removes

**There is no ground truth, no correctness metric, and no ranked comparison of detector
candidates.** [ADR 0003](0003-correctness-metric-and-ground-truth.md) is superseded in
full, `ground-truth/` and `tools/groundtruth/` are deleted, and no stage is specified as
"measured against" anything.

**There is no slide-frame gate.** A frame that is not a slide is excess, and excess is
what pass 2 exists for. Gating it in pass 1 can only lose captures.

## Why

The superseded path asked the operator to **codify his judgement into a file** so that
algorithms could be built to reproduce it, and then to rank candidates against it. Two
things were wrong with that, and neither is about the metric's design:

1. **It optimises for the wrong quantity.** The only outcome that costs anything is a
   lost capture. Everything else costs one deletion. A machinery that spends its effort
   deciding *what to call* a surplus capture is spending it where nothing is at stake —
   ADR 0003's own History section had already measured this, and dropped two versions of
   the taxonomy for exactly that reason. This ADR finishes the same movement rather than
   starting a new one.
2. **The labelling is the expensive part, and it is the operator's time.** Producing the
   ground truth was a manual pass over every candidate state of every fixture, done by
   hand, in order to buy a number that only ever chose between candidates. Skipping the
   choice makes the labelling unnecessary; the shortlist's leading candidate, tuned to
   over-capture, is good enough for a pass whose only requirement is not to lose anything.

## How we know pass 1 is not losing captures

By watching a video and comparing it against what came out. That is the whole protocol.
It needs no file format, no labelling session and no scoring script. The six sweep
fixtures in [`docs/reference-set.md`](../reference-set.md) stay for this, as material to
look at — they are no longer a measured reference set.

If pass 1 ever *does* look like it is losing captures, the fix is to capture more, not to
build an instrument that proves it.

## Consequences

- **[#11](https://github.com/henricos/extract-slides/issues/11) builds pass 1**, it does
  not compare candidates. `docs/research/reference-implementations.md` and
  `docs/research/slide-change-detection.md` still supply the techniques; they now say
  *what to use*, not *what to measure against each other*.
- **[#12](https://github.com/henricos/extract-slides/issues/12) keeps the crop stage**
  (it is a requirement in [`docs/idea.md`](../idea.md)) with the same rule applied to it:
  never cut slide content, fall back to the full frame when unsure, do not optimise how
  little non-slide is kept.
- **[#14](https://github.com/henricos/extract-slides/issues/14) must make deletion cheap.**
  The manifest has to survive images being removed and renumbered, and re-derive the
  slide-to-speech mapping when they are. This is a firmer requirement than before, because
  deletion is now a designed step rather than an escape hatch.
- **Nothing in the pipeline gets a threshold tuned against a score.** Where a constant has
  to be chosen, it is chosen toward over-capture.

## What this decision does not decide

- How pass 1 detects a change, or which duplicates count as "easy" to discard (#11).
- Whether pass 2 is manual, AI, or both ([#21](https://github.com/henricos/extract-slides/issues/21)).
- The crop strategy (#12).
