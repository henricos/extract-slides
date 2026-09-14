# The deletion pass: two ways to name the surplus, one way to apply it

- **Status:** accepted
- **Date:** 2026-09-14
- **Ticket:** [#21 — The deletion pass: by hand, or by AI?](https://github.com/henricos/extract-slides/issues/21)
- **Builds on:** [ADR 0004](0004-capture-generously-delete-afterwards.md) (pass 1 captures
  generously, pass 2 deletes), [ADR 0006](0006-crop-by-cutting-the-presenter-away.md) (the
  later of two duplicates survives)
- **Amends:** [ADR 0002](0002-cli-surface.md) — `review` is removed

## Decision

**Pass 2 is not an algorithm. It is two ways of producing a list of numbers, and one
procedure that applies it.**

The tool renders no review surface. The operator looks at `slides/` in a file manager,
which is already a contact sheet and already has a delete key.

```
extract-slides drop DIR 7 12 30    # delete those, then reconcile
extract-slides drop DIR            # reconcile what the operator already deleted on disk
extract-slides prune DIR           # the model lists what to cut; deletes nothing
extract-slides prune DIR --apply   # the model deletes, then reconciles
```

**Reconciliation** is one procedure, reached by every path above: re-read `slides/`,
renumber the survivors, print the old-to-new mapping, rewrite the manifest, regenerate
`presentation.md`. Deletion is real — no trash directory, no restore.

**The speech of a deleted slide merges forward**, into the next surviving slide; when
there is no next one, backward into the previous. The manifest side of this is
[#14](https://github.com/henricos/extract-slides/issues/14).

**The AI pass never fires on its own.** A key in the environment enables nothing; only an
explicit `prune` runs it. One request, images at **680 px** on the long edge, `claude-opus-5`
by default, overridable by environment variable. No loop, no tools, no agent framework.
Without a key the path is simply absent, and the tool says once how to enable it.

## Why

**Because the surplus is most of the output, not a rounding error.** Pass 1 plus the crop
emit **4.7 images per minute of video** across the six sweep fixtures — 216 images from
45 min 55 s, so a 45-minute talk arrives with about 210. Counted by eye on two of them,
the real deck is roughly a third of that: `pJc0l2DASpo` has 38 captures for some 13
slides, `2AWv_nIfp-U` has 53 for some 30. The ticket's premise of "~100 images" was half
the measured volume, and its framing of a deletion as "one keystroke" holds per image
while the pass as a whole is the largest single piece of work in using the tool.

**Because the operating scenario is a person, not an agent.** An earlier draft of this
decision leaned on the map's note that the CLI is shaped for an agent to install and
invoke, and concluded the AI should live outside the tool. That inverted a footnote into a
premise. The operator runs this himself; if the tool is to delete for him, the tool has to
contain the model.

**Because the file manager already is the review surface.** A contact sheet, an HTML
gallery and a keep/drop prompt loop were all on the table. The prompt loop is the worst
fit for what the surplus actually looks like: a progressive build is only judgeable
against its neighbours, and 210 sequential yes/no decisions is the wrong shape for a
question answered by scanning. A rendered gallery is better, and the operating system
ships one.

**Because a build's survivor comes last, so its orphans lie behind it.** "Merge into the
previous slide" was the intuitive answer and is wrong here.
[ADR 0006](0006-crop-by-cutting-the-presenter-away.md) keeps the *later* of two duplicates,
precisely so a build keeps its finished state. The captures deleted around it are
therefore the earlier, half-built ones, and the speech said over them is speech about the
slide that survives — which is ahead of them, not behind.

**Because no trash means no reason for numbering gaps.** `AutoSlides-Extractor` never
reflows its numbers, deliberately: the number is a stable identity for its trash metadata
and its timeline. With real deletion that argument has nothing to hold up, and
[ADR 0002](0002-cli-surface.md) already states that slide numbers are not stable
identities. A deck read by a human runs 1 to N. The old-to-new mapping is printed because
a second review round otherwise works from numbers that silently moved.

### Why 680 px, measured

The hardest pair found in the fixtures is `022`/`023` of `2AWv_nIfp-U`: two captures of
the same table, one row further along, differing in **0.62 % of pixels**. Downscaled
together and looked at:

| Long edge | Visual tokens/image | 210 images | Cost (Opus 5 input) | Difference visible |
|---|---|---|---|---|
| 240 px | 45 | 9k tokens | $0.05 | no |
| 340 px | 91 | 19k | $0.10 | marginal |
| 480 px | 180 | 38k | $0.19 | yes |
| 680 px | 350 | 74k | $0.37 | obvious |

The knee is 480. 680 is chosen because nothing else binds: 210 images at 680 px is 6.6 MB
base64 against a 32 MB per-request ceiling, and 74k visual tokens against a 1M context.
An image costs `⌈w/28⌉ × ⌈h/28⌉` visual tokens, so the whole talk fits in **one request** —
the API allows 600 images per request on 1M-context models, with a 2000 px per-side limit
above 20 images that 680 px passes comfortably. Where the constraint does not bite, buying
the minimum is a false economy.

This failure mode was observed before it was measured: reading a 320 px contact sheet of
this fixture, `008` and `009` were taken for the same image. They differ in 13.9 % of
pixels.

### Why one request and not an agent

The question put to the model is *"do these carry the same content"* — not *"where is the
slide"*, not *"when did it change"*. That is one vision call with a structured list of
numbers coming back. A loop would earn its place only by giving the model a tool to open a
capture at full resolution when a thumbnail will not decide; 680 px is chosen instead to
make that rare, and the loop stays available if the shipped default turns out to keep too
much. The cost of keeping one image too many is one keystroke — the same asymmetry
[ADR 0004](0004-capture-generously-delete-afterwards.md) rests on.

## Consequences

- **`review DIR` is removed from [ADR 0002](0002-cli-surface.md).** It existed to walk the
  flagged slides, and the file manager took its job. The map carried "what `review`
  renders" as fog since #3; the fog is cleared by deleting the command.
- **"Automatic by default" is deliberately weakened.** An unattended run now ends with
  ~210 images and no deletion, because an AI pass that fires merely because a key is
  present is not a choice the operator made. `prune --apply` is the unattended ending, and
  it is opt-in per invocation. This is a decision, not an oversight.
- **The safe mode is the one to start on.** `prune` without `--apply` writes the list; the
  operator reads it and runs `drop`. `--apply` exists for when that list has been trusted
  enough times.
- **[#14](https://github.com/henricos/extract-slides/issues/14) inherits two requirements**:
  the manifest must survive forward-merging a deleted slide's cues, and it must survive
  renumbering. Both are firmer than [ADR 0004](0004-capture-generously-delete-afterwards.md)
  left them, because the numbers now move on every pass.
- **`drop` is re-runnable and idempotent.** Review is expected to take more than one round.

## What this decision does not decide

- The manifest representation of a forward-merged cue, and what a reconciliation rewrites
  versus preserves ([#14](https://github.com/henricos/extract-slides/issues/14)).
- The prompt given to the model, and its structured output schema. Implementation.
- Whether `prune` ever gains a deterministic, key-free suggestion mode. The surplus does
  have a detectable shape — content that only accumulates across adjacent captures — but a
  deterministic rule that *deletes* is a rule that can lose a capture, and the taxonomy
  behind it is what [ADR 0003](0003-correctness-metric-and-ground-truth.md) dropped three
  times. Not ruled out; not needed to ship.

## Observations kept for later

**The survivor of a repeated run is not always the last one.** Raised by the operator
while settling the merge direction: where a slide recurs several times, the final
occurrence is not necessarily the one worth keeping. Judged rare enough to ignore, and
recorded here rather than designed around. If review keeps hitting it, the merge rule and
[ADR 0006](0006-crop-by-cutting-the-presenter-away.md)'s "later survives" are where to look.
