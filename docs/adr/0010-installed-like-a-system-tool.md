# Installed like a system tool: one line, no root, exact pins, self-update

- **Status:** accepted
- **Date:** 2026-09-16
- **Ticket:** [#15 — Dependency installation, packaging and distribution](https://github.com/henricos/extract-slides/issues/15)
- **Builds on:** [ADR 0001](0001-python-runtime-for-the-cli.md) (Python, glibc, wheels-only),
  [ADR 0007](0007-transcribe-with-small-and-trust-the-media-clock.md) (the model and its
  cache), [ADR 0008](0008-the-deletion-pass-two-ways-to-name-the-surplus.md) (the AI pass)
- **Amends:** [ADR 0002](0002-cli-surface.md) — the surface gains two non-stage commands,
  `prepare` and `self-update`; [ADR 0008](0008-the-deletion-pass-two-ways-to-name-the-surplus.md)
  — the vision request is made through OpenRouter, not against Anthropic's API directly

## Decision

**`extract-slides` is a classic system CLI, installed the way `yt-dlp` is installed.** Not a
container image, not a library, and not something an agent installs into a sandbox of its
own before each use. It lands on a machine once and stays there; an agent, a script or a
person then *invokes* it like any other command.

**Installation is one line and needs no root:**

```
curl -LsSf https://raw.githubusercontent.com/henricos/extract-slides/<tag>/install.sh | sh
```

The script ensures `uv` is present (installing it into the user's own directory if not),
installs `extract-slides` from the tagged repository into an isolated environment, and puts
the entry point on the PATH. There is no `apt`, no `sudo`, no compiler, and no system
package of any kind.

**Everything is pinned to an exact version, except `yt-dlp`.**

**Two non-stage commands join the surface of [ADR 0002](0002-cli-surface.md):**

```
extract-slides prepare             # download the STT model now instead of on first use
extract-slides self-update         # update the tool and its dependencies
extract-slides self-update --yt-dlp  # update only yt-dlp, leaving the rest pinned
```

**The 464 MB model lives in the shared Hugging Face cache** (`~/.cache/huggingface` by
default, `HF_HOME` respected), downloaded on first use with an explicit message saying what
is being fetched and that it happens once.

**The AI pass of [ADR 0008](0008-the-deletion-pass-two-ways-to-name-the-surplus.md) goes
through OpenRouter, using the `openrouter` SDK** — 13 packages, 17 MB. Configuration lives
in `~/.config/extract-slides/config.toml`; environment variables override it where present.

**One install. No optional extras, no light profile.**

## Why

### There are no system prerequisites left to obtain

The ticket was written expecting a fight with `ffmpeg`, absent from the target host. There
is no fight. Measured across the spikes:

| What was feared | What was measured |
|---|---|
| `ffmpeg` needed to decode video | the `opencv-python-headless` wheel reports `FFMPEG: YES` and decoded all six sweep fixtures at 480p/720p/1080p and 25/30/50 fps |
| `ffmpeg` needed to write images | the same wheel writes JPEG; the only PySceneDetect paths that shell out are `split-video` and the MoviePy backend, neither of which is used |
| `ffmpeg` needed to decode audio | the PyAV wheel bundled with `faster-whisper` decoded YouTube's DASH m4a format 140 in about a second |
| `cmake` needed for whisper.cpp | whisper.cpp is out on other grounds, and `pywhispercpp` ships a prebuilt wheel anyway |

So the prerequisite list is glibc and a Python 3.12 that `uv` will fetch if the host has
none. That is a short enough list to be satisfied by a script rather than documented as a
chore, which is what makes the one-line installer honest rather than a wrapper hiding work.

Alpine remains ruled out, inherited unchanged from [ADR 0001](0001-python-runtime-for-the-cli.md):
`ctranslate2` and `onnxruntime` publish neither a musllinux wheel nor an sdist, so
`faster-whisper` is simply uninstallable there.

### The set that ships is seven packages, and it was measured

[ADR 0001](0001-python-runtime-for-the-cli.md) measured a 893 MB *superset* holding every
candidate on every shortlist. The spikes then chose, and nothing had re-measured what is
actually left. Taken from the imports of the three spike branches and installed clean,
wheels only:

```
opencv-python-headless  numpy  faster-whisper  yt-dlp  typer  rich  openrouter
```

**38 packages, 578 MB, 2.6 seconds, zero compilation**, and `yt-dlp` resolving to 2026.08.19
— the release that works against the PO-token gate. The seven import together in one
interpreter with no conflict; `openrouter`'s `pydantic<2.13` constraint resolves to 2.12.5
against a stack that otherwise has no opinion about `pydantic`.

Four things the superset carried are **not** in it, which is what makes the number honest:

- **No PySceneDetect.** [ADR 0005](0005-pass-1-pinned-anchor-edge-signal-watchdog.md) built
  its own detector; PySceneDetect was a measurement harness and never shipped.
- **No `ImageHash`, no `scikit-image`.** The 256-bit pHash both stages depend on is eleven
  lines over `cv2.dct`, in pass 1 and again in the crop.
- **No `sherpa-onnx`, no `pywhispercpp`.** Both were STT candidates that
  [ADR 0007](0007-transcribe-with-small-and-trust-the-media-clock.md) rejected.
- **No `opencv-contrib-*`.** The ticket flagged that OpenCV 5.0.0 moved `CascadeClassifier`
  and `HOGDescriptor` out of the base wheel, so a Haar path would need contrib. Verified on
  the installed wheel: `CascadeClassifier` is indeed gone, and nothing in the chain wants it
  — no Haar, no HOG, no DNN anywhere in pass 1 or the crop. The base headless wheel is
  correct, and it reports `FFMPEG: YES`.

### The container route is not forced, and was the wrong shape anyway

The operator's condition for reconsidering the last-resort container was that the
dependency chain could not be installed cleanly on the target host. It installs cleanly: 23
packages for the STT stack in 6 seconds, zero compilation, on a host with 96 GB free. The
condition did not fire.

But the deeper correction is about shape, not weight. A container would have been the right
answer to "an agent provisions an environment and runs the tool inside it"; it is the wrong
answer to "a tool lives on my machine and I run it". The requirement that an agent can
install and invoke it unattended is satisfied by the second reading too — `curl … | sh`
once, then a command — and the second reading is what was actually wanted.

Docker was never available to test the first reading in any case: the working container
cannot reach the Docker socket (`permission denied … /var/run/docker.sock`), which is also
what closed the route of obtaining `ffmpeg` from whisper.cpp's official image.

### Pinned, except the one dependency that breaks *because* it is pinned

Two facts pull in opposite directions and the split between them is the whole version
policy.

**Everything else must be pinned**, because the spikes measured a specific combination and
nothing re-measures it on the user's machine. `opencv-python` 5.0.0 moved
`CascadeClassifier` and `HOGDescriptor` into `opencv_contrib`; PySceneDetect's 0.7.1 and its
post-0.7.1 `main` disagree on detector defaults while reporting the *same* `__version__`
string. Floating versions turn each of these into a silent behaviour change on a machine
nobody is watching.

The instance this ticket had carried as its sharpest turned out to have expired, which is
its own argument. [#13](https://github.com/henricos/extract-slides/issues/13) found that
`faster-whisper` **1.2.0** imports `requests` without declaring it, so a clean install
raises `ModuleNotFoundError` on first use, and recorded that this project would have to
declare `requests` on its behalf. **Re-measured while closing this ticket: 1.2.1 fixed it.**
It is the current release (2025-10-31), its metadata declares its dependencies correctly,
the string `requests` appears nowhere in its code but a docstring, and a clean install pulls
no `requests` at all — `huggingface-hub` needs it only under its `gradio` extra. So the
workaround is not carried, and the constraint recorded on
[#15](https://github.com/henricos/extract-slides/issues/15) and in
[ADR 0007](0007-transcribe-with-small-and-trust-the-media-clock.md) is superseded: it was
true of the version the spike had, and the pin is 1.2.1.

**`yt-dlp` must not be pinned**, because YouTube is an adversary on a schedule. 17
YouTube-touching releases in 12 months; the target host's 2026.07.04 returns HTTP 403 for
every format on every player client (the GVS PO-token gate), while 2026.08.19 fetches
everything through the `visionos` client. A version pinned today is a tool that stops
downloading in an unpredictable number of weeks, and the failure is total, not degraded.

`--yt-dlp` on `self-update` exists because these two cadences must not be forced to move
together. The common case is "YouTube changed again", which should cost one fast update of
one dependency, not a re-resolution of the pinned stack.

### `yt-dlp` is the tool's own copy, not the host's

The tool brings `yt-dlp` as a declared dependency inside its isolated environment, and never
calls whatever binary the PATH happens to offer. The target host demonstrates why: it
carries 2026.07.04 at `/usr/local/bin/yt-dlp`, root-owned, which cannot download anything at
all. A tool that used it would fail on every video, with an error pointing at YouTube rather
than at the real cause.

This narrows, but does not contradict, [ADR 0001](0001-python-runtime-for-the-cli.md)'s
"external binaries are a first-class seam": the seam is still there, it just resolves inside
the tool's own environment rather than against the system.

One known risk stays open: `yt-dlp` warns that without a JavaScript runtime "some formats
may be missing". Every fixture in the spikes came down anyway, but this is precisely the
kind of thing that degrades between releases. If it ever bites, the fix is a documented
optional prerequisite, not a change of design.

### The abstraction over the API is exactly one SDK thick

Raw HTTP was proposed and rejected by the operator: an API called over hand-written requests
is a thing that changes and breaks, and nothing upgrades it. The question then becomes how
thick the replacement should be. Measured on the target host, clean install, wheels only:

| Candidate | Packages | Size | Last release |
|---|---|---|---|
| **`openrouter`** (official SDK) | **13** | **17 MB** | 2026-09-15 |
| `openai` (official SDK) | 14 | 24 MB | 2026-09-15 |
| `pydantic-ai-slim[openai]` | 26 | 42 MB | 2026-09-12 |
| `llm` | 29 | — | 2026-09-07 |
| `langchain-openai` | 38 | 71 MB | 2026-09-14 |
| `instructor` | 41 | — | 2026-09-09 |
| `litellm` | 55 | — | 2026-09-14 |
| `aisuite` | 10 | — | **2025-11-25** |

**LangChain is rejected on what it would buy here, not on size alone.** What it sells is
provider abstraction and validated structured output. The provider abstraction was already
bought when OpenRouter was chosen — OpenRouter *is* that layer, and stacking a second one on
top is paying twice for it. Structured output is a list of numbers, which the endpoint
returns against a JSON schema natively. What is actually delivered is 38 packages including
`langsmith` (a client for their tracing service), `tiktoken`, `websockets`, `xxhash`,
`zstandard`, and a second HTTP lineage (`httpx2`/`httpcore2`) beside the `httpx` the
transcription stack already carries — for one request, with no conversation, no tools and
no loop. `litellm` and `instructor` are the same argument at 55 and 41 packages.

`aisuite` is the cheapest at 10 packages and is rejected on maintenance: ten months without
a release is the exact failure the operator was protecting against. A thin wrapper is only
safe while someone is maintaining it.

**`openrouter` over `openai`.** Both are official, both shipped on the day this was
measured. The `openai` SDK is the more portable choice — its interface is implemented by
everyone, so the same code survives leaving OpenRouter — and it was the recommendation. The
operator chose the OpenRouter SDK, which is smaller, purpose-built for the chosen provider,
and reaches OpenRouter's own features (provider routing, automatic fallback, the `:batch`
variants at half price) as first-class calls rather than as an untyped extra field. It also
uses the same `httpx` generation the existing stack already installs, where the `openai` SDK
would add `httpx2`/`httpcore2` alongside it. The portability that is given up is cheap to
recover: the call is one function, against an endpoint whose wire format is the OpenAI one.

The cost measured in [ADR 0008](0008-the-deletion-pass-two-ways-to-name-the-surplus.md)
survives the change of route. `anthropic/claude-opus-5` is served on OpenRouter with a 1M
context and image input at $5 per million input tokens — the same number that produced
$0.37 per talk — plus OpenRouter's platform fee on credit purchases.

### The model lives in the shared cache, and downloads when it is needed

`small` is 464 MB, fetched once from the Hugging Face hub and served offline thereafter
(verified with `HF_HUB_OFFLINE=1`). Two choices were available: a tool-owned directory that
disappears on uninstall, or the shared Hugging Face cache.

The shared cache wins because it is where a user of this stack already expects it, and
because a machine that already holds those weights should not download them twice. The
honest cost is that uninstalling the tool leaves 464 MB behind; that is documentation, not
a defect, and a tool-owned cache would have traded it for a guaranteed second download.

`prepare` exists because the alternative is a first run that appears to hang. The download
happens lazily by default — that is the behaviour a person gets without reading anything —
but an unattended installation can pull it forward to install time, where a long wait is
expected.

### One install, because the profile that would justify a second one is out of scope

The caption path is genuinely prerequisite-light: no `ffmpeg`, no JS runtime, no browser,
and none of the 464 MB. That argues for a slim transcript-only install profile. It argues
for it in service of a **transcript-only mode**, which this map ruled out of scope: it would
mostly duplicate `yt-dlp`, and the only part `yt-dlp` misses is the local STT fallback,
which is exactly the part a slim profile would omit.

So the profile has no user. What it would have added is a second way to install the tool
wrongly and discover it mid-run.

### The key sits in a config file, and having it still fires nothing

Now that this is a system tool rather than something running inside an agent's environment,
the key needs a home. `~/.config/extract-slides/config.toml` holds the key, the model and
the base URL; environment variables override each of them. A person configures once; a
script or a cron passes `OPENROUTER_API_KEY` and writes no file.

This leaves [ADR 0008](0008-the-deletion-pass-two-ways-to-name-the-surplus.md)'s rule
intact, and it is worth restating because a config file makes it easier to forget: a key
being present enables the `prune` command, and enables nothing else. No run deletes anything
because credentials happen to exist.

## Consequences

- **`install.sh` is a shipped artefact**, versioned in the repository and fetched by tag.
  It ensures `uv`, installs from the tag, and fixes the PATH.
- **The repository is the distribution channel.** Nothing is published to PyPI. That stays
  available later without rework, and would only be worth doing for third parties.
- **`pyproject.toml` carries exact pins** for the seven direct dependencies measured
  above. `yt-dlp` is declared with a floor, not a pin. `opencv-python-headless`, never
  `opencv-python` and never `opencv-contrib-*`; if PySceneDetect is ever added as a spike
  harness, `scenedetect-headless` is the distribution name, since plain `scenedetect`
  declares the GUI `opencv-python` and collides with this pin under the same `cv2` import
  name.
- **`self-update` is part of the CLI surface** and must keep working across the version it
  is updating from, which makes it the one command that cannot be freely restructured.
- **Uninstalling does not reclaim the model.** Documented, with the path and the command to
  remove it.
- **Nothing AGPL-licensed may be shipped.** `perelman/slide-detector` is AGPL-3.0 against
  this project's MIT, and both `.onnx` models bundled by `AutoSlides-Extractor` carry no
  licence, model card or training-data statement. All were legitimate to read and measure;
  none can go into a release artefact. Techniques are re-implemented from description.
- **The first run after installation is slow and says so**, or `prepare` was run.
- **One implementation note must survive this ticket's closure.** `cap.set(cv2.CAP_PROP_ORIENTATION_AUTO, 1.0)`
  (citing opencv/opencv#26795) was recorded here while reading the reference
  implementations: without it, a phone-recorded talk carrying rotation metadata decodes
  sideways and breaks both detection and crop. It is implementation, not packaging, and
  belongs in `docs/stack.md` ([#16](https://github.com/henricos/extract-slides/issues/16)).
  The other note filed beside it — that PySceneDetect's `StatsManager.load_from_csv()` is
  deprecated toward a no-op — is moot, since PySceneDetect does not ship.
- **The dependency that [#17](https://github.com/henricos/extract-slides/issues/17) would
  have added never arrives.** A learned slide-frame gate would have brought an OpenCV DNN
  path plus an unlicensed model file; the gate was ruled out of scope, and it was the
  blocker that held this ticket longest.

## What this decision does not decide

- **Whether `prune` can send ~210 images in one request over this route.**
  [ADR 0008](0008-the-deletion-pass-two-ways-to-name-the-surplus.md) rests on limits
  measured against Anthropic's API directly (600 images per request on 1M-context models, a
  32 MB request ceiling). OpenRouter documents no such limits and states that they vary by
  provider and model, and there is a public report of `too many images and documents:
  27 + 0 > 20` surfacing through it. Changing the route put this premise in doubt;
  [#23](https://github.com/henricos/extract-slides/issues/23) settles it.
- **Windows and macOS.** The installer targets Linux, which is where the tool runs. Nothing
  here forbids the others; nothing here verified them either.
- **How often anyone actually runs `self-update`.** The mechanism is decided; the cadence is
  the operator's.
