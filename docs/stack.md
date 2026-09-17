# The stack

The whole technical strategy for `extract-slides` in one document: every stage, the tool or
technique it uses, the number or the argument that chose it, and where the reasoning lives.

This is the document to read first before writing the CLI. It is a **summary, not a source**:
every decision here was taken on a ticket of the
[strategy map](https://github.com/henricos/extract-slides/issues/1) and recorded in an ADR
under [`docs/adr/`](adr/). Where this document and an ADR disagree, the ADR wins and this one
is wrong — fix it here. Where an ADR and its own research note disagree, the ADR wins: the
research was read before anything was measured, and several of its rankings did not survive
measurement.

Nothing below has been implemented. What exists is six throwaway spikes, on branches, that
measured the numbers quoted here.

---

## 1. The shape of the tool

Three rules decide almost everything else. Read these before any stage.

**Losing a capture is the only failure that costs anything.** A duplicate costs one
keystroke. Every threshold in the pipeline is set toward over-capture, and a stage that is
unsure returns the larger, safer answer rather than the cleverer one.
→ [ADR 0004](adr/0004-capture-generously-delete-afterwards.md)

**There is no ground truth and no correctness metric.** The path that would have built one
was ended deliberately: labelling what is correct only ever bought a ranking between detector
candidates, and it cost a hand pass over every state of every fixture. How anyone knows a
stage is not losing captures: **watch a video and compare it against the output.** That is
the whole protocol. Do not rebuild `ground-truth/` or a scoring harness.
→ [ADR 0004](adr/0004-capture-generously-delete-afterwards.md), and
[ADR 0003](adr/0003-correctness-metric-and-ground-truth.md) for the record of three attempts
at the same idea.

**The tool works in two passes, and only the first is automatic.** Pass 1 captures
generously and deliberately leaves too much; pass 2 deletes the excess, by hand or by a model
the operator invokes explicitly. A 45-minute talk arrives with roughly **210 images**, of
which about two thirds are surplus. An unattended run ends there, with nothing deleted.
→ [ADR 0004](adr/0004-capture-generously-delete-afterwards.md),
[ADR 0008](adr/0008-the-deletion-pass-two-ways-to-name-the-surplus.md)

A fourth rule worth stating because it was tested rather than assumed: **deterministic
first.** AI enters a stage only where it is the only way to reach the quality needed. It
enters exactly one stage — `prune` — and the crop's learned option was measured and refused.

---

## 2. The pipeline at a glance

```
acquire → transcribe → detect → crop → pair        then, by hand: drop / prune
```

| Stage | What it does | What decides it | Where |
|---|---|---|---|
| **acquire** | `yt-dlp`, the tool's own copy, floating version | the host's pinned `yt-dlp` cannot download at all | [ADR 0010](adr/0010-installed-like-a-system-tool.md) |
| **transcribe** | YouTube caption first; `faster-whisper` otherwise | caption on 9 of 9 sampled talks; `small`/`medium` by language | [ADR 0007](adr/0007-transcribe-with-small-and-trust-the-media-clock.md) |
| **detect** | edge difference against a pinned anchor, with a watchdog | the watchdog supplied 20 of 22 captures on the hardest fixture | [ADR 0005](adr/0005-pass-1-pinned-anchor-edge-signal-watchdog.md) |
| **crop** | remove what the presenter occupies; never look for the slide | every "find the slide" recipe cut real content on some fixture | [ADR 0006](adr/0006-crop-by-cutting-the-presenter-away.md) |
| **pair** | each cue whole to the slide whose interval it overlaps most | intervals tile the video, so there is nothing to tune | [ADR 0009](adr/0009-the-output-contract-a-table-of-instants.md) |
| **drop / prune** | delete the surplus, renumber, regenerate | the surplus is ~two thirds of the output, not a rounding error | [ADR 0008](adr/0008-the-deletion-pass-two-ways-to-name-the-surplus.md) |

**End-to-end cost on the target host** (i3-4170, 2 cores, no GPU): detect at 6 % of real time,
crop at one more decode pass of the same order, transcribe at 28–30 % of real time in English
and 89 % in Portuguese. ADR 0007 puts a 45-minute English talk with no caption at roughly
**16 minutes** end to end, counting detect and transcribe; the crop adds a few minutes on top
of that. Where a caption exists the pipeline is dominated by the two video passes, under ten
minutes. A 45-minute Portuguese talk transcribes in about 40 minutes instead of 13.

This is why resumability is a convenience rather than a necessity, and why no stage caches
anything beyond the output directory.

---

## 3. Stage 0 — runtime, language, dependencies

**Python, floor `>=3.12`, `typer` for the CLI, wheels only, glibc only.**
→ [ADR 0001](adr/0001-python-runtime-for-the-cli.md),
[ADR 0010](adr/0010-installed-like-a-system-tool.md)

Python was not chosen on reputation. It was chosen because `uv pip install --only-binary
:all:` — which fails if anything needs a source build — succeeded for the entire candidate
superset, and Node reaches none of it: no maintained native OpenCV binding, a WASM build with
`USE_PTHREADS=0` and no video decoding, no configurable-size DCT perceptual hash, an archived
SSIM library.

**The seven direct dependencies that ship**, measured clean on the target host at **38
packages, 578 MB, 2.6 s, zero compilation**:

```
opencv-python-headless   numpy   faster-whisper   yt-dlp   typer   rich   openrouter
```

- **Everything is pinned to an exact version except `yt-dlp`**, which carries a floor. The
  spikes measured one combination and nothing re-measures it on the user's machine; `yt-dlp`
  is the exception because a pin there stops working in an unpredictable number of weeks.
- **`opencv-python-headless`, never `opencv-python`, never `opencv-contrib-*`.** Always
  headless: this is a CLI. If PySceneDetect is ever added as a spike harness, the
  distribution name is **`scenedetect-headless`** — plain `scenedetect` declares the GUI
  `opencv-python` and collides under the same `cv2` import name.
- **There are no system dependencies at all.** The feared fight with the missing `ffmpeg`
  never happened: the OpenCV wheel reports `FFMPEG: YES` and decoded all six fixtures at
  480p/720p/1080p and 25/30/50 fps and writes JPEG; the PyAV wheel bundled with
  `faster-whisper` decodes YouTube's DASH m4a in about a second.
- **Alpine is ruled out.** `ctranslate2` and `onnxruntime` publish neither a musllinux wheel
  nor an sdist, which would remove `faster-whisper` entirely. Use `ubuntu:24.04` or
  `debian:12/13-slim` wherever a base image is needed.
- **`ImageHash` and `scikit-image` do not ship.** The 256-bit pHash both stages need is
  eleven lines over `cv2.dct`.

**CLI framework details.** `typer` with `rich_markup_mode=None`, so it delegates to click's
plain formatter — indented, two-column, no boxed panels. `typer` 0.27 **vendors** click as
the private `typer._click`: there is no importable `click`, so `import click` will not run,
and subclassing goes through `typer.core.TyperGroup`. `rich` is used for the program's own
progress output and the final report; the ban on bordered panels is scoped to `--help`.

---

## 4. Stage 1 — acquire

**`yt-dlp`, brought as a declared dependency inside the tool's own environment, never the
binary the PATH offers.** → [ADR 0010](adr/0010-installed-like-a-system-tool.md)

The target host demonstrates why: it carries a root-owned 2026.07.04 at
`/usr/local/bin/yt-dlp` that returns **HTTP 403 for every format on every player client** —
the GVS PO-token gate — while 2026.08.19 fetches everything through the `visionos` client. A
tool that used the host's copy would fail on every video with an error pointing at YouTube.

- **The version floats and `self-update --yt-dlp` moves it alone.** 17 YouTube-touching
  releases in 12 months; the failure mode is total, not degraded.
- **The source video stays in the output directory.** There is no input cache. The crop needs
  to re-decode the video, so it has to be there anyway, and a shared cache would only serve a
  second output directory for the same video — spike work, not use.
- **Known risk, open:** `yt-dlp` warns that without a JavaScript runtime "some formats may be
  missing". Every fixture came down anyway. If it bites, the fix is a documented optional
  prerequisite, not a change of design.

---

## 5. Stage 2 — transcribe

**The YouTube caption is the primary path; local STT is the fallback and the quality
opt-in.** → [ADR 0007](adr/0007-transcribe-with-small-and-trust-the-media-clock.md),
[ADR 0009](adr/0009-the-output-contract-a-table-of-instants.md)

A ready caption existed on **9 of 9** sampled talks (all ASR, none human). Word-level timings
exist only via `--sub-format json3`. **Never request a machine-translated track** — 4 of 5
attempts hit HTTP 429.

**Track selection follows the audio language `yt-dlp` reports** — the `-orig` track of the
original audio — falling through to local STT when that is absent or ambiguous. There is no
`--lang` flag; `--force-stt` is the override.

### Local STT

**`faster-whisper` on CTranslate2**, `device="cpu"`, `compute_type="int8"`, `cpu_threads=2`,
`vad_filter=True`, `beam_size=5`, `word_timestamps=True`.

**The model is `small` for English and `medium` for Portuguese — the language decides, not
the material.** The language is read in **2.7 s** by `detect_language` on the `small` model
that loads anyway (`pt` p=0.94, `en` p=0.96); YouTube metadata also states a language but is
absent for local files, so detection is the general handle.

| | English | Portuguese |
|---|---|---|
| model | `small` | `medium` |
| cost | 17–18 min per hour of audio | 53.3 min per hour |
| peak RSS | 1.2–1.6 GB | 2.7 GB |
| weights | 464 MB | 1.5 GB |

Why not `medium` everywhere: across three English talks it was **three times the cost of
`small` and never once better** (3.6/1.4/11.1 % against 4.4/1.4/11.4 %). Why not `small`
everywhere: on a pt-BR talk reading selectors off a slide, `small` produced text a reader who
knows the subject cannot repair (*"estou buscando os mais lindos HPNL"*) while `medium` stayed
wrong-but-standing. The confounder was ruled out — an English talk on the same subject reading
code aloud showed **zero** windows above 0.35 disagreement against Portuguese's five.

`--model` remains as the manual opt-in on any language. Rejected: `large-v3-turbo` (invented
73 fluent words after the audio ended), `sherpa-onnx` + Parakeet (six times faster, worst on
quality, Portuguese unmeasured and flagged European), `whisper.cpp` (needs compilation to read
anything but WAV), greedy decoding as the default (40 % cheaper, slightly worse; the lever to
pull if a long video ever needs to finish sooner), `cpu_threads=4` (18 % *slower* than 2).

### Two guards, one rule: the media's duration is the authority on time

- **Discard any transcript segment stamped at or after the end of the audio.**
  `large-v3-turbo` emitted nine fluent, punctuated, entirely invented segments past the
  476.6 s end of a TED talk; clipping took its error from 10.1 % to 4.2 %. VAD did not prevent
  it.
- **Reject a caption track whose last cue ends more than a couple of seconds past the end of
  the video.** `b9dBJnQ_kpo` is a 300 s lightning talk carrying a **manual** English caption
  676 s long that contains the next speaker's talk from 293 s on. A caption being human-made
  says nothing about whether it belongs to the video.

`--force-stt` has a measured basis and the number to beat is YouTube's, not zero: local
`small` scored 3.6 % against YouTube's ASR 4.3 % on the one talk carrying both.

---

## 6. Stage 3 — detect (pass 1)

**Sample twice a second, analyse at 480 px wide, hold the full-resolution colour frame of the
current anchor in memory** so an export costs no second decode and no re-seek.
→ [ADR 0005](adr/0005-pass-1-pinned-anchor-edge-signal-watchdog.md)

**The signal is the edge difference.** Auto-Canny with thresholds derived per frame from the
luma median, dilate both edge maps, mean absolute difference as the percentage of pixels whose
edge state differs. **Fire at ≥ 0.5.** It sits at exactly 0.0 on a static frame and at
1.18–1.83 on a one-bullet reveal, so any threshold in that gap catches every build and every
hard cut. Its per-frame thresholds make it immune to projector gain ramps, and the dilation
absorbs the 1–2 px wobble of a filmed screen.

Rejected: `max(blur(|a−b|)) > 10`, the more recall-biased reduction in isolation, which fires
on 16×16 codec blocks at 2 grey levels and misses Δ8-contrast light-on-dark text.

**The capture rule is the pinned anchor.** Every sample is compared against a held anchor, not
against its predecessor. When a sample differs, the anchor is emitted if it had held for
**≥ 1.5 s**, and the anchor advances. Three rules complete it:

- **The first frame is always emitted** (which is what makes the first interval open at zero).
- **The pending anchor is flushed at EOF**, or every talk loses its closing slide.
- **The watchdog: if 10 s pass with no emission while the anchor keeps advancing, emit the
  current frame anyway.**

**The watchdog is the load-bearing decision.** On `X3uFwLj2u7Q` — a camera filming a screen in
a dark auditorium, so the frame is never still — the ordinary dwell rule fired **once in
5 min 19**; the watchdog supplied 20 of that fixture's 22 captures. Without it the video
yields one image. Note the asymmetry that makes this the right shape: **under a pinned anchor a
trigger-happy signal produces silence, not surplus** — the anchor never settles, so nothing is
emitted. Silence is the only outcome that costs anything.

**The watchdog also removed the need for a detection region.** Pass 1 has none: no ROI, no
activity mask, no exclusion list, no second hash, no feature cache, no burst suppression, no
slide-frame gate. `min_scene_len` and its relatives are miss generators and there are none.

**An easy duplicate is a near-identical image already emitted.** 256-bit DCT perceptual hash,
dropped below **0.02 of differing bits** — always a fraction of bits, never a raw Hamming
count. Compared against **every** image already kept, not just the previous one, which is what
absorbs a camera cutting away from the slide and back.

Measured over the six sweep fixtures — 45 min 55 s of video — **241 images, roughly five per
minute, at 6 % of real time**. Verified the way ADR 0004 says to verify: the operator reviewed
`pJc0l2DASpo` capture by capture against the video and found nothing missing.

---

## 7. Stage 4 — crop

**The crop starts from the whole frame and removes only what the presenter occupies. It never
tries to find the slide.** → [ADR 0006](adr/0006-crop-by-cutting-the-presenter-away.md)

The signal is time, in two resolutions, which separates three populations of pixels:

| population | between two samples ½ s apart | between two captures |
|---|---|---|
| chrome — branding, background, furniture | still | still |
| **slide** | still | changes |
| presenter — speaker, webcam tile, embedded video | **moves** | moves |

- A pixel that moves in more than **6 %** of consecutive samples is the presenter.
- A pixel that changes by more than **45 grey levels** in more than **8 %** of consecutive
  captures is slide content.
- **The region is computed once per layout**, a layout being a cluster of captures agreeing on
  at least **half** their pixels. This is what makes a mid-video layout change work with no
  segmentation pass: `b9dBJnQ_kpo` yields three rectangles. A layout of fewer than three
  captures gets no rectangle.
- **A side is cut only when a whole blob of movement lies in the strip beyond the content** —
  80 % of it — and the cut lands **halfway between the presenter's edge and the content's**,
  then grown outward by 1.5 %. Specks under 10 % of the largest blob are ignored.
- **The fallback chain has two steps: this rectangle, then the whole frame.** A rectangle
  under 10 % or over 98 % of the frame, a layout too thin, or no content found — all give the
  full frame. The stage never returns "no crop".

**Why not find the slide.** Every positive recipe cut real content on at least one fixture,
and three of them are worth carrying forward as measured negatives:

- **The prior art's own recipe picks the speaker.** `AutoSlides-Extractor`'s `AutoCropDetector`
  — 552 lines the research had recommended as candidate 1.5 — returns nothing on all 19
  captures of `jqpdveK2XAU`, and on `b9dBJnQ_kpo` its highest-scoring rectangle is the
  **speaker's video panel** (aspect 1.77, fill 1.00). In a composed layout the webcam feed is
  a cleaner 16:9 rectangle than the slide is, so **the aspect prior actively prefers the
  presenter.** There is no aspect-ratio gate here.
- **Cropping to the content's bounding box slices the title off.** It did exactly that on
  every slide of `pJc0l2DASpo`, because a header identical on every slide never registers as
  content that changes. **Static slide furniture is indistinguishable from static chrome by
  any temporal signal.** The bounding box can only say how far a cut *could* go.
- **Black-bar removal is not recall-safe**, contradicting the research note that ranked it
  first "by construction". On `YBH8rQv4aTQ` — white text on near-black slides — the inward walk
  hit its 10 % cap on all four sides of **77 of 78** images and cut content out of four. A
  letterbox bar and a dark slide's margin are the same pixels. The step is not in the chain.

**The duplicate test runs again after the crop, and the later of two duplicates survives.**
Same 256-bit hash, same 0.02 threshold. The direction is reversed from pass 1 on purpose: the
test only bites on a progressive build once the moving part of the frame is gone, and "keep
the first" would keep the half-built state and delete the complete one.

Measured: **241 images in, 216 out**, about 3 minutes for 45 min 55 s. **The stage fires on
two fixtures of six and declines on four**, and declining is correct on all four. A stage that
does nothing four times out of six is not weak; it is a stage that refuses to guess.

---

## 8. Stage 5 — pair

**A transcript cue is assigned whole to the slide whose interval it overlaps most.** No
splitting on word boundaries, no offset applied to the boundary, ties to the earlier slide.
→ [ADR 0009](adr/0009-the-output-contract-a-table-of-instants.md)

The intervals are not stored; they are derived from the instants (§9) and **tile the video**,
which is what makes this rule trivial. The one piece of prior art on pairing leaves an
unmatched cue at `assigned_scene_index == -1` and drops it with no warning — a disqualifying
defect for a recall-first project, and tiling makes that bucket unreachable.

**No offset**, because there is nothing to tune it against. A speaker who starts on the next
slide before advancing it produces a cue under the previous slide; that is visible in
`presentation.md` and costs nothing to read past. **No splitting**, because the clock would
support it — word timestamps land within half a second of the caption clock on 96–99 % of cues,
free — but a cue split at a boundary produces two fragments that each read as broken prose.

`pair DIR` **reads** the manifest rather than writing it. Its remaining job is regenerating
`presentation.md`, which is what to run after editing the transcript by hand.

---

## 9. The output contract

→ [ADR 0009](adr/0009-the-output-contract-a-table-of-instants.md),
[ADR 0002](adr/0002-cli-surface.md)

```
<slug>-<video-id>/
  manifest.json      the machine contract
  presentation.md    each slide's image + only the speech said over it
  transcript.md      prose in paragraphs, no timestamps
  transcript.json    one normalised shape across the three origins, word timings kept
  slides/001.jpg …
  <the source video, and the raw caption or STT output>
```

**`manifest.json` describes what is in `slides/` now, and nothing else.** A current-state
table, not a history. Nothing deleted leaves a trace in it.

**A slide row stores an instant, not an interval:**

```
slides[i] = { file, change_at, reason, rect, rect_rule, layout }
```

Slide `i` is on screen for `[change_at[i], change_at[i+1])`, and the last runs to the media's
duration. **Intervals are derived at read time, never stored.** This is the decision that
dissolves three hard questions instead of answering them: deleting slide 7 is deleting the
line, so the forward merge stops being a rule and becomes a property of the representation;
the unassigned bucket becomes unreachable; and surviving two renumberings costs nothing
because no second date exists to disagree.

- **`change_at` is the slide's identity.** Numbers renumber on every `drop`; the instant does
  not. There is no invented id.
- **`reason` is `first`, `dwell`, `watchdog` or `eof`** — the capture's origin from pass 1. It
  is a field because **half the captures are not slide changes**: `X3uFwLj2u7Q` took 20 of 22
  from the watchdog, `YBH8rQv4aTQ` 39 of 78. A `dwell` capture's time is the moment the screen
  became that state; a `watchdog` capture corresponds to no transition at all. It is also the
  context `prune` needs — fifteen consecutive watchdog captures is a camera moving, not a deck
  building.
- **`rect` is normalised, `rect_rule` is `activity` or `full`, `layout` is the cluster.**
- **One interval per slide, always.** A capture dropped as a duplicate of an earlier one does
  not give that earlier slide a second span.
- **Every slide gets a row, including one with no speech over it.** It appears in
  `presentation.md` with an empty body; a slide that vanishes because nobody spoke over it is
  a slide silently lost.

**The run header carries provenance per run, never per slide**: tool version, video id and
URL, media duration, transcript origin (`asr-caption` / `human-caption` / `stt`) and fidelity
(`word` / `cue`), the STT model where one ran, whether the crop ran, and the detection
parameters.

**The speech is never in the manifest.** `presentation.md` is cut out of `transcript.json` by
the derived intervals when it is written, and is **regenerated, never patched**.

**Images are JPEG.** Measured on 36 cropped captures: 143 KB an image against PNG's 986 KB —
**29 MB against 202 MB** for a 45-minute talk — to losslessly preserve the artefacts of a
lossily compressed video frame. WebP ties on size and loses where it matters: the review
surface is the operating system's file manager, and WebP thumbnailing is the first place that
bet fails.

**Numbering is fixed-width with a floor of three digits**, widening only past 999. Do not copy
the adaptive width that rewrites every filename when the count crosses a power of ten.

**Word timings are kept wherever the origin has them** — the contract's only irreversible loss
if dropped. Nothing in the pipeline uses them; they arrive free from both the ASR caption
(`tOffsetMs` at 1 ms) and `faster-whisper`, cues can be derived from words and not the
reverse, and regenerating them means transcribing the talk again.

**The raw caption or STT output stays on disk.** `json3` carries quirks a parser must survive
— roughly half the events are rolling-window scroll markers, event 0 is a caption window
spanning the whole video, some events have no duration — and human tracks open with non-speech
metadata lines. When a pairing looks wrong, the question is whether the parser erred or the
caption is like that, and without the raw file that costs a re-download.

---

## 10. Pass 2 — drop and prune

**Pass 2 is not an algorithm. It is two ways of producing a list of numbers, and one procedure
that applies it.** → [ADR 0008](adr/0008-the-deletion-pass-two-ways-to-name-the-surplus.md)

**The tool renders no review surface at all.** The operator looks at `slides/` in a file
manager, which is already a contact sheet and already has a delete key. A prompt loop was the
worst fit for the shape of the question — a progressive build is only judgeable against its
neighbours, and 210 sequential yes/no decisions is the wrong shape for something answered by
scanning.

```
extract-slides drop DIR 7 12 30    # delete those, then reconcile
extract-slides drop DIR            # reconcile what was deleted on disk
extract-slides prune DIR           # the model lists what to cut; deletes nothing
extract-slides prune DIR --apply   # the model deletes, then reconciles
```

**Reconciliation is one procedure reached by every path**: re-read `slides/`, renumber the
survivors, print the old-to-new mapping, rewrite the manifest, regenerate `presentation.md`.
The mapping is printed because a second review round otherwise works from numbers that
silently moved. **Deletion is real — no trash, no restore**, which is also why there are no
numbering gaps. `drop` is re-runnable and idempotent.

**A file in `slides/` the manifest does not know stops the command**, naming the file and
changing nothing. Renaming a file is indistinguishable from deleting one and adding another,
so ignoring the stranger would silently discard a slide's `change_at` — its identity.

**The speech of a deleted slide merges forward** into the next surviving slide, backward only
when there is no next one. This corrects the intuitive answer: the crop keeps the *later* of
two duplicates, so a build's orphans lie behind its survivor.

### The AI pass

**One request. No loop, no tools, no agent framework.** The question put to the model is *"do
these carry the same content"*, which is one vision call with a list of numbers coming back.

| | |
|---|---|
| Route | **OpenRouter**, via the official `openrouter` SDK (13 packages, 17 MB) |
| Model | **`google/gemini-3.8-flash`** by default, overridable |
| Image size | **680 px** on the long edge |
| `max_tokens` | **65 536** — the model's ceiling, and this is load-bearing |
| `reasoning_effort` | `low` |
| Measured | 216 images in **one request, 172 s, $0.278** per talk |

- **680 px was chosen on what a human can see in the hardest pair** — `022`/`023` of
  `2AWv_nIfp-U`, two captures of the same table one row apart, differing in **0.62 % of
  pixels**: invisible at 240 px, marginal at 340, visible at 480, obvious at 680. The knee is
  480; 680 is taken because nothing else binds. That decision survived the change of model;
  the per-image token arithmetic behind it did not (Anthropic charges 350 visual tokens at
  that size, Gemini charges 1 099).
- **`max_tokens` sized for the answer alone silently destroys the answer.** Reasoning tokens
  grow with the image count — 1 918 at 3 images, 26 318 at 216. A run capped at 16 000 with
  100 images left 637 tokens for the reply, which degenerated from the index list into
  per-image prose and was cut at `length`. **`reasoning: {"enabled": false}` is silently
  ignored** by this model; `reasoning_effort` is the working lever.
- **Nothing was refused for image count** at 3, 25, 50, 100 or 216. The
  `too many images and documents: 27 + 0 > 20` report that raised the doubt is a *validation*
  error returned in seconds, and nothing of that kind appeared.
- **The AI pass never fires on its own.** A key in the environment or config enables the
  `prune` command and nothing else. No run deletes anything because credentials exist. Without
  a key the path is simply absent and the tool says once how to enable it.
- **The safe mode is the one to start on**: `prune` without `--apply` writes the list, the
  operator reads it and runs `drop`.

---

## 11. The CLI surface

→ [ADR 0002](adr/0002-cli-surface.md), with amendments from
[ADR 0008](adr/0008-the-deletion-pass-two-ways-to-name-the-surplus.md),
[ADR 0009](adr/0009-the-output-contract-a-table-of-instants.md) and
[ADR 0010](adr/0010-installed-like-a-system-tool.md) folded in below.

```
extract-slides URL                   # default path: every stage, resuming
extract-slides URL --force           # ignore existing work, recompute

extract-slides fetch URL             # step 1: acquire + transcribe
extract-slides transcribe DIR        # redo the transcript, no re-download
extract-slides detect DIR            # redo detection; chains into crop and pair
extract-slides crop DIR              # redo the crop; chains into pair
extract-slides crop DIR --no-crop    # keep the full frame, crop nothing
extract-slides pair DIR              # regenerate presentation.md from the manifest

extract-slides drop DIR N...         # delete those, renumber, rewrite
extract-slides drop DIR              # reconcile against the disk
extract-slides prune DIR             # the model lists what to cut
extract-slides prune DIR --apply     # the model deletes, then reconciles

extract-slides prepare               # download the STT model now instead of on first use
extract-slides self-update           # update the tool and its dependencies
extract-slides self-update --yt-dlp  # update only yt-dlp, leaving the rest pinned
```

- **The bare root dispatches to a hidden default command.** A first token that is not a known
  subcommand is the target. This needs a `typer.core.TyperGroup` subclass overriding
  `parse_args`, `list_commands` and `format_usage` — standard `Group` methods, no private API,
  measured as working. A bare token colliding with a subcommand name fails **loudly**, asking
  for `DIR`; write `./crop` for that case.
- **Only step 1 takes a URL.** Every later stage takes a directory.
- **Resume by default, never silently.** Every reused stage prints a line saying so and naming
  `--force`. State lives inside the output directory, per video — there is no global run index,
  and the run-workspace shape was rejected for asking the operator to hold an abstraction the
  problem never had.
- **A stage command chains forward** into the stages that depend on it: `detect` re-runs `crop`
  and `pair`, `transcribe` re-runs `pair`, `crop` re-runs `pair` (because the crop deletes).
  Only `pair` stops at itself.
- **`--force` works per stage.** `--no-crop` and `--roi` (four normalised floats) are the
  operator's escape hatches; `cv2.selectROI` is not used.
- **Two output streams under `--report json`**: the JSON document on stdout, all human
  narration on stderr, a machine-readable object on failure with exit 2.
- **Stage output is a block, reuse is a line.** No borders in the running log; the final report
  is a bordered panel.
- **There is no `review`, no `--transcript-only`, no `--slides-only`, no `--lang`.** Each was
  removed as a second way to reach something already reachable, or as a rendering nobody
  wanted.

---

## 12. Installation and distribution

**Installed the way `yt-dlp` is installed: one line, no root, no system packages.**
→ [ADR 0010](adr/0010-installed-like-a-system-tool.md)

```
curl -LsSf https://raw.githubusercontent.com/henricos/extract-slides/<tag>/install.sh | sh
```

`install.sh` is a shipped artefact, versioned in the repository and fetched by tag. It ensures
`uv` is present, installs `extract-slides` from the tag into an isolated environment, and puts
the entry point on the PATH. **The repository is the distribution channel** — nothing is
published to PyPI, which stays available later without rework.

- **The prerequisite list is glibc and a Python 3.12 that `uv` fetches if absent.**
- **The 464 MB model lives in the shared Hugging Face cache** (`~/.cache/huggingface`,
  `HF_HOME` respected), downloaded lazily on first use with an explicit message saying what is
  being fetched and that it happens once. `prepare` pulls that wait forward to install time.
  Portuguese adds the 1.5 GB `medium` weights. **Uninstalling does not reclaim them** — that is
  documentation, not a defect.
- **Configuration is `~/.config/extract-slides/config.toml`** (key, model, base URL), with
  environment variables overriding. A person configures once; a script passes
  `OPENROUTER_API_KEY` and writes no file.
- **One install. No optional extras, no light profile.** The profile that would have justified
  one served a transcript-only mode, which is out of scope.
- **`self-update` is the one command that cannot be freely restructured**, since it must keep
  working across the version it is updating from.
- **Nothing AGPL-licensed may be shipped.** `perelman/slide-detector` is AGPL-3.0 against this
  project's MIT, and both `.onnx` models bundled by `AutoSlides-Extractor` carry no licence,
  model card or training-data statement. All were legitimate to read and measure; none can go
  into a release artefact. Techniques are re-implemented from description.

---

## 13. Every constant in one place

| Constant | Value | Stage | Source |
|---|---|---|---|
| sample rate | 2 / s | detect, crop | [0005](adr/0005-pass-1-pinned-anchor-edge-signal-watchdog.md) |
| analysis width | 480 px | detect | [0005](adr/0005-pass-1-pinned-anchor-edge-signal-watchdog.md) |
| edge-difference trigger | ≥ 0.5 % of pixels | detect | [0005](adr/0005-pass-1-pinned-anchor-edge-signal-watchdog.md) |
| anchor dwell | ≥ 1.5 s | detect | [0005](adr/0005-pass-1-pinned-anchor-edge-signal-watchdog.md) |
| watchdog | 10 s | detect | [0005](adr/0005-pass-1-pinned-anchor-edge-signal-watchdog.md) |
| pHash | 256-bit DCT | detect, crop | [0005](adr/0005-pass-1-pinned-anchor-edge-signal-watchdog.md) |
| duplicate threshold | 0.02 of differing bits | detect, crop | [0005](adr/0005-pass-1-pinned-anchor-edge-signal-watchdog.md) |
| presenter pixel | moves in > 6 % of samples | crop | [0006](adr/0006-crop-by-cutting-the-presenter-away.md) |
| content pixel | > 45 grey levels in > 8 % of captures | crop | [0006](adr/0006-crop-by-cutting-the-presenter-away.md) |
| layout cluster | agree on ≥ 50 % of pixels | crop | [0006](adr/0006-crop-by-cutting-the-presenter-away.md) |
| minimum layout size | 3 captures | crop | [0006](adr/0006-crop-by-cutting-the-presenter-away.md) |
| blob-in-strip test | 80 % of the blob | crop | [0006](adr/0006-crop-by-cutting-the-presenter-away.md) |
| speck filter | < 10 % of the largest blob | crop | [0006](adr/0006-crop-by-cutting-the-presenter-away.md) |
| cut position | midpoint, then +1.5 % outward | crop | [0006](adr/0006-crop-by-cutting-the-presenter-away.md) |
| rectangle sanity | reject < 10 % or > 98 % of frame | crop | [0006](adr/0006-crop-by-cutting-the-presenter-away.md) |
| STT threads | 2 | transcribe | [0007](adr/0007-transcribe-with-small-and-trust-the-media-clock.md) |
| STT beam | 5 | transcribe | [0007](adr/0007-transcribe-with-small-and-trust-the-media-clock.md) |
| caption overrun tolerance | a couple of seconds | transcribe | [0007](adr/0007-transcribe-with-small-and-trust-the-media-clock.md) |
| `prune` image size | 680 px long edge | prune | [0008](adr/0008-the-deletion-pass-two-ways-to-name-the-surplus.md) |
| `prune` max tokens | 65 536 | prune | [0008](adr/0008-the-deletion-pass-two-ways-to-name-the-surplus.md) |
| slide numbering | 3 digits, widening past 999 | output | [0009](adr/0009-the-output-contract-a-table-of-instants.md) |

**None of these was tuned against a score, and none can be** — there is no metric. Where a
constant had to be chosen, it was chosen toward over-capture. Whether any of them becomes a
CLI flag is an implementation decision; the spikes exposed six and seven respectively, and the
production surface is ADR 0002's business.

---

## 14. Implementation notes that must not be lost

These are measured traps, not style preferences. Each cost a spike some time to find.

- **`cap.set(cv2.CAP_PROP_ORIENTATION_AUTO, 1.0)`** (see opencv/opencv#26795). Without it a
  phone-recorded talk carrying rotation metadata decodes sideways, and both detection and crop
  break. Carried forward explicitly from [ADR 0010](adr/0010-installed-like-a-system-tool.md).
- **On the headless OpenCV wheel, `cv2.selectROI` and `cv2.imshow` exist as attributes** —
  `hasattr` returns `True` — but raise `The function is not implemented` when called. Headless
  capability cannot be feature-detected that way.
- **`import click` will not run.** `typer` vendors it as the private `typer._click`. Falling
  back to plain click means adding a real dependency.
- **The crop needs the video, not only pass 1's images.** The movement map cannot be rebuilt
  from captures that are seconds or minutes apart, so `extract-slides crop DIR` running on its
  own requires the source video still on disk.
- **The duplicate test is nearly inert before the crop.** It compares whole frames, so a
  presenter moving in shot makes two captures of one slide look different: 27 dropped on
  `jqpdveK2XAU` while the same slide was still kept five times over. The deck actually shrinks
  in the *second* test, after the crop.
- **What a README says about a project is not evidence.** Reading twelve reference
  implementations at pinned commits found five load-bearing disagreements between
  documentation and code, two of them in this project's own research notes.
  `AutoSlides-Extractor` does **not** use SSIM — it is a single-window *global* correlation, so
  its published 0.9985 threshold is meaningless for a windowed implementation.
- **One decode pass can sweep a whole parameter grid bit-exactly** — 400 configs in 0.56 s
  against ~107 minutes of re-decoding. Worth knowing before anyone writes a re-decoding loop.
- **Re-running detection is cheap**: the whole sweep set, 45 min 55 s, runs in 2 min 45 s, and
  the analysis itself is 0.56 ms per sample. Decode is the entire cost. A persisted per-sample
  feature cache was designed and cut for this reason.

---

## 15. Known-unsolved cases, and what the tool does about them

Nothing here is a defect to fix before shipping. Each is a case where the safe answer is known
and taken.

| Case | What happens | Why it is acceptable |
|---|---|---|
| A moving camera intercutting the audience (`C5`, `C7`) | full frame, no crop | inherent to the input; the operator will rarely ask for that kind of video. **C5 and C7 are the cheapest fixtures to disappoint** — do not spend effort there |
| A corner webcam over a full-frame slide (`C4`) | full frame | cannot be removed by a straight line without taking slide with it |
| A screen filmed at an angle | full frame, no perspective correction | nobody in the field warps, and warping moves content pixels |
| A progressive build | every step plus the complete slide | telling the complete state from a partial one is pass 2's judgement call, by design and with the operator's agreement |
| A slow cross-fade that plateaus | may emit one washed-out capture | the clean state is captured too, so it is surplus |
| A slide shown, left and returned to | one interval, the return's speech lands on a neighbour | measured as narrow — the large duplicate counts are adjacent builds, not distant returns. Reopens with a case in hand, visible as speech out of place in `presentation.md` |
| Burned-in subtitles changing every phrase | continuous churn → watchdog captures | surplus, not silence, which is the trade the watchdog exists to make |
| A very short video | may get no crop at all | a layout of fewer than three captures gets no rectangle |
| A repeated slide whose best occurrence is not the last | the last survives | judged rare enough to ignore; if review keeps hitting it, the merge rule and "later survives" are where to look |
| `yt-dlp` without a JS runtime | some formats may be missing | every fixture came down anyway; the fix would be a documented optional prerequisite |
| YouTube's pt-BR ASR looked worse than both local models | unchanged — the caption is still the default path | one video. If it reproduces, what changes is which *path* is default in Portuguese, not which model |

---

## 16. What an implementation session still has to decide

The map decided *how to build the tool*. It deliberately did not decide these, and none of
them is blocked on anything:

- **Field names and JSON spelling** in `manifest.json` and `transcript.json`. The contract
  fixes what is carried and what is derived; the keys are implementation.
- **The prompt and the structured output schema `prune` sends to the model.** The endpoint
  returns a list of numbers against a JSON schema natively.
- **Which constants from §13 become CLI flags**, and their names.
- **Module boundaries, error taxonomy, logging, and the exact text of every message.** ADR 0002
  fixes the *shape* of the output — block versus line, stdout versus stderr, panel versus log —
  not the wording.
- **Test strategy.** There is no metric and no ground truth, so there is nothing to assert an
  output against beyond the structural contract. The six sweep fixtures exist as material to
  look at, not as expected values.
- **Windows and macOS.** The installer targets Linux. Nothing forbids the others; nothing
  verified them either.
- **The cadence of `self-update`.** The mechanism is decided; when to run it is the operator's.

Two things are ruled **out of scope** and should not creep back in: **writing a ground truth or
a correctness metric**, and **a slide-frame gate** (a frame that is not a slide is excess, and
excess is what pass 2 exists for; a gate in pass 1 can only lose captures). Also out of scope
for the tool itself: OCR, summarization, reconstructing an editable deck, a transcript-only
mode, a cloud container, and the agent skill that would call the CLI.

---

## 17. Where the reasoning lives

**Decisions** — [`docs/adr/`](adr/):

| ADR | What it settles |
|---|---|
| [0001](adr/0001-python-runtime-for-the-cli.md) | Python, `typer`, `>=3.12`, headless OpenCV, glibc |
| [0002](adr/0002-cli-surface.md) | the CLI surface, the output layout, resume semantics |
| [0003](adr/0003-correctness-metric-and-ground-truth.md) | **superseded** — kept as the record of three attempts at a metric |
| [0004](adr/0004-capture-generously-delete-afterwards.md) | two passes, recall over precision, no metric |
| [0005](adr/0005-pass-1-pinned-anchor-edge-signal-watchdog.md) | pass 1: edge signal, pinned anchor, watchdog |
| [0006](adr/0006-crop-by-cutting-the-presenter-away.md) | the crop cuts the presenter away and nothing else |
| [0007](adr/0007-transcribe-with-small-and-trust-the-media-clock.md) | `small`/`medium` by language, the media clock as the authority |
| [0008](adr/0008-the-deletion-pass-two-ways-to-name-the-surplus.md) | pass 2: `drop`, `prune`, one vision request |
| [0009](adr/0009-the-output-contract-a-table-of-instants.md) | the manifest, the pairing rule, JPEG |
| [0010](adr/0010-installed-like-a-system-tool.md) | one-line install, exact pins, `prepare`, `self-update` |

**Research** — [`docs/research/`](research/), read before anything was measured. Useful for
*why a candidate was on the list*; superseded by the ADRs wherever they disagree.
`youtube-captions.md`, `stt-cpu.md`, `slide-change-detection.md`, `slide-region-crop.md`, and
`reference-implementations.md` (twelve projects read at pinned commits — the densest of the
five).

**Material to look at** — [`docs/reference-set.md`](reference-set.md): six sweep fixtures,
45 min 55 s, every one verified frame by frame, spanning the classes that break naive
detectors, plus a final-validation tier of the operator's own videos. They are fixtures to
watch, not a measured reference set.
[`docs/reference-set-method.md`](reference-set-method.md) is how to find more.

**Spikes** — throwaway, evidence for the decisions, not the start of the implementation:
[`prototype/cli-surface`](https://github.com/henricos/extract-slides/tree/prototype/cli-surface),
[`prototype/pass1-detect`](https://github.com/henricos/extract-slides/tree/prototype/pass1-detect),
[`prototype/crop`](https://github.com/henricos/extract-slides/tree/prototype/crop),
[`prototype/stt`](https://github.com/henricos/extract-slides/tree/prototype/stt),
[`prototype/stt-ptbr`](https://github.com/henricos/extract-slides/tree/prototype/stt-ptbr),
[`prototype/prune-request`](https://github.com/henricos/extract-slides/tree/prototype/prune-request).
