# Slide-region isolation and webcam overlay handling

Research for [issue #8](https://github.com/henricos/extract-slides/issues/8). Facts and citations only — the choice
between the candidates below is made by the crop spike ([issue #12](https://github.com/henricos/extract-slides/issues/12)),
measured against the reference set.

`docs/similar-tools.md` already records *that* four strategies exist. This note reads the code behind each one, and the
headline result is that the strategy table in that document overstates what the prior art achieves: **no surveyed project
actually crops a frame to an automatically-detected slide region.** Everything else here follows from that.

Scan date: September 2026. Every claim carries the URL of the source that owns it. Where a number was measured locally
rather than published, it is labelled as such.

---

## Summary of findings

> **Amended by [`reference-implementations.md`](reference-implementations.md), which read the source of
> eleven more projects.** Finding 1 below was verified at the same commits and holds for every project
> this document surveyed — and now holds against the learned state of the art too, which hand-labels
> one rectangle per video in a text file. But it is **not true of the whole field**:
> `bit-admin/AutoSlides-Extractor` ships `AutoCropDetector`, 552 lines of complete, tuned, `cv2`-only
> slide-bbox detection — black-bar strip, Canny(20/60), dilate, 4-vertex contours, area/margin/fill
> gates, and a score of `areaRatio × aspectScore` against 16:9 and 4:3 — plus a single-class YOLOv8.
> Nobody had read it. It belongs above plain letterbox removal in the candidate ranking, and what it
> lacks is the recall-first fallback: when no contour passes its five gates it returns nothing. See
> [§B.7](reference-implementations.md#b7-auto-crop-12-is-not-greenfield).

1. **The prior art does not solve this.** `vid2slides` is the only project that attempts automatic crop detection, and
   its detector reduces to "strip pixels that are near-pure-black in every slide keyframe" — a letterbox-bar remover, not
   a slide-region detector. `kovitking/video2slides` detects the webcam box well but only masks it *for hashing* and
   saves the **unmasked** full frame. `antonkulaga` masks corners *for change detection only*. Only the two manual tools
   (`sumerene`, `bibo242`) alter the output image at all. See [§1](#1-what-the-prior-art-actually-does).
2. **`vid2slides` computes the webcam location and then throws it away.** `pip_location` is written to its JSON output
   and read by nothing. The "find the webcam by clustering face detections" idea exists in code but was never wired to a
   mask or a crop. See [§1.1](#11-vid2slides).
3. **The "slide in a small box next to a big webcam" layout is not what call platforms produce.** Zoom documents the
   speaker thumbnail in a screen-share cloud recording as **fixed 224×126 px, fixed top-right** — 1.4 % of a 1080p frame.
   Google Meet documents the recording resolution as *derived from* the shared screen. Microsoft documents nothing about
   Teams recording geometry. The inset-slide case therefore comes from presenter-side composition (OBS-style), from a
   Zoom **local** recording with "Place video next to the shared screen", or from post-production — not from the default
   platform output. See [§2](#2-where-the-slide-in-a-small-box-input-actually-comes-from).
4. **`ffmpeg cropdetect` in its default mode only finds *black* borders**, so it cannot find a slide sitting on a grey
   call background. Its `mode=mvedges` (FFmpeg 6.0+) *can* find a non-black embedded region, but it locks onto the
   **moving** sub-region — which on a talk recording is the presenter, not the slide. See [§3.1](#31-black-bar--letterbox--pillarbox-removal).
5. **OpenCV ships an official quadrilateral detector** (`samples/python/squares.py`) and an officially tuned version of
   the same pipeline inside the ArUco detector, with resolution-independent size gates. Neither is documented as a
   document/screen detector, and OpenCV ships nothing purpose-built for finding a screen or document region.
   See [§3.2](#32-quadrilateral--contour-detection) and [§7](#7-is-there-a-library-that-solves-find-the-slide-rectangle).
6. **Plain per-pixel temporal variance fails; median-of-consecutive-differences works.** This is a documented, empirically
   established negative result from `kovitking/video2slides`' own design notes: a real slide change is a rare but huge
   whole-frame jump, and variance is dominated by rare large values, so the whole frame reads as high-variance. The median
   of short-baseline frame differences filters those spikes out. See [§3.3](#33-temporal-statistics-the-strongest-deterministic-signal).
7. **Haar cascades are no longer OpenCV's recommendation, and in OpenCV 5 they are not even in the main package.**
   OpenCV's own roadmap calls the old `objdetect` algorithms *"'ancient'"* and moved `cv::CascadeClassifier` and
   `cv::HOGDescriptor` to `xobjdetect` in `opencv_contrib`; the migration guide points new projects at
   `cv::FaceDetectorYN` (YuNet) as *"both faster and more accurate"*. YuNet is MIT, ~227 KB, ~0.7 ms per 160×120
   inference on a desktop CPU, and — decisively for a small webcam tile — has an **absolute** published detection range
   of *"around 10x10 to 300x300"* pixels. MediaPipe BlazeFace is documented **out of scope** for this case: its size
   floors are *frame-relative* (short-range ≥ 20 % of the image side, full-range ≥ 5 %), and a face inside a
   sixth-of-frame-width tile sits at roughly 8 %. OpenCV's bundled upper-body cascade README says outright *"Don't
   expect these detectors to be as accurate as a frontal face detector."*
   See [§4](#4-face-and-person-detection-as-a-negative-signal).
8. **Nothing off the shelf answers "where is the screen in this frame".** The `opencv_zoo` model inventory has no
   document/screen/quad model; `doctr`, PaddleOCR/PP-DocLayout, `docling` and `kornia` all solve adjacent problems; the
   neural document localizers that do exist (`DocScanner`, `DocTr`) are research-licensed and trained on paper documents.
   The one maintained, permissive, pip-installable corner detector (`DocAligner`) is out of domain and pulls
   `onnxruntime_gpu` on Linux. See [§7](#7-is-there-a-library-that-solves-find-the-slide-rectangle).
9. **Perspective correction is almost certainly unnecessary** for this project's primary input. A screen recording or a
   call recording contains an axis-aligned upright rectangle; homography only matters for a camera filming a projected
   screen at an angle. See [§8](#8-perspective-correction-when-it-is-and-is-not-needed).

---

## 1. What the prior art actually does

Read at source level, at pinned commits. `docs/similar-tools.md` describes the *intent* of each strategy; this section
describes the code.

### 1.1 `vid2slides`

Source: [`vid2slides.py` @ `62121168`](https://github.com/patrickmineault/vid2slides/blob/62121168143d0576aa0990530c2af0d6dba629ec/vid2slides/vid2slides.py),
[`slides2pdf.py`](https://github.com/patrickmineault/vid2slides/blob/62121168143d0576aa0990530c2af0d6dba629ec/vid2slides/slides2pdf.py).

The whole crop detector is `extract_crop()`, 12 lines:

```python
A = np.stack(ims, axis=0)                      # ims = mean-over-channels of every 'slide' keyframe
broad_crop = (A.mean(axis=0) > .2).astype(np.uint8)
contours, _ = cv2.findContours(broad_crop, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
# keep the largest contour by cv2.contourArea, return cv2.boundingRect(contour)
```

The load-bearing detail is the threshold. `cv2.imread` returns uint8 0–255, so `im.mean(axis=2)` is on a 0–255 scale, and
`> .2` therefore means **"mean intensity above 0.2/255 across all slide keyframes"** — i.e. *"not essentially pure
black"*, not a 20 % brightness threshold. In practice the mask is 1 almost everywhere and the crop only strips regions
that are near-black in **every** slide keyframe: letterbox/pillarbox bars and black padding around a shared screen.
Nothing grey, white or coloured is removed.

The author's own demo output confirms it: the OCR text of the shipped demo contains
`00:01:06 - Adobe Acrobat Reader DC Anzeige Unterschreiben Fenster Hilfe`
([`demo/91004320940_1_out.txt`](https://github.com/patrickmineault/vid2slides/blob/62121168143d0576aa0990530c2af0d6dba629ec/demo/91004320940_1_out.txt))
— the Acrobat menu bar survived the crop in the project's showcase.

Other facts:

- **Computed once per video**, from every keyframe classified `type == 'slide'` (not a fixed sample count), and applied
  identically to every output frame (`slides2pdf.py:12-13`).
- Crop is computed on the hi-res keyframes (fitted to 1920×1080); face detection and change detection run on 360×202
  thumbnails sampled every 2 s.
- **Face detection has two uses.** (a) A face wider than 25 % of the thumbnail height marks the frame `has_full_face`;
  those frames are excluded from keyframe selection and from the HMM entirely — a *temporal* filter, not a spatial one.
  (b) Small faces are pooled across the whole video and clustered with `sklearn.cluster.KMeans()` at its **default
  `n_clusters=8`**; the centroid of the most populous cluster becomes `pip_location`. **`pip_location` is read by
  nothing** — not `slides2pdf.py`, not `slides2gif.py`, not `slides2chapters.py`. The crop is entirely independent of
  face detection.
- Model: a vendored `haarcascade_frontalface_default.xml`, run as `detectMultiScale(im, 1.1, 4)` on the **colour**
  thumbnail (not grayscale, not histogram-equalised), with no `minSize`.
- Failure modes visible in the code: an all-ones mask (no visible border, slide bleeding to the frame edge) makes the
  crop a **no-op**; a truly `#000000` slide background can invert the crop into "everything except the slide";
  `np.stack([])` raises if no frame was classified as a slide; `x, y, w, h` are never assigned if no contour is found
  (`UnboundLocalError`).
- **No license file** — `gh api repos/patrickmineault/vid2slides --jq .license` returns `null`. All rights reserved.
  Read for ideas; do not copy code.
- Also dead on modern stacks: `np.int` (removed in NumPy 1.24+), `moviepy.editor` (removed in MoviePy 2.x),
  `decord==0.4.2`, `opencv-python==4.4.0.46`, Python 3.8.5 pinned in `environment.yml`.

### 1.2 `kovitking/video2slides`

Source: [`webapp/static/app.js` @ `2e16e89`](https://github.com/kovitking/video2slides/blob/2e16e894d6bab283a35505c390f5f8888695261f/video2slides/webapp/static/app.js),
[`PLAN.md`](https://github.com/kovitking/video2slides/blob/2e16e894d6bab283a35505c390f5f8888695261f/video2slides/PLAN.md).

The PiP detector (`detectPipBbox`) is the most interesting piece of prior art in the whole scan:

- Working resolution `min(240, videoWidth)` wide (≈240×135 for 16:9).
- `n = clamp(floor(duration / 2), 2, 60)` sample **pairs**, pair start times spread uniformly across the whole video,
  the two frames of a pair **1.0 s apart**.
- Per pair, a full per-pixel absolute grayscale difference map; all `n` maps retained (≈15 MB at 60 pairs).
- Exact per-pixel **median** across the `n` difference values.
- **Fixed absolute threshold `PIP_DIFF_THRESHOLD = 4.0`** on the 0–255 scale — not adaptive, not a percentile, not
  configurable from the UI.
- Mask → rectangle is a **single global min/max scan**: no connected components, no morphology, no clustering. Then a
  plausibility gate: `area > 0.01·frameArea && area < 0.35·frameArea && boxW < 0.6·workW && boxH < 0.6·workH`, then
  scale up, pad 6 px, clamp. Failing the gate returns `null` and the run proceeds **unmasked, with no warning**.

Two things about it matter for this project:

- **It masks, it does not crop, and the saved image is unmasked.** The mask is applied only on the hashing path; pass 2
  captures the slide image with a code comment saying so verbatim: *"Saves the UNMASKED frame — the PiP mask is only used
  for hashing."* The exported PDF contains the webcam overlay. There is no crop, no boundary detection and no perspective
  code anywhere in the repo.
- **The single-bbox scan is a regression from its own deleted Python version.** At the initial commit,
  [`process_video.py` @ `dfe8404`](https://github.com/kovitking/video2slides/blob/dfe8404bd31a08bca5b45a2aa97256b1c14a0f2d/video2slides/process_video.py)
  did `morphologyEx(MORPH_CLOSE, 15×15)` → `MORPH_OPEN, 9×9` → `findContours(RETR_EXTERNAL)` → per-contour `boundingRect`
  → the same 1 %/35 %/0.6 gates per contour → merge contours within 40 px of the largest. The JS port dropped all of it,
  so one stray moving pixel (a clock, an animated watermark, a taskbar) now inflates the single box.

Detection runs **exactly once per video**, cached in a module-level `pipBbox`; it cannot adapt to a mid-video layout
change, and the web UI exposes no manual override (the deleted CLI had `--pip-box x,y,w,h` and `--no-pip`).

Its own validation numbers, from `PLAN.md`: on a synthetic 24 s video (4 slides × 6 s plus a corner box with a circle
moving every frame), masking gave **4/4** slides and `--no-pip` gave **1/4** — a moving overlay collapses naive
perceptual hashing. Documented open problem: *"Multiple PiP boxes: some webinar tools show two presenters side by side …
hasn't been tested against two separated boxes on opposite corners"* — and the merge logic that would have handled it no
longer exists.

**No license** (`license: null`, no `LICENSE` file). Not reusable as code.

### 1.3 `antonkulaga/video2slides` — blanket corner masking

Source: [`video2slides/converter.py` @ `50479c0`](https://github.com/antonkulaga/video2slides/blob/50479c00106f12bf3ec7b0efac77fc42847dbae0/video2slides/converter.py).

Masks **all four corners**, `corner_size_percent = 0.15` applied to width and height **independently** (so 288×162 px
each at 1080p; 2.25 % of frame area per corner, 9 % total). Configurable via `--ignore-corners/--no-ignore-corners` and
`--corner-size`. The comment in the code is honest about why all four: *"typically bottom-right for speaker, but mask all
for safety"*.

The mask is **comparison-only**. It feeds `_compute_frame_similarity` → SSIM gate (`similarity_threshold = 0.95`, frames
downscaled to 480 px height); the frame written to disk is the untouched `cap.read()` result. There is no crop or ROI
anywhere in the repo. README claims MIT but ships no `LICENSE` file and the API reports `license: null`.

### 1.4 `sumerene/video2slides` — manual ROI, and a documented negative result

Source: [`scripts/detect_roi.py` @ `65b2a77`](https://github.com/sumerene/video2slides/blob/65b2a777709cd2811282bc8700452029cb5cc64f/scripts/detect_roi.py),
[`SKILL.md`](https://github.com/sumerene/video2slides/blob/65b2a777709cd2811282bc8700452029cb5cc64f/SKILL.md). **MIT licensed** —
one of only two in the scan that actually is.

Zero automatic detection, by design. Flow: extract the frame at t = 10 s → the user draws a **red rectangle** on it in an
external image editor → the script recovers the ROI as the bounding box of red pixels via two HSV hue bands
(`[0,100,100]–[10,255,255]` and `[160,100,100]–[180,255,255]`) → coordinates normalised to 3 decimals so they are
resolution-independent → 5 evenly spaced sample frames are cropped for the user to confirm → the ROI is passed to the
extractor as `--roi x1 y1 x2 y2`. The ROI is applied statically to every frame, and **the cropped ROI is what gets
written** — unlike every other project here.

Its `SKILL.md` records the most useful negative result in the scan, under the heading *"不可靠的方法（不要用）"*
("Unreliable methods — do not use"):

- *"CV edge detection / brightness analysis / Sobel projection: meeting decorations (logos, title bars, separator lines)
  have brightness/edge characteristics similar to PPT content, so they cannot be distinguished."*
- *"Multimodal LLM reading the image to give coordinates: measured deviation is large, still includes decoration areas,
  unreliable."*

It also mandates asking up front whether the video needs an ROI at all: *"Full-screen screen recordings don't; PiP /
conference livestreams do."* Two adjacent details worth noting: a **Laplacian-variance gate**
(`cv2.Laplacian(gray, CV_64F).var() < 300 → skip`) discards speaker close-ups and transitions, and dedupe requires pHash
**and** dHash to agree.

### 1.5 `bibo242/Video2Slides-Pro` — manual mask tool

Source: [`app.py` @ `710127f`](https://github.com/bibo242/Video2Slides-Pro/blob/710127f3bb435afc05efc8b2299ec5014b8a9d10/app.py),
[`core/pipeline.py`](https://github.com/bibo242/Video2Slides-Pro/blob/710127f3bb435afc05efc8b2299ec5014b8a9d10/core/pipeline.py).

A Streamlit wizard step with four pixel sliders (`X`, `Y`, `Width`, `Height`), four one-click corner presets each 25 % of
width × 25 % of height, a colour picker, and a *"Pick from Slide"* button that averages the pixels inside the rectangle so
the mask blends into the slide background instead of being a black box. **One** rectangle only; static for the whole
video; no per-timestamp mask.

The mask is applied as an **ffmpeg `drawbox` filter appended to the frame-extraction chain**, so it is burned into every
extracted frame and therefore into the exported PDF/ZIP/PPTX:

```python
vf += (f",drawbox=x={mask['x']}:y={mask['y']}:w={mask['w']}:h={mask['h']}:color={drawbox_color}@1:t=fill")
```

Separately there is a `center_crop_ratio = 0.70` centre crop used **only** to build the SSIM comparison thumbnail and the
blank-frame check — never applied to output. The review gallery lets the user delete slides and resolve similar pairs
(pairwise SSIM matrix, adjustable threshold, default 0.80); it does **not** let the user revise the mask without redoing
the step and re-extracting. The CLI (`extract_slides.py`) exposes no mask option at all — masking is GUI-only. README
claims MIT, no `LICENSE` file, API reports `license: null`.

### 1.6 `binh234/video2slides` — no crop at all

Source: [`bg_modeling.py` @ `ceaf516`](https://github.com/binh234/video2slides/blob/ceaf516d3099d96a42ebbab742ac416717230ada/bg_modeling.py),
[`frame_differencing.py`](https://github.com/binh234/video2slides/blob/ceaf516d3099d96a42ebbab742ac416717230ada/frame_differencing.py). MIT.

Detects changes only. No crop, no ROI, no mask, no corner handling, no face detection. The only geometry operation is a
downscale to 640 px wide for speed; both capture paths write the full original frame. Consequence: a webcam PiP moving in
a corner is indistinguishable from a slide change — motion anywhere in the frame drives capture.

### 1.7 Cross-cutting conclusions

- **Two problems are routinely conflated.** (a) Excluding the overlay from *change detection* — `antonkulaga`'s corner
  mask, `bibo242`'s centre crop, `kovitking`'s median-diff mask, `vid2slides`' full-face frame rejection. Cheap and
  effective. (b) Excluding it from the *output image* — only `sumerene`'s ROI crop and `bibo242`'s `drawbox` do this,
  and both are manual. **This project's requirement is (b).**
- **Licensing.** Only `sumerene/video2slides` and `binh234/video2slides` are actually MIT-licensed. `vid2slides` and
  `kovitking/video2slides` have no license at all; `antonkulaga` and `bibo242` claim MIT in their READMEs but ship no
  `LICENSE` file. Techniques can be reimplemented; code cannot be copied.

---

## 2. Where the "slide in a small box" input actually comes from

`docs/idea.md` motivates the crop with "a smaller box in a corner, next to the speaker's webcam feed or a video-call UI".
Checking that against the vendors' own documentation changes the priority order of the work.

### Zoom — documented in detail

[Frequently asked questions about Zoom recording](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0061246):

> "The resolution of the video thumbnail is **fixed to 224 by 126 pixels**. If the shared screen resolution is very large
> (for example, 4K resolution), the thumbnail will be small in comparison."
> "**The position of the video thumbnail is fixed in the top-right corner.**"

224×126 in a 1920×1080 frame is 1.4 % of the frame area. That is an overlay, not a layout.

[Adjusting recording video layouts](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0062314) gives only
two **cloud** screen-share layouts — "Shared content only" and "Shared content with active speaker" (tile "in the
top-right corner next to the shared content") — with the note:

> "Cloud recordings only capture the active speaker during screen sharing. **To prevent the speaker's tile from
> overlapping the shared content, set the resolution of the shared content to 1600x900.**"

i.e. by default the tile *overlaps* full-frame content; the side-by-side geometry only appears if the presenter
deliberately shrinks the shared content. The genuine inset case is a **local** recording option: *"Share with participants
video next to shared content"* (requires both "Record video during screen sharing" and "Place video next to the shared
screen"). Zoom does not document the resulting geometry.

Other Zoom facts worth knowing for detection:

- Separate files per layout are supported; the cloud-recording API enumerates `shared_screen`,
  `shared_screen_with_speaker_view`, `shared_screen_with_gallery_view`, `active_speaker`, `gallery_view`, …
  ([Zoom Meeting API](https://developers.zoom.us/docs/api/meetings/#tag/cloud-recording)).
- A documented **green border around the shared area** appears in some cloud recordings: *"The green box is used to
  indicate the shared area during the meeting. The green border only appears in cloud recordings when you have a 2-core
  computer and enable the option to optimize for full-screen video."* (KB0061246). Both an exploitable edge cue and a
  potential false positive.
- Optional per-tile name banner: *"Display participants' names in the recording: Add participants' name to the
  bottom-right corner of their video."*
  ([KB0064676](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0064676)).
- Black bars are documented on mobile: *"the narrower screen may add black bars to the sides of video or shared
  screens."* (KB0062314).
- Zoom's meeting **toolbar** is never described as recorded — recordings are composed from streams, not captured from the
  Zoom window.
- Which layout is the **default is not documented** in any of KB0062314, KB0064676, KB0065362 or KB0081993.

### Google Meet

[Record a video meeting](https://support.google.com/meet/answer/9308681):

> "**Video recordings include the active speaker and anything presented.**"
> "**Other windows or notifications aren't saved in the recording.**"
> "If you pin a participant to your screen, it won't change who's shown in the recording."
> "If a screen is shared in a recorded meeting, **the video resolution depends on the resolution of the largest screen
> shared, which is up to 1080p.**"

So: composed server-side, independent of the recorder's own view, and the frame size is derived from the shared screen.
Google **does not document** the tile geometry, size or position, and says nothing about letterboxing.

### Microsoft Teams

[Record a meeting in Microsoft Teams](https://support.microsoft.com/en-us/office/record-a-meeting-in-microsoft-teams-34dfbe7f-b07d-4a27-b4c6-de62f1348c24)
and [Teams meeting recording (admin)](https://learn.microsoft.com/en-us/microsoftteams/meeting-recording) document that
recording "captures audio, video, and screen-sharing activities", that no more than four video streams appear at once,
and that whiteboards, annotations, shared notes, app-shared content and *"videos or animations embedded in PowerPoint Live
presentations"* are **not** captured. **The recording geometry during a screen share is not documented at all.**

### Aspect-ratio priors

- PowerPoint: *"The 16:9 widescreen setting is the default value for new presentations you create"*; Standard 4:3 is
  10 × 7.5 in, Widescreen 13.333 × 7.5 in
  ([Microsoft](https://support.microsoft.com/en-us/office/change-the-size-of-your-slides-040a811c-be43-40b9-8d04-0de5ed79987e)).
- Google Slides offers Widescreen 16:9 and 16:10 plus custom sizes
  ([Google](https://support.google.com/docs/answer/3447672)).
- YouTube: *"The standard aspect ratio for YouTube on a computer is 16:9"*, the player adapts rather than baking bars,
  and creators are told to *"avoid adding padding or black bars directly to your video"*
  ([Google](https://support.google.com/youtube/answer/6375112)). Any bars in a downloaded file were therefore baked in by
  the recorder or the screen-share scaling, not by YouTube.

**Consequence for the shortlist:** the dominant real-world case is *full-frame slide, plus a small corner overlay, plus
possible black bars*. A crop strategy that handles black bars and the corner overlay covers most of the ground; a strategy
that finds a genuinely inset slide rectangle is the exception case, and it is also the one with the least prior-art
support.

---

## 3. Deterministic building blocks

### 3.1 Black-bar / letterbox / pillarbox removal

**`ffmpeg cropdetect`** ([filter docs](https://ffmpeg.org/ffmpeg-filters.html),
[`doc/filters.texi`](https://github.com/FFmpeg/FFmpeg/blob/master/doc/filters.texi),
[`libavfilter/vf_cropdetect.c`](https://github.com/FFmpeg/FFmpeg/blob/master/libavfilter/vf_cropdetect.c)):

> "Auto-detect the crop size. It calculates the necessary cropping parameters and prints the recommended parameters via
> the logging system. The detected dimensions correspond to the non-black or video area of the input video according to
> `mode`."

| option | default | notes |
|---|---|---|
| `mode` | `black` | `black` = "Detect black pixels surrounding the playing video"; `mvedges` = detect the playing video from motion vectors + edge pixels |
| `limit` | `24` | "An intensity value greater to the set value is considered non-black." Also accepts 0.0–1.0, scaled by bit depth |
| `round` | `16` | "The value which the width/height should be divisible by… Use 2 to get only even dimensions" |
| `skip` | `2` | initial frames whose evaluation is skipped |
| `reset_count` / `reset` | `0` | "0 indicates 'never reset', and returns the largest area encountered during playback"; "useful when channel logos distort the video area" |
| `mv_threshold` | `8` | motion threshold in pixels (`mvedges` only) |
| `low` / `high` | docs say 5/255 and 15/255 | Canny thresholds (`mvedges` only). **Doc/code mismatch**: the source declares `high = 25/255.`, `low = 15/255.` — trust the code |
| `max_outliers` | `0` | **undocumented**; present in `cropdetect_options[]`, absent from `filters.texi` |

`mode` was added in **FFmpeg 6.0** (commit
[`9d66417`](https://github.com/FFmpeg/FFmpeg/commit/9d66417cc5bd705dca15e90aea3fa59d07422705), 2022-07-30, *"This filter
allows crop detection even if the video is embedded in non-black areas"*; listed in the
[6.0 Changelog](https://github.com/FFmpeg/FFmpeg/blob/n6.0/Changelog)).

Results are **programmatically consumable**: the filter is `AVFILTER_FLAG_METADATA_ONLY` (never modifies pixels) and sets
frame metadata `lavfi.cropdetect.x1|x2|y1|y2|w|h|x|y` in addition to logging a ready-made `crop=w:h:x:y` string. The
robust route is `ffprobe -f lavfi ... -show_entries frame_tags=lavfi.cropdetect.w,... -of csv` rather than scraping
stderr.

Two limits that matter here:

- `mode=black` is a pure black-border scanner: `checkline()` averages raw luma along each candidate row/column and
  compares against `limit`. There is no notion of "background colour", so **a slide on a grey call background yields the
  full frame**.
- `mode=mvedges` builds its box from motion vectors above `mv_threshold`, expands to the nearest zero-edge line in a
  Canny map, then takes a per-coordinate median over `max(reset_count, 15)` frames. A static slide generates no motion
  vectors; a talking head does. **On a talk recording `mvedges` will tend to lock onto the presenter, not the slide.**
  It also needs `mestimate,cropdetect=mode=mvedges` or `-flags2 +export_mvs`, otherwise it logs *"Cannot detect: no motion
  vectors available"*.

**`ffmpeg bbox`**: "Compute the bounding box for the non-black pixels in the input frame luma plane"; single option
`min_val` default `16`; sets `lavfi.bbox.x1|x2|y1|y2|w|h` and logs both a `crop=` and a `drawbox=` string. Same
black-relative limitation, plus it returns **one global extent** — any bright pixel anywhere (a name banner, a corner
webcam) expands the box.

**`blackdetect`** (`black_min_duration` 2.0 s, `picture_black_ratio_th` 0.98, `pixel_black_th` 0.10; metadata
`lavfi.black_start`/`lavfi.black_end`) and **`blackframe`** (`amount` 98, `threshold` 32) are whole-frame temporal
detectors and localise nothing.

**Masking rather than cropping, in ffmpeg**: `delogo` (mandatory `x`,`y`,`w`,`h`; interpolates from the 1-px ring outside
the box — the docs' own warning: *"and sometimes something even uglier appear - your mileage may vary"*) and `removelogo`
(arbitrary same-size bitmap mask; *"if logo pixels are not covered, the filter quality will be much reduced. Marking too
many pixels as part of the logo does not hurt as much"*).

**`crop` cannot resize per frame from an expression.** Verbatim: `w`/`h` — *"This expression is evaluated **only once**
during the filter configuration, or when the `w` or `out_w` command is sent"*; `x`/`y` — *"This expression is evaluated
**per-frame**"*. So the window can pan per frame but a per-frame resize needs runtime commands or a re-invocation.

**`freezedetect`** averages the absolute difference over the **whole frame** (`noise` default −60 dB, `duration` 2 s), so
a static slide next to a moving webcam will not trigger it; it would have to be applied *after* cropping to the candidate
region. **`signalstats`** produces whole-frame scalars only, with no spatial localisation.

There is **no ffmpeg filter that segments an arbitrary-coloured rectangular sub-region**. `find_rect` is template
matching (needs a gray8 template you do not have, and *"If the input video contains multiple instances of the object, the
filter will find only one of them"*); `colordetect` reports ranges, not geometry.

The `vid2slides` approach in [§1.1](#11-vid2slides) is the OpenCV equivalent of `cropdetect=mode=black`, computed once
over many keyframes instead of per frame — which is strictly more robust for bars, since a bar must be black in *every*
sampled slide.

Intel also holds a granted patent on a more elaborate deterministic version of the same idea:
[US10360687B2](https://patents.google.com/patent/US10360687B2/en), *"Detection and location of active display regions in
videos with static borders"* (filed 2016-07-01, granted 2019-07-23, active). It uses **horizontal/vertical gradient runs**
(*"each HGR is a group of consecutive pixels in a row … for which the differences between each pair of adjacent pixels
all have the same sign"*) plus per-row/column HGR-start counts, HGR-start position sums, average luminance and a temporal
frame-to-frame comparison; boundaries are the rows/columns whose vertical-gradient-run-start count peaks above a
threshold. It explicitly covers letterbox, pillarbox, windowbox, **asymmetrical borders**, and borders containing logos
or static text — and names its own failure case (HGRS checks passing while VGR checks fail, leaving *"no clear
distinction between static region black bar (if any) and active region content"*). Relevant as prior art to be aware of,
and as evidence that row/column projection profiles are the standard deterministic tool for this sub-problem.

### 3.2 Quadrilateral / contour detection

OpenCV's official quad detector is
[`samples/python/squares.py`](https://github.com/opencv/opencv/blob/4.x/samples/python/squares.py) (C++ twin:
[`samples/cpp/squares.cpp`](https://github.com/opencv/opencv/blob/4.x/samples/cpp/squares.cpp)):

```python
img = cv.GaussianBlur(img, (5, 5), 0)
for gray in cv.split(img):                       # each of B, G, R
    for thrs in range(0, 255, 26):               # 10 threshold levels
        if thrs == 0:
            bin = cv.Canny(gray, 0, 50, apertureSize=5)
            bin = cv.dilate(bin, None)           # close gaps between edge segments
        else:
            _retval, bin = cv.threshold(gray, thrs, 255, cv.THRESH_BINARY)
        contours, _h = cv.findContours(bin, cv.RETR_LIST, cv.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            cnt = cv.approxPolyDP(cnt, 0.02*cv.arcLength(cnt, True), True)
            if len(cnt) == 4 and cv.contourArea(cnt) > 1000 and cv.isContourConvex(cnt):
                if max_corner_cosine(cnt) < 0.1:  # all angles ~90 degrees
                    squares.append(cnt)
```

The C++ version uses `pyrDown`+`pyrUp` denoising, `thresh = 50`, `N = 11` levels and a looser `maxCosine < 0.3`.

Notable costs and caveats:

- The sample deliberately sweeps ~10–11 threshold levels × 3 colour planes = **~30 `findContours` passes per frame**, and
  uses `RETR_LIST` rather than `RETR_EXTERNAL` because a Canny pass produces both sides of each edge ridge. Collapsing
  the sweep (grayscale only, single Otsu or adaptive pass) is the obvious CPU saving.
- `contourArea(approx) > 1000` is a **resolution-dependent** hard-coded gate; a resolution-independent equivalent is
  wanted.

**Better-tuned official values for the same pipeline** come from OpenCV's ArUco detector, which is documented as exactly
this algorithm: *"It begins with an adaptive thresholding to segment the markers, then contours are extracted from the
thresholded image and those that are not convex or do not approximate to a square shape are discarded"*
([ArUco tutorial](https://docs.opencv.org/4.x/d5/dae/tutorial_aruco_detection.html)). Its
[`DetectorParameters`](https://docs.opencv.org/4.x/d1/dcd/structcv_1_1aruco_1_1DetectorParameters.html) give:
`adaptiveThreshWinSizeMin = 3`, `WinSizeMax = 23`, `WinSizeStep = 10` (a **3-pass** sweep, not 30),
`adaptiveThreshConstant = 7`, `minMarkerPerimeterRate = 0.03` and `maxMarkerPerimeterRate = 4.0` (*"defined as a rate
respect to the maximum dimension of the input image"* — resolution-independent size gating),
`polygonalApproxAccuracyRate = 0.03`, `minCornerDistanceRate = 0.05`, `minDistanceToBorder = 3`, and
`minOtsuStdDev = 5.0` (OpenCV's own guard acknowledging that Otsu needs contrast to be meaningful).

Primitive contracts that matter ([`imgproc.hpp`](https://github.com/opencv/opencv/blob/4.x/modules/imgproc/include/opencv2/imgproc.hpp),
[imgproc_shape](https://docs.opencv.org/4.x/d3/dc0/group__imgproc__shape.html)):

- `findContours`: *"Source, an 8-bit single-channel image. Non-zero pixels are treated as 1's… You can use #compare,
  #inRange, #threshold, #adaptiveThreshold, #Canny, and others to create a binary image"* — it does not need 0/255. And
  *"Since opencv 3.2 source image is not modified by this function."* Python gotcha: *"In Python, hierarchy is nested
  inside a top level array."* The `offset` parameter exists precisely to map ROI-extracted contours back into full-frame
  coordinates.
- Tutorial guidance: *"For better accuracy, use binary images. So before finding contours, apply threshold or canny edge
  detection"*, and *"object to be found should be white and background should be black"*
  ([Contours: Getting Started](https://docs.opencv.org/4.x/d4/d73/tutorial_py_contours_begin.html)).
- `approxPolyDP` epsilon is **absolute pixels**; the `0.02 · arcLength` idiom is a tutorial convention
  ([Contour Features](https://docs.opencv.org/4.x/dd/d49/tutorial_py_contour_features.html)).
- `boundingRect` is axis-aligned (and also accepts a grayscale image directly); `minAreaRect` is rotated, with angle
  *"always … between [-90, 0)"* and a documented risk of *"negative indices when data is close to the containing Mat
  element boundary"*.
- `contourArea` caveats: *"the returned area and the number of non-zero pixels… can be different"* and *"will most
  certainly give a wrong results for contours with self-intersections"*.
- `Canny`: *"The smallest value between threshold1 and threshold2 is used for edge linking. The largest value is used to
  find initial segments of strong edges"* — the two thresholds are order-independent. Official guidance
  ([C++ tutorial](https://docs.opencv.org/4.x/da/d5c/tutorial_canny_detector.html)): *"Canny recommended a upper:lower
  ratio between 2:1 and 3:1."* The hysteresis mechanism means a slide border whose gradient never exceeds the upper
  threshold **anywhere along its length** is dropped entirely, not partially
  ([Python tutorial](https://docs.opencv.org/4.x/da/d22/tutorial_py_canny.html)).
- `THRESH_OTSU`/`THRESH_TRIANGLE` are flags OR-ed into `type`; *"Otsu's method is implemented only for CV_8UC1 and
  CV_16UC1 images, and the Triangle's method is implemented only for CV_8UC1"*. OpenCV documents the **assumption**
  (*"Consider an image with only two distinct image values (bimodal image)… Otsu's method determines an optimal global
  threshold value from the image histogram"*,
  [Image Thresholding](https://docs.opencv.org/4.x/d7/d4d/tutorial_py_thresholding.html)) but **never states a failure
  condition**. "Otsu fails on non-bimodal histograms" is an inference from its documented objective, not an OpenCV claim —
  and it is exactly the situation of a dark slide plus a bright webcam tile plus grey chrome (≥ 3 modes).
- `adaptiveThreshold` is **local** (`blockSize` odd and > 1, `C` subtracted from the local mean or Gaussian-weighted
  mean), so a large uniform dark slide interior becomes noise rather than a solid blob. Good for finding the border, bad
  for producing the region as a filled component.

**Line-based alternatives.** `HoughLines`/`HoughLinesP` both warn *"The image may be modified by the function"*.
`HoughLines`' `min_theta`/`max_theta` are directly useful — restrict the accumulator to near-vertical and near-horizontal
only. `createLineSegmentDetector` **is present in the main package**, with an important history recorded in its own
doxygen note: *"Implementation has been removed from OpenCV version 3.4.6 to 3.4.15 and version 4.1.0 to 4.5.3 due
original code license conflict. restored again after Computation of a NFA code published under the MIT license."*
Verified against tags: in 4.5.3 `lsd.cpp` is a stub that raises `StsNotImplemented`; in 4.5.4 it is a real
implementation. Defaults: `refine=LSD_REFINE_STD, scale=0.8, sigma_scale=0.6, quant=2.0, ang_th=22.5, log_eps=0,
density_th=0.7, n_bins=1024`. LSD is present in both the
[4.x](https://github.com/opencv/opencv/blob/4.x/modules/imgproc/include/opencv2/imgproc.hpp) and
[5.x](https://github.com/opencv/opencv/blob/5.x/modules/imgproc/include/opencv2/imgproc.hpp) `imgproc` headers.
`ximgproc.createFastLineDetector` (contrib) has a useful free polarity cue — *"Returned lines are directed so that the
brighter side is on their left"* — plus `canny_aperture_size=0` to skip its internal Canny and accept a precomputed edge
map.

**Package split matters** ([opencv-python README](https://github.com/opencv/opencv-python/blob/4.x/README.md)):
`HoughLines*`, `createLineSegmentDetector`, `MOG2`/`KNN` are in main (`opencv-python`); `ximgproc.*` (FastLineDetector,
EdgeDrawing, FastHoughTransform) and `bgsegm.*` (GMG, CNT) require `opencv-contrib-python`. All wheels are described as
*"Pre-built CPU-only OpenCV packages for Python"*. Current PyPI state as of this scan (from the PyPI JSON API):
`opencv-python` and `opencv-python-headless` are at **5.0.0.93**, uploaded 2026-07-02;
`opencv_python_headless-5.0.0.93-cp37-abi3-manylinux_2_28_x86_64.whl` is **61.2 MB**.

**OpenCV 5 is a live hazard for this stage.** The
[4→5 migration guide](https://github.com/opencv/opencv/wiki/OpenCV-4-to-5-migration) states that
*"`cv::CascadeClassifier` (Haar-based) and `cv::HOGDescriptor` (for pedestrian detection) have been moved to the
`xobjdetect` module in `opencv_contrib`"*. Verified directly: OpenCV 5.x
[`modules/objdetect`](https://github.com/opencv/opencv/tree/5.x/modules/objdetect) contains no `cascadedetect.cpp` and no
`hog.cpp` (4.x has both), and the Haar XML data now lives in
[`opencv_contrib/modules/xobjdetect/data/haarcascades`](https://github.com/opencv/opencv_contrib/tree/5.x/modules/xobjdetect).
**The spike must pin an explicit OpenCV version.**

**Threading and cost signals** (verified in source at the 4.x tip):

- Python bindings **release the GIL on every call** — every generated binding wraps the C++ call in `ERRWRAP2`, whose
  first act constructs `PyAllowThreads` (`PyEval_SaveThread`)
  ([`cv2_util.hpp`](https://github.com/opencv/opencv/blob/4.x/modules/python/src2/cv2_util.hpp),
  [`gen2.py`](https://github.com/opencv/opencv/blob/4.x/modules/python/src2/gen2.py)).
- `parallel_for_` call sites: `canny.cpp` 4, `hough.cpp` 6, `thresh.cpp` 2, **`contours.cpp` 0**, MOG2 1, KNN 1. So
  Canny, Hough and threshold scale across the host's 4 threads, while **`findContours` is single-threaded** in every
  released 4.x (a parallel `RETR_LIST` path lands only in 4.14 per the header note). In a `squares.py`-style sweep the
  ~30 sequential `findContours` passes, not the edge detection, are the serial bottleneck.
- `setNumThreads`/`getNumThreads`/`getNumberOfCPUs` and `OPENCV_FOR_THREADS_NUM` control this
  ([core_utils](https://docs.opencv.org/4.x/db/de0/group__core__utils.html),
  [env reference](https://docs.opencv.org/4.x/d5/de7/tutorial_env_reference.html)). Expect materially less than 4× from
  4 logical threads on 2 physical cores: OpenCV's own `parallel_for_` tutorial measured *"around 6.9X"* on 8 logical /
  4 physical threads.
- The only comparative cost statements OpenCV publishes for these algorithms: `convexHull` is *"O(N logN)"*; MOG2's
  `detectShadows` *"decreases the speed a bit"*; KNN is *"Very efficient if number of foreground pixels is low"* (its bad
  case is exactly a slide transition); and `bgsegm`'s CNT is *"About as fast as MOG2 on a high end system. More than
  twice faster than MOG2 on cheap hardware (benchmarked on Raspberry Pi3)"*.

**Deterministic quad detection is still competitive with neural methods**, which is worth stating because it justifies
the deterministic-first preference. Tropin, Ershov, Nikolaev, Arlazarov, *"Advanced Hough-based method for on-device
document localization"*, Computer Optics 45(5):692–701, 2021, DOI
[10.18287/2412-6179-CO-895](https://doi.org/10.18287/2412-6179-CO-895), arXiv
[2106.09987](https://arxiv.org/abs/2106.09987): a Hough-based method that *"accounts for the geometric invariants of the
central projection model and combines both edge and color features"* achieves *"the second best result for SmartDoc
dataset in terms of precision, surpassed by U-net like neural network"* and *"the best precision compared to published
methods"* on MIDV-500 — explicitly framed around execution on *"consumer-grade end devices such as smartphones"*. No
per-frame runtime is given in the abstract or the journal landing page.

### 3.3 Temporal statistics: the strongest deterministic signal

The single most useful empirical result in the scan is a **documented negative result plus its fix**, from
`kovitking/video2slides`'
[`PLAN.md`](https://github.com/kovitking/video2slides/blob/2e16e894d6bab283a35505c390f5f8888695261f/video2slides/PLAN.md):

> "First implementation used per-pixel variance across sampled frames … That failed: a real slide change is a rare but
> huge whole-frame jump, and variance is dominated by rare large values, so the whole frame looked 'high variance,' not
> just the webcam box. Fix: use the median of consecutive-frame absolute differences instead."

And its README's statement of why the median works:

> "Slide content differs on at most 1-2 samples out of dozens (a rare transition spike), so its median difference is ~0.
> A webcam box differs a little on almost every sample, so its median stays above the threshold. That's what makes the
> region-finder immune to the rare 'big jump' of an actual slide change — median filters out spikes without needing to
> know where the transitions are ahead of time."

The mechanism holds for a slowly-changing deck. Its unstated assumptions: the presenter actually moves (a static or
absent webcam yields a median ≈ 0 and therefore no detection at all), the moving content is confined to one rectangle,
and slide changes are rare relative to the pair spacing. Animations, an embedded video, scrolling content or a moving
cursor raise the median over slide area — and the project's own "next steps" acknowledges the analogous case: *"Helps on
slides with subtle background motion (e.g. an animated brand watermark) that isn't confined to a clean rectangular PiP
box."*

This is the inverse formulation of the problem, and it is the one that fits the input reality in [§2](#2-where-the-slide-in-a-small-box-input-actually-comes-from):
instead of finding the slide, find the **temporally active** region (the webcam) and the **near-black** region (the
bars), then keep the complement. Note that keeping the complement of an arbitrary mask is not itself a rectangle — the
active region has to be removable by an axis-aligned cut (all the way across the frame in x or in y) for a rectangular
crop to exist at all. Whether that condition holds on the reference set is a question for the spike, and a row/column
projection profile of the activity mask is the cheap way to test it (the same projection-profile device the Intel patent
in [§3.1](#31-black-bar--letterbox--pillarbox-removal) uses for bars).

OpenCV's motion primitives, for comparison
([video_motion](https://docs.opencv.org/4.x/de/de1/group__video__motion.html),
[bgsegm](https://docs.opencv.org/4.x/d2/d55/group__bgsegm.html)): background subtraction is documented as being for
*"generating a foreground mask… by using **static cameras**"*, which a screen recording satisfies.
`createBackgroundSubtractorMOG2(history=500, varThreshold=16, detectShadows=true)` and
`createBackgroundSubtractorKNN(history=500, dist2Threshold=400.0, detectShadows=true)` are in the main package;
`bgsegm.createBackgroundSubtractorGMG(initializationFrames=120, decisionThreshold=0.8)` is contrib and needs **120 warm-up
frames** by default. `absdiff` needs no model, no warm-up and no state — and it carries a Python-specific trap:
*"`absdiff(src,X)` means `absdiff(src,(X,X,X,X))`. `absdiff(src,(X,))` means `absdiff(src,(X,0,0,0))`."*

**Measured on the target host during this research** (i3-4170, 4 threads, NumPy 2.5.3, Python 3.12; synthetic uint8→float32
stacks, no video decode):

| working resolution | n frames | median-of-diffs | min/max/std over stack | stack RAM (float32) |
|---|---|---|---|---|
| 240×135 | 60 | 43 ms | 6 ms | 8 MB |
| 240×135 | 120 | 72 ms | 12 ms | 16 MB |
| 480×270 | 60 | 171 ms | 31 ms | 31 MB |
| 480×270 | 120 | 342 ms | 51 ms | 62 MB |
| 960×540 | 120 | 1.39 s | 240 ms | 249 MB |
| 1920×1080 | 120 | 6.55 s | 1.07 s | 995 MB |

The arithmetic is effectively free at sane working resolutions. **The real cost of this family of strategies is video
decoding and seeking, not the statistics** — `kovitking`'s browser implementation performs ~120 seeks for the PiP pass
alone (and ~1,800 more for its hashing pass on a 60-minute video), all serial. Sampling strategy, not pixel math, is what
the spike should measure.

### 3.4 Blanket corner masking

`antonkulaga`'s four-corner mask at 15 % × 15 % (see [§1.3](#13-antonkulagavideo2slides--blanket-corner-masking)) is the
cheapest possible strategy and needs no detection at all. Two facts frame its usefulness:

- Zoom's documented thumbnail is 224×126 at fixed top-right ([§2](#2-where-the-slide-in-a-small-box-input-actually-comes-from)),
  which is 11.7 % × 11.7 % of a 1080p frame — comfortably inside a 15 % corner. So a fixed corner mask is
  **provably sufficient for the documented Zoom cloud-recording case**.
- But it is a *mask*, not a *crop*: recall-first, blanking a corner of the slide is content loss, exactly the failure the
  map says costs most. It is only safe as an output transform if the corner provably contains no slide content — and only
  a top-right *crop* line (cutting the full width or full height) preserves the recall guarantee, at the price of cutting
  real slide content when the overlay overlaps it.

### 3.5 Manual ROI

`sumerene`'s normalised-ROI flow ([§1.4](#14-sumerenevideo2slides--manual-roi-and-a-documented-negative-result)) is the
only prior art whose **output** is a correctly cropped slide, and its coordinate format (four floats normalised to 3
decimals, resolution-independent) is worth copying directly. Its red-rectangle-in-an-image-editor input mechanism is not
— an interactive `cv2.selectROI` or four CLI floats achieves the same with no external editor.

### 3.6 Text density as a positive signal

The literature and the tooling both support "where the text is" as a positive signal, but nobody in the scan uses it to
find the slide region.

- `opencv_zoo` ships **PP-OCRv3 text detection** as ONNX runnable through `cv2.dnn`
  ([model card](https://github.com/opencv/opencv_zoo/tree/main/models/text_detection_ppocr)), benchmarked at
  **18.76 ms mean at 640×480** on an Intel i7-12700K CPU
  ([benchmark](https://github.com/opencv/opencv_zoo/blob/main/benchmark/README.md)). OpenCV also exposes
  `cv::dnn::TextDetectionModel_DB` and `TextDetectionModel_EAST` in the main `dnn` module
  ([`dnn.hpp`](https://github.com/opencv/opencv/blob/4.x/modules/dnn/include/opencv2/dnn/dnn.hpp)), with models supplied
  separately.
- The classical equivalents are MSER and the Stroke Width Transform; the Houston group's lecture-video work uses OCR
  text blocks plus *"a simple technique to identify image regions… A transition frame is scanned for pixel changes with a
  sliding window protocol. Bounding boxes enclosing image objects are identified as regions surrounded by a border with
  no visual content"* (Rahman et al., *Visual Summarization of Lecture Video Segments for Enhanced Navigation*,
  [arXiv:2006.02434](https://arxiv.org/abs/2006.02434), 2020 — 40 segments across four courses; 78 % precision / 72 %
  F1 for most-selected images; region-localisation failures not separately reported).
- Caution: `sumerene`'s documented negative result explicitly includes *"logos, title bars, separator lines"* as
  confounders whose *"brightness/edge characteristics"* resemble slide content. Text detection has the same exposure —
  a video-call name banner and a participant list are text too.

Text density is best treated as a **tie-breaker or validation gate** ("does the candidate region contain most of the
frame's text?"), not as the primary detector.

### 3.7 Aspect-ratio prior as an acceptance gate

Because slide decks are overwhelmingly 16:9 (PowerPoint's documented default), with 4:3 and 16:10 as the other
realistic values ([§2](#2-where-the-slide-in-a-small-box-input-actually-comes-from)), a candidate crop whose aspect
ratio is not close to one of `{16:9, 16:10, 4:3}` is suspect. This is a cheap deterministic sanity check, and it is
absent from all six surveyed projects. It is a *rejection* rule (fall back to full frame), not a *snapping* rule —
snapping a crop to a target ratio would cut content, which the recall-first preference forbids.

---

## 4. Face and person detection as a negative signal

`vid2slides` uses a Haar cascade as its negative signal ([§1.1](#11-vid2slides)). OpenCV itself no longer recommends
that path, and the primary sources point clearly at one replacement.

### 4.1 OpenCV's own position on Haar cascades

OpenCV's roadmap issue [#25004, *"Clean Objdetect module"*](https://github.com/opencv/opencv/issues/25004), in
OpenCV's own words:

> "object detection is one of the key computer vision tasks where machine learning was used long before deep learning
> era. Nowadays, with deep learning, the problem is largely solved, at least for common cases. **But objdetect module in
> OpenCV still contains 'ancient' algorithms. We need to clean it up in OpenCV 5:** * Move HaarCascadeClassifier to
> opencv_contrib/xobjdetect. * Move HOGDescriptor to opencv_contrib/xobjdetect. * **Move all Haar/LBP models
> (opencv/data/\*) to opencv_contrib.**"

Executed by [PR #25198](https://github.com/opencv/opencv/pull/25198), merged into `5.x` on 2024-03-21. Verified in the
trees: `CascadeClassifier` and `HOGDescriptor` are absent from
[5.x `objdetect.hpp`](https://github.com/opencv/opencv/blob/5.x/modules/objdetect/include/opencv2/objdetect.hpp),
`cascadedetect.cpp` and `hog.cpp` are gone from `modules/objdetect/src`, and the cascades now live in
[`opencv_contrib/modules/xobjdetect/data/haarcascades`](https://github.com/opencv/opencv_contrib/tree/5.x/modules/xobjdetect).
The [4→5 migration guide](https://github.com/opencv/opencv/wiki/OpenCV-4-to-5-migration) states the move and adds:
*"For new projects, consider using the DNN-based face detector available in the main `objdetect` module, which is both
faster and more accurate."*

There is **no `CV_DEPRECATED` marker** on `CascadeClassifier` in 4.x; it is still shipped and documented there. But under
OpenCV 5 a Haar approach requires `opencv-contrib-python` rather than `opencv-python`, and in 4.x its tutorial sits in
`doc/tutorials/others/` alongside SVM and PCA, while `FaceDetectorYN`'s sits in `doc/tutorials/dnn/`.

### 4.2 What is and is not documented about Haar

**OpenCV documents no limitations for `CascadeClassifier`.** The full doxygen block
([`objdetect.hpp`](https://github.com/opencv/opencv/blob/4.x/modules/objdetect/include/opencv2/objdetect.hpp)) and the
[cascade tutorial](https://github.com/opencv/opencv/blob/4.x/doc/tutorials/others/cascade_classifier.markdown) contain
no statement about frontal-only operation, rotation or lighting sensitivity, or false-positive rate. Claims of that kind
should not be attributed to OpenCV docs. `detectMultiScale` defaults are `scaleFactor = 1.1`, `minNeighbors = 3`,
`flags = 0`, `minSize = Size()`, `maxSize = Size()`; the only documented confidence handle is `detectMultiScale3`,
which *"allows you to retrieve the final stage decision certainty of classification… This value can then be used to
separate strong from weaker classifications"*.

What **is** documented sits in the shipped model files and the cited paper:

- [`haarcascade_frontalface_default.xml`](https://github.com/opencv/opencv/blob/4.x/data/haarcascades/haarcascade_frontalface_default.xml)
  header: *"Stump-based **24x24** discrete(?) adaboost **frontal face** detector. Created by Rainer Lienhart."* So the base
  window is 24×24 px — the hard floor on detectable face size — and the model is explicitly frontal. Profile views need a
  **separate** cascade,
  [`haarcascade_profileface.xml`](https://github.com/opencv/opencv/blob/4.x/data/haarcascades/haarcascade_profileface.xml)
  (*"20x20 profile face detector"*), doubling the per-frame cost and producing two detectors that disagree.
- The XML carries the **Intel License Agreement** (BSD-style), not OpenCV's Apache-2.0.
- Viola & Jones, *Rapid Object Detection using a Boosted Cascade of Simple Features*, CVPR 2001 (the paper OpenCV cites):
  a 38-layer cascade trained to detect *"frontal upright faces"* from *"4916 hand labeled faces scaled and aligned to a
  base resolution of 24 by 24 pixels"*. Its Table 2, on the MIT+CMU test set of *"130 images and 507 faces"*:

  | false detections | 10 | 31 | 50 | 65 | 78 | 95 | 167 |
  |---|---|---|---|---|---|---|---|
  | detection rate | **76.1 %** | 88.4 % | 91.4 % | 92.0 % | 92.1 % | 92.9 % | **93.9 %** |

  That is the honest recall/false-positive curve for this detector family: ~76 % recall at 10 false positives across 130
  images, and 167 false positives are needed to reach 94 %. The paper also reports *"about .067 seconds"* for a 384×288
  image on a 700 MHz Pentium III.

**OpenCV publishes no benchmark for `CascadeClassifier` or `HOGDescriptor` at all.**

### 4.3 YuNet (`cv2.FaceDetectorYN`), the recommended replacement

Added in **OpenCV 4.5.4** (the [DNN face tutorial](https://github.com/opencv/opencv/blob/4.x/doc/tutorials/dnn/dnn_face/dnn_face.markdown)
compatibility line reads `OpenCV >= 4.5.4`). Model from
[`opencv_zoo/models/face_detection_yunet`](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet),
which the class doxygen links directly.

- **MIT licensed** (`Copyright (c) 2020 Shiqi Yu`,
  [LICENSE](https://github.com/opencv/opencv_zoo/blob/main/models/face_detection_yunet/LICENSE)) — the only permissive
  option in this note that ships weights. The zoo repo itself is Apache-2.0.
- File sizes, from the git-LFS pointers: `face_detection_yunet_2023mar.onnx` **232,589 B (~227 KB)** fp32;
  `_int8.onnx` **100,416 B**; `_int8bq.onnx` **122,489 B**; `face_detection_yunet_2026may.onnx` **229,738 B**.
- **Minimum detectable face size is absolute and published:** *"This model can detect **faces of pixels between around
  10x10 to 300x300** due to the training scheme."* Corroborated upstream by the model author
  ([libfacedetection](https://github.com/ShiqiYu/libfacedetection#cnn-based-face-detection-on-intel-cpu): *"Minimal face
  size ~10x10"*). Note the **upper** bound too — a face larger than ~300 px is outside the trained range, which matters
  if detection is run on a crop.
- WIDER Face validation AP, from the zoo's own `tools/eval`: **Easy 0.8844 / Medium 0.8656 / Hard 0.7503**
  (int8: 0.8810 / 0.8629 / 0.7503 — quantization costs essentially nothing, and hard AP is identical to four decimals).
  The README header also quotes the older 0.834 / 0.824 / 0.708. The paper claims 81.1 % mAP on WIDER Face hard with
  75,856 parameters (Wu, Peng, Yu, *YuNet: A Tiny Millisecond-level Face Detector*, Machine Intelligence Research
  20(5):656–665, 2023, [DOI 10.1007/s11633-023-1423-y](https://link.springer.com/article/10.1007/s11633-023-1423-y)).
- **Recall knob.** `FaceDetectorYN::create` defaults are `score_threshold = 0.9f`, `nms_threshold = 0.3f`,
  `top_k = 5000`. But OpenCV's own benchmark runs at `confThreshold: 0.6`
  ([benchmark config](https://github.com/opencv/opencv_zoo/blob/main/benchmark/config/face_detection_yunet.yaml)) and the
  author's WIDER Face evaluation runs at `confidence_threshold = 0.02`
  ([libfacedetection](https://github.com/ShiqiYu/libfacedetection#performance-on-wider-face)). So there is a documented
  0.02–0.9 operating range, and **the API default sits at the precision end of it** — the wrong end for a recall-first
  negative signal.
- **Input-size behaviour differs between OpenCV 4 and 5.** `setInputSize` *"overwrites the input size of creating model.
  Call this method when the size of input image does not match the input size when creating model"*. The zoo README:
  *"`face_detection_yunet_2023mar.onnx` has **fixed input shape. OpenCV 4.x DNN infers on the exact shape of input
  image**, but the ONNX Runtime engine in OpenCV 5.x requires dynamic dims for variable input sizes"*, while
  `face_detection_yunet_2026may.onnx` has dynamic dims *"allowing inference at any resolution without resizing"*.
  On OpenCV 4.x, therefore, **inference cost scales with the frame area you pass**, and the frame size is the cost knob.
- `detect()` returns a `[num_faces, 15]` CV_32F matrix: bbox, five landmarks, and the face score in column 14.

**Published CPU latency** ([opencv_zoo benchmark](https://github.com/opencv/opencv_zoo/blob/main/benchmark/README.md);
mean/median/min of 10 runs after warm-up, batch 1, `DNN_BACKEND_OPENCV` + `DNN_TARGET_CPU`, opencv-python 4.10.0,
*including pre- and post-processing*). The benchmark config pins the input to **160×120 only**:

| host | input | fp32 | int8 |
|---|---|---|---|
| Intel Core i7-12700K (8P+4E, 20 threads) | 160×120 | **0.69 ms** | 0.79 ms |
| Raspberry Pi 4B (Cortex-A72 ×4 @ 1.5 GHz) | 160×120 | **6.23 ms** | 6.68 ms |
| Khadas Edge2 / RK3588S | 160×120 | 2.30 ms | 2.70 ms |
| Jetson Nano B01 (CPU) | 160×120 | 5.62 ms | 6.14 ms |
| Horizon Sunrise X3 (Cortex-A53 ×4) | 160×120 | 10.56 ms | 12.45 ms |
| StarFive VisionFive 2 (RISC-V ×4) | 160×120 | 41.13 ms | 37.43 ms |
| Toybrick RV1126 / MAIX-III AX-PI (Cortex-A7 ×4) | 160×120 | 56.78 / 83.95 ms | 51.16 / 79.35 ms |

**There is no published number for an i3-4170, for any 2-core x86, or for any resolution other than 160×120.** The only
x86 host in the table has 20 threads. The closest usable proxy for a Haswell 2-core comes from the model author's own
SIMD C++ implementation — a **different implementation from OpenCV DNN**, so cite it as such — on an Intel i7-7820X
@ 3.60 GHz with AVX2, [single thread](https://github.com/ShiqiYu/libfacedetection#cnn-based-face-detection-on-intel-cpu):
**3.61 ms at 160×120, 13.09 ms at 320×240, 50.02 ms at 640×480** (roughly linear in pixel count). The paper reports
1.6 ms at 320×320 on an i7-12700K. The spike must measure the real figure on the target host at the resolution it
actually uses.

### 4.4 Why MediaPipe BlazeFace is the wrong choice *here*

Google's [Face Detector docs](https://developers.google.com/edge/mediapipe/solutions/vision/face_detector) list three
variants, all Apache-2.0: short-range (~224 KB, 128×128×3 input), full-range (~1.03 MB, 160×192×3), and full-range sparse
(~661 KB, *"roughly 60% smaller"*). Python install is `pip install mediapipe`, config defaults
`min_detection_confidence = 0.5`, `min_suppression_threshold = 0.3`. Wheels are healthy: PyPI **1.0.1**, uploaded
2026-08-14, `mediapipe-1.0.1-py3-none-manylinux_2_28_x86_64.whl` (37.9 MB), classifiers Python 3.9–3.12 — note
`manylinux_2_28` means **glibc ≥ 2.28**.

The disqualifying facts are in Google's own model cards, and they are stated as conditions of use, not soft guidance:

> "**Face bounding box sides should be at least 20% of the corresponding image sides.**" (short-range)
> "**Face bounding box sides should be at least 5% of the corresponding image sides.**" (full-range)
> "At least 70% of the face bounding box should lie inside the input image." (both)
> "Face roll and pitch (tilt) angles should be not more than 45 degrees away from the straight orientation. The yaw
> (pan) angle should not exceed 90 degrees." (both)
> Out of scope: "Detecting faces **looking away from the camera, significantly inclined from the vertical
> orientation**, or individuals' back of the head"; "Detecting people too far away from the camera (e.g. further than
> 2 meters)" (short-range) / "further than 5 meters" (full-range).
> Trade-offs: "the model… **is sensitive to face position, scale and orientation in the input image**."
> Bias (short-range): "**only detects the faces that are relatively large**."
> — [Short-Range model card](https://storage.googleapis.com/mediapipe-assets/MediaPipe%20BlazeFace%20Model%20Card%20(Short%20Range).pdf),
> [Full-Range model card](https://storage.googleapis.com/mediapipe-assets/MediaPipe%20BlazeFace%20Model%20Card%20(Full%20Range).pdf)

These constraints are **relative to the frame**, which is exactly the wrong geometry for this problem. A webcam tile
occupying ~1/6 of frame width, with a face filling perhaps half of it, puts the face at roughly **8 % of frame width** —
below the short-range model's documented 20 % floor and only marginally above full-range's 5 %. Worse, the short-range
card's own evaluation datasets were filtered to faces *"≥ 15% of respective image sides"*, so **the published accuracy
results say nothing about faces at this scale**. Pre-downscaling does not help: the constraint is a ratio, so it does not
change. Published latency is ARM-only and short-range-only (2.94 ms CPU on a Pixel 6; ~275 FPS on a Pixel 2 single core
with XNNPACK). BlazeFace's headline "200-1000+ FPS" is explicitly *mobile GPU*
([arXiv:1907.05047](https://arxiv.org/abs/1907.05047)). **No x86 CPU number is published for any variant.**

### 4.5 res10 SSD: no case for it

`res10_300x300_ssd_iter_140000` still has its prototxt in
[`samples/dnn/face_detector/`](https://github.com/opencv/opencv/tree/4.x/samples/dnn/face_detector) and a live download
entry in [4.x `samples/dnn/models.yml`](https://github.com/opencv/opencv/blob/4.x/samples/dnn/models.yml), but the
`opencv_fd` entry has been **removed from the 5.x `models.yml`**, and the Python sample that used it no longer exists
(the face sample there is now `face_detect.py`, i.e. YuNet). Weight sizes measured from `opencv_3rdparty`: fp32 Caffe
**10.2 MB**, fp16 **5.1 MB**, TF uint8 `.pb` **2.6 MB** — 23–46× YuNet fp32.
**OpenCV never published accuracy for it**, and its only provenance document says: *"The model was trained in Caffe
framework on some huge and available online dataset… For some reasons I can't provide links here"*
([how_to_train_face_detector.txt](https://github.com/opencv/opencv/blob/4.x/samples/dnn/face_detector/how_to_train_face_detector.txt)).
That same file instructs removing faces *"smaller when 16 along at least one side"* from the annotations, so ~16 px is
the documented annotation floor with no min-size guarantee.

### 4.6 Person / upper-body detectors: OpenCV's own docs argue against them

The ticket asks whether a person detector would be a better negative signal than a face detector. The primary sources
say no.

- **HOG** (`cv2.HOGDescriptor_getDefaultPeopleDetector`): *"Returns coefficients of the classifier trained for people
  detection (**for 64x128 windows**)"*; the Daimler variant is 48×96. Dalal & Triggs (the cited paper,
  [HAL inria-00548512](https://hal.inria.fr/inria-00548512/document)) scope the task to *"pedestrian detection (the
  detection of mostly visible people in more or less upright poses)"*, with training images where *"the people are
  usually standing"*, and note the features work *"provided that they maintain a roughly upright orientation"*. A seated
  presenter framed head-and-shoulders in a PiP tile is neither upright nor mostly visible, and a PiP-sized person is
  below the 64×128 window. HOG is also slower than YuNet, and OpenCV publishes no benchmark for it.
- **`haarcascade_upperbody.xml`** ships with its own limitations written into the file header
  ([source](https://github.com/opencv/opencv/blob/4.x/data/haarcascades/haarcascade_upperbody.xml)), which is the most
  directly relevant primary-source answer available:

  > "**22x18 upperbody detector**"
  > "NOTE: These detectors deal with **frontal and backside views but not with side views**"
  > "**KNOWN LIMITATIONS** … 2) **Don't expect these detectors to be as accurate as a frontal face detector.** … they
  > have to rely on **fragile silhouette information** rather than internal (facial) features."
  > "You will notice that **successful detections containing the target do not sit tightly on the body but also include
  > some of the background left and right.** This is not a bug but accurately reflects the employed training data."
  > "On an Intel Xeon 1.7GHz machine the detectors operate at something between 6Hz to 14 Hz (on 352 x 288 frames)"

  The deliberately loose bounding box is actively harmful for a crop decision: it would over-reject slide area.
  `haarcascade_fullbody.xml` and `haarcascade_lowerbody.xml` carry the same readme, and all three moved to
  `xobjdetect` in 5.x.
- **The benchmarked alternatives**, if a second, person-shaped signal is wanted, are the two `opencv_zoo` models that do
  have published numbers on the same i7-12700K CPU table: `person_detection_mediapipe` (MPPersonDet, BlazePose's
  detector converted to ONNX) at **7.65 ms at 224×224** — about 11× YuNet's 0.69 ms — and
  `human_segmentation_pphumanseg` at **5.59 ms at 192×192**. A per-pixel human mask is arguably the better *spatial*
  negative signal for this problem, because it fires on a presenter turned away, in profile, or cropped at the
  shoulders, all cases where a frontal face detector returns nothing and the webcam tile silently survives into the
  crop. Neither is characterised on this task.

### 4.7 Downscaling the frame before detection

Downscale-then-`setInputSize` is the **officially sanctioned pattern**: OpenCV's own
[`samples/dnn/face_detect.py`](https://github.com/opencv/opencv/blob/4.x/samples/dnn/face_detect.py) has a first-class
`--scale` argument (*"Scale factor used to resize input video frames"*) and then calls
`detector.setInputSize([frameWidth, frameHeight])` on the scaled size, with no accuracy caveat attached. OpenCV's own
benchmark resizes every image to 160×120 before timing. **No official accuracy-vs-downscale curve is published by either
OpenCV or Google.** The one hard bound to cite is YuNet's published *"around 10x10 to 300x300"* range: downscaling is
free until the smallest face of interest approaches 10 px, and it *helps* when faces would otherwise exceed ~300 px.
MediaPipe is structurally different — it always resizes internally to 128×128 or 160×192, and its size constraints are
frame-relative, so pre-downscaling changes nothing about whether a face clears the threshold.

### 4.8 What this means for the crop stage

**YuNet is what the primary sources support**, on four documented grounds: it is the only candidate with an *absolute*
(10 px) rather than frame-relative minimum face size; OpenCV itself moved the alternatives out of core and points new
projects at it; it has published accuracy on the metric that matters (WIDER hard AP 0.7503) and a documented low-threshold
operating range for recall; and it is a single ~227 KB MIT-licensed ONNX file needing no extra runtime.

But the deeper lesson from the prior art stands: **face detection does not produce a crop.** `vid2slides` already found
the PiP box by clustering small-face detections across the video and then did nothing with it
([§1.1](#11-vid2slides)). Face or person detection belongs in this pipeline as a **validator** of a region proposed by
another method — "reject any candidate crop that contains a face", "prefer the complement of the region that contains a
face" — not as the proposer. And for recall, `score_threshold` should be set well below the API's 0.9 default.

---

## 5. Once per video, or per captured frame?

### What the prior art does

| project | when the region is computed | can it adapt mid-video? |
|---|---|---|
| `vid2slides` | once, from **all** frames classified as slides | no |
| `kovitking` | once, from 60 sample pairs spread across the whole video | no — cached in a module-level variable |
| `antonkulaga` | never (fixed 15 % corners) | n/a |
| `sumerene` | once, manually, from the frame at t = 10 s | no |
| `bibo242` | once, manually, from the frame at `start_sec` | no |
| SliTraNet (2022) | frames are *"cropped to the content of the slides"*, **pre-determined** | no |

Nobody recomputes per frame. Even the most recent CNN work in the literature assumes a fixed crop: Sindel, Hernandez,
Yang, Christlein, Maier, *"SliTraNet: Automatic Detection of Slide Transitions in Lecture Videos using Convolutional
Neural Networks"*, [arXiv:2202.03540](https://arxiv.org/abs/2202.03540) (2022) — frames *"cropped to the content of the
slides"*, then *"scaled to a maximum length of 256 and filled up with zero padding to a patch size of 256×256"*, with a
second stream over the full raw frame precisely so that full-screen interruptions (speaker view, memes) can be
distinguished. Dataset: 12 train / 4 validation / 14 test videos from two university courses, Full HD 25 fps, 6–33 min,
4:3 and 16:9 decks; best F1 ≈ 90 % (precision 86.76 %, recall 93.16 %). Named failure modes: animated slides with minimal
changes, memes with colour distributions similar to slides, and *"slides of one frame length cannot be detected"* (8-frame
minimum).

### The argument each way

**Once per video** is what the evidence supports as the default:

- All the strong deterministic signals are **inherently temporal** — near-black in *every* sampled frame
  ([§3.1](#31-black-bar--letterbox--pillarbox-removal)), median-of-differences across *many* sampled pairs
  ([§3.3](#33-temporal-statistics-the-strongest-deterministic-signal)). They have no single-frame equivalent, so
  per-frame computation would mean falling back to a strictly weaker signal.
- Cost: one detection pass instead of one per captured slide. On the target host the arithmetic is negligible either way
  ([§3.3](#33-temporal-statistics-the-strongest-deterministic-signal)); the cost is the extra seeking.
- Stability: a per-frame crop that wobbles by a few pixels between slides produces a visibly inconsistent deck, and
  the output contract ([issue #14](https://github.com/henricos/extract-slides/issues/14)) is easier to reason about with
  one region per video.
- `cropdetect`'s own default reflects this preference: `reset_count = 0` means *"never reset, and returns the largest
  area encountered during playback"* — the union over the whole video, deliberately biased toward not cropping too much.
  That bias is exactly the recall-first preference.

**Per captured frame** is what a layout change demands. The layout-change cases, and what happens to a once-per-video
region in each:

| layout event | effect on a single global region |
|---|---|
| screen share starts partway in (talking heads first) | frames before the share are not slides; if they are included in the statistics they contaminate the region. Mitigated by computing the region **only from frames already classified as slides**, as `vid2slides` does |
| presenter goes full-screen (slide fills the frame) then returns to a shared-window layout | a union region is the full frame → crop becomes a no-op for the inset portion; an intersection region cuts content from the full-screen portion |
| camera cuts between speaker and slide (reference-set class 5) | same as above, and the speaker frames must be excluded from the statistics or the "active region" is the whole frame |
| webcam tile moves corner mid-video | a single global activity mask now covers two corners; `kovitking`'s single-bbox scan spans both and then fails its own plausibility gate, silently producing no mask at all |
| deck aspect ratio changes (a 4:3 deck opened after a 16:9 one) | pillarbox bars differ; the union keeps the wider one |

### What this note recommends the spike measure

Compute the region **once per video, but not once per file**: segment the video into layout-stable runs and compute one
region per run, taking the **union** (never the intersection) of candidate regions within a run so that no slide content
is ever cut. Concretely, the three variants worth measuring against each other are:

1. **One region for the whole video**, computed only from frames the detector already classified as slides.
2. **One region per layout-stable segment.** Segment boundaries are cheap to obtain: a large, sustained change in the
   per-frame near-black mask or in the activity mask is itself the layout-change signal.
3. **Per captured frame**, as the control — with the expectation that it is both more expensive and less stable, and that
   it will be measurably worse on recall unless every per-frame region is unioned with the video-level region anyway.

This ordering follows the map's recall-first preference: a union region can only ever include *extra* material (webcam,
chrome), which is the cheap failure; an intersection or a per-frame region can cut slide content, which is the expensive
one.

---

## 6. Documented failure modes

| failure mode | who documents it | what happens |
|---|---|---|
| **Slide bleeding to the frame edge / no visible border** | `vid2slides` code | the near-black mask is all-ones → one contour = the whole frame → `boundingRect` = full frame → **crop is a silent no-op**. This is also the common case: the project's own demo retains the Acrobat menu bar |
| **Dark or black slide background** | `vid2slides` code; OpenCV's Otsu documentation | a `#000000` background fails the near-black mask over large areas, and `findContours` may then pick the surrounding chrome instead — the crop can invert into "everything except the slide". Separately, a dark slide + bright webcam + grey chrome is a ≥3-mode histogram, and OpenCV documents Otsu only under a *"bimodal image"* assumption; it states no failure condition, so behaviour is simply unspecified |
| **Grey / non-black surround** | `ffmpeg` `cropdetect` docs (`limit`: *"An intensity value greater to the set value is considered non-black"*) | `mode=black` returns the full frame. `bbox` likewise |
| **Letterboxing / pillarboxing** | `ffmpeg` `cropdetect`, `bbox`, `vid2slides`, [US10360687B2](https://patents.google.com/patent/US10360687B2/en) | this is the **one case that is solidly solved** deterministically — provided the bars are black. Grey or white bars are kept by all of these. The Intel patent additionally covers asymmetrical bars and bars containing logos/static text |
| **No contrast at the border at all** | OpenCV Canny hysteresis docs | a border whose gradient never exceeds the upper threshold anywhere along its length produces no sure-edge seed and is dropped **entirely**, not partially |
| **Rounded corners** | OpenCV `squares.py` / ArUco parameters | `approxPolyDP` at a 2–3 %-of-perimeter epsilon returns >4 vertices for a rounded rectangle, so a strict `len(cnt) == 4` gate rejects it. `boundingRect` of the contour is unaffected, which is a reason to prefer the axis-aligned bounding box over strict quad fitting for this project |
| **Meeting chrome resembling slide content** | `sumerene` `SKILL.md` | *"logos, title bars, separator lines have brightness/edge characteristics similar to PPT content, so they cannot be distinguished"* — the reason that project requires a human ROI |
| **Multimodal LLM asked for coordinates** | `sumerene` `SKILL.md` | *"measured deviation is large, still includes decoration areas, unreliable"* — a documented negative result for the AI escape hatch at *this* stage |
| **Multiple webcam tiles (two presenters, opposite corners)** | `kovitking` `PLAN.md` | acknowledged as untested; the code path that would have merged them was deleted. A single min/max bbox spans both corners and then fails the plausibility gate → **no mask at all, silently** |
| **Animated watermark / embedded video / moving cursor** | `kovitking` `PLAN.md`; SliTraNet | non-rectangular or distributed motion defeats the activity-mask approach; SliTraNet reports failure on *"animated slides with minimal changes"* |
| **Static or absent webcam** | `kovitking` code (inferred from mechanism) | median difference ≈ 0 everywhere → no PiP found → no masking. Benign here (nothing to remove), but it means "no detection" and "nothing to detect" are indistinguishable |
| **Motion-vector-based detection on a talk** | `ffmpeg` `vf_cropdetect.c` source | `mode=mvedges` builds its box from *moving* pixels, so it locks onto the presenter rather than the static slide |
| **Presenter occlusion, camera motion, camera switches** | lecture-video literature | methods *"fail to deal with frames which contain people movement and camera motion"*, and screen-localisation approaches targeted at single-PTZ-camera recordings do not allow camera switches — directly relevant to reference-set class 5 |
| **Zoom's green share border** | Zoom KB0061246 | a real rectangular border around the shared region in some cloud recordings: an exploitable edge cue *and* a source of a false slide boundary |
| **Speaker tile overlapping the slide** | Zoom KB0062314 | the documented default; the workaround is presenter-side (*"set the resolution of the shared content to 1600x900"*). When the tile overlaps, **no axis-aligned crop can remove it without cutting slide content** — the tool must keep the overlap and accept it, per the recall-first preference |

For the perspective/camera-recorded case the canonical reference is Li, Wang, Wang, Dai, *"Structuring Lecture Videos by
Automatic Projection Screen Localization and Analysis"*, IEEE TPAMI 37(6):1233–1246, 2015, DOI
[10.1109/TPAMI.2014.2361133](https://doi.org/10.1109/TPAMI.2014.2361133) (paywalled; abstract via
[PubMed 26357345](https://pubmed.ncbi.nlm.nih.gov/26357345/)): a system that *"automatically detects and tracks both the
projection screen and the presenter whenever they are visible in the video"* and *"by analyzing the tracked screen
region… detect[s] slide progressions and extract[s] a high-quality, non-occluded, geometrically-compensated image for
each slide"*. Note what that buys: tracking the screen *and* the presenter, to produce a non-occluded, rectified slide
image. That is the full-strength version of this stage, and it is a 2015 TPAMI paper — a useful calibration of how much
work "do it properly for camera footage" actually is.

---

## 7. Is there a library that solves "find the slide rectangle"?

**No.** The honest answer, with the evidence:

- **`opencv_zoo` model inventory** ([models/](https://github.com/opencv/opencv_zoo/tree/main/models), 25 entries):
  `deblurring_nafnet, edge_detection_dexined, face_detection_yunet, face_image_quality_assessment_ediffiqa,
  face_recognition_sface, facial_expression_recognition, handpose_estimation_mediapipe, human_segmentation_pphumanseg,
  image_classification_mobilenet, image_classification_ppresnet, image_segmentation_efficientsam, inpainting_lama,
  license_plate_detection_yunet, object_detection_nanodet, object_detection_yolox, object_tracking_vittrack,
  optical_flow_estimation_raft, palm_detection_mediapipe, person_detection_mediapipe, person_reid_youtureid,
  pose_estimation_mediapipe, qrcode_wechatqrcode, text_detection_ppocr, text_recognition_crnn`. Nothing detects a
  document, screen, page or generic quadrilateral. `license_plate_detection_yunet` is the only quad-ish model and is
  plate-specific.
- **OpenCV's `objdetect` documented scope** is cascade classifier, HOG, barcode, QR code, DNN face, ArUco
  ([`objdetect.hpp`](https://github.com/opencv/opencv/blob/4.x/modules/objdetect/include/opencv2/objdetect.hpp)).
  `ximgproc`'s scope is structured-forest edges, EdgeBoxes, filters, superpixels, segmentation, line detectors, Fourier
  descriptors, RLE morphology. No screen/document/whiteboard detector in either. There is also **no official OpenCV
  document-scanner tutorial** — the only perspective tutorial is the homography one, and it uses **chessboard corners**,
  not a detected quad ([homography tutorial](https://docs.opencv.org/4.x/d9/dab/tutorial_homography.html)).
- **`Mindee/doctr`** (Apache-2.0, pushed 2026-09-01): text detection and recognition. Its `detect_orientation` /
  `straighten_pages` / `page_orientation_predictor` correct the **rotation of an already-supplied page**; there is no
  page-boundary detection ([docs](https://mindee.github.io/doctr/using_doctr/using_models.html)).
- **PaddleOCR / PP-DocLayout** (Apache-2.0, pushed 2026-07-22): 23 *intra-document* layout classes (title, paragraph,
  table, formula, header, footer, seal, …) and **no page/screen-boundary class**
  ([layout detection](https://www.paddleocr.ai/latest/en/version3.x/module_usage/layout_detection.html)). Model sizes /
  CPU: L 123.76 MB / 503 ms, M 22.58 MB / 43 ms, S 4.83 MB / 18.5 ms. Its "Text Image Rectification" module is UVDoc
  (30.3 MB, ~870 ms CPU) and **unwarps an image it is given** rather than locating it
  ([unwarping](https://www.paddleocr.ai/latest/en/version3.x/module_usage/text_image_unwarping.html)). Cost of entry:
  `paddlepaddle` 3.3.1 manylinux x86_64 wheels are **194.8 MB** each ([PyPI](https://pypi.org/project/paddlepaddle/)).
- **`kornia`** (Apache-2.0, pushed 2026-09-08): provides `get_perspective_transform`, `warp_perspective`,
  `find_homography_dlt*` and RANSAC — the differentiable equivalents of the OpenCV calls. A recursive grep of the tree
  for `dewarp|document|rectif|scan` returns nothing. Primitives, not a detector.
- **`docling`** (MIT, pushed 2026-09-08): accepts raster images but treats the whole image as the page; video support is
  **audio transcription only** ([supported formats](https://docling-project.github.io/docling/usage/supported_formats/)).
- **`imutils.perspective.four_point_transform`** (MIT): exists and works, but **takes the four points as an argument** —
  it does not find them. ~60 lines of glue over OpenCV, and it pulls `scipy` for one `cdist` call. Repo pushed
  2024-06-24, but the **last PyPI release is 0.5.4, 2021-01-15** ([PyPI](https://pypi.org/project/imutils/)) — over five
  years. Copy the function rather than depend on it.
- **Neural document localizers exist but are research-licensed.** `fh2019ustc/DocScanner` (pushed 2025-06-18) does
  include a document-localization module and downloadable weights (T 2.6M / B 5.2M / L 8.5M params), but its
  [LICENSE.md](https://github.com/fh2019ustc/DocScanner/blob/main/LICENSE.md) reads *"Any Commercial Use of the Algorithm
  is strictly prohibited without explicit prior written permission from the Author"* plus a share-alike clause;
  `fh2019ustc/DocTr` and `DocTr-Plus` carry the identical text. `cvlab-stonybrook/DewarpNet` is genuinely MIT but
  dewarps an already-cropped document and was last pushed 2024-11-10.
- **`DocsaidLab/DocAligner`** is the one maintained, permissive, pip-installable thing with the right *shape* of API —
  Apache-2.0, pushed 2026-01-13, `pip install docaligner-docsaid` (PyPI 1.1.1, `python_requires >=3.10,<=3.12`),
  `model(img) -> np.ndarray shape (4,2)`. Heatmap regression of the four corners with classical post-processing
  (threshold 0.3, largest polygon, centroid), shipped as ONNX. SmartDoc-2015 Jaccard 0.9826–0.9937 depending on backbone
  (1.7 MB to 83.1 MB), inference resolution 256×256; **no CPU or GPU timing is published anywhere**
  ([benchmark](https://docsaid.org/en/docs/docaligner/benchmark/)). Four problems for this host: weights download from
  hardcoded Google Drive file IDs at first run; its dependency `capybara_docsaid` requires
  `onnxruntime_gpu==1.22.0; platform_system == "Linux"` (the CPU wheel is gated to Darwin only) — a large useless
  download on a GPU-less box ([PyPI JSON](https://pypi.org/pypi/capybara-docsaid/0.12.0/json)); it also needs system
  `libturbojpeg` and `poppler-utils`; and it is trained on photographed paper and ID documents, so a monitor showing a
  slide is out of domain — including for its "is a document present" head.
- **COCO detectors as a proxy**: COCO includes `tv` and `laptop` (also `keyboard`, `cell phone`, `remote`) but no
  `screen`, `monitor`, `projector`, `whiteboard` or `slide`
  ([class list](https://github.com/amikelive/coco-labels/blob/master/coco-labels-2014_2017.txt)); `tv`/`laptop` bound the
  whole device, not the display area, and for a projected slide on a wall there is no applicable class at all.
  Permissive CPU options if pursued as a coarse prior: `opencv_zoo`'s NanoDet/YOLOX (Apache-2.0, ONNX via `cv2.dnn`) or
  torchvision's COCO detectors (BSD-3-Clause; SSDLite320-MobileNetV3-Large 21.3 box mAP / 3.4M params through
  Faster R-CNN ResNet50-FPN-V2 46.7 / 43.7M — [torchvision models](https://docs.pytorch.org/vision/stable/models.html)).
  Ultralytics YOLO is **AGPL-3.0**.
- **torchvision's DeepLabV3-MobileNetV3-Large** has pretrained weights, but they are COCO-with-VOC-labels (21 Pascal
  classes, mIoU 60.3) — no document or screen class, so the well-known DeepLabV3 document scanner requires **training on
  a synthetic dataset you generate yourself**; the published checkpoints for it are Dropbox links inside
  `spmallick/learnopencv`, a repo with **no license file at all**.
- **A GitHub sweep confirms the pattern.** `gh search repos "document scanner opencv" --sort updated --limit 25` returns
  25 repos, 24 of them with 0–2 stars, nearly all describing the same "edge detection, contour detection, four-point
  perspective transformation" pipeline. `gh search repos "screen detection"` returns only game-bot and anti-cheat
  projects. And the flagship maintained document-scanning library, `puffinsoft/jscanify` (MIT, 1.7k★, pushed 2026-07-20),
  **is** the OpenCV recipe:

  ```js
  cv.Canny(img, imgGray, 50, 200);
  cv.GaussianBlur(imgGray, imgBlur, new cv.Size(3,3), 0, 0, cv.BORDER_DEFAULT);
  cv.threshold(imgBlur, imgThresh, 0, 255, cv.THRESH_OTSU);
  cv.findContours(imgThresh, contours, hierarchy, cv.RETR_CCOMP, cv.CHAIN_APPROX_SIMPLE);
  // -> pick the largest-area contour
  ```
  ([`src/jscanify.js`](https://github.com/puffinsoft/jscanify/blob/master/src/jscanify.js))

**Conclusion:** for this stage there is nothing to adopt. The primitives are OpenCV's (and ffmpeg's), the assembly is
ours, and the design question is which signals to combine — not which library to install.

---

## 8. Perspective correction: when it is and is not needed

Two distinct input classes, and only one of them needs a homography:

- **Axis-aligned** — a screen recording, or a Zoom/Meet/Teams recording. The slide is an upright rectangle, only
  translated, scaled and possibly letterboxed. **No perspective distortion exists**, so `getPerspectiveTransform` /
  `warpPerspective` add nothing but interpolation loss. The right tools are `cropdetect` / a threshold + `boundingRect`.
  This is `docs/idea.md`'s primary case (a YouTube URL of a recorded talk).
- **Perspective** — a camera filming a projected screen at an angle. This needs corner detection plus a homography, and
  it is what the entire document-scanner literature and toolchain targets. It is also the case Li et al. (TPAMI 2015)
  address with screen *and* presenter tracking to get a non-occluded rectified slide.

If perspective correction is ever needed, the OpenCV contracts are:
`getPerspectiveTransform(src, dst, solveMethod=DECOMP_LU)` takes exactly four point pairs;
`warpPerspective` *"cannot operate in-place"*, supports only `INTER_LINEAR`/`INTER_NEAREST` and
`BORDER_CONSTANT`/`BORDER_REPLICATE`, and inverts `M` internally unless `WARP_INVERSE_MAP` is set;
`findHomography` only earns its keep with more than four noisy correspondences (*"if there are no outliers and the noise
is rather small, use the default method (method=0)"*, `ransacReprojThreshold` *"somewhere in the range of 1 to 10"*
pixels, and *"Whenever an H matrix cannot be estimated, an empty one will be returned"*)
([imgproc_transform](https://docs.opencv.org/4.x/da/d54/group__imgproc__transform.html),
[calib3d](https://docs.opencv.org/4.x/d9/d0c/group__calib3d.html)).

**Recommendation for the spike:** do not measure perspective correction. If the reference set contains a
camera-filmed-projector video, record it as an explicitly unsolved class and fall back to the full frame rather than
building a homography path for it in this map.

---

## 9. Shortlist for the crop spike (issue #12)

Ranked by expected value per unit of implementation cost, given everything above. Every candidate below is deterministic;
the AI options are deliberately not in the list, because the only measured data point on them at this stage is
`sumerene`'s negative result.

### Rank 1 — Black-bar removal (baseline that must be beaten)

Union-over-slide-frames near-black mask → largest contour → `boundingRect`; equivalently
`ffmpeg cropdetect` consumed via `lavfi.cropdetect.*` frame metadata. `vid2slides`' actual behaviour, made explicit.

Why first: it is the only case the prior art solves, it is cheap, it can only ever remove uniformly black margins, and it
is therefore **recall-safe by construction**. It also sets the floor: any candidate that does not beat this is not worth
its complexity. Measure both the OpenCV and the `cropdetect` implementations — the map notes `ffmpeg` is not installed on
the target host, so whether this stage needs it at all is a real question.

### Rank 2 — Activity-complement crop (median-of-differences)

`kovitking`'s median-of-consecutive-differences activity mask, restored to its deleted Python form (morphological close
15×15 → open 9×9 → `findContours(RETR_EXTERNAL)` → per-contour `boundingRect` → merge nearby boxes), then **crop to the
complement** rather than mask — via a row/column projection profile of the activity mask to find an axis-aligned
separating cut, and no crop at all when no such cut exists.

Why second: it is the only strategy with a documented mechanism for the actual target case (webcam next to slide), it
comes with a documented negative result for its obvious alternative (plain variance), and the arithmetic is free at
working resolution ([§3.3](#33-temporal-statistics-the-strongest-deterministic-signal)). The novel part — crop the
complement instead of masking the box — is exactly what no prior project does, and it is what turns this from a
detection-quality improvement into a usable output.

What to measure: threshold sensitivity (the fixed `4.0` is unjustified), sample count and spacing, morphology on vs off,
behaviour with two tiles in opposite corners, behaviour with a static webcam, and how often a separating cut exists at
all on the reference set.

### Rank 3 — Fixed corner crop, guarded

`antonkulaga`'s blanket corner mask reworked as a **crop** (a full-width or full-height cut) rather than a mask, applied
only when a guard passes: the region to be cut must contain a face or person (per [§4](#4-face-and-person-detection-as-a-negative-signal))
and must not contain a meaningful share of the frame's edge or text energy.

Why third: it needs no detection, and Zoom's documented 224×126 top-right thumbnail (11.7 % × 11.7 % at 1080p) sits
comfortably inside a 15 % corner, so it is provably sufficient for the single most common documented layout. The guard is
what keeps it recall-safe. Cheapest possible win on the dominant real-world case.

### Rank 4 — Quad detection, OpenCV/ArUco-tuned

`squares.py` collapsed to a grayscale pipeline with the ArUco parameter set (3-pass adaptive threshold with
`WinSize 3→23 step 10`, `C=7`, `polygonalApproxAccuracyRate=0.03`, perimeter gates as a **rate** of the image's maximum
dimension), taking the **axis-aligned `boundingRect`** of the best candidate rather than a strict 4-vertex quad (so
rounded corners do not disqualify it), plus an aspect-ratio acceptance gate against `{16:9, 16:10, 4:3}`.

Why fourth: it is the textbook approach and OpenCV supplies both the recipe and tuned parameters, and Tropin et al. show
Hough/geometric methods remain competitive with U-Net for document localization. But `sumerene`'s documented negative
result targets precisely this family (*"meeting decorations… have brightness/edge characteristics similar to PPT content,
so they cannot be distinguished"*), it is the most expensive of the four (`findContours` is single-threaded on every
released 4.x), and it fails silently in the most common case (slide bleeding to the frame edge). Worth measuring as the
representative of the classical approach; not worth betting on.

### Rank 5 — Manual ROI (must exist, is not a candidate to be ranked against the others)

`sumerene`'s normalised four-float ROI, resolution-independent to three decimals, supplied via a CLI flag or an
interactive `cv2.selectROI`, applied to every frame, with the crop being what is written. This is the escape hatch the
map already requires ("automatic by default, with an optional review mode"), not a competitor to ranks 1–4.

### Not shortlisted, and why

- **`ffmpeg cropdetect=mode=mvedges`** — locks onto the moving region, i.e. the presenter, not the slide
  ([§3.1](#31-black-bar--letterbox--pillarbox-removal)).
- **`find_rect` / template matching** — needs a template of the thing being searched for.
- **Text detection as the primary detector** — same confounders as edge detection (banners, participant lists are text);
  keep it as a validation gate ([§3.6](#36-text-density-as-a-positive-signal)).
- **COCO `tv`/`laptop` detection** — no applicable class for a projected or shared slide; bounds the device, not the
  display ([§7](#7-is-there-a-library-that-solves-find-the-slide-rectangle)).
- **`DocAligner` / `DocScanner` / UVDoc / DeepLabV3 document segmentation** — out of domain (paper and ID documents),
  research-licensed, or requiring training; plus a GPU-only runtime dependency in the one permissive case
  ([§7](#7-is-there-a-library-that-solves-find-the-slide-rectangle)).
- **VLM asked for crop coordinates** — the only measured evidence available is negative (`sumerene`).

### Fallback chain when detection fails

Recall-first, so every step falls back to *more* pixels, never fewer:

1. Best accepted candidate from ranks 2–4, **unioned** with the rank-1 black-bar rectangle.
2. If no candidate passes the acceptance gates → the rank-1 black-bar crop alone.
3. If black-bar detection finds nothing → **the full frame**, which `docs/idea.md` explicitly accepts as the baseline.
4. In every case, record in the manifest which rule produced the region, so the review mode
   ([issue #14](https://github.com/henricos/extract-slides/issues/14)) can surface the frames that fell through.

An explicit acceptance gate is what makes the chain safe, and no surveyed project has one. Candidate rules, all cheap:
area must be at least some share of the frame; aspect ratio must be near `{16:9, 16:10, 4:3}`; the candidate must contain
substantially all of the frame's non-background content outside the rejected region; and the candidate must not contain a
detected face or person. Calibrating those thresholds is spike work.

---

## 10. What this note could not establish

- **Per-frame CPU cost of every candidate on the target host.** Only the temporal-statistics arithmetic was measured
  here ([§3.3](#33-temporal-statistics-the-strongest-deterministic-signal)); decode and seek cost dominate and were not
  measured. YuNet's published CPU numbers are at 160×120 input only.
- **Whether a separating axis-aligned cut actually exists** between slide and overlay on real videos — the precondition
  for rank 2 producing a crop at all. Zoom's documented default (tile overlapping the content) implies it often does
  not.
- **Microsoft Teams and Google Meet recording geometry.** Neither vendor documents it. Only Zoom does.
- **Zoom's default recording layout.** Not stated in any of the four support articles checked.
- **Small-face recall inside a webcam tile** for YuNet vs a Haar cascade vs a human-segmentation model, at the
  resolutions this pipeline would actually use. No primary source characterises that specific regime. Specifically
  missing: any opencv_zoo benchmark for a 2-core x86 CPU or for any YuNet input size other than 160×120; any OpenCV
  benchmark for `CascadeClassifier` or `HOGDescriptor` at all; any OpenCV-published accuracy for the res10 SSD detector;
  any MediaPipe CPU latency on x86 or for the full-range/sparse variants; and any official accuracy-vs-downscale curve
  from OpenCV or Google.
- **Li et al. (TPAMI 2015) in detail** — paywalled; only the abstract was available, so its algorithm and failure modes
  are described here at abstract level only.
- **`DocAligner`'s CPU inference time** — not published by the project at any backbone size.

---

## Sources

Prior art (read at source level):

- [patrickmineault/vid2slides](https://github.com/patrickmineault/vid2slides) — `vid2slides.py`, `slides2pdf.py`, `demo/91004320940_1_out.txt`, `environment.yml`
- [kovitking/video2slides](https://github.com/kovitking/video2slides) — `webapp/static/app.js`, `PLAN.md`, `CLAUDE.md`, deleted `process_video.py` at `dfe8404`
- [antonkulaga/video2slides](https://github.com/antonkulaga/video2slides) — `video2slides/converter.py`, `main.py`
- [sumerene/video2slides](https://github.com/sumerene/video2slides) — `scripts/detect_roi.py`, `scripts/extract_slides.py`, `SKILL.md`
- [bibo242/Video2Slides-Pro](https://github.com/bibo242/Video2Slides-Pro) — `app.py`, `core/pipeline.py`, `extract_slides.py`
- [binh234/video2slides](https://github.com/binh234/video2slides) — `bg_modeling.py`, `frame_differencing.py`, `post_process.py`, `config.py`

OpenCV:

- [imgproc_shape](https://docs.opencv.org/4.x/d3/dc0/group__imgproc__shape.html) · [imgproc_feature](https://docs.opencv.org/4.x/dd/d1a/group__imgproc__feature.html) · [imgproc_misc](https://docs.opencv.org/4.x/d7/d1b/group__imgproc__misc.html) · [imgproc_transform](https://docs.opencv.org/4.x/da/d54/group__imgproc__transform.html) · [calib3d](https://docs.opencv.org/4.x/d9/d0c/group__calib3d.html) · [video_motion](https://docs.opencv.org/4.x/de/de1/group__video__motion.html) · [bgsegm](https://docs.opencv.org/4.x/d2/d55/group__bgsegm.html) · [ximgproc fast line detector](https://docs.opencv.org/4.x/df/ded/group__ximgproc__fast__line__detector.html) · [core_utils](https://docs.opencv.org/4.x/db/de0/group__core__utils.html)
- Tutorials: [Contours: Getting Started](https://docs.opencv.org/4.x/d4/d73/tutorial_py_contours_begin.html) · [Contour Features](https://docs.opencv.org/4.x/dd/d49/tutorial_py_contour_features.html) · [Canny (Python)](https://docs.opencv.org/4.x/da/d22/tutorial_py_canny.html) · [Canny (C++)](https://docs.opencv.org/4.x/da/d5c/tutorial_canny_detector.html) · [Image Thresholding](https://docs.opencv.org/4.x/d7/d4d/tutorial_py_thresholding.html) · [Background Subtraction](https://docs.opencv.org/4.x/d1/dc5/tutorial_background_subtraction.html) · [parallel_for_](https://docs.opencv.org/4.x/d7/dff/tutorial_how_to_use_OpenCV_parallel_for_.html) · [Environment variables](https://docs.opencv.org/4.x/d5/de7/tutorial_env_reference.html) · [ArUco detection](https://docs.opencv.org/4.x/d5/dae/tutorial_aruco_detection.html) · [Homography](https://docs.opencv.org/4.x/d9/dab/tutorial_homography.html)
- Source: [`imgproc.hpp` (4.x)](https://github.com/opencv/opencv/blob/4.x/modules/imgproc/include/opencv2/imgproc.hpp) · [`imgproc.hpp` (5.x)](https://github.com/opencv/opencv/blob/5.x/modules/imgproc/include/opencv2/imgproc.hpp) · [`objdetect.hpp`](https://github.com/opencv/opencv/blob/4.x/modules/objdetect/include/opencv2/objdetect.hpp) · [`objdetect/face.hpp` (5.x)](https://github.com/opencv/opencv/blob/5.x/modules/objdetect/include/opencv2/objdetect/face.hpp) · [`dnn.hpp`](https://github.com/opencv/opencv/blob/4.x/modules/dnn/include/opencv2/dnn/dnn.hpp) · [`background_segm.hpp`](https://github.com/opencv/opencv/blob/4.x/modules/video/include/opencv2/video/background_segm.hpp) · [`core/utility.hpp`](https://github.com/opencv/opencv/blob/4.x/modules/core/include/opencv2/core/utility.hpp) · [`cv2_util.hpp`](https://github.com/opencv/opencv/blob/4.x/modules/python/src2/cv2_util.hpp) · [`gen2.py`](https://github.com/opencv/opencv/blob/4.x/modules/python/src2/gen2.py)
- Samples: [`samples/python/squares.py`](https://github.com/opencv/opencv/blob/4.x/samples/python/squares.py) · [`samples/cpp/squares.cpp`](https://github.com/opencv/opencv/blob/4.x/samples/cpp/squares.cpp)
- [ArUco DetectorParameters](https://docs.opencv.org/4.x/d1/dcd/structcv_1_1aruco_1_1DetectorParameters.html) · [LineSegmentDetector](https://docs.opencv.org/4.x/db/d73/classcv_1_1LineSegmentDetector.html) · LSD history: [removal `3ba49cce`](https://github.com/opencv/opencv/commit/3ba49cce), [restore `9b768727`](https://github.com/opencv/opencv/commit/9b768727)
- [OpenCV 4 to 5 migration guide](https://github.com/opencv/opencv/wiki/OpenCV-4-to-5-migration) · [OpenCV 5.0.0 release](https://github.com/opencv/opencv/releases/tag/5.0.0) · [`opencv_contrib/modules/xobjdetect` (5.x)](https://github.com/opencv/opencv_contrib/tree/5.x/modules/xobjdetect) · [opencv-python README](https://github.com/opencv/opencv-python/blob/4.x/README.md)
- [opencv_zoo models](https://github.com/opencv/opencv_zoo/tree/main/models) · [opencv_zoo benchmark](https://github.com/opencv/opencv_zoo/blob/main/benchmark/README.md) · [YuNet model card](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) · [YuNet LICENSE](https://github.com/opencv/opencv_zoo/blob/main/models/face_detection_yunet/LICENSE) · [YuNet benchmark config](https://github.com/opencv/opencv_zoo/blob/main/benchmark/config/face_detection_yunet.yaml) · [PP-OCRv3 text detection card](https://github.com/opencv/opencv_zoo/tree/main/models/text_detection_ppocr) · [MPPersonDet card](https://github.com/opencv/opencv_zoo/blob/main/models/person_detection_mediapipe/README.md)

Face and person detection:

- OpenCV: [issue #25004 "Clean Objdetect module"](https://github.com/opencv/opencv/issues/25004) · [PR #25198](https://github.com/opencv/opencv/pull/25198) · [cascade tutorial](https://github.com/opencv/opencv/blob/4.x/doc/tutorials/others/cascade_classifier.markdown) · [DNN face tutorial](https://github.com/opencv/opencv/blob/4.x/doc/tutorials/dnn/dnn_face/dnn_face.markdown) · [`samples/dnn/face_detect.py`](https://github.com/opencv/opencv/blob/4.x/samples/dnn/face_detect.py) · [`samples/dnn/models.yml`](https://github.com/opencv/opencv/blob/4.x/samples/dnn/models.yml) · [`samples/dnn/face_detector/`](https://github.com/opencv/opencv/tree/4.x/samples/dnn/face_detector) · [`how_to_train_face_detector.txt`](https://github.com/opencv/opencv/blob/4.x/samples/dnn/face_detector/how_to_train_face_detector.txt)
- Shipped model headers: [`haarcascade_frontalface_default.xml`](https://github.com/opencv/opencv/blob/4.x/data/haarcascades/haarcascade_frontalface_default.xml) · [`haarcascade_profileface.xml`](https://github.com/opencv/opencv/blob/4.x/data/haarcascades/haarcascade_profileface.xml) · [`haarcascade_upperbody.xml`](https://github.com/opencv/opencv/blob/4.x/data/haarcascades/haarcascade_upperbody.xml)
- [ShiqiYu/libfacedetection](https://github.com/ShiqiYu/libfacedetection#cnn-based-face-detection-on-intel-cpu) (upstream YuNet, x86 AVX2 timings and WIDER Face evaluation thresholds)
- MediaPipe: [Face Detector task](https://developers.google.com/edge/mediapipe/solutions/vision/face_detector) · [Python API](https://developers.google.com/edge/mediapipe/solutions/vision/face_detector/python) · [Short-Range model card](https://storage.googleapis.com/mediapipe-assets/MediaPipe%20BlazeFace%20Model%20Card%20(Short%20Range).pdf) · [Full-Range model card](https://storage.googleapis.com/mediapipe-assets/MediaPipe%20BlazeFace%20Model%20Card%20(Full%20Range).pdf) · [mediapipe on PyPI](https://pypi.org/project/mediapipe/)
- Papers: Viola & Jones, *Rapid Object Detection using a Boosted Cascade of Simple Features*, CVPR 2001 · Dalal & Triggs, *Histograms of Oriented Gradients for Human Detection*, CVPR 2005 — [HAL inria-00548512](https://hal.inria.fr/inria-00548512/document) · Bazarevsky et al., *BlazeFace*, [arXiv:1907.05047](https://arxiv.org/abs/1907.05047)

ffmpeg:

- [ffmpeg filter documentation](https://ffmpeg.org/ffmpeg-filters.html) · [`doc/filters.texi`](https://github.com/FFmpeg/FFmpeg/blob/master/doc/filters.texi) · [`libavfilter/vf_cropdetect.c`](https://github.com/FFmpeg/FFmpeg/blob/master/libavfilter/vf_cropdetect.c) · [`mvedges` commit `9d66417`](https://github.com/FFmpeg/FFmpeg/commit/9d66417cc5bd705dca15e90aea3fa59d07422705) · [FFmpeg 6.0 Changelog](https://github.com/FFmpeg/FFmpeg/blob/n6.0/Changelog)

Vendor documentation:

- Zoom: [Recording FAQ (KB0061246)](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0061246) · [Adjusting recording video layouts (KB0062314)](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0062314) · [Cloud recording settings (KB0064676)](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0064676) · [Presenter layouts (KB0074062)](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0074062) · [Meeting API, cloud recording](https://developers.zoom.us/docs/api/meetings/#tag/cloud-recording)
- Google: [Record a video meeting](https://support.google.com/meet/answer/9308681) · [Change your layout](https://support.google.com/meet/answer/10550593) · [Recording quality limits](https://support.google.com/a/answer/14107956) · [Slide size](https://support.google.com/docs/answer/3447672) · [YouTube aspect ratio](https://support.google.com/youtube/answer/6375112)
- Microsoft: [Record a meeting in Teams](https://support.microsoft.com/en-us/office/record-a-meeting-in-microsoft-teams-34dfbe7f-b07d-4a27-b4c6-de62f1348c24) · [Teams meeting recording (admin)](https://learn.microsoft.com/en-us/microsoftteams/meeting-recording) · [Recording and transcription overview](https://learn.microsoft.com/en-us/microsoftteams/recording-transcription-overview) · [Change the size of your slides](https://support.microsoft.com/en-us/office/change-the-size-of-your-slides-040a811c-be43-40b9-8d04-0de5ed79987e)

Papers and patents:

- Sindel, Hernandez, Yang, Christlein, Maier, *SliTraNet: Automatic Detection of Slide Transitions in Lecture Videos using Convolutional Neural Networks*, 2022 — [arXiv:2202.03540](https://arxiv.org/abs/2202.03540)
- Li, Wang, Wang, Dai, *Structuring Lecture Videos by Automatic Projection Screen Localization and Analysis*, IEEE TPAMI 37(6):1233–1246, 2015 — [DOI 10.1109/TPAMI.2014.2361133](https://doi.org/10.1109/TPAMI.2014.2361133), [PubMed 26357345](https://pubmed.ncbi.nlm.nih.gov/26357345/)
- Tropin, Ershov, Nikolaev, Arlazarov, *Advanced Hough-based method for on-device document localization*, Computer Optics 45(5):692–701, 2021 — [DOI 10.18287/2412-6179-CO-895](https://doi.org/10.18287/2412-6179-CO-895), [arXiv:2106.09987](https://arxiv.org/abs/2106.09987)
- Rahman et al., *Visual Summarization of Lecture Video Segments for Enhanced Navigation*, 2020 — [arXiv:2006.02434](https://arxiv.org/abs/2006.02434)
- Wu, Peng, Yu, *YuNet: A Tiny Millisecond-level Face Detector*, Machine Intelligence Research 20(5):656–665, 2023 — [DOI 10.1007/s11633-023-1423-y](https://link.springer.com/article/10.1007/s11633-023-1423-y)
- Intel, *Detection and location of active display regions in videos with static borders*, [US10360687B2](https://patents.google.com/patent/US10360687B2/en) (granted 2019-07-23)

Libraries evaluated:

- [Mindee/doctr](https://mindee.github.io/doctr/using_doctr/using_models.html) · [PaddleOCR module overview](https://www.paddleocr.ai/latest/en/version3.x/module_usage/module_overview.html) · [PP-DocLayout](https://www.paddleocr.ai/latest/en/version3.x/module_usage/layout_detection.html) · [Text image unwarping](https://www.paddleocr.ai/latest/en/version3.x/module_usage/text_image_unwarping.html) · [paddlepaddle on PyPI](https://pypi.org/project/paddlepaddle/)
- [kornia imgwarp](https://github.com/kornia/kornia/blob/main/kornia/geometry/transform/imgwarp.py) · [kornia homography](https://github.com/kornia/kornia/blob/main/kornia/geometry/homography.py) · [docling supported formats](https://docling-project.github.io/docling/usage/supported_formats/)
- [imutils/perspective.py](https://github.com/PyImageSearch/imutils/blob/master/imutils/perspective.py) · [imutils on PyPI](https://pypi.org/project/imutils/)
- [DocsaidLab/DocAligner](https://github.com/DocsaidLab/DocAligner) · [DocAligner benchmark](https://docsaid.org/en/docs/docaligner/benchmark/) · [DocAligner architecture](https://docsaid.org/en/docs/docaligner/model_arch/) · [capybara-docsaid PyPI metadata](https://pypi.org/pypi/capybara-docsaid/0.12.0/json)
- [fh2019ustc/DocScanner LICENSE](https://github.com/fh2019ustc/DocScanner/blob/main/LICENSE.md) · [fh2019ustc/DocTr](https://github.com/fh2019ustc/DocTr) · [cvlab-stonybrook/DewarpNet](https://github.com/cvlab-stonybrook/DewarpNet)
- [puffinsoft/jscanify](https://github.com/puffinsoft/jscanify/blob/master/src/jscanify.js) · [ternaus/midv-500-models](https://github.com/ternaus/midv-500-models) · [torchvision models](https://docs.pytorch.org/vision/stable/models.html) · [COCO class list](https://github.com/amikelive/coco-labels/blob/master/coco-labels-2014_2017.txt)
