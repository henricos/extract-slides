# The output contract: a table of instants, and the speech cut from it

- **Status:** accepted
- **Date:** 2026-09-15
- **Ticket:** [#14 — Output contract: artifacts, manifest and reconciliation](https://github.com/henricos/extract-slides/issues/14)
- **Builds on:** [ADR 0002](0002-cli-surface.md) (which artifacts exist),
  [ADR 0005](0005-pass-1-pinned-anchor-edge-signal-watchdog.md) (the capture reasons),
  [ADR 0006](0006-crop-by-cutting-the-presenter-away.md) (what the crop needs carried),
  [ADR 0007](0007-transcribe-with-small-and-trust-the-media-clock.md) (the media clock),
  [ADR 0008](0008-the-deletion-pass-two-ways-to-name-the-surplus.md) (reconciliation)
- **Amends:** [ADR 0002](0002-cli-surface.md) — images are JPEG, `pair` reads the manifest
  rather than writing it, and `crop` chains forward

## Decision

**`manifest.json` describes what is in `slides/` now, and nothing else.** It is a
current-state table, not a history. Nothing deleted leaves a trace in it.

**A slide row stores an instant, not an interval.**

```
slides[i] = {
  file, change_at, reason, rect, rect_rule, layout
}
```

`change_at` is the capture's own timestamp on the media clock. Slide `i` is on screen for
`[change_at[i], change_at[i+1])`, and the last slide runs to the media's duration. The
intervals therefore **tile the video** — no gaps, no overlaps — and are **derived at read
time, never stored**. `reason` is the capture's origin from
[ADR 0005](0005-pass-1-pinned-anchor-edge-signal-watchdog.md): `first`, `dwell`,
`watchdog` or `eof`. `rect` is normalised, `rect_rule` is `activity` or `full`, and
`layout` is the cluster the rectangle was computed for, all three required by
[ADR 0006](0006-crop-by-cutting-the-presenter-away.md).

**`change_at` is the slide's identity.** Numbers renumber on every `drop`; the instant does
not. No invented id.

**One interval per slide, always.** A capture dropped as a duplicate of an earlier one does
not give that earlier slide a second span.

**The run header carries the provenance, per run and never per slide**: tool version, video
id and URL, media duration, transcript origin (`asr-caption`, `human-caption` or `stt`) and
fidelity (`word` or `cue`), the STT model where one ran, whether the crop ran, and the
detection parameters.

**A transcript cue is assigned whole to the slide whose interval it overlaps most.** No
splitting on word boundaries, no offset applied to the boundary, ties to the earlier slide.

**The speech is not in the manifest.** `presentation.md` is cut out of `transcript.json` by
those intervals when it is written.

**`transcript.json` is one normalised shape across the three origins**, and **keeps word
timings wherever the origin has them**. The raw caption file or STT output is kept beside
it. `transcript.md` is prose in paragraphs, with no timestamps.

**The caption track follows the audio language `yt-dlp` reports** — the `-orig` track of the
original audio — and falls through to local STT when that is absent or ambiguous. There is
no `--lang`; `--force-stt` from [ADR 0007](0007-transcribe-with-small-and-trust-the-media-clock.md)
is the override.

**Reconciliation deletes rows and renumbers.** `drop` removes every row whose file is gone;
[ADR 0008](0008-the-deletion-pass-two-ways-to-name-the-surplus.md)'s forward merge is what
not storing intervals does by itself. **A file in `slides/` that the manifest does not know
stops the command**, naming the file and changing nothing.

**Images are JPEG**, not the `.png` written in [ADR 0002](0002-cli-surface.md).

**There is no input cache.** The source video stays in the output directory, which
[ADR 0006](0006-crop-by-cutting-the-presenter-away.md) already requires so that `crop DIR`
can recompute.

## Why

### A manifest that remembers deletions is a trash directory under another name

`docs/research/reference-implementations.md` recommended copying `AutoSlides-Extractor`'s
`timeline.json`: capture events appended and never removed, changing only their
*resolution* — `canonical`, `duplicate` with a `duplicateOf`, `gap` with a reason. It is a
good design and it belongs to a tool that keeps its rejects.

This one does not. [ADR 0008](0008-the-deletion-pass-two-ways-to-name-the-surplus.md)
decided that deletion is real: no trash, no restore, and numbers reflow because nothing
holds a gap open. A manifest carrying the deleted rows would restore exactly that, in
metadata, and leave two places on disk disagreeing about what exists. The old-to-new
mapping `drop` already prints is what a second review round needs; a history is not.

### An instant cannot contradict itself; two dates can

The alternative was a `dwell_start` and a `dwell_end` on every row, which reads better when
you open the file. It also means that after a `drop` the end of one row and the start of the
next are two facts that can disagree, and something has to keep them in step through a pass
that renumbers twice — once when pass 1 drops easy duplicates, once when the crop drops what
it made identical.

Storing only the instant removes the question. **Deleting slide 7 is deleting the line**:
slide 8's interval starts where 7's did, with nothing recomputed, because nothing was stored.
The forward-merge rule [ADR 0008](0008-the-deletion-pass-two-ways-to-name-the-surplus.md)
requires stops being a rule and becomes a property of the representation.

### Tiling dissolves the unassigned bucket rather than managing it

The one piece of prior art on pairing leaves an unmatched cue at `assigned_scene_index == -1`
and drops it with no warning and no counter — the defect
`docs/research/reference-implementations.md` singled out as disqualifying for a recall-first
project.

Tiling makes it unreachable. [ADR 0005](0005-pass-1-pinned-anchor-edge-signal-watchdog.md)
always emits the first frame, so the first interval opens at zero; the last runs to the
media's duration, which [ADR 0007](0007-transcribe-with-small-and-trust-the-media-clock.md)
made the authority on time. Every cue inside the media lands somewhere, and anything stamped
outside it was already discarded by that ADR's two guards. There is no bucket to diagnose
because there is nothing to put in one.

### No offset, because there is nothing to tune it against

The ticket asked how pairing handles the overlap where a speaker starts on the next slide
before advancing it. The honest answer is that the boundary stays dry at the timestamp.
Pushing it back by some seconds is choosing a constant with no way to know whether it helped,
and [ADR 0004](0004-capture-generously-delete-afterwards.md) closed that path for the whole
project: where a constant has to be chosen, it is chosen toward over-capture, and there is no
metric to move it against. A cue that ends up under the previous slide is visible in
`presentation.md` and costs nothing to read past.

Whole-cue assignment comes from the same place. The clock would support splitting — word
timestamps land within half a second of the caption clock on 96–99 % of cues, free
([ADR 0007](0007-transcribe-with-small-and-trust-the-media-clock.md)) — but a cue split at
a boundary produces two fragments that each read as broken prose.

### Half the captures are not slide changes, which is why `reason` is a field

Counting the emission reasons across the six sweep fixtures of
[ADR 0005](0005-pass-1-pinned-anchor-edge-signal-watchdog.md):

| fixture | `dwell` | `watchdog` | `first`/`eof` |
|---|---|---|---|
| `X3uFwLj2u7Q` | 1 | **20** | 1 |
| `YBH8rQv4aTQ` | 37 | **39** | 2 |
| `b9dBJnQ_kpo` | 15 | **14** | 2 |
| `jqpdveK2XAU` | 13 | 4 | 2 |
| `pJc0l2DASpo` | 34 | 2 | 2 |
| `2AWv_nIfp-U` | 49 | 2 | 2 |

A `dwell` capture's timestamp is the moment the screen became that state. A `watchdog`
capture is the current frame in the middle of continuous churn and corresponds to no
transition at all. `docs/research/reference-implementations.md` advises aligning the
transcript on the transition rather than on the confirmation; on this evidence that advice
covers only half the rows, and the other half are boundaries that are arbitrary by
construction.

The field is cheap and it is the context `prune` needs: fifteen consecutive captures out of
the watchdog is a camera moving, not a deck building.

### One interval, and the return case is left to declare itself

[ADR 0005](0005-pass-1-pinned-anchor-edge-signal-watchdog.md) compares each capture against
*every* image already kept, not just the previous one, specifically to absorb a camera
cutting away from the slide and back. When it comes back, the capture is dropped as a
duplicate — and the speech said during the return is real. Giving that slide a second span
was the reference implementations' answer.

It is refused here for the same reason as the event log: a second span is a row for something
that is not in `slides/`. The case is also narrower than it looks — the large duplicate
counts measured (27 dropped against 19 kept on `jqpdveK2XAU`) are adjacent progressive
builds, not distant returns. If it hurts, the symptom is speech visibly out of place in
`presentation.md`, and it reopens with a case in hand rather than a hypothesis.

### JPEG, measured

Thirty-six cropped captures from the sweep set, re-encoded:

| format | per image | a 45-minute talk (210 images) |
|---|---|---|
| JPEG | 143 KB | **29 MB** |
| WebP q95 | 131 KB | 27 MB |
| PNG | 986 KB | **202 MB** |

The sample is already JPEG, so re-encoding it to PNG measures a PNG of a JPEG and overstates
PNG somewhat. The direction survives the caveat: what enters the pipeline is a lossily
compressed video frame, so PNG preserves the codec's artefacts rather than any detail that
exists, at seven times the size. `prune` downsamples everything to 680 px before the request
([ADR 0008](0008-the-deletion-pass-two-ways-to-name-the-surplus.md)), and the OCR extension
`docs/idea.md` defers reads a high-quality JPEG without difficulty.

WebP ties on size and loses where it matters: the review surface
[ADR 0008](0008-the-deletion-pass-two-ways-to-name-the-surplus.md) chose is the operating
system's file manager, and WebP thumbnailing is the first place that bet fails.

### Word timings are the only irreversible loss in the contract

Nothing in the pipeline uses them: pairing assigns whole cues. They arrive free from both
the ASR caption (`tOffsetMs` at 1 ms, `docs/research/youtube-captions.md`) and from
`faster-whisper` (17.5 against 18.1 min/h, within noise).

They are kept because cues can be derived from words and words cannot be derived from cues,
and regenerating them means transcribing the talk again. A human caption already arrives
without them. If the offset or word-level splitting refused above ever comes back, it comes
back needing a file that no longer exists.

### An unknown file stops the command

`drop DIR` with no numbers reconciles against the disk, which is the path for images deleted
in a file manager. A file in `slides/` that the manifest does not know has three possible
treatments: stop, ignore it, or adopt it as a slide with no metadata.

It stops. Renaming a file is indistinguishable from deleting one and adding another, so
ignoring the stranger would silently discard the metadata of a slide the operator only meant
to rename — including its `change_at`, which this ADR made the identity. Adopting it would
create a row with no instant, no rectangle and no layout. Both cost data that does not come
back; stopping costs a message. This is the same principle as
[ADR 0002](0002-cli-surface.md)'s "resume by default, never silently", in a place where
silence costs more.

### The `-orig` ambiguity did not reproduce, and the right handle was elsewhere

`docs/reference-set.md` recorded on 2026-09-10 that `VGN22pPpb-8` and `Sir59K8ZDPU` each
carried **21** different `-orig` caption tracks — YouTube multi-language audio, one ASR per
dubbed track — which made `-orig` ambiguous and is why track selection landed on this ticket.

Re-measured on 2026-09-15, same host and same `yt-dlp` 2026.07.04, both videos carry **one**
`-orig` track (`en-orig`) out of 157 automatic captions, a top-level `language` of `en`, and
a single audio format marked `en-US` / *"English (US) original (default)"*. Either YouTube
withdrew the dubbing or the earlier reading came from a different client.

The measurement matters less than what it exposed: `yt-dlp` states which audio is the
original, and that is a handle the caption research never used. Selection follows it. A
`--lang` flag was rejected as a second way to reach what `--force-stt` already reaches, the
same argument that removed `--transcript-only` in [ADR 0002](0002-cli-surface.md).

### No input cache, because the video has to stay anyway

The split was raised while assembling the reference set: re-downloading a large video is pure
waste, and the fixture cache built for the spikes looked like something the tool would need.

[ADR 0006](0006-crop-by-cutting-the-presenter-away.md) settled it by accident. The crop finds
its rectangle from continuous movement, which cannot be rebuilt from pass 1's captures, so
the source video must remain in the output directory or `crop DIR` cannot recompute and
`--no-crop` becomes irreversible. A shared cache would then exist to serve a *second* output
directory for the same video, which happens when parameters are being compared — spike work,
not use. [ADR 0002](0002-cli-surface.md) rejected the run-workspace shape for asking the
operator to hold an abstraction the problem does not have; a cache brings the same
invalidation question without the benefit.

## Consequences

- **[ADR 0002](0002-cli-surface.md) is amended in three places**, recorded there: the image
  extension, `pair`'s job, and `crop`'s chaining.
- **`pair DIR` reads the manifest rather than writing it.** With the assignment derived at
  read time there is no stored pairing to redo; what survives is regenerating
  `presentation.md`, which is also what `drop` does after reconciling. The command is kept
  because it is what to run after editing the transcript by hand — unlike `review`, which was
  removed when its only job turned out to be a rendering nobody wanted.
- **`crop DIR` chains forward.** [ADR 0002](0002-cli-surface.md) had `crop` stopping at
  itself because "cropping changes pixels, not slide count or timing";
  [ADR 0006](0006-crop-by-cutting-the-presenter-away.md) then put the second duplicate test
  inside the crop stage, which deletes — 241 images to 216 across the sweep set. The premise
  is gone and the chain has to close.
- **Every slide gets a row, including one with no speech over it.** A slide whose interval
  catches no cue still appears in `presentation.md` with an empty body. `m2kar/video2slides`
  does this deliberately and it is right: a slide that vanishes because nobody spoke over it
  is a slide silently lost.
- **Numbering is fixed-width with a floor of three digits**, widening only past 999. Do not
  copy `m2kar`'s adaptive width, which rewrites every filename when the count crosses a power
  of ten; at 4.7 images per minute
  ([ADR 0008](0008-the-deletion-pass-two-ways-to-name-the-surplus.md)) the floor covers any
  talk under about three and a half hours.
- **A re-run that changes the transcript's origin is visible.** If a caption is rejected
  mid-pipeline by [ADR 0007](0007-transcribe-with-small-and-trust-the-media-clock.md)'s
  duration guard and STT replaces it, the header's origin and fidelity change with it, so a
  manifest never silently describes cues from a producer other than the one named in it.
- **The raw caption or STT output stays on disk.** `json3` carries quirks the parser has to
  survive — roughly half the events are rolling-window scroll markers, event 0 is a caption
  window spanning the whole video, some events have no duration — and human tracks open with
  non-speech metadata lines. When a pairing looks wrong, the question is whether the parser
  erred or the caption is like that, and without the raw file that costs a re-download.

## What this decision does not decide

- **Re-attributing a single cue without moving a boundary.** There is no command for it in
  [ADR 0002](0002-cli-surface.md), and the correction surface this project chose is deleting
  images, not editing pairings. If it is ever wanted, cue-level rows carrying their slide are
  the shape to add.
- **The prompt and structured output `prune` sends to the model.** Implementation, as
  [ADR 0008](0008-the-deletion-pass-two-ways-to-name-the-surplus.md) already said.
- **Whether the multi-language-audio case returns.** It is not reproducible today; if a video
  ever presents several `-orig` tracks again, selection by the reported original audio
  language is the rule and local STT is the fall-through.
- **Field names and JSON spelling.** The contract above fixes what is carried and what is
  derived; the key names are implementation.
