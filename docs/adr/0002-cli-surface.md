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
extract-slides crop DIR --no-crop  # keep the full frame, crop nothing
extract-slides pair DIR            # redo the pairing, rewrite the manifest
extract-slides drop DIR N...       # delete duplicates, renumber, rewrite
extract-slides review DIR          # walk the flagged slides
```

The last two lines were revised on 2026-09-14 — `review` is removed, `drop` also runs with
no numbers, and `prune` joins them. The `pair` line was revised on 2026-09-15 — it reads the
manifest rather than rewriting it, and `crop` now chains into it. Both revisions are in the
amendments at the end.

Stages: `acquire → transcribe → detect → crop → pair`.

Output directory, per video:

```
<slug>-<video-id>/
  manifest.json      machine contract (schema: ADR 0009)
  presentation.md    each slide's image + only the speech said over it
  transcript.md      the whole video, one document
  transcript.json
  slides/001.jpg …
```

The extension was `.png` until 2026-09-15; see the amendment at the end.

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
  **A fourth method, `main`, was added and the error now says `./crop` itself** — see the
  amendment at the end.
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
  **`crop` no longer stops at itself** — see the amendment at the end.
- **`--force` also works per stage**, so `crop DIR --force` is expressible.
- **`--no-crop` keeps the full frame.** Available on the crop stage and on the default
  path. It is the escape hatch for a video where cropping goes wrong, and it is always a
  *safe* answer rather than a degraded one: ADR 0003's crop metric is binary on content
  preservation, so the full frame always passes and only loses on the secondary measure.
  A user who does not trust the crop on a given video should be able to say so in one flag
  rather than reaching for `--roi`, which asks for four numbers they would have to measure.
  Requested by the operator while reviewing the ground truth for `jqpdveK2XAU`.
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
  [#14](https://github.com/henricos/extract-slides/issues/14). **Answered:**
  [ADR 0009](0009-the-output-contract-a-table-of-instants.md) makes the capture's own
  timestamp the identity.
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

- ~~The manifest schema, and the rule that decides which speech belongs to which slide
  ([#14](https://github.com/henricos/extract-slides/issues/14)). This ADR fixes only that
  a manifest and a `presentation.md` exist and what they are for.~~ Settled by
  [ADR 0009](0009-the-output-contract-a-table-of-instants.md).
- ~~What `review` actually renders — a prompt loop, a contact sheet, an HTML gallery. Still
  fog on the map; this ADR fixes only that it is a command taking a directory.~~ Answered
  by removing the command — see the amendment below.
- Which detection metric or crop method runs
  ([#11](https://github.com/henricos/extract-slides/issues/11),
  [#12](https://github.com/henricos/extract-slides/issues/12),
  [#17](https://github.com/henricos/extract-slides/issues/17)).

## Amendments

### 2026-09-14 — `review` is removed; `drop` reconciles; `prune` is added

From [#21](https://github.com/henricos/extract-slides/issues/21), settling the deletion
pass. See [ADR 0008](0008-the-deletion-pass-two-ways-to-name-the-surplus.md) for the
reasoning. The surface above changes in three places.

**`review DIR` is gone.** It was listed as "walk the flagged slides", with what it renders
left open. The answer turned out to be that the tool renders nothing: the operator reviews
`slides/` in a file manager, which is already a contact sheet and already has a delete key.
A command whose whole job was a rendering does not survive the decision not to render.

**`drop DIR` without numbers is now meaningful.** It reconciles the output with whatever is
on disk, which is what the operator needs after deleting images in the file manager.
`drop DIR N...` is the same procedure with a deletion in front of it. Both renumber the
survivors and print the old-to-new mapping — this ADR already established that slide
numbers are not stable identities, and the mapping is what keeps a second review round from
working off numbers that moved.

**`prune DIR` is added**, with `--apply`. It is the third way of producing the list of
numbers, by asking a model instead of a person. It never fires implicitly.

### 2026-09-15 — JPEG, `pair` reads the manifest, `crop` chains forward

From [#14](https://github.com/henricos/extract-slides/issues/14), settling the output
contract. See [ADR 0009](0009-the-output-contract-a-table-of-instants.md) for the
reasoning. Three corrections.

**The images are JPEG, not PNG.** The output layout above wrote `slides/001.png`; all three
spikes emitted `.jpg` and nobody reviewing the results noticed. Measured on 36 cropped
captures, PNG costs 986 KB an image against JPEG's 143 KB — 202 MB against 29 MB for a
45-minute talk — to losslessly preserve the artefacts of a lossily compressed video frame.

**`pair DIR` reads the manifest rather than rewriting it.** It is listed above as "redo the
pairing, rewrite the manifest". [ADR 0009](0009-the-output-contract-a-table-of-instants.md)
stores an instant per slide and derives every interval at read time, so there is no stored
assignment to redo. What is left is regenerating `presentation.md`, which is the command to
run after editing the transcript by hand. Unlike `review`, it keeps a job worth a name.

**`crop DIR` chains forward into `pair`.** The consequence above has it stopping at itself,
"since cropping changes pixels, not slide count or timing". That premise died with
[ADR 0006](0006-crop-by-cutting-the-presenter-away.md), which runs the duplicate test a
second time inside the crop stage and deletes — 241 images to 216 across the sweep set.

### 2026-09-16 — two non-stage commands: `prepare` and `self-update`

From [#15](https://github.com/henricos/extract-slides/issues/15), settling installation and
distribution. See [ADR 0010](0010-installed-like-a-system-tool.md) for the reasoning. The
surface above is a stage pipeline and lists only stages; packaging adds two commands that
are not stages and do not touch an output directory.

```
extract-slides prepare               # download the STT model now instead of on first use
extract-slides self-update           # update the tool and its dependencies
extract-slides self-update --yt-dlp  # update only yt-dlp, leaving the rest pinned
```

**`prepare`** exists because the 464 MB model otherwise downloads during the first real run,
which looks like a hang. Lazy download stays the default — it is what a person gets without
reading anything — and `prepare` lets an unattended install pull the wait forward to install
time, where it is expected.

**`self-update`** exists because the tool is installed like `yt-dlp` and inherits `yt-dlp`'s
problem: every pinned dependency must stay pinned, and that one must not. `--yt-dlp` updates
it alone, because "YouTube changed again" is the common case and should not re-resolve the
stack that the spikes measured.

Neither command takes a URL or a directory, so neither disturbs the verbless default path:
`prepare` and `self-update` are not plausible filenames, and the ambiguity this ADR worried
about does not arise.

### 2026-09-24 — `--out`, `--version`, and a fourth `Group` method

From [#25](https://github.com/henricos/extract-slides/issues/25), while building the shell
this ADR specifies. Three corrections, none of them to the structure.

**`--out DIR` / `-o DIR` joins the surface**, on the default path and on `fetch`, and
defaults to `./out`. The surface above says what the output directory is called
(`<slug>-<video-id>/`) and never says where it is put, which left the parent implied. It
was not entirely undocumented — this repository's `.gitignore` has carried
`out/` with the comment "Default output directory of the CLI (see
docs/adr/0002-cli-surface.md)" since before the tool existed, pointing at an ADR that did
not in fact say so. This closes that loop. The flag is on the two commands that create a
directory; every later stage is given one and has nothing to place.

**`--version` joins the surface** on the root. It is in no decision above because it is a
convention rather than a choice, but a tool that ships `self-update` has to be able to say
what it is updating from, and [#26](https://github.com/henricos/extract-slides/issues/26)
puts the tool version in the manifest's run header. Recording it keeps the surface
enumerable — which is the property the "there is no `review`, no `--transcript-only`" rule
depends on.

**The `TyperGroup` subclass overrides a fourth method: `main`.** The consequence above
names `parse_args`, `list_commands` and `format_usage`. `main` is the same kind of
override — a standard `Group` method, no private API — and it exists for one reason: this
ADR promises "a machine-readable object on failure with exit 2" under `--report json`, and
a *parsing* failure is a failure the caller must handle too. Left to the framework, a bad
command line prints a message and exits 2 with nothing on stdout, so an unattended caller
gets the exit code and nothing to parse. The framework still parses and still writes the
message a person reads; only the handling of what it raises is the tool's.

The same override is where the collision this ADR accepts finally names its own way out.
`extract-slides crop` already failed loudly asking for `DIR`; it now also prints that a
file called `crop` is written `./crop`. The advice was in this document and not in the
error, which is the wrong place for it — the person who needs it is at a prompt, not
reading an ADR.

### 2026-09-26 — the stage registry, and what a command invalidates

From [#26](https://github.com/henricos/extract-slides/issues/26), while building the stage
registry this ADR specifies. The surface is unchanged.

**The three rules above come off one declaration.** The forward chain, resume-by-default
and per-stage `--force` are written here as three separate consequences; each stage now
declares only what it needs finished before it can run, and the rest is read off that graph.
It reproduces the chain exactly as stated: `detect` re-runs `crop` and `pair`, `transcribe`
re-runs `pair`, `crop` re-runs `pair` (per the 2026-09-15 amendment), and only `pair` stops
at itself. Declaring the graph before any stage exists is deliberate: it changes shape every
time a stage is born, and a `detect` written before `crop` existed would chain into nothing
and need revisiting later.

**A stage's block is headed by its position in the whole pipeline**, so `crop DIR` opens at
`4/5` after three reuse lines rather than renumbering itself to `1/2`. The position is
where in the run the operator is, which is the thing the number is for.

**What a command invalidates is what distinguishes the two halves of the surface**, and this
ADR does not say it anywhere.

The **verbless default path** and **`fetch`** resume: they invalidate nothing, so every stage
recorded as finished is reused and says so. `--force` invalidates what they cover. Both reach
that state through the output directory, so both can only resume once they have one: given a
URL, resuming waits on the acquirer resolving it to a directory
([#27](https://github.com/henricos/extract-slides/issues/27)), and until then only the form
that names a directory resumes.

A **stage command names a stage to redo**, and redoing it is what the command means.
`transcribe DIR` transcribes. This is not symmetry for its own sake — it is forced by
[ADR 0009](0009-the-output-contract-a-table-of-instants.md), which keeps `pair DIR` on the
surface for exactly one job, "what to run after editing the transcript by hand". A `pair`
that reused its own record would do nothing on the one invocation it exists for. The tool
cannot see a hand edit; the operator typing `pair` is the signal.

The rejected alternative was the uniform one: a stage command resumes like everything else
and recomputes only under `--force`. It reads better as a rule and fails on the case above.

**`--force` on a stage command is therefore accepted and adds nothing**, because naming the
stage already asked for it. What "`--force` works per stage" describes is the *granularity*,
and that part is real and is what the registry provides: `crop DIR` recomputes the crop and
the pairing while reusing the download, the transcript and the detection, where
`extract-slides DIR --force` recomputes all five.
