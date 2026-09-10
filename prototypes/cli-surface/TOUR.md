# CLI surface mock — tour

**THROWAWAY PROTOTYPE.** Answers [issue #3](https://github.com/henricos/extract-slides/issues/3):
what is the user-facing surface of the `extract-slides` CLI? Nothing here does real
work. No video is downloaded, no model is loaded. The output tree *is* materialised
with stub files, so the layout can be inspected for real.

This file describes the **single surface** the three variants converged on. The
variants themselves (task verbs / stage verbs / run workspace) are the primary source
and stay in this branch's history at commit `5aa28c2`.

## Run it

```bash
E=./prototypes/cli-surface/es    # wrapper: uv fetches typer and rich inline

$E --help
```

## The surface

```
extract-slides URL                 # default path: everything, resuming
extract-slides URL --force         # ignore existing work, recompute

extract-slides fetch URL           # step 1: acquire + transcribe
extract-slides transcribe DIR      # redo the transcript, no re-download
extract-slides detect DIR          # redo detection; chains into crop and pair
extract-slides crop DIR            # redo the crop only
extract-slides pair DIR            # redo the pairing and rewrite the manifest
extract-slides drop DIR N...       # delete duplicates, renumber, rewrite manifest
extract-slides review DIR          # walk the flagged slides
```

Stages: `acquire → transcribe → detect → crop → pair`.

What it encodes:

- **The bare root is the default path.** No verb for the common case. A first token
  that is not a known subcommand falls through to the hidden default command.
- **Only step 1 takes a URL.** Every later stage takes a directory.
- **Resumes by default, never silently.** Every reused stage prints a `=` line saying
  so and naming `--force`.
- **A stage command chains forward** into the stages that depend on it, so a redone
  `detect` cannot leave a stale manifest and stale crops behind. `crop` and `pair`
  stop at themselves — cropping changes pixels, not slide count or timing.
- **State lives inside the output directory** (`.extract-slides.json`), per video.
  Not a global run index; that was the variant-C abstraction that got ruled out.
- **Transcript-only is out of scope.** `yt-dlp` already downloads a ready caption.

## Drive it

```bash
O=/tmp/es; rm -rf $O

# 1. first run: nothing to resume
$E "https://youtu.be/X2vr81CJ934" -o $O

# 2. same command again: five reused lines, no work done
$E "https://youtu.be/X2vr81CJ934" -o $O

# 3. redo one stage; the expensive ones are reused
D=$O/designing-data-intensive-pipelines-X2vr81CJ934
$E crop $D          # stops at crop
$E detect $D        # chains into crop and pair, and says so

# 4. step 1 alone, then continue from it
rm -rf $O
$E fetch "https://youtu.be/3sB4Iv_tM7U" -o $O --case no-caption
$E "https://youtu.be/3sB4Iv_tM7U" -o $O --case no-caption   # reuses the 40-min STT

# 5. force
$E "https://youtu.be/X2vr81CJ934" -o $O --force

# 6. point the root at the directory instead of the URL
$E $D
```

`--case captioned|no-caption|ptbr|suspects|fail` drives the mock into the hard
messages rather than the happy path. `--case no-caption` is the one to look at first:
`yt-dlp` exits 0 when a video has no caption, so the tool must name its transcript
source out loud. `--slow` paces the simulation so the STT progress is watchable.

## Output layouts

Still an open axis — pick one while driving:

```bash
for L in flat paired staged; do $E "u" -o /tmp/es-$L --layout $L; done
```

- **flat** — `slides/001.png` … plus `transcript.md`, `transcript.json`, `manifest.json`.
- **paired** — one directory per slide: `001/slide.png` + `001/speech.md`.
- **staged** — numbered by stage: `01-transcript/`, `02-frames/`, `03-slides/`, `logs/`.

## The unattended / agent invocation

```bash
$E "URL" -o $O --report json 2>/dev/null
```

A single JSON document on stdout, every human line on stderr. Failures are
machine-readable too, with exit 2:

```bash
$E "URL" -o $O --case fail --report json 2>/dev/null; echo "exit=$?"
```

## The one ambiguity of the bare root, measured

Only a **bare** token colliding with a subcommand name is ambiguous, and it fails
loudly rather than silently:

```bash
touch crop
$E crop          # -> treated as the subcommand; errors asking for DIR
$E ./crop        # -> treated as the file
```

## Two things this mock surfaced

1. **`typer` 0.27 vendors click.** There is no importable `click` module alongside it;
   it lives as `typer._click`. The bare-root dispatch therefore subclasses
   `typer.core.TyperGroup`, which worked using only standard `Group` method overrides
   (`parse_args`, `list_commands`, `format_usage`) and no private imports. But ADR 0001's
   consequence "it remains reversible because typer is click underneath" needs a
   correction: falling back to plain click now means adding a real dependency.

2. **A fully-finished run is a noisy no-op.** Re-running the bare root when every stage
   is done prints five reused lines, then the whole report and tree. Whether a complete
   run should short-circuit with one line instead is still open.

## Not proposed here, on purpose

The manifest schema and the slide-to-speech pairing rule ([#14](https://github.com/henricos/extract-slides/issues/14),
which this ticket blocks); the concrete shape of review mode (still fog on the map —
`review` only lists the flagged slides); which detection metric or crop method runs
([#11](https://github.com/henricos/extract-slides/issues/11),
[#12](https://github.com/henricos/extract-slides/issues/12),
[#17](https://github.com/henricos/extract-slides/issues/17) — the mock prints `TBD`).
