# CLI surface mock — tour

**THROWAWAY PROTOTYPE.** Answers [issue #3](https://github.com/henricos/extract-slides/issues/3):
what is the user-facing surface of the `extract-slides` CLI? Nothing here does real
work. No video is downloaded, no model is loaded.

Three **radically different command structures** are implemented, switchable with the
`V` env var. Output layout is a **second, independent axis** (`--layout`) and is really
materialised on disk, so the tree can be inspected with `tree` or `ls -R`.

Flip through, then steal the best bits from each. The interesting feedback is usually
"I want B's `transcript` command with A's flat output".

## Run it

One command, no setup. `uv` fetches `typer` and `rich` inline.

```bash
alias es='uv run --quiet --with typer --with rich prototypes/cli-surface/mock.py'

V=A es --help          # task verbs, one shot
V=B es --help          # stage verbs, composable
V=C es --help          # run workspace, resumable
```

Every invocation ends with a footer on stderr saying which variant is active and how
to flip. That footer is the mock's scaffolding, not part of the proposed surface.

## The three variants

| | `V=A` task verbs | `V=B` stage verbs | `V=C` run workspace |
|---|---|---|---|
| shape | one shot, flags carry everything | one command per stage, `all` chains them | a run is a first-class object |
| commands | `extract` `drop` `review` | `transcript` `slides` `crop` `pair` `all` `drop` `review` | `new` `run` `status` `ls` `drop` `review` |
| transcript-only | `extract --transcript-only` | `transcript` (its own command) | `run --from transcript` |
| re-crop without re-download | not expressible | `crop DIR` | `run --from crop` |
| resumability | none | implicit, via re-running one stage | explicit, tracked per stage |
| state on disk | output dir only | output dir only | output dir + a runs index |
| cost | smallest surface to learn | more commands, each obvious | most machinery; earns it only if resuming matters |

`V=B` matters because the caption research found the transcript path is
prerequisite-light (no ffmpeg, no JS runtime, no browser) while the video path needs
all the heavy prerequisites — so "give me just the transcript" can run on a much
thinner image. `V=C` matters because the map's fog asks whether any stage needs
caching or resumability to stay usable.

## Drive it into the interesting messages

`--case` picks which simulated video to pretend to process. This is where the mock
earns its keep: the hard messages, not the happy path.

```bash
V=A es extract URL --out /tmp/es --case captioned    # happy path: ASR caption exists
V=A es extract URL --out /tmp/es --case no-caption   # yt-dlp exits 0 with nothing -> STT fallback
V=A es extract URL --out /tmp/es --case ptbr         # pt-BR caption
V=A es extract URL --out /tmp/es --case suspects     # 63 min, 11 dedupe suspects
V=A es extract URL --out /tmp/es --case fail         # HTTP 429 mid-run
V=A es extract URL --out /tmp/es --case no-caption --slow   # watch the STT progress render
```

`--case no-caption` is the one to look at first. It is the message shape forced by a
research finding: yt-dlp exits 0 when a video has no caption, indistinguishable from
success, so the tool must say out loud which transcript source it used rather than
leaving the operator to guess.

## Compare the output layouts

```bash
for L in flat paired staged; do V=A es extract URL --out /tmp/es --layout $L; done
```

- **flat** — `slides/001.png` … plus `transcript.md`, `transcript.json`, `manifest.json`.
- **paired** — one directory per slide: `001/slide.png` + `001/speech.md`.
- **staged** — numbered by pipeline stage: `01-transcript/`, `02-frames/`, `03-slides/`, `logs/`.

The *data* contract behind these (manifest schema, how a slide is paired with the
speech said over it) is deliberately not proposed here — it is locked separately in
[issue #14](https://github.com/henricos/extract-slides/issues/14), which this ticket blocks.

## The unattended / agent invocation

```bash
V=A es extract URL --out ./out --report json 2>/dev/null
```

`--report json` puts a single JSON document on stdout and every human line on stderr,
so an agent parses stdout and a human reads stderr. Failures are machine-readable too:

```bash
V=A es extract URL --case fail --report json 2>/dev/null; echo "exit=$?"
```

## Reconcile: drop, renumber, rewrite

```bash
V=A es extract URL --out /tmp/es --case suspects
V=A es review /tmp/es/kubernetes-na-vida-real-63-min-7JbOagrwysE
V=A es drop   /tmp/es/kubernetes-na-vida-real-63-min-7JbOagrwysE 59 60 61
```

`drop` deletes, renumbers the survivors, and rewrites the manifest, per the map's
standing preference. Watch the warning it prints: renumbering means a slide number is
**not** a stable identity across a drop. Whether the manifest also carries a stable id
is a question for issue #14.

## What the mock does NOT propose

- The manifest schema and the slide↔speech pairing rule (issue #14).
- The concrete shape of review mode. `review` here only lists the flagged slides and
  says so — whether it is a prompt loop, a contact sheet, or an HTML gallery is still
  fog on the map.
- Which detection metric or crop method runs (issues #11, #12, #17). The mock prints
  `TBD` where a real choice belongs.
