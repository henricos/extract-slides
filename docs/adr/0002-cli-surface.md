# The CLI surface: a stage pipeline behind a verbless default path

- **Status:** accepted
- **Date:** 2026-09-10
- **Ticket:** [#3 — Navigable CLI mock: subcommands, flags, output layout, messages](https://github.com/henricos/extract-slides/issues/3)

## Decision

```
extract-slides URL                 # default path: every stage, resuming
extract-slides URL --force         # ignore existing work, recompute

extract-slides fetch URL           # step 1: acquire + transcribe
extract-slides transcribe DIR      # redo the transcript, no re-download
extract-slides detect DIR          # redo detection; chains into crop and pair
extract-slides crop DIR            # redo the crop only
extract-slides pair DIR            # redo the pairing, rewrite the manifest
extract-slides drop DIR N...       # delete duplicates, renumber, rewrite
extract-slides review DIR          # walk the flagged slides
```

Stages: `acquire → transcribe → detect → crop → pair`.

Output directory, per video:

```
<slug>-<video-id>/
  manifest.json      machine contract (schema: issue #14)
  presentation.md    each slide's image + only the speech said over it
  transcript.md      the whole video, one document
  transcript.json
  slides/001.png …
```

## Why

Three structurally different surfaces were built as a navigable mock and driven by the
operator ([`prototype/cli-surface`](https://github.com/henricos/extract-slides/tree/prototype/cli-surface),
commit `5aa28c2`): task verbs (one shot), stage verbs (composable), and a run workspace
(stateful, resumable).

**The run workspace was ruled out.** It makes a run a first-class object with a lifecycle
and a "current" pointer, so it requires the operator to hold an abstraction the problem
never had. It also hides the target — `drop 7` acting on an implicit current run can
delete from the wrong video — and duplicates state in an index that can drift from the
files on disk. Its one real benefit, resuming where a run stopped, does not need its
interface (see below).

**The one-shot converter was ruled out** as a structure, but kept as the default path. As
a structure it makes a single stage impossible to redo: a bad crop costs the whole run,
including the ~40-minute STT pass on the target host. That is the wrong trade for a tool
whose crop and detection quality are still unmeasured.

**So: the stage pipeline is the structure, and the bare root is the default path.** The
common case costs no extra word, and the stage commands exist for the refinements the
one-shot shape forbade. The two were never really in tension: the stage pipeline's
"run every stage" command *is* the one-shot converter under another name.

## Consequences

- **The bare root dispatches to a hidden default command.** A first token that is not a
  known subcommand is treated as the target. This needs a `typer.core.TyperGroup`
  subclass overriding `parse_args`, `list_commands` and `format_usage` — standard `Group`
  methods, no private API. Measured cost: a bare token colliding with a subcommand name
  is ambiguous (`extract-slides crop` meaning a local file named `crop`), and it fails
  **loudly**, asking for `DIR`, rather than silently. Write `./crop` for that case.
- **Only step 1 takes a URL.** Every later stage takes a directory. The mock's first
  version had two commands each taking a URL and doing its own acquisition, which
  duplicated work and blurred the pipeline.
- **Resume by default, never silently.** Every reused stage prints a line saying so and
  naming `--force`. This is what absorbs the run-workspace's benefit at no conceptual
  cost, because **the state lives inside the output directory**, per video, not in a
  global run index.
- **A stage command chains forward** into the stages that depend on it. `detect` re-runs
  `crop` and `pair`; `transcribe` re-runs `pair`; `crop` and `pair` stop at themselves,
  since cropping changes pixels, not slide count or timing. Without this, a redone
  `detect` would silently leave a stale manifest pointing at slides that no longer exist.
- **`--force` also works per stage**, so `crop DIR --force` is expressible.
- **No `--transcript-only` / `--slides-only` flags.** With `transcribe` as a stage, they
  were a second way to reach the same result.
- **Transcript-only is out of scope.** A caption-only mode would mostly duplicate
  `yt-dlp`, which already downloads a ready caption. The tool's value is the slide
  reconstruction. This overrides the addendum on
  [#3](https://github.com/henricos/extract-slides/issues/3), which had argued for
  designing the thin path in because the caption stage needs no `ffmpeg`; the
  prerequisite finding stands, the feature does not.
- **Output layout is flat**, because opening `slides/` in an image viewer flips through
  the deck in order. Flat alone had no readable per-slide speech view, so
  `presentation.md` is generated alongside it and is **regenerated from the manifest**,
  never patched — which is also why one document beat per-slide sidecars, since sidecars
  force `drop` to renumber two series in step and admit stale orphans.
- **Slide numbers are not stable identities.** `drop` renumbers survivors, so number 7
  before a drop is not number 7 after. Whether the manifest also carries a stable id is
  [#14](https://github.com/henricos/extract-slides/issues/14).
- **Two output streams under `--report json`**: the JSON document on stdout, all human
  narration on stderr, and a machine-readable object on failure with exit 2. The mock's
  first version printed progress to stdout and corrupted the JSON, which made the
  unattended invocation unusable.
- **Stage output is a block, reuse is a line.** An executed stage renders as an indented
  block with a blank line around it, headed by its position in the pipeline; a reused
  stage renders as one line. No borders in the running log.
- **The final report is a bordered panel.** See the amendment to
  [ADR 0001](0001-python-runtime-for-the-cli.md): "never as a bordered panel" is scoped
  to `--help`.

## What this decision does not decide

- The manifest schema, and the rule that decides which speech belongs to which slide
  ([#14](https://github.com/henricos/extract-slides/issues/14)). This ADR fixes only that
  a manifest and a `presentation.md` exist and what they are for.
- What `review` actually renders — a prompt loop, a contact sheet, an HTML gallery. Still
  fog on the map; this ADR fixes only that it is a command taking a directory.
- Which detection metric or crop method runs
  ([#11](https://github.com/henricos/extract-slides/issues/11),
  [#12](https://github.com/henricos/extract-slides/issues/12),
  [#17](https://github.com/henricos/extract-slides/issues/17)).
