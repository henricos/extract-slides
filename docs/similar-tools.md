# Similar tools and prior art

Landscape scan done in September 2026. Only projects/libraries that bring something concrete to reuse or learn from are listed — plenty of near-duplicate repos exist and were left out when they added nothing beyond what's already covered here.

**Activity criterion:** "last commit" below is each repo's last push as observed in September 2026. A repo with no push in the last **~12 months** is flagged **stale**; one with no push in **~2+ years** and no active fork is flagged **orphan** (abandoned, unlikely to receive fixes).

**This table says what each project claims to do.** [`docs/research/reference-implementations.md`](research/reference-implementations.md) says what twelve of them *actually* do, read from source at pinned commits — including several places where a README and its code disagree. Read it before relying on a description here.

## Similar projects

Projects that attempt the problem end to end — download/ingest a talk video and produce slide screenshots, not just detect scene changes on a local file.

| Project | What it does | Last commit | Status |
|---|---|---|---|
| **[vid2slides](https://github.com/patrickmineault/vid2slides)** (Python, ~54★, license not verified) | The closest prior art to the whole problem: downloads the video (YouTube/Zoom/Meet), detects slide transitions with an HMM, discards frames with a face (OpenCV), crops off black borders (OpenCV — a `mean > 0.2/255` threshold across keyframes, not the slide region proper), and OCRs the result (Tesseract) into JSON + PDF/GIF utilities. **No audio transcript** — only OCR of the slide's own text. | 2020-11-23 | **Orphan** — 10 forks, none pushed in the last 2 years. |
| **[m2kar/video2slides](https://github.com/m2kar/video2slides)** (Python) | Scene detection → PPTX export, **plus speech-to-text subtitles** (`--srt`) — the only similar project found that pairs slide extraction with an actual audio transcript, matching this project's two-track requirement. Takes a local video file, not a URL. | 2024-12-01 | Stale (~21 months) but not orphaned. |
| **[kovitking/video2slides](https://github.com/kovitking/video2slides)** (JavaScript) | Runs entirely client-side in the browser: canvas frame capture, **auto-detects and masks a moving webcam PiP overlay** (median pixel-difference between frames, robust to real slide transitions), then a DCT perceptual hash with a stability window to confirm a slide. Privacy-oriented (video never leaves the machine). Its README notes an **earlier version had a server-side CLI and Whisper transcription, both since removed** — evidence the full pipeline (crop + transcript) was built and worked before being scoped back down to slides-only. | 2026-07-28 | Active. |
| **[AnuragSingh2101/Video2Slides](https://github.com/AnuragSingh2101/Video2Slides)** ("YouTube AI Studio") | The heavy/SaaS end of the spectrum: `faster-whisper` for transcription, OpenCV histogram-diff + `easyocr` for slide extraction/OCR, then Gemini for chaptering, per-slide summaries, mind maps, flashcards and quizzes, exported back to `.pptx`. Far beyond this project's scope (RAG chat, quizzes, spaced repetition) but a concrete example of every piece — transcript, slide capture, slide OCR, summarization — implemented together, and validates that the "LLM extensions" this project defers to later (see `docs/idea.md`) are exactly what the closed SaaS competitors already ship. | 2026-08-05 | Active. |

## Supporting tools

Building blocks that solve one piece of the pipeline well and are meant to be reused or learned from, not full solutions on their own.

### Download (video + captions)

| Tool | What it does | Last commit | Status |
|---|---|---|---|
| **[yt-dlp](https://github.com/yt-dlp/yt-dlp)** (Python, Unlicense) | De facto standard for downloading video (and captions, manual or auto-generated) from YouTube and hundreds of other sites. | 2026-08-30 | Active (very). |
| **[youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api)** (Python, MIT) | Fetches a video's transcript/captions without an API key or a headless browser; works with auto-generated captions. | 2026-05-19 | Active. |

### Transcription (STT)

| Tool | What it does | Last commit | Status |
|---|---|---|---|
| **[Whisper](https://github.com/openai/whisper)** (OpenAI, MIT) | Baseline multilingual STT model; the quality reference. | 2026-08-31 | Active. |
| **[faster-whisper](https://github.com/SYSTRAN/faster-whisper)** (Python, MIT) | CTranslate2 reimplementation, ~4× faster and ~40% less VRAM than stock Whisper; best for NVIDIA GPU/batch processing. | 2025-11-19 | Active. |
| **[whisper.cpp](https://github.com/ggml-org/whisper.cpp)** (C/C++, MIT) | High-performance port; runs on CPU, Apple Metal and CUDA with quantized GGML models — no Python runtime needed. | 2026-09-08 | Active. |

### Slide-change detection

| Tool | What it does | Last commit | Status |
|---|---|---|---|
| **[larry-xue/video-slide-extractor](https://github.com/larry-xue/video-slide-extractor)** (JS/Node, zero deps) | Frame-differencing scene detection that runs in the browser or in Node with no external dependencies — a good reference for a lightweight "light path" implementation (a script callable from a skill, per `docs/idea.md`). | 2026-09-06 | Active (pushed 2 days before this scan). |
| **[ffmpeg `select`/`scdet`](https://ffmpeg.org/ffmpeg-filters.html)** | Built-in scene detection (`select=gt(scene\,X)` or the `scdet` filter), no external deps; `scdet` also emits transition timestamps for downstream use. Already needed in the pipeline for the download/decode step regardless. | — | Actively maintained (part of ffmpeg itself). |
| **[PySceneDetect](https://github.com/Breakthrough/PySceneDetect)** (Python, BSD-3-Clause) | Content-aware scene detection (frame comparison + thresholding) with timecode and per-scene image output out of the box. | 2026-08-28 | Active. |
| **[binh234/video2slides](https://github.com/binh234/video2slides)** (Python) | Offers three interchangeable background-subtraction strategies (frame differencing, KNN, GMG) selectable via a flag, plus a perceptual-hash post-processing pass (`dhash`/`phash`/`ahash`) to drop near-duplicate slides — a useful reference for how many practical detectors this step actually needs. | 2024-03-14 | Stale (~30 months). |
| **[sumerene/video2slides](https://github.com/sumerene/video2slides)** (Python) | Dedupes with **two** perceptual hashes at once (pHash + dHash) specifically because academic slide templates are visually similar enough to fool a single hash — only drops a frame when both agree it's a duplicate. Also filters non-slide frames with a Laplacian (blur) check before hashing. | 2026-04-20 | Active. |
| **[bit-admin/AutoSlides-Extractor](https://github.com/bit-admin/AutoSlides-Extractor)** (C++/Qt, MIT) | The most complete actively maintained tool found: chunked hardware decoding for long videos, a global-statistics change metric with three presets, a K-sample verification window, all-pairs pHash dedupe, a user-curated persisted "never capture this" hash list, a 3-class learned slide-frame gate, and a working slide-bbox auto-crop. The two bundled `.onnx` models carry no licence statement. | 2026-08-08 | Active. |
| **[perelman/slide-detector](https://git.aweirdimagination.net/perelman/slide-detector)** (Python, **AGPL-3.0**, self-hosted Gitea) | 144 lines, and the deterministic ancestor `SliTraNet` was built on and failed to beat on recall in its own ablation. Compares every frame against a **pinned anchor** rather than its predecessor, blurs before differencing, and exports the anchor that survived the dwell — so the change detector also answers "which frame do I capture". AGPL against this project's MIT: re-implement from description, never copy. | 2020-05-30 | Orphan, and it does not matter — the technique is what is wanted. |
| **[sidharth-anand/lectures-2-slides](https://github.com/sidharth-anand/lectures-2-slides)** (Python, MIT) | SSIM at a 0.82 threshold over a batch of videos. Notable only for where it applies its rectangle: a **manual** `slide_bounds` crop applied *before* diffing, making the crop a detection input rather than an export step. | 2021-10-17 | Orphan. |
| **[andererka/MaViLS](https://github.com/andererka/MaViLS)** (Python/Jupyter, Apache-2.0) | Not a detector — a **human-labelled dataset** (Interspeech 2024) of 20 real lectures with `.srt` transcripts and source decks in git, videos on Kaggle. Labels include `Slidenumber = -1` for "no slide on screen", which makes it the only slide-frame-gate training and test data found anywhere. Labels are at transcript-sentence granularity, so it supports a coverage-style metric and not ±2 s transition matching. | 2024-09-25 | Stale, but it is data, not code. |
| **HMM (Hidden Markov Model)** | The approach `vid2slides` uses for slide-transition detection — more robust than plain frame differencing. Algorithm reference, not a standalone repo. Note its transition matrix is **left-to-right with no backward transitions**, which makes a return to an earlier slide structurally impossible. | — | — |

### Slide region cropping / isolation

**None of the projects below actually crops to the slide region.** Each was checked against its own source while researching this stage (see `docs/research/slide-region-crop.md`): they detect a region, mask it for change detection, or ship a manual tool, but the frame they write to disk is uncropped.

**One project outside this table does crop**, found later by reading source (`docs/research/reference-implementations.md`): `bit-admin/AutoSlides-Extractor`'s `AutoCropDetector` — black-bar strip, Canny, 4-vertex contours, area/margin/fill gates, and a score preferring the large rectangle whose aspect is nearest 16:9 or 4:3. So the stage is not greenfield, but it is close: everything else in the field either hand-labels the rectangle or ignores it, including the learned state of the art.

| Tool | What it does | Last commit | Status |
|---|---|---|---|
| **[OpenCV](https://opencv.org)** (Apache 2.0) | Contour/edge detection (`findContours`, minimum bounding rectangle) and tracking across frames — the building blocks any crop strategy is assembled from. `vid2slides` does *not* use them to find its crop region: it thresholds on `mean > 0.2/255` across keyframes, which is black-bar removal, and its own demo output still retains an application menu bar. | — | Actively maintained. |
| **[kovitking/video2slides](https://github.com/kovitking/video2slides)** (JavaScript) | Auto-detects a moving webcam/PiP box via median pixel-difference between consecutive frames (robust to the "big jump" of a real slide change) and masks it out before hashing — the most robust PiP detection found here, but it addresses *detection* only: the frame the project saves is the unmasked one, so the "slide in a smaller box, webcam in the corner" case from `docs/idea.md` is left unsolved. | 2026-07-28 | Active. |
| **[bibo242/Video2Slides-Pro](https://github.com/bibo242/Video2Slides-Pro)** (Python) | Ships a manual "mask tool" to cover webcam overlays plus a review gallery with a similar-pairs finder — a useful UX reference for a human-in-the-loop verification step, if automatic cropping/dedup isn't fully trusted. | 2026-05-01 | Active. |
| **[sumerene/video2slides](https://github.com/sumerene/video2slides)** (Python) | Ships a manual ROI-selection tool (`detect_roi.py`) for the picture-in-picture/meeting-recording case, as a fallback when the crop region can't be found automatically. | 2026-04-20 | Active. |
| **[antonkulaga/video2slides](https://github.com/antonkulaga/video2slides)** (Python, MIT) | Simpler heuristic: masks out the corner regions of the frame (where a speaker's webcam typically sits) rather than detecting the PiP box explicitly — a cheaper fallback worth comparing against the detection-based approaches above. | 2025-11-06 | Active. |

### OCR / slide text extraction

| Tool | What it does | Last commit | Status |
|---|---|---|---|
| **[Tesseract OCR](https://github.com/tesseract-ocr/tesseract)** (Apache 2.0) | Classic OCR engine; used to validate/extract the text of a cropped slide region and produce a searchable PDF. | 2026-09-02 | Active. |
| **[johan456789/slide-extractor](https://github.com/johan456789/slide-extractor)** (Python) | A concrete, working pipeline for the "searchable PDF" idea: `imagehash`+`cv2` to dedupe frames, `img2pdf` to combine image-only pages, Tesseract+Ghostscript to OCR and merge in a text layer. The README also documents why `ocrmypdf` was rejected in favor of this manual pipeline (faster, better image quality) — useful if this project ever needs the same searchable-PDF output. | 2023-10-24 | Stale (~35 months). |

## Discarded

Also scanned during this research but deliberately left out of the tables above, with the reason each was cut:

- **[youtube-dl](https://github.com/ytdl-org/youtube-dl)** — the original downloader; `yt-dlp` is its actively maintained fork and strictly ahead on bypass fixes, so it adds nothing beyond `yt-dlp`.
- **[video2pdf](https://github.com/alexander-pick/video2pdf)**, **[radiantly/slide-extractor](https://github.com/radiantly/slide-extractor)**, **[TalentedB/Slideshow-Extractor](https://github.com/TalentedB/Slideshow-Extractor)** — simple frame-diff-to-PDF scripts, all orphaned (no push in 2+ years) and none introduce a technique not already covered by the entries above.
- **[realChesta/slide-extractor](https://github.com/realChesta/slide-extractor)**, **[Slide-extractor-beta/slide-extractor](https://github.com/Slide-extractor-beta/slide-extractor)** — full-frame screenshot on frame-diff only, no crop, no transcript, no download from URL; nothing beyond what's already covered.
- **[szanni/slideextract](https://github.com/szanni/slideextract)** (C, BSD-2-Clause) — minimal frame-comparison extractor, no crop, no transcript; kept out because `binh234`/`sumerene` above cover the same idea with more technique to learn from.
- A long tail of near-duplicate repos literally named `video2slides` (`amirothman`, `alwleedamado`, `aabi8113`, `ErnestGu`, `crebro`, `KyojiUmemura`, `lgerrets`) were checked and dropped: each is either a trivial frame-to-image script, a hackathon wrapper around another entry in this list, or has no README/description to evaluate.
- **[larry-xue/awesome-video-to-slides](https://github.com/larry-xue/awesome-video-to-slides)** — a curated awesome-list of video-to-slides tools, not itself a tool. Worth a periodic re-scan for new entries, but not something to build on. Re-scanned in full while reading source for `docs/research/reference-implementations.md`; it yielded three repos this table did not have, two of which are now above. Its "manually-labelled product benchmark" has no labels: the ground-truth file is one header row.
- **[Wangxs404/video2ppt](https://github.com/Wangxs404/video2ppt)** (Python, MIT, 239★) — the stars are not evidence of technique. Its single 201-line `main.py` dumps a screenshot every *n* seconds into a PPTX; grepping it for `similar|dedup|compare|hash|ssim` returns zero hits. There is no change detection in it at all.
- **[jackellenberger/video2slideshow](https://github.com/jackellenberger/video2slideshow)** — solves a different problem (turning a full-motion video into a subtitle-paced slideshow for accessibility), not presentation-slide extraction.
