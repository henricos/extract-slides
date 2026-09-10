# Python is the runtime and language for the CLI

- **Status:** accepted
- **Date:** 2026-09-09
- **Ticket:** [#2 — Runtime and language for the CLI](https://github.com/henricos/extract-slides/issues/2)

## Decision

`extract-slides` is a Python CLI. The pipeline's three hard stages — slide-change
detection, slide-region cropping and local speech-to-text — are all measured from Python,
and every candidate on the detection and crop shortlists is reachable there as a prebuilt
wheel, with external tools invoked as subprocesses where a candidate *is* an external tool.

## Why

Python was not chosen on ecosystem reputation. It was chosen because it reaches the whole
shortlist without compiling anything, and Node does not.

**Measured on the target host (Intel i3-4170, 2 physical cores, no GPU, Ubuntu 24.04
container over a Debian 12 host):**

- `uv pip install --only-binary :all:` — which fails if any package needs a source build —
  succeeded for `opencv-python-headless` 5.0.0.93, `scenedetect` 0.7.1, `ImageHash` 4.3.2,
  `scikit-image` 0.26.0, `faster-whisper` 1.2.1, `ctranslate2` 4.8.2, `sherpa-onnx` 1.13.7,
  `pywhispercpp` 1.5.1 and `yt-dlp`. Zero compilation, 893 MB for the full superset.
- `pywhispercpp` shipping a prebuilt wheel means whisper.cpp is reachable **without**
  `cmake` and without a source build.
- The `opencv-python` wheel reports `FFMPEG: YES`, `Parallel framework: pthreads` and
  dispatch for `SSE4_1 SSE4_2 AVX FP16 AVX2 AVX512_SKX`. It wrote and re-read an mp4 with
  no system `ffmpeg` present, backend `FFMPEG`. `PyAV` 18.1.0 (a `faster-whisper`
  dependency) bundles `libavcodec` 62 / `libavformat` 62, so audio decodes too.

**Why not Node/TypeScript.** It would narrow the shortlists rather than the reverse:

- No maintained native OpenCV binding exists. `opencv4nodejs` declares itself abandoned in
  its own README (last publish 2020-05-13); the `@u4/opencv4nodejs` fork has no prebuilt
  npm binaries and compiles the native addon on every install (last npm release
  2024-09-13, last code commit 2025-06-18).
- The only actively published option is the WASM build `@techstark/opencv-js`, whose own
  embedded build information reads `USE_PTHREADS=0`, `Parallel framework: none`, an empty
  SIMD baseline, and `Disabled: highgui imgcodecs stitching videoio world` — single-core,
  no SIMD, and no video decoding at all. On a two-core host this is the worst available
  case.
- No Node library offers a configurable-size DCT perceptual hash. `sharp-phash` hardcodes
  `SAMPLE_SIZE = 32` / `LOW_SIZE = 8`, i.e. 64 bits — and `docs/research/slide-change-detection.md`
  measured a real slide edit at Hamming distance **exactly 0** at that hash size, which is
  precisely why the research requires `hash_size >= 16`. `imghash` reaches 256 bits but is
  Blockhash, a different algorithm.
- `ssim.js`, the de-facto Node SSIM, is an archived repository (read-only, last publish
  2020-10-12) and defaults to a non-reference algorithm with silent downsampling.
- There is no Node equivalent of PySceneDetect — no adaptive detector, no per-frame stats
  export, which is exactly what makes PySceneDetect the rank 2 and 3 detection candidate.
- `yt-dlp` is always a subprocess from Node; Python can drive the `YoutubeDL` class
  in-process.

Node's one genuine advantage, `sherpa-onnx-node` shipping prebuilt binaries with no
compile step, is matched by the `sherpa-onnx` Python wheel.

**Why not a split** (thin CLI in one language, heavy lifting in the other). It pays for two
runtimes and two package managers and buys nothing, since "no Python runtime needed" was
explicitly not a goal.

## Consequences

- **CLI framework:** `typer` with `rich_markup_mode=None`. `typer`'s default help draws
  bordered rich panels, which this project rejects; with rich markup off it delegates to
  click's plain formatter — indented, two-column, explicit defaults, no boxes. `cyclopts`
  was rejected because its panels are structural (`HelpPanel` in `cyclopts/core.py`) with
  no plain mode. `click` alone renders the same output; `typer` was preferred for
  type-hint-driven declaration, which is easier for an agent to read and modify, and it
  remains reversible because `typer` is `click` underneath — but see the amendment below
  on what "underneath" now means.
- **`rich` usage:** allowed for the program's own progress output and final report, where
  richer formatting is wanted. Never as a bordered panel **in `--help`** — see the
  amendment below.
- **Python floor:** `requires-python = ">=3.12"`, the Ubuntu 24.04 ruler. Note the
  measured alternative: the whole stack also installs on 3.11 wheels-only, resolving
  identical versions except `numpy` 2.4.6 instead of 2.5.3. `>=3.12` was chosen anyway to
  keep a single target. Consequence: the Debian 12 bookworm host (Python 3.11.2) needs an
  interpreter fetched by `uv` rather than its system Python.
- **OpenCV:** `opencv-python-headless` only, always headless — this is a CLI tool. The
  manual-ROI escape hatch required by the crop shortlist is a CLI flag taking four
  normalised floats; `cv2.selectROI` is not used. Note the trap: on the headless wheel
  `cv2.selectROI` and `cv2.imshow` **exist as attributes** (`hasattr` returns `True`) but
  raise `The function is not implemented` when called, so capability cannot be
  feature-detected that way.
- **The base image must be glibc.** Alpine is ruled out, and not over Python versions:
  `ctranslate2` 4.8.2 and `onnxruntime` 1.29.0 publish **neither a musllinux wheel nor an
  sdist**, so they are simply uninstallable there — which removes `faster-whisper`, the
  rank 1 STT candidate. `opencv-python-headless` and `sherpa-onnx` would each need a source
  build. Use `ubuntu:24.04` or `debian:12/13-slim`. This constraint is inherited by
  [#15](https://github.com/henricos/extract-slides/issues/15).
- **External binaries are a first-class seam.** `yt-dlp`, `whisper-cli`, `ffmpeg` and the
  Node tool in the detection shortlist are invoked as subprocesses.
- **System prerequisites may require root.** Installing `ffmpeg` or `cmake` via the package
  manager is acceptable and preferred over duplicating a normally system-wide package into
  a user directory. What is avoided is *compiling at install time*. Note that `ffmpeg` is
  not needed for the core pipeline (the wheels carry their own decoders); it is needed only
  to measure the candidates that *are* ffmpeg.
- **Spikes are written in Python**, except that a candidate which *is* an external tool is
  measured as-is by invoking it, not reimplemented to stay in-language. Spike code remains
  disposable.
- **Python-version syntax:** 3.12 features are permitted, since the floor is 3.12.

## What this decision does not decide

No component is selected here. Every candidate on the detection shortlist
(`docs/research/slide-change-detection.md` §10) and the crop shortlist
(`docs/research/slide-region-crop.md` §9) remains reachable, so
[#11](https://github.com/henricos/extract-slides/issues/11) and
[#12](https://github.com/henricos/extract-slides/issues/12) choose freely.
[#13](https://github.com/henricos/extract-slides/issues/13) was never gated by this ticket
and still picks the STT runtime and model on measurement.

## Amendments

### 2026-09-10 — `typer` vendors `click`, and boxes are banned only in help

Both from [#3](https://github.com/henricos/extract-slides/issues/3), while building the
CLI surface mock. Neither changes the decision; both correct a consequence stated above.

**`typer` 0.27.2 vendors `click`.** There is no importable `click` module installed
alongside it: it lives as the private `typer._click`. Two effects.

- "Reversible because `typer` is `click` underneath" is still true in substance, but
  falling back to plain `click` now means **adding a real dependency**, not dropping a
  wrapper off something already present.
- Subclassing for CLI behaviour goes through `typer.core.TyperGroup`. Measured: the
  verbless default path in [ADR 0002](0002-cli-surface.md) needed exactly this, and it
  worked using only standard `Group` method overrides (`parse_args`, `list_commands`,
  `format_usage`) with **no private imports**. So the cost is modest, but code that does
  `import click` will not run.

**"Never as a bordered panel" is scoped to `--help`.** The original reasoning was about
`typer`'s help panels, which fragment reference text the reader scans. It over-generalised
to all `rich` output. A border does earn its keep on the **final report**: a discrete
block of result, read at a glance, visually distinct from the log above it. The running
log stays borderless and uses indentation, symbols and whitespace instead. See
[ADR 0002](0002-cli-surface.md).
