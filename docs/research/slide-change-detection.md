# Slide-change detection techniques

Research for issue [#7](https://github.com/henricos/extract-slides/issues/7), gathered September 2026. **Facts only** — the choice between candidates belongs to the detection spike ([#11](https://github.com/henricos/extract-slides/issues/11)), which will measure them against a ground-truth-labelled reference video set.

`docs/similar-tools.md` already catalogues *which* tools exist. This document does not repeat that. It answers *how each technique behaves* on the three cases that break naive detectors, what knobs exist with their documented defaults, and what each costs on the target host (Intel i3-4170, 2 cores / 4 threads, no GPU, 15 GB RAM, 45–60 minute 1080p input).

Every claim below is sourced. Where the primary sources are silent, that is stated as a negative finding rather than filled in.

## 1. The three hard cases, stated precisely

| Case | Why naive detection fails |
|---|---|
| **Progressive build** — bullets appear one at a time on the same slide | Each reveal is a genuine visible frame change. A difference detector is not wrong to fire; the question is a *policy* question about what counts as one slide, and it has to be answered somewhere. |
| **Camera cutaway** — the vision mixer cuts to the speaker/audience and back to a slide already captured | Every consecutive-frame detector sees the return as a new scene, because none of them remember what they already emitted. |
| **Embedded video / animation inside a slide** | Continuous change on part of the frame either floods the detector with transitions or, in some metrics, masks a real slide change happening at the same time. |

Two structural observations frame everything that follows:

1. **These are three different problems with three different homes in a pipeline.** The build case is a *threshold and policy* problem in the detector. The cutaway case is a *global deduplication* problem that no consecutive-frame detector can solve, no matter how it is tuned. The embedded-video case is a *temporal stability* problem. Any design that expects one knob on one library to handle all three will fail at least one of them.
2. **Recall-over-precision resolves the tension between cases 1 and 3.** In every library surveyed, the single knob that suppresses an animation flood (minimum scene length / stability window) is the same knob that merges away progressive builds. Biasing toward recall means turning that knob down, accepting the flood, and cleaning up afterwards with global deduplication — which is also the only thing that solves case 2.

## 2. Summary table

Read this as a map into the sections below, not as a verdict.

| Technique | Progressive build | Camera cutaway | Embedded video | Min-scene-length knob |
|---|---|---|---|---|
| ffmpeg `scdet` | Scores ~1–2 orders of magnitude below a slide swap; missed at defaults | No mechanism | Suppressed *for free* by `min(mafd, diff)` — and so are crossfades | **None** |
| ffmpeg `select=scene` | Same metric, 39× finer scale, plus an expression-level time refractory | No mechanism | Same `min(mafd, diff)` property | **None** (but `prev_selected_t` idiom) |
| ffmpeg `freezedetect` / `mpdecimate` | Finds the *stable island*, not the transition | No mechanism | Inherently robust — motion just means "not frozen" | `freezedetect duration`, default **2 s** |
| PySceneDetect `detect-content` | Likely missed at defaults; edge weights + `-d 1` are the fix | **No mechanism** (see 4.9) | `min_scene_len` + `filter_mode` MERGE collapses a burst | `min_scene_len`, CLI default `0.6s` |
| PySceneDetect `detect-adaptive` | Degenerates to `content_val >= min_content_val` (15.0) on static slides | **No mechanism** | Rolling average — the only mechanism the project advertises for sustained motion | `min_scene_len` (own check) |
| PySceneDetect `detect-hash` | Structurally insensitive — low-frequency DCT discards a bullet | **No mechanism** | Only `min_scene_len` | `min_scene_len` |
| Perceptual hash + global hash set | Structurally insensitive — measured **distance 0** for a real edit at `hash_size=8` (5.5); needs `hash_size >= 16` | **This is the mechanism** | Needs an explicit stability window | Stability window (hand-rolled) |
| `absdiff` + `countNonZero` frame differencing | **The only primitive with a usable margin** — 5–10× between build and slide change (5.3) | No mechanism | Floods; needs masking or hysteresis | None |
| OpenCV background subtraction as a *change* detector | Transient that decays to zero in ~4 s | **Non-deterministic** — result depends on cutaway length (5.1) | Absorbs it, then forgets the slide too | `history`, default 500 |
| Block-diff + activity mask (`larry-xue`) | Near the trigger floor at low working resolution (measured) | No mechanism (compares to last kept frame) | **Activity mask** excludes permanently-moving blocks | None; hysteresis instead |
| Background subtraction, capture-on-settle (`binh234`) | Each reveal is motion, then settles → fires per reveal | Window of last 5 hashes only | **Capture when foreground % drops** — waits for motion to stop | Two-threshold hysteresis |
| Left-to-right HMM (`vid2slides`) | Collapses to the final, fullest state | **This is the mechanism** (state persists across the gap) | Smoothed by the self-transition prior | `jump_probability` = 0.2 |
| SSIM + verification + pHash exclusion list (`AutoSlides-Extractor`) | Fires on every reveal at its 0.9985 default | pHash exclusion list handles *known* recurring frames only | 3-sample verification, not configurable | `verificationCount` = 3 (hardcoded) |
| **Edge-localised superset test** (TalkMiner, 8.1) | **This is the mechanism** — deterministic, OCR-free | Speaker-appearance SVM removes the cutaway frames | Spatial-extent filter on the difference bounding box | 3 s stability, made safe by the spatial filter |
| **Connected-component two-tier segmenter** (Yang et al., 8.2) | **This is the mechanism** — tier 1 catches every reveal, tier 2 scopes to the title region | Not addressed | **Not handled** — the authors excluded such videos and added an SVM | `Ts1` = 20 CCs, `Ts2` = 5 CCs |

**The one thing every deterministic technique in sections 3–6 misses, and both deployed systems in section 8 get right:** the discriminator between a build and a new slide is the **subset/superset relation between consecutive states**, not the magnitude of the difference. A build *adds* content and preserves what was there; a transition *drops* content. Every threshold-on-magnitude technique above is measuring the wrong quantity. See 8.3 and 9.1.

## 3. ffmpeg

`ffmpeg` is not installed on the target host, so anything here is a new system prerequisite. Verified directly against the FFmpeg source, not only the docs.

### 3.1 `scdet`

Options and defaults, from [`libavfilter/vf_scdet.c`](https://github.com/FFmpeg/FFmpeg/blob/master/libavfilter/vf_scdet.c) (`scdet_options[]`) and [ffmpeg-filters.html#scdet](https://ffmpeg.org/ffmpeg-filters.html#scdet):

| Option | Alias | Type | Default | Range |
|---|---|---|---|---|
| `threshold` | `t` | double | `10.0` | 0–100 |
| `sc_pass` | `s` | bool | `0` | 0–1 |

That is the entire option list. The score, from `get_scene_score()` in the same file:

```
sad   = Σ over nb_planes of SAD(prev_plane, cur_plane)
count = Σ plane pixel counts
mafd  = sad * 100 / count / (1 << bitdepth)
diff  = |mafd - prev_mafd|
score = clip(min(mafd, diff), 0, 100)
```

Three properties follow from that expression, and they matter more than the threshold value does:

1. **Luma only, for any YUV input.** `config_input` sets `s->nb_planes = is_yuv ? 1 : av_pix_fmt_count_planes(...)`, where `is_yuv` means non-RGB, planar, ≥3 components. Every ordinary H.264 talk recording is `yuv420p`, so **chroma is ignored**: a slide change that alters colour but not luminance is invisible to `scdet`. All planes are summed only for RGB/GBRP input.
2. **`min(mafd, diff)` is a steady-motion suppressor, for free.** During continuous motion — an embedded video, a moving camera — `mafd` is large but roughly constant, so `diff` is small, and `min()` returns the small number: no detection. A cut out of a static slide produces a large `mafd` *and* a large `diff`, so both terms are large. This is a real mechanism against the embedded-video flood, obtained with no extra knob.
3. **The same property is a recall hazard.** A slide change that happens *while* an embedded video is playing has an already-high `mafd`, so `diff` stays small and the transition is suppressed. Under a recall-first policy that is the worst failure mode available: a silently missed slide.

Metadata is written on every frame: `lavfi.scd.mafd` and `lavfi.scd.score`. `lavfi.scd.time` is set — and an `AV_LOG_INFO` line printed — only when `score >= threshold`. With `sc_pass=1` only frames at or above the threshold are forwarded; at the default `sc_pass=0` every frame passes and the decision lives in the metadata, which can be harvested without re-encoding.

The filter is declared `AVFILTER_FLAG_METADATA_ONLY` and carries no `AVFILTER_FLAG_SLICE_THREADS`, so the per-frame SAD is single-threaded. On a 4-thread host it is decoder threading, not filter threading, that uses the cores.

**`scdet` has no minimum-scene-length knob.** Two options, no cooldown, no burst suppression. Any "one slide, not five" policy must be applied by the caller downstream. This is the single biggest functional gap against PySceneDetect.

### 3.2 `select` with the `scene` variable

Not the same metric, despite sharing the SAD helper. From [`libavfilter/f_select.c`](https://github.com/FFmpeg/FFmpeg/blob/master/libavfilter/f_select.c):

```
nb_planes = is_yuv ? 1 : count_planes          // luma only for YUV
mafd      = sad / count / (1 << (bitdepth-8))  // 0..255 scale
diff      = |mafd - prev_mafd|
scene     = clip(min(mafd, diff) / 100, 0, 1)
```

Both filters are luma-only on YUV; the real difference is the **normalisation**, and it is worth pinning down because the two filters' own documented "sane ranges" disagree. For 8-bit input, `mafd_sel = sad/count` (mean absolute luma difference in code levels, 0–255) while `mafd_scd = mafd_sel · 100/256`, so before clipping:

```
scdet_score = 39.0625 × select_scene
```

| `select` `scene` | equivalent `scdet` threshold |
|---|---|
| 0.205 | 8.0 — `scdet` docs' lower bound |
| **0.256** | **10.0 — `scdet` default** |
| 0.30 | 11.7 — `select` docs' lower bound |
| **0.40** | **15.6 — the classic `select` idiom** |
| 0.50 | 19.5 — `select` docs' upper bound |

`scdet`'s documented "good values are in the `[8.0, 14.0]` range" ([ffmpeg-filters.html#scdet](https://ffmpeg.org/ffmpeg-filters.html#scdet)) corresponds to `scene` in `[0.205, 0.358]`, while `select`'s "comparing scene against a value between 0.3 and 0.5 is generally a sane choice" ([ffmpeg-filters.html#select](https://ffmpeg.org/ffmpeg-filters.html#select_002c-aselect)) corresponds to `scdet` `[11.7, 19.5]`. **`select`'s advice is the stricter, lower-recall one.** Two further asymmetries: `select`'s score saturates at 1.0 for any `mafd_sel >= 100`, so it loses dynamic range at the high end but is 39× finer per unit at the low end — which is where progressive builds live; and enabling `scene` restricts the negotiated pixel formats to a short list (`RGB24, BGR24, RGBA, ABGR, BGRA, GRAY8, YUV420P, YUVJ420P, YUV422P, YUVJ422P, YUV420P10`), potentially forcing an extra swscale conversion on unusual input.

Scene detection is computed at all only when the expression string contains the substring `scene` (`do_scene_detect = !!strstr(select->expr_str, "scene")`). `select` also writes `lavfi.scene_score` on every frame — **undocumented**; the source carries a literal `// TODO: document metadata` above that line, so it is not a stable contract.

### 3.3 The one in-ffmpeg burst suppressor: `select`'s `prev_selected_t`

`scdet` has no minimum-scene-length knob, but `select` exposes `prev_selected_t` / `prev_selected_pts` / `prev_selected_n` as expression variables, and the docs give the idiom for a minimum gap:

> *Select frames with a minimum distance of 10 seconds:*
> `select='isnan(prev_selected_t)+gte(t-prev_selected_t\,10)'`

— [ffmpeg-filters.html#select](https://ffmpeg.org/ffmpeg-filters.html#select_002c-aselect)

Composed with `scene`, that is a min-gap-enforcing scene detector built entirely from documented primitives:

```
select='gt(scene,0.30)*(isnan(prev_selected_t)+gte(t-prev_selected_t,2))'
```

`prev_selected_t` advances only when a frame is actually selected, so this keeps the **first** frame of a burst and suppresses the tail — the right polarity for slides. Two limits: it merges by *time*, never by *content*, so a build with 4 s between bullets is indistinguishable from two real slides 4 s apart; and there is no equivalent for `scdet` (no expression language, and `scdet` does not declare `AVFILTER_FLAG_SUPPORT_TIMELINE_GENERIC`, so even `enable='between(t,...)'` is unavailable).

### 3.4 The inverse framing: detect staticness, not change

A slide is defined by being *still*, so "find the stable islands" is a first-class alternative to "find the transitions", and ffmpeg ships two filters for it.

[`mpdecimate`](https://github.com/FFmpeg/FFmpeg/blob/master/libavfilter/vf_mpdecimate.c) defaults: `hi` = `64*12` = **768**, `lo` = `64*5` = **320**, `frac` = **0.33**, `mode` = **0** (drop similar frames only), `max`/`max_drop_count` = **0**, `keep`/`max_keep_count` = **0**, `min_dup_count` = **1**. Documented at [ffmpeg-filters.html#mpdecimate](https://ffmpeg.org/ffmpeg-filters.html#mpdecimate).

[`freezedetect`](https://github.com/FFmpeg/FFmpeg/blob/master/libavfilter/vf_freezedetect.c) defaults: `noise`/`n` = **0.001** (range 0–1), `duration`/`d` = `2000000` µs = **2 s**. Also `AVFILTER_FLAG_METADATA_ONLY`.

`freezedetect` is the only stock ffmpeg filter with a built-in **minimum duration** — which is exactly the temporal-stability primitive the build and embedded-video cases need, just expressed as "this stretch of timeline was frozen for at least N seconds" instead of "this frame is a transition". Worth measuring in the spike as a candidate *shape*, not only as a filter.

Two mechanisms make these structurally different from `scdet`, and the difference is load-bearing:

- **The reference frame is pinned, not rolling.** `freezedetect` replaces `s->reference_frame` only when a frame is *not* frozen, and `mpdecimate` updates `decimate->ref` only on `DECIMATE_KEEP_UPDATE`. So change accumulates against a fixed anchor instead of being compared to the immediately previous frame. That is exactly why they survive slow transitions that `scdet`'s `min(mafd, diff)` suppresses.
- **`freezedetect` counts every plane.** `mafd = sad / count / (1 << bitdepth)` summed over all planes with `width[plane]` set, so chroma participates — unlike `scdet`. With `noise = 0.001` the tolerance is a mean absolute difference of ~0.256 code levels: extremely tight. **Consequence: a composited picture-in-picture webcam prevents any freeze from ever being reported.** `crop` before `freezedetect` is the deterministic mitigation.

`mpdecimate`'s implementation has two documented-vs-actual mismatches worth knowing before trusting its knobs. `diff_planes` evaluates 8×8 blocks stepped by **4** pixels (heavily overlapping) and short-circuits to "different" as soon as **one** block exceeds `hi` — so a single word appearing on a slide already marks the frame different, making it a high-recall change detector rather than a coarse one. But `frac`'s denominator is computed as `(w/16)*(h/16)`, i.e. as if blocks were non-overlapping 16×16, so at 1920×1080 `frac=0.33` behaves like roughly 2% of the ~127,600 blocks actually evaluated, not 33% of the image. The leftmost 8 columns are never examined (`x` starts at 8).

**`mpdecimate` emits no metadata at all** — its only trace is an `AV_LOG_DEBUG` line (`"%s pts:%s pts_time:%s drop_count:%d keep_count:%d"`). To use it you take its surviving frames as the output (`-vf mpdecimate -fps_mode vfr slide_%05d.png`), which is structurally "one frame per distinct run" — i.e. already the shape this project wants.

`freezedetect`, by contrast, emits exactly the interval triple you would want: `lavfi.freezedetect.freeze_start` (set on the first frame whose elapsed duration reaches `duration`, carrying the PTS of the **first** frame of the freeze), then `lavfi.freezedetect.freeze_duration` and `lavfi.freezedetect.freeze_end` on the first frame after the freeze ends ([ffmpeg-filters.html#freezedetect](https://ffmpeg.org/ffmpeg-filters.html#freezedetect)).

[`thumbnail`](https://ffmpeg.org/ffmpeg-filters.html#thumbnail) is **not** a change detector: it picks the frame whose 3×256-bin RGB histogram is closest to the batch average, over each batch of `n` frames (default **100**), and therefore emits exactly `ceil(frames/n)` frames regardless of content, with no metadata. It is a candidate for *within-island representative selection*, not for detection. It is also the only filter in this group that declares `AVFILTER_FLAG_SLICE_THREADS`.

[`siti`](https://ffmpeg.org/ffmpeg-filters.html#siti) is worth noting as a raw-signal alternative: it writes `lavfi.siti.si` and `lavfi.siti.ti` per frame with no threshold at all (only option: `print_summary`, default `0`). `ti` is a thresholdless temporal-change metric, so it hands the whole decision to downstream code rather than baking in `scdet`'s `min(mafd, diff)` heuristic.

[`decimate`](https://ffmpeg.org/ffmpeg-filters.html#decimate) (distinct from `mpdecimate`) is **not applicable**: `cycle` default 5 means it drops one frame in every N on a fixed cadence, for inverse telecine.

[`signature`](https://ffmpeg.org/ffmpeg-filters.html#signature) (MPEG-7 Video Signature) is the only ffmpeg filter that does content matching, and it does **not** help with the cutaway case: it matches between *separate inputs* (`nb_inputs`, default 1; `detectmode` default `off`), with no facility to match a single stream against its own earlier frames. Its `th_di` — "minimum length of a sequence in frames to recognize it as matching sequence" — is the only minimum-length knob in this area, and it applies to cross-input clip matching.

### 3.5 Harvesting the scores, and what the decode actually costs

Two documented ways to get per-frame scores out without re-encoding:

1. `metadata=mode=print` plus the `null` muxer. The `metadata` filter's print mode writes to a file (`-` for stdout) or to the log at `AV_LOG_INFO` if `file` is unset ([ffmpeg-filters.html#metadata](https://ffmpeg.org/ffmpeg-filters.html#metadata_002c-ametadata)); the `null` muxer "does not generate any output file" and is documented as "mainly useful for testing or benchmarking purposes" ([ffmpeg-formats.html#null](https://ffmpeg.org/ffmpeg-formats.html#null)). Output format, from `f_metadata.c`: `frame:%-4lld pts:%-7s pts_time:%s` followed by `<key>=<value>`. Adding `:value=10:function=greater` filters to transitions only.
2. `ffprobe -show_frames` prints frame metadata as a `frame_tags` subsection, so `-show_entries frame=pts_time:frame_tags=lavfi.scd.score` works. But **`ffprobe` has no `-vf`/`-filter` option**, so the input has to come through the lavfi virtual device (`-f lavfi -i "movie=in.mp4,scdet=t=10"`), and `movie=` exposes only `format_opts`, **not decoder options** — so this path forecloses `-skip_frame`.

Cost facts, each verified rather than assumed:

| Claim | Verdict |
|---|---|
| `-skip_frame nokey` avoids full decode | **Yes.** A decoder option ([ffmpeg-codecs.html](https://ffmpeg.org/ffmpeg-codecs.html)); in `h264_slice.c` the decoder returns from slice-header parsing before any macroblock reconstruction — no IDCT, no motion compensation, no deblocking. Caveat: frames carrying a recovery-point SEI are also kept, so open-GOP streams yield more than just IDRs. |
| `select='eq(pict_type,I)'` avoids decode | **No.** `select` runs inside the filtergraph, after the decoder; every frame is fully decoded and then discarded. It saves only downstream filter/encoder work. |
| `-discard nokey` avoids decode | **Yes, earlier still** — it drops at the demuxer, but the docs warn it "is not supported by all demuxers" ([ffmpeg.html](https://ffmpeg.org/ffmpeg.html#Main-options)), so whether mp4/matroska honours it for a given file is a measurement. |
| Input `-r` samples frames | **No.** As an input option it "ignore[s] any timestamps stored in the file and instead generate[s] timestamps assuming constant frame rate" — it rewrites timestamps. Only the `fps` filter (default `25`) or output `-r` drop frames, and the `fps` filter runs post-decode, so it saves detection work but **zero decode time**. |
| `-lowres` gives a decode-time downscale | **Not for H.264 or HEVC.** `ff_h264_decoder` declares no `max_lowres`; `mpeg12dec` and `mjpegdec` do. |
| `scdet` is slice-threaded | **No.** Only `AVFILTER_FLAG_METADATA_ONLY`; same for `select`, `freezedetect` and `mpdecimate`. `-filter_threads` (default: number of CPUs) parallelises *across* filters, not within these. The parallelism available on the target host is **decoder frame-threading** (`-threads`, default `auto`; H.264 declares both `AV_CODEC_CAP_SLICE_THREADS` and `AV_CODEC_CAP_FRAME_THREADS`). |
| `scdet` downscales internally | **No.** Full-resolution per-pixel SAD over the luma plane every frame, with SSE2/AVX2/AVX-512 kernels for 8-bit (`x86/scene_sad_init.c`). An i3-4170 is Haswell, so the AVX2 path applies. `scale=iw/4:ih/4` beforehand cuts the SAD work 16×, at the cost of attenuating small changes. |

**Sampling rate changes the meaning of the score**, which is easy to miss: `mafd` is measured against the previous *sampled* frame and `diff` against the previous *sampled* `mafd`, so a lower sampling rate produces larger inter-frame deltas and therefore higher scores for identical content. Any threshold calibrated at full frame rate is wrong at `fps=2`. The magnitude of that shift is not documented and must be measured.

### 3.6 What ffmpeg's docs do *not* say

Grepping the filter, CLI and codec docs turns up **no statement anywhere** about false positives from camera motion, flashes or fades, and no discussion of content-dependence of scene thresholds beyond the two hedged sentences quoted above ("good values are in the `[8.0, 14.0]` range"; "generally a sane choice"). Any claim about how these thresholds behave on talk video has to be established by measurement — the project cannot cite ffmpeg for it. And the one real mechanism the source reveals, `min(mafd, diff)`, is undocumented, untunable, and suppresses crossfades as readily as it suppresses embedded video.

## 4. PySceneDetect

### 4.0 Version caveat — read this before quoting any default

Two default sets are live and they disagree. The released **0.7.1** on PyPI and the published docs say `HashDetector(threshold=0.395, size=16)` and `HistogramDetector(threshold=0.05, bins=256)`; post-0.7.1 `main` says `0.35 / 8` and `0.20 / 128`. `main` adopted the parameter-sweep winners published at [scenedetect.com/benchmarks](https://www.scenedetect.com/benchmarks/), whose "best parameters" table lists exactly those values. `ContentDetector` (27.0), `AdaptiveDetector` (3.0 / 15.0 / 2) and `ThresholdDetector` (12) are identical in both. The spike must record which version it measured.

Sources: [`hash_detector.py`](https://github.com/Breakthrough/PySceneDetect/blob/main/scenedetect/detectors/hash_detector.py), [`histogram_detector.py`](https://github.com/Breakthrough/PySceneDetect/blob/main/scenedetect/detectors/histogram_detector.py), [`_cli/config.py`](https://github.com/Breakthrough/PySceneDetect/blob/main/scenedetect/_cli/config.py), [docs/latest/cli.html](https://www.scenedetect.com/docs/latest/cli.html).

### 4.1 `detect-content` (ContentDetector)

[`content_detector.py`](https://github.com/Breakthrough/PySceneDetect/blob/main/scenedetect/detectors/content_detector.py)

| Param | Default | Meaning |
|---|---|---|
| `threshold` | `27.0` (0.0–255.0) | `content_val` must reach it. Docs: "the max difference … that adjacent frames score must exceed to trigger a cut. Lower values are more sensitive." |
| `min_scene_len` | `15` frames (API) / `0.6s` (CLI global) | Handed to `FlashFilter(mode=filter_mode, length=min_scene_len)` |
| `weights` | `Components(delta_hue=1.0, delta_sat=1.0, delta_lum=1.0, delta_edges=0.0)` | **Edge detection is off by default**, "to improve performance" |
| `luma_only` | `False` | Overrides `weights` with `(0,0,1,0)` |
| `kernel_size` | `None` → auto = `4 + round(sqrt(W·H)/192)`, forced odd | For 1080p that is **13** |
| `filter_mode` | `FlashFilter.Mode.MERGE` | CLI `-f merge|suppress` |

The score is a **whole-frame mean absolute per-pixel delta** in HSV: each component is `sum(|int32(a) - int32(b)|) / num_pixels`, and `content_val = Σ(component·weight) / Σ|weight|`. The edge component is `cv2.Canny(lum, low, high)` with `sigma = 1/3`, `low = (1-sigma)·median(lum)`, `high = (1+sigma)·median(lum)`, dilated by the kernel. The source's own note: dilation "increases edge overlap leading to improved robustness against noise and slow camera movement. Note that very large kernel sizes can negatively affect accuracy."

Performance trap worth knowing: `calculate_edges = (weights.delta_edges > 0.0) or self.stats_manager is not None`, so attaching a stats manager (`--stats`) runs Canny + dilate on **every frame even at weight 0**. Slower, but it gives you the `delta_edges` column for free.

Docs' own starting point for turning edges on: `--weights 1.0 0.5 1.0 0.2 --threshold 32`, with the note that "delta_edges … [is] typically larger than other components, so threshold may need to be increased to compensate".

### 4.2 `detect-adaptive` (AdaptiveDetector) — the CLI default

[`adaptive_detector.py`](https://github.com/Breakthrough/PySceneDetect/blob/main/scenedetect/detectors/adaptive_detector.py)

| Param | Default | Meaning |
|---|---|---|
| `adaptive_threshold` | `3.0` | `adaptive_ratio` must reach it |
| `window_width` | `2` (CLI `-f/--frame-window`) | frames before **and** after the target; buffer = `1 + 2·window_width` = 5 |
| `min_content_val` | `15.0` | floor on the raw `content_val` |
| `min_scene_len` | `15` frames / `0.6s` | enforced by the detector itself, **not** by FlashFilter |
| `filter_mode` | **not available** | no such argument, no `--filter-mode` on this command |

It subclasses `ContentDetector` with `threshold=255.0, min_scene_len=0`, i.e. it disables the parent's threshold and disables FlashFilter entirely, then:

```
average_window_score = mean(scores in buffer excluding the centre frame)
adaptive_ratio       = min(target_score / average_window_score, 255.0)
   # if |average| < 1e-5: ratio = 255.0 if target_score >= min_content_val else 0.0
cut iff ratio >= adaptive_threshold and target_score >= min_content_val
        and (timecode - last_cut) >= min_scene_len
```

The cut is reported `window_width` frames behind the current frame. Project's stated purpose: "the threshold isn't fixed, but is a rolling average of adjacent frame changes. **This can help mitigate false detections in situations such as fast camera motions.**" It is the CLI's `default-detector`.

**The consequence that matters for slides:** on static slide content the neighbouring scores are ≈ 0, so the `average_is_zero` branch fires and `adaptive_ratio` is forced to `255.0` — but only if `target_score >= min_content_val`. Both gates then collapse into the single test `content_val >= 15.0`. So **on static content AdaptiveDetector degenerates into ContentDetector with threshold 15**, and `-c/--min-content-val` is the only knob that improves build recall. That degeneration is arguably favourable here: 15 is lower (more sensitive) than content's 27, while the rolling average still suppresses sustained motion elsewhere in the video.

### 4.3 `detect-hash` (HashDetector)

[`hash_detector.py`](https://github.com/Breakthrough/PySceneDetect/blob/main/scenedetect/detectors/hash_detector.py). Defaults: `threshold` `0.35` (main) / `0.395` (0.7.1), `size` `8` / `16`, `lowpass` `2`, `min_scene_len` `15`.

It is pHash, explicitly "based on phash from https://github.com/JohannesBuchner/imagehash". Algorithm: BGR→GRAY, `cv2.resize` to `(size·lowpass, size·lowpass)` with `INTER_AREA`, divide by max, `cv2.dct`, keep the top-left `size × size` block, binarise at the median. On `main` the frame is squashed to **16×16** and the hash is **64 bits**; in 0.7.1 it is 32×32 → **256 bits**. `hash_dist_norm = count_nonzero(curr != last) / (size·size)`, cut when it reaches `threshold`. So the threshold is a **fraction of differing bits**, as the docstring says: "a distance of 0 means the image is the same, and 1 means no correlation".

### 4.4 `detect-hist` (HistogramDetector) and `detect-threshold`

`HistogramDetector` ([source](https://github.com/Breakthrough/PySceneDetect/blob/main/scenedetect/detectors/histogram_detector.py)) takes a 1-D histogram of the **Y (luma) channel only** after `BGR2YUV`, normalises it, and compares with `cv2.compareHist(..., cv2.HISTCMP_CORREL)`. The threshold is inverted internally (`self._threshold = clamp(1.0 - threshold, 0, 1)`, test is `hist_diff <= self._threshold`), so CLI `--threshold 0.20` means "cut when correlation ≤ 0.80". It is **spatially blind by construction**.

`ThresholdDetector` ([source](https://github.com/Breakthrough/PySceneDetect/blob/main/scenedetect/detectors/threshold_detector.py)) measures `numpy.mean(frame_img)` against `threshold` (default `12`) to find fades to/from black, with `fade_bias` (default `0.0`), `method` (`Method.FLOOR`), `add_final_scene` and a deprecated `block_size`. It is not a shot-to-shot detector and its published hard-cut recall is ~0.

### 4.5 Downscaling, frame skip, threading — the cost story

[`scene_manager.py`](https://github.com/Breakthrough/PySceneDetect/blob/main/scenedetect/scene_manager.py)

- **`DEFAULT_MIN_WIDTH = 256`.** `compute_downscale_factor(frame_width, effective_width=256)` returns `frame_width / 256.0`, and `detect_scenes` calls it with the **larger** of width/height after `--crop`. **For 1080p input the default factor is `1920/256 = 7.5`, so detection runs at 256×144.** This is the single biggest recall risk for slide text, and `-d 1` (or `-d 2`) is the fix. The resize happens in the decode thread with `Interpolation.LINEAR` (config `downscale-method`, config-file only, no CLI flag — note [scenedetect.com/cli](https://www.scenedetect.com/cli/) still claims nearest-neighbour, which is stale).
- **`--frame-skip` is discouraged by the docs, for a reason that matters here:** "If set too large, enough frames may be skipped each time that the threshold is met during every iteration, continually triggering scene changes. This is because frame skipping essentially raises the threshold between frames in the same scene (making them more likely to appear as cuts) while not affecting the threshold between frames of different scenes." It is also **incompatible with `--stats`** (hard error).
- **Threading: exactly one background thread.** "Video decoding is done in a separate thread to improve performance"; `_decode_thread` reads, crops and downscales into a `queue.Queue(maxsize=4)`, and detectors run in the caller's thread. **No multiprocessing, no `--threads` flag.** So ~2 busy threads — a 2C/4T i3 has no idle-core headroom to exploit at the library level.
- **The one real multi-core lever** is the PyAV backend's `threading-mode` (config `[backend-pyav] threading-mode = auto|frame|none|slice`), which hands decode to ffmpeg's internal threading. Source warns that with `auto`/`frame`, if not all frames decode the video is reopened and the remainder decoded single-threaded. The OpenCV backend has no threading knob. **No published speed comparison between backends** — negative finding.
- Backend guidance ([backends docs](https://www.scenedetect.com/docs/latest/cli/backends.html)): OpenCV is the default and "mostly reliable and fast"; PyAV is "more robust … handles multiple audio tracks and frame decode errors gracefully" and gives the most accurate timecodes for VFR; MoviePy launches ffmpeg as a subprocess and does not support VFR.

### 4.6 Published accuracy and timing

[scenedetect.com/benchmarks](https://www.scenedetect.com/benchmarks/) publishes TRECVID-SBD-style scoring over BBC Planet Earth, AutoShot and ClipShots. Hard cuts at default settings, tolerance 0 (recall/precision/F1):

| Detector | BBC | AutoShot | ClipShots | ClipShots fades |
|---|---|---|---|---|
| Adaptive | 87.12/96.55/91.59 | 70.59/77.46/73.86 | 85.97/41.25/55.75 | 13.65/98.12/23.96 |
| Content | 84.70/88.77/86.69 | 63.49/76.19/69.26 | 81.93/42.36/55.84 | 26.03/98.04/41.14 |
| Hash | **92.30**/75.56/83.10 | 56.48/76.11/64.84 | 81.34/30.14/43.98 | 18.77/94.53/31.33 |
| Histogram | 89.84/72.03/79.96 | 63.27/53.23/57.82 | 72.20/11.47/19.80 | **69.67/81.99/75.33** |
| Threshold | 0.06/0.70/0.11 | 0.75/38.64/1.47 | 0.08/0.58/0.14 | 5.69/99.24/10.77 |

For a recall-first project the interesting column is recall: **HashDetector is the highest-recall hard-cut detector on BBC (92.30)**, Adaptive the highest on ClipShots (85.97), and Histogram is the fade specialist. Cross-dataset sweep optima ([SWEEP_REPORT.md](https://github.com/Breakthrough/PySceneDetect/blob/main/benchmark/SWEEP_REPORT.md)): Adaptive `3.5 / window 3 / 0.6s`, Content `31 / 0.6s`, Hash `0.35 / size 8`, Hist `0.20 / bins 128`, with the note that "long-form broadcast content (BBC) generally prefers lower thresholds than short web clips" — talk recordings are long-form.

Relative timing ([benchmark/README.md](https://github.com/Breakthrough/PySceneDetect/blob/main/benchmark/README.md), mean wall-clock seconds per video, **no hardware stated anywhere**, at the default 7.5× auto-downscale): BBC — Adaptive 36.12, Content 37.02, Hash 25.51, Histogram 22.29, Threshold 16.05. Treat as relative cost only: Hash ≈ 0.7× and Histogram ≈ 0.6× the cost of Content. At `-d 1` on 1080p the pixel work is ~56× larger than these numbers reflect.

### 4.7 Statsfile — the reason to keep PySceneDetect in the running regardless

`-s CSV / --stats CSV` writes per-frame metrics: "Used for tuning detection parameters and data analysis." Columns are `Frame Number` (1-based), `Timecode`, then each detector's metric keys:

| Detector | Columns |
|---|---|
| ContentDetector | `content_val`, `delta_hue`, `delta_sat`, `delta_lum`, `delta_edges` |
| AdaptiveDetector | the five above plus `adaptive_ratio (w=2)` |
| HashDetector | `hash_dist [size=8 lowpass=2]` |
| HistogramDetector | `hist_diff [bins=128]` (raw correlation, not the inverted threshold) |
| ThresholdDetector | `average_rgb` |

The docs' own tuning workflow: "generate a stats file (`-s`), open it with a spreadsheet editor … and examine the `content_val` column … The threshold value should be set so that most scenes fall below the threshold value, and scenes where changes occur should *exceed* the threshold value." For a spike that has to fit thresholds to labelled ground truth, this is the cheapest instrument available in any of the candidate libraries: one pass produces every metric, and thresholds are then fitted offline without re-decoding.

### 4.8 `min_scene_len` and FlashFilter — the exact merge algorithm

FlashFilter lives in [`scenedetect/detector.py`](https://github.com/Breakthrough/PySceneDetect/blob/main/scenedetect/detector.py) ("Filters fast-cuts to enforce minimum scene length") and is used by **ContentDetector only**; Adaptive, Hash and Histogram each roll their own simple refractory check. `length <= 0` disables it, and every above-threshold frame becomes a cut.

- **`Mode.SUPPRESS`** — emit the **first** above-threshold frame, then a hard refractory period of `min_scene_len`; everything inside it is dropped permanently. No lookahead.
- **`Mode.MERGE`** (default) — a burst of above-threshold frames spaced closer than `min_scene_len` collapses to **one cut at the LAST above-threshold frame of the burst**, reported only once the signal has been quiet for `min_scene_len`. A burst whose *total span* is shorter than `min_scene_len` is swallowed and deferred, not emitted, until a later above-threshold frame pushes the span past the limit. Lookahead cost is `filter_length` frames, or `ceil(seconds · 240.0)` when specified in seconds.

So `filter_mode` decides **which state of a progressive build you keep**: `MERGE` gives you the *fully built* slide, `SUPPRESS` gives you the *first, most incomplete* state. Setting `-m 1` (or `0`) disables the filter and emits **every** reveal — the maximum-recall setting, at the cost of N near-duplicates per slide. `--drop-short-scenes` is the alternative shape: it forces the detector's `min_scene_len` to `0` and instead post-filters the finished scene list by duration.

### 4.9 The three hard cases

**Progressive build.** ContentDetector will very likely miss it at defaults: `content_val` is a whole-frame mean, one bullet line moves it by a few units at most, and the default 7.5× downscale reduces the bullet to 1–3 px of height at 256×144. Knobs in order of leverage: (1) `-d 1` or `-d 2`; (2) `--threshold` well below 27; (3) turn edges on — a text reveal is almost pure edge energy, and the docs' own starting point is `--weights 1.0 0.5 1.0 0.2 --threshold 32`, with `--weights 0 0 0 1` plus a retuned threshold as the aggressive version. For AdaptiveDetector, `--min-content-val` (default 15.0) is the only knob that matters on static content, per 4.2. HashDetector is structurally the wrong tool — it squashes the frame to 16×16 (or 32×32), DCTs it, and keeps only the low-frequency block, deliberately discarding exactly the high-frequency detail a bullet consists of. HistogramDetector is worse still: a luma histogram barely moves when a line of text appears.

**Camera cutaway. No mechanism exists — definitive negative finding.** Every detector compares only against the immediately previous frame or a tiny window: `self._last_frame` (one frame), `self._last_hash`, `self._last_hist`, or Adaptive's 5-frame score buffer. No detector maintains any library, index or memory of previously seen frames or scenes; grepping the package for `duplicate|dedup|near-duplicate|repeat|revisit` yields nothing relevant. The output API (`get_scene_list()` → `(start, end)` timecode pairs) has no concept of scene identity or similarity. The return to slide 7 is emitted as a brand-new scene and you get a second screenshot of it. **Repeat detection has to be built outside PySceneDetect.**

**Embedded video.** Two mechanisms, both real, neither documented *as* embedded-video handling. (1) FlashFilter `MERGE` collapses a contiguous above-threshold run into a single cut, so an embedded clip yields one cut per burst rather than a flood; raise `-m/--min-scene-len` above the clip's internal cut spacing to widen the collapse window. (2) AdaptiveDetector's rolling average is the mechanism the project actually advertises for sustained motion: inside an embedded clip every frame in the ±`window_width` window scores high, so `adaptive_ratio = target/average` stays near 1.0, well under 3.0, and is suppressed. `--crop X0 Y0 X1 Y1` (added in 0.7) is the third, blunt lever — crop to the slide region to exclude a speaker inset entirely, which also shrinks the auto-downscale factor since it is computed from the cropped frame.

**The design tension, stated plainly:** the same single knob (`min_scene_len`) that suppresses an embedded-video flood also merges away progressive builds, and `filter_mode` only chooses whether you keep the first or the last frame of a merged burst. There is no per-region, per-duration or content-aware control.

### 4.10 Slide-specific mode?

**No.** Nothing in the repo, the docs or the website addresses slides, presentations, screencasts or static content; grepping source, `docs/` and `website/pages/` for `slide|presentation|screencast|static content|animation` returns only unrelated hits (e.g. "presentation timestamp"). All five detectors are generic shot-boundary detectors on adjacent-frame difference. There is a commented-out, never-implemented `MotionDetector` stub in `detectors/__init__.py` ("Detects motion events in scenes containing a static background") and a commented-out `DissolveDetector`. Notably, [scenedetect.com/features](https://www.scenedetect.com/features/) still lists "suppression of short-length flashes/bursts of light" under *Planned Features* even though FlashFilter exists — the site is stale in places.

One more finding worth flagging: `scenedetect/detectors/transnet_v2.py` exists on `main` (a pretrained neural detector via `onnxruntime`, docstring mentions a `detect-transnetv2` command) but is **not exported, not wired into the CLI, not in the config and not in the docs** — unreleased. Irrelevant for a no-GPU host, but it is where the project is heading.

## 5. OpenCV primitives and perceptual hashing

Defaults here were read from the OpenCV 4.x headers, because `docs.opencv.org` sits behind a Cloudflare bot challenge that refused every fetch from this network; the headers carry the exact doxygen text those pages are generated from, so the URLs below point at the source.

**A note on the numbers marked [measured]:** during this research a sub-agent ran micro-benchmarks on a host that happens to be an *`Intel(R) Core(TM) i3-4170 CPU @ 3.70GHz`, `nproc` 4* — the actual target hardware — using `cv2` 5.0.0 and `ImageHash` 4.3.2 against synthetically rendered 1920×1080 PIL slides and an mp4v test clip. **These are indicative, not primary sources**, and the fixtures are synthetic rather than a real H.264 talk recording, so decode figures are optimistic. They are included because they answer questions no primary source answers, and every one of them is a question spike #11 should re-measure on real video. Treat the *orderings and ratios* as transferable and the absolute numbers as provisional.

### 5.1 Background subtraction — the wrong object for a slide deck

Factory defaults, from [`background_segm.hpp`](https://github.com/opencv/opencv/blob/4.x/modules/video/include/opencv2/video/background_segm.hpp) and [`bgsegm.hpp`](https://github.com/opencv/opencv_contrib/blob/4.x/modules/bgsegm/include/opencv2/bgsegm.hpp):

| Factory | Defaults |
|---|---|
| `createBackgroundSubtractorMOG2` | `history=500`, `varThreshold=16`, `detectShadows=true` |
| `createBackgroundSubtractorKNN` | `history=500`, `dist2Threshold=400.0`, `detectShadows=true` |
| `bgsegm::createBackgroundSubtractorGMG` | `initializationFrames=120`, `decisionThreshold=0.8` |

Additional runtime defaults: MOG2 `nmixtures=5`, `backgroundRatio=0.9`; KNN `kNNSamples=2`, `nSamples=7`; GMG (from [`bgfg_gmg.cpp`](https://github.com/opencv/opencv_contrib/blob/4.x/modules/bgsegm/src/bgfg_gmg.cpp)) `maxFeatures=64`, `learningRate=0.025`, `quantizationLevels=16`, `backgroundPrior=0.8`, `smoothingRadius=7`.

What the docs say each one *models*: `history` is "the number of last frames that affect the background model"; MOG2 is a per-pixel mixture of 5 Gaussians (Zivkovic 2004/2006) whose `varThreshold` is "the main threshold on the squared Mahalanobis distance to decide if the sample is well described by the background model" and which "does not affect the background update"; KNN is the K-nearest-neighbours variant, "very efficient if number of foreground pixels is low"; GMG's learning rate "determines how quickly features are 'forgotten' from histograms".

The decisive fact is the learning rate. `BackgroundSubtractor::apply(image, fgmask, learningRate=-1)` is documented as: *"The value between 0 and 1 that indicates how fast the background model is learnt. Negative parameter value makes the algorithm to use some automatically chosen learning rate. 0 means that the background model is not updated at all, 1 means that the background model is completely reinitialized from the last frame."* The auto rate is in the source, identically in MOG2 ([`bgfg_gaussmix2.cpp`](https://github.com/opencv/opencv/blob/4.x/modules/video/src/bgfg_gaussmix2.cpp)) and KNN ([`bgfg_KNN.cpp`](https://github.com/opencv/opencv/blob/4.x/modules/video/src/bgfg_KNN.cpp)):

```cpp
learningRate = learningRate >= 0 && nframes > 1 ? learningRate : 1./std::min( 2*nframes, history );
```

So with defaults the adaptation rate settles at `1/history` = 0.002, a time constant of ~500 frames ≈ **20 s at 25 fps**. `getBackgroundImage` even warns that "sometimes the background image can be very blurry, as it contain the average background statistics".

**[measured]** What that means in practice, and it is worse than "not ideal":

- A static slide held on screen: default MOG2 reported foreground fraction `1.000000` on frame 1 and **`0.000000` from frame 2 onward**, unchanged through frame 2000 (80 s). The slide is absorbed into the background immediately; there is no "this slide is present" state to read.
- A real slide change is a decaying transient, not a state: after slide A was absorbed, switching to slide B gave a foreground fraction of `0.012006`, held it for ~50 frames, and was **back to `0.000000` by frame 100 (4 s)**. Miss the window and the event is gone.
- The cutaway case is **non-monotonic and history-dependent**, which is the real disqualifier:

  | Cutaway length | Foreground on returning to the *identical* slide A | Then a genuinely new slide B |
  |---|---|---|
  | 100 frames (4 s) | `0.000000` | `0.012006` |
  | 250 frames (10 s) | `0.000000` | `0.012006` |
  | 1000 frames (40 s) | `0.000000` | `0.012006` |
  | 5000 frames (200 s) | **`1.000000`** | **`1.000000`** |

  For short and medium cutaways the mixture still holds slide A as one of its five modes, so the return fires **nothing** — a silent miss. For a long cutaway the slide-A mode is evicted, the return fires the **whole frame**, and so does the next slide: the model is displaced and its output is meaningless for a while. The same visual event produces opposite outputs depending only on how long the camera was away. KNN behaved identically.
- Freezing the model with `learningRate=0` gives sane results (`A→0.000000`, `B→0.012006`) — but that is no longer background subtraction. It is "compare against one stored reference frame", i.e. `absdiff` with a Gaussian mixture bolted on at 23 ms/frame.

**Conclusion from the primary sources, not from taste:** all three model a temporal background with a forgetting curve, and a slide deck is a sequence of discrete stable states you want to *keep*, not a background you want to subtract away. The one legitimate use is the inverse framing `binh234` already implements: ignore the transition entirely and capture **when the foreground percentage falls below a threshold** (motion has stopped). Used that way it is a stability detector, and a good one for embedded video. Used as a change detector it fails the project's determinism preference by construction, because the answer for a given frame depends on the entire history before it.

`detectShadows=true` is the MOG2/KNN default and is meaningless on slide content; `binh234` correctly passes `False`. **[measured]** it saves nothing measurable (22.71 vs 22.99 ms) — the way to make a background subtractor affordable is to downscale (23 ms → 2.1 ms at 480×270), not to turn off shadows.

### 5.2 Histogram comparison — spatially blind by construction

`compareHist` metric formulas, from [`imgproc.hpp`](https://github.com/opencv/opencv/blob/4.x/modules/imgproc/include/opencv2/imgproc.hpp) (`enum HistCompMethods`):

| Method | Formula | Direction |
|---|---|---|
| `HISTCMP_CORREL` | `Σ(H₁−H̄₁)(H₂−H̄₂) / sqrt(Σ(H₁−H̄₁)²·Σ(H₂−H̄₂)²)` | 1 = identical |
| `HISTCMP_CHISQR` | `Σ (H₁−H₂)² / H₁` | 0 = identical; unbounded, asymmetric, undefined where `H₁=0` |
| `HISTCMP_INTERSECT` | `Σ min(H₁, H₂)` | larger = more similar; **unnormalised** |
| `HISTCMP_BHATTACHARYYA` | `sqrt(1 − (1/sqrt(H̄₁H̄₂N²))·Σ sqrt(H₁·H₂))` — docs note OpenCV actually computes the **Hellinger** distance | 0 = identical |
| `HISTCMP_CHISQR_ALT` | `2·Σ (H₁−H₂)²/(H₁+H₂)` | 0 = identical |
| `HISTCMP_KL_DIV` | `Σ H₁ log(H₁/H₂)` | 0 = identical; asymmetric |

**Every formula is a sum over bins. There is no position term anywhere**, because `calcHist` increments a bin per pixel value and discards location. Two consequences, both fatal for slides:

1. A new bullet line only changes the *count* of dark pixels. On a 1920×1080 slide a 48 px text line is roughly 0.5% of pixels, perturbing two bins by 0.5% of the total mass — invisible against a background bin that dominates the denominator.
2. Worse, the converse: **a different layout of the same ink is an exact match.**

**[measured]**, 256-bin normalised grey histograms on synthetic slides:

| Pair | Changed-pixel fraction | CORREL | CHISQR | INTERSECT | BHATTACHARYYA |
|---|---|---|---|---|---|
| 4→5 bullets (one line added) | 0.00651 | 0.99999 | 0.0021 | 1.0456 | 0.0145 |
| tiny footnote added | 0.00265 | 1.00000 | 0.0930 | 1.0457 | 0.0244 |
| **completely different slide** | 0.03103 | **0.99997** | 0.0061 | 1.0343 | 0.0299 |
| **same slide flipped vertically** | 0.08393 | **1.00000** | **0.0000** | 1.0457 | **0.0000** |

The flip row is the proof: 8.4% of pixels changed and all four metrics report a *perfect* match. `CHISQR` even ranks the footnote (0.0930) as a bigger change than the full slide swap (0.0061), and the entire CORREL spread across these four cases is inside 3×10⁻⁵ — **no threshold separates the classes.** Histogram comparison is a colour-palette detector, and a slide deck has one palette. Cost is trivial (**[measured]** 1.25 ms/frame at 1080p), and its one genuine strength, per PySceneDetect's published benchmarks (4.6), is fades.

This is the technique `AnuragSingh2101` relies on (HSV correlation < 0.92) and the one behind PySceneDetect's `detect-hist`. It should be in the spike only as a control.

### 5.3 Frame differencing — the honest baseline, and the only primitive with a usable margin

`absdiff` computes `dst(I) = saturate(|src1(I) − src2(I)|)` per element, per channel; `countNonZero` returns `Σ 1` over non-zero elements and, per the docs, "do not work with multi-channel arrays" ([`core.hpp`](https://github.com/opencv/opencv/blob/4.x/modules/core/include/opencv2/core.hpp)). So `frac = countNonZero(absdiff(a,b) > τ) / (W·H)` is the fraction of pixels whose intensity moved by more than τ — a spatially localised, stateless, order-preserving scalar. Unlike a histogram it *does* have a position term.

**[measured]** at 1920×1080, τ = 25 on greyscale:

| Change | Changed-pixel fraction |
|---|---|
| footnote line added (28 px text) | 0.00265 |
| one bullet line added (48 px text) | 0.0033 – 0.0065 across five build steps |
| whole new slide (new title, 4→2 bullets) | **0.03103** |
| same slide flipped vertically | 0.08393 |

That is a **5–10× separation between a progressive build and a full slide change** — the only usable ordering produced by any of the OpenCV change primitives. Note the absolute scale, though: catching a one-line build needs a threshold below 0.3%, about 5,500 of 2.07 M pixels, which is the same amplitude as sensor noise, auto-exposure drift, H.264 mosquito noise and a laser pointer. Recall-first therefore means threshold low, accept duplicates, and deduplicate afterwards on a **different signal** — which is exactly the two-stage shape 5.5 argues for.

Two implementation choices in the reference code matter as much as the primitive: **block-wise aggregation** rather than per-pixel (a block counts only if its mean absolute difference exceeds `blockDelta`, absorbing compression noise — `larry-xue`), and **dilation** of the thresholded difference before counting (`getStructuringElement(MORPH_ELLIPSE, (7,7))` in `binh234`), which grows thin text strokes into countable area.

Cost **[measured]**: `absdiff` + `threshold` + `countNonZero` is **0.82 ms/frame** at 1080p and **0.04 ms** at 480×270 — the cheapest thing measured.

### 5.4 The blur gate

`Laplacian(src, dst, ddepth, ksize=1, ...)` computes `Δsrc = ∂²src/∂x² + ∂²src/∂y²` via Sobel when `ksize > 1`; **at the default `ksize=1` it filters with the plain 3×3 aperture `[[0,1,0],[1,-4,1],[0,1,0]]`** ([`imgproc.hpp`](https://github.com/opencv/opencv/blob/4.x/modules/imgproc/include/opencv2/imgproc.hpp)).

**Negative finding: OpenCV's documentation never mentions variance-of-Laplacian, focus measures, or blur detection.** `cv2.Laplacian(...).var()` is a community idiom with no OpenCV-documented standing. The algorithmic reference is Pech-Pacheco, Cristóbal, Chamorro-Martínez and Fernández-Valdivia, *"Diatom autofocusing in brightfield microscopy: a comparative study"*, ICPR 2000 — [DOI 10.1109/ICPR.2000.903548](https://doi.org/10.1109/ICPR.2000.903548), [dblp](https://dblp.org/rec/conf/icpr/Pech-PachecoCCF00.html). The paper is paywalled and could not be read in full during this research, so its exact formulation is **not** verified here; it is cited as the origin of the measure, not as a source for a threshold.

**[measured]** it does work, with large margins — 1080p synthetic slide, `cv2.Laplacian(gray, CV_64F).var()`: crisp **960.29**, 1 px Gaussian blur 81.05, 2 px 12.78, 4 px 1.14, 8 px 0.41. Nearly 12× for one pixel of blur; any threshold in 100–300 separates crisp from soft, which is consistent with `sumerene`'s choice of 300.

**Cost warning [measured]:** `Laplacian(CV_64F)` + `.var()` is **15.10 ms/frame** at 1080p — the most expensive primitive apart from the background subtractors — and it is memory-bandwidth-bound, not compute-bound: `setNumThreads(1)` → 13.28 ms, `(2)` → 13.65 ms, `(4)` → **16.67 ms**, i.e. threads make it *worse*. Two cheap fixes: `CV_16S` + `meanStdDev` = 3.12 ms, or run it on a 480×270 downscale = 0.41 ms (37×). Use it as a gate on candidate frames, never per frame.

Limitation to keep in mind: a speaker or audience shot in sharp focus also has high Laplacian variance. This gate rejects *blurry* non-slide frames, not non-slide frames in general.

### 5.5 Perceptual hashing — the cutaway mechanism, and the build blind spot

Signatures and defaults, from [`imagehash/__init__.py`](https://github.com/JohannesBuchner/imagehash/blob/master/imagehash/__init__.py):

| Function | Signature | Bits at default |
|---|---|---|
| `average_hash` | `(image, hash_size=8, mean=numpy.mean)` | 64 |
| `phash` | `(image, hash_size=8, highfreq_factor=4)` | 64 |
| `phash_simple` | `(image, hash_size=8, highfreq_factor=4)` | 64 |
| `dhash` / `dhash_vertical` | `(image, hash_size=8)` | 64 |
| `whash` | `(image, hash_size=8, image_scale=None, mode='haar', remove_max_haar_ll=True)` | 64 |
| `colorhash` | `(image, binbits=3)` | 42 |
| `crop_resistant_hash` | `(image, hash_func=dhash, limit_segments=None, segment_threshold=128, min_segment_size=500, segmentation_image_size=300)` | multi-hash |

`ImageHash.__sub__` is `numpy.count_nonzero(self.hash.flatten() != other.hash.flatten())` — plain Hamming distance, so the maximum is `hash_size²` = **64** at the default (42 for `colorhash`).

`phash`'s implementation is the whole answer to the progressive-build question:

```python
img_size = hash_size * highfreq_factor          # 8 * 4 = 32
image = image.convert('L').resize((img_size, img_size), ANTIALIAS)
dct = scipy.fftpack.dct(scipy.fftpack.dct(pixels, axis=0), axis=1)
dctlowfreq = dct[:hash_size, :hash_size]        # top-left 8x8, DC included
diff = dctlowfreq > numpy.median(dctlowfreq)
```

A 1920×1080 slide is antialias-downsampled to **32×32**, and only the **8×8 lowest-frequency DCT coefficients** survive — spatial frequencies up to 8 cycles across the frame. A text line is a far higher-frequency feature than that, so most of its energy lands in the discarded coefficients. `dhash` is coarser still (resize to 9×8, compare adjacent columns), and `average_hash` operates on an **8×8 thumbnail** of the whole slide.

**[measured]**, and it is worse than "a handful of bits". Progressive build, state *n* vs *n+1* bullets:

| Build step | phash₈ | dhash₈ | ahash₈ | phash₁₆ | dhash₁₆ |
|---|---|---|---|---|---|
| 1→2 bullets | 12 | 4 | 5 | 30 | 14 |
| 2→3 | 10 | 5 | 6 | 28 | 7 |
| 3→4 | 8 | 5 | 3 | 20 | 11 |
| 4→5 | 6 | 4 | 5 | 18 | 10 |
| 5→6 | 8 | 3 | 3 | 24 | 7 |

And the decisive case — one 28 px footnote line added, 0.27% of pixels:

| | phash₈ | dhash₈ | ahash₈ | phash₁₆ | phash₃₂ |
|---|---|---|---|---|---|
| footnote added | **0** | 2 | 2 | 6 | 46 |

**A visible content change produced Hamming distance exactly 0 at the default `hash_size=8`** — not "below threshold", *bit-identical*, same 16 hex characters. Reference points from the same run: an entirely different slide scored phash₈ 24 / dhash₈ 20 / ahash₈ 12; the same slide flipped vertically scored phash₈ 28. So at `hash_size=8`:

- `dhash₈`: builds at 3–5, a new slide at 20. Workable only with a threshold ≤ 2, which is 3% of the space and leaves nothing for codec noise.
- `ahash₈`: builds at 3–6, a new slide at 12 — and in one run a *different* slide scored 5, the same as a one-bullet build. **Total overlap; no threshold exists.**
- `phash₈`: builds at 0–12, a new slide at 24. The thresholds that circulate in practice (5, 10) **silently swallow most builds.**

**Under a recall-first policy this is the exact damage the map says is unacceptable: a silent miss.** It also explains, mechanically, why `sumerene` (pHash/dHash distance 10 of 64) and `kovitking` (10 of 256) collapse builds — they were not designed to see them.

**Larger `hash_size` fixes it, and is nearly free on this CPU.** The README states the principle ("increasing the hash size allows an algorithm to store more detail in its hash, increasing its sensitivity to changes in detail"), and `phash(hash_size=32)` resizes to 128×128 and keeps a 32×32 DCT block = 1024 bits, so text-line-scale features survive. **[measured]** on the footnote pair: phash₈ 0 → phash₁₆ 6 → phash₃₂ **46**; on the 4→5-bullet build: 6 → 18 → **100** → 448 at hash_size 64. Cost is flat, because PIL's resize of the 1080p image dominates the DCT: **[measured]** 9.94 ms at `hash_size=8` vs 10.91 ms at 32 (dhash₈ 7.85 ms, ahash₈ 7.81 ms). The trade-off is that wider hashes are also more sensitive to camera noise and re-encoding, so the threshold has to be recalibrated as a *fraction* of bits — Zauner's normalised-BER framing, below.

**Negative finding on thresholds:** no primary source recommends a number. The README says only "you may want to adjust the hashsize or require some manhattan distance (`hash1 - hash2 < threshold`)" and defers to third-party blog posts. [Issue #76 "Rule of thumb Threshold for phash"](https://github.com/JohannesBuchner/imagehash/issues/76) is answered "it all depends on your data, check the diff between your images and see how low does the threshold needs to be in order to avoid collision". The only default threshold in the library is `bit_error_rate = 0.25` for crop-resistant multi-hashes. Every threshold quoted anywhere in this document is a project's own choice, not library guidance.

**Primary-source acknowledgement that this blind spot is inherent:** in [issue #150 "Many images are mistakenly identified as identical"](https://github.com/JohannesBuchner/imagehash/issues/150) the maintainer's diagnosis is the mechanism itself — "have a look at the images after `image.convert("L").resize((hash_size, hash_size), Image.ANTIALIAS)`, which is what average_hash operates on. hash_size is 8 by default" — closed with "I'm closing this as it is a property of the implemented algorithms." A user in that thread swept `hash_size` from 8 to 1024 over 3,500 photos and saw duplicates fall 213 → 187 (16) → 182 (32) → 179 (64) and then flat, i.e. widening recovers real distinctions up to a point and then saturates. See also [#145](https://github.com/JohannesBuchner/imagehash/issues/145) and [#13](https://github.com/JohannesBuchner/imagehash/issues/13) (pHash's bias toward repetitive bit patterns).

**Determinism hazards to pin:** `crop_resistant_hash`'s docstring warns that "slightly different segmentations are produced when using pillow version 6 vs. >=7, due to a change in rounding in the greyscale conversion"; [#128](https://github.com/JohannesBuchner/imagehash/issues/128) notes the downscaling interpolation method changes results; the changelog records that "4.0: changed binary to hex implementation … this change breaks compatibility to previously stored hashes"; and [#152](https://github.com/JohannesBuchner/imagehash/issues/152) reports that `ImageMultiHash.__sub__` is **not commutative**. Pin `Pillow`, `ImageHash`, `numpy` and `scipy`, and store the versions alongside any persisted hashes.

### 5.6 Why hashing is the cutaway mechanism

A hash is a **stateless, order-independent function of a single frame**, so you can keep every slide already captured and match a returning frame against the whole set. Nothing decays, nothing is forgotten, and the answer for a frame does not depend on what came before it — which is also what makes it deterministic, in exactly the way background subtraction is not (5.1).

What the API actually offers:

- **Exact matching via dict keys** works (`ImageHash` "can be used for dictionary keys and comparisons"), but with a caveat straight from the source: `__hash__` carries the comment `# this returns a 8 bit integer, intentionally shortening the information`. So dict membership is a 256-bucket hash with exact-bit equality — O(1), but it only ever finds *bit-identical* returns. Given 5.5, an exact-match dict on `phash₈` would happily unify a slide with its next build step.
- **Persistence** via `str(hash)` → hex and `imagehash.hex_to_hash(hexstr)` (with `hex_to_flathash` for colorhash and `hex_to_multihash` for crop-resistant), and `old_hex_to_hash` to migrate pre-4.0 values.
- **Distance search: you write the loop.** There is no index and no threshold helper for plain `ImageHash`. The README is explicit — "for storing the hashes in a database and using fast hamming distance searches, see pointers at [issue #127](https://github.com/JohannesBuchner/imagehash/issues/127) (a blog post on how to do this would be a great contribution!)". **Negative finding: `imagehash` ships no nearest-neighbour search at all.** At this project's scale that is irrelevant: a 45–60 minute talk has O(100) slides, so a linear scan of 100 stored hashes per candidate frame is ~100 numpy `count_nonzero` calls on 64–1024-bit arrays, i.e. microseconds.
- The one built-in set-matching API is on `ImageMultiHash` (crop-resistant hashes only): `best_match(other_hashes, hamming_cutoff=None, bit_error_rate=None)`, `matches(...)`, `hash_diff(...)`, default `bit_error_rate=0.25`.

`crop_resistant_hash` implements *"Efficient Cropping-Resistant Robust Image Hashing"* ([DOI 10.1109/ARES.2014.85](https://doi.org/10.1109/ARES.2014.85)), which the docstring says claims "resistance to up to 50% cropping, while most other algorithms stop at about 5% cropping" — worth knowing if dedupe has to run before the slide-region crop is stable.

### 5.7 OpenCV's own `img_hash` module — and why it is disqualified

Classes and defaults, from the [`img_hash` headers](https://github.com/opencv/opencv_contrib/tree/4.x/modules/img_hash/include/opencv2/img_hash): `AverageHash::create()` (no params, "only work on simple case"), `PHash::create()` (no params, "slower than average_hash, but tolerant of minor modifications"), `BlockMeanHash::create(mode = BLOCK_MEAN_HASH_MODE_0)`, `MarrHildrethHash::create(alpha=2.0f, scale=1.0f)` ("slowest but more discriminative"), `RadialVarianceHash::create(sigma=1, numOfAngleLine=180)`, `ColorMomentHash::create()` ("the one and only hash algorithm resist to rotation attack (-90~90 degree)").

Two findings matter:

1. **`ImgHashBase::compare` returns a value whose "meaning … vary from algorithms to algorithms"** — Hamming for AverageHash/PHash/BlockMeanHash/MarrHildrethHash, `norm(L2)·10000` for ColorMomentHash, a custom Pearson correlation for RadialVarianceHash. Values are not comparable across algorithms.
2. **`cv::img_hash::PHash` is hard-wired to 64 bits and cannot be widened.** From `src/phash.cpp`: resize to `Size(32,32)` with `INTER_LINEAR_EXACT`, `cv::dct`, take `Rect(0,0,8,8)`, zero the DC term, threshold on the **mean** (Python `imagehash` keeps DC and uses the **median**). `average_hash.cpp` resizes to `Size(8,8)`. Neither exposes a `hash_size`. Given that 5.5 shows 64 bits is *insufficient* for progressive builds, **`cv::img_hash` is disqualified for that job — only Python `imagehash` can widen the hash.**

The docs page does publish speed charts (as JPEG images, not text). Read from [`hash_computation_chart.JPG`](https://github.com/opencv/opencv_contrib/blob/4.x/modules/img_hash/doc/hash_computation_chart.JPG), total µs over 100 ukbench images: **AverageHash 739, PHash 3927**, BlockMeanHash-zero 75,263, BlockMeanHash-one 97,342, RadialVarianceHash 180,618, ColorMomentHash 424,210, **MarrHildrethHash 787,125**. Comparison cost is 30–500 µs for all of them. So only AverageHash, PHash and BlockMeanHash are viable per frame on a 90,000-frame job; Marr-Hildreth is three orders of magnitude too slow. **Negative finding:** the module's `attack_performance.JPG` robustness chart is an unlabelled 3-D cone plot, so **the OpenCV docs publish no extractable robustness numbers**.

### 5.8 Zauner 2010 — the algorithmic reference, and what it does *not* cover

Christoph Zauner, *"Implementation and Benchmarking of Perceptual Image Hash Functions"*, Diplomarbeit, FH Hagenberg, July 2010 — [phash.org/docs/pubs/thesis_zauner.pdf](http://www.phash.org/docs/pubs/thesis_zauner.pdf). This is the work OpenCV cites as `@cite zauner2010implementation`.

- Its metric is the **Bit Error Rate** `ρ = i/k`, "the number *i* of bit errors of the perceptual hash normalized by the length *k*", where "the number of the bit errors *i* equals the hamming distance". Key calibration: "**when comparing perceptually different images the BER should be approximately 0.5** … perceptually equal images should yield a BER close to 0."
- On DCT hashing: "**low-frequency DCT coefficients of an image are mostly stable under image manipulations** … the elements close to the top-left … represent low-frequency components and are therefore deemed to be perceptually most significant." That is the property being exploited — and, for a progressive build, the property that causes the miss.
- On thresholds: "**consequently, the selection of the threshold is crucial** … authentic and not authentic media objects can not be separated clearly. **The boundary between these two sets is fuzzy.**"
- Discrimination (Table 6.4, where a perfect hash would always yield 0.5): DCT mean 0.501/0.496 on its two image sets, Marr-Hildreth 0.499/0.500, Radial 0.565/0.532, Block-mean 0.482/0.478. "The Marr-Hildreth operator based image hash has by far the most discriminative abilities. **The DCT based image hash performs as second best.**" It also notes that with DCT hashing "specific distance scores occur very often (e.g. 0.531 or 0.469)".
- Robustness (lower BER = more robust): JPEG q=80 — DCT mean **0.001**, Marr-Hildreth 0.045, Radial 0.000, Block-mean 0.001, robust "up to a quality parameter of 10"; resize to 1024 px — DCT 0.076, Block-mean 0.012; rotation 5° — "**none of the tested image hash functions is robust**"; horizontal flip — "**none** of the tested perceptual image hash functions is robust against horizontal flipping" (DCT 0.497).
- Speed on a Core 2 Duo T9300 (Table 6.3, 94 images): DCT 911 s total, Marr-Hildreth 343 s, Radial 118 s, Block-mean 58 s — "the newly implemented block mean value based perceptual image hash function is the fastest … far behind are the Marr-Hildreth operator based (343 seconds) and the DCT based (911 seconds)". CPU-era numbers on 2008 hardware; the ordering, not the magnitude, transfers.

**The transferable lesson, and the gap:** DCT hashing is near-perfectly robust to *global photometric* perturbation — mean BER 0.001 at JPEG q80, which is exactly the good news for a slide re-encoded by a video codec — and its inter-image distances sit tightly around 0.5. But the thesis measures robustness against *whole-image* transforms and discrimination against *entirely different images*. **It never measures a small local content edit.** The primary literature is silent on precisely the case a progressive build presents, which is why 5.5 had to be measured rather than cited.

### 5.9 Cost on the target host

Threading API, from [`utility.hpp`](https://github.com/opencv/opencv/blob/4.x/modules/core/include/opencv2/core/utility.hpp): `setNumThreads(n)` — "if threads == 1, OpenCV will disable threading optimizations and run all it's functions sequentially. Passing threads < 0 will reset threads number to system default. **The function is not thread-safe.**"; `getNumThreads()` — "always returns 1 if OpenCV is built without threading support"; `useOptimized()` reports whether SIMD dispatch is active, and `setUseOptimized` is "only safe to call … on the very top level in your application".

**[measured]** on the target i3-4170: `getNumberOfCPUs()` 4, `getNumThreads()` 4, `useOptimized()` True, CPU features line `SSE SSE2 SSE3 *SSE4.1 *SSE4.2 *AVX *FP16 *AVX2 *AVX512-SKX?` — AVX2 available (Haswell), AVX-512 not.

**Does `VideoCapture` decode every frame? Yes, unless you use `grab()`.** The `grab()` doxygen ([`videoio.hpp`](https://github.com/opencv/opencv/blob/4.x/modules/videoio/include/opencv2/videoio.hpp)) describes the mechanism for exactly this purpose: "you call `VideoCapture::grab()` for each camera and after that call the slower method `VideoCapture::retrieve()` to decode and get frame from each camera. This way **the overhead on demosaicing or motion jpeg decompression etc. is eliminated**." `retrieve()` "**decodes** and returns the grabbed video frame"; `read()` "combines `VideoCapture::grab()` and `VideoCapture::retrieve()` in one call".

**[measured]** on a 750-frame 1080p mp4v file, FFMPEG backend: `read()` every frame → 408 fps; `grab()` only → **977 fps**; `grab()` every frame plus `retrieve()` every 25th → 1001 fps. So **~2.4× is saved by skipping the retrieve**. Caveat: mp4v decodes far faster than a real 1080p H.264 talk, so treat the ratio rather than the absolute rate as transferable.

**Seeking is not the cheap option it looks like.** `CAP_PROP_POS_FRAMES` is documented as the "0-based index of the frame to be decoded/captured next", with the only guarantee being that "when the index i is set in RAW mode (`CAP_PROP_FORMAT == -1`) this will seek to the key frame k, where k <= i". `set()` returning `true` "doesn't ensure that the property value has been accepted", and `get()` carries a warning that "reading / writing properties involves many layers … the returned value might be different from what really used by the device". **Negative finding: OpenCV documents neither the cost nor the accuracy of a non-RAW-mode seek.** **[measured]** retrieving 30 frames out of 750: `set(POS_FRAMES)` + `read()` thirty times = 0.709 s (23.6 ms per seek); sequential `grab()`-all + `retrieve()` every 25th = 0.691 s. **Sequential grab wins and cannot silently land on the wrong frame** — seek only when the sampling interval is much coarser than one in 25 frames.

**[measured]** per-frame cost table, i3-4170, 4 threads, warmed up:

| Operation | 1920×1080 | 480×270 |
|---|---|---|
| `cvtColor BGR2GRAY` | 0.67 ms | — |
| `resize` 1080p → 480×270, `INTER_AREA` | 1.91 ms | — |
| `absdiff` + `threshold` + `countNonZero` | 0.82 ms | **0.04 ms** |
| `calcHist` 256 bins | 1.25 ms | — |
| `Laplacian CV_64F` + `.var()` | 15.10 ms | 0.41 ms |
| `Laplacian CV_16S` + `meanStdDev` | 3.12 ms | — |
| `MOG2.apply` | 22.99 ms | 2.11 ms |
| `MOG2.apply` (`detectShadows=False`) | 22.71 ms | — |
| `KNN.apply` | 23.43 ms | 2.21 ms |
| `imagehash.phash` (hash_size 8 / 16 / 32) | 9.94 / 9.74 / 10.91 ms | — |
| `imagehash.dhash` (hash_size 8) | 7.85 ms | — |
| `imagehash.average_hash` (hash_size 8) | 7.81 ms | — |

**Budget sanity check.** A 60-minute 25 fps video is 90,000 frames. Walking the file with `grab()` alone is ~92 s. Per-frame `MOG2` at 1080p would add 90,000 × 22.99 ms ≈ **34 minutes**. Per-frame `absdiff` on a 480×270 downscale adds 90,000 × (1.91 + 0.04) ms ≈ **3 minutes**. Hashing every sampled frame at 1 fps (3,600 frames × ~10 ms) is ≈ 36 s. That spread — three minutes versus thirty-four — is the whole cost argument, and it says the same thing the reference implementations do: sample sparsely, work at low resolution for the trigger, and spend the expensive per-frame operations only on candidates.

### 5.10 Summary of the primitives

| Primitive | Deterministic? | Separates a build from a slide change? | Cost/frame at 1080p **[measured]** |
|---|---|---|---|
| MOG2 / KNN / GMG | **No** — output depends on the whole frame history; the same event gives 0.0 or 1.0 depending on cutaway length | No — a real change is 1.2% foreground vs ~0.5% for a build, and both decay to 0 within 4 s | 23 ms (2.1 ms at 480×270) |
| `compareHist` | Yes | **No** — a vertical flip scores a perfect match on all four metrics | 1.25 ms |
| `absdiff` + `countNonZero` | Yes, stateless | **Yes, 5–10× margin** (0.003–0.006 build vs 0.031 slide change) | **0.82 ms** (0.04 ms at 480×270) |
| `Laplacian` variance | Yes, stateless | n/a — a quality gate (960 crisp vs 81 at 1 px blur) | 15.1 ms (3.1 ms `CV_16S`; 0.41 ms at 480×270) |
| `imagehash` phash/dhash | Yes, stateless, and **set-matchable** — solves the cutaway | Only at `hash_size >= 16`; **at the default 8 a real edit scored distance 0** | ~8–11 ms, flat in `hash_size` |

The two mechanisms that survive all three of the project's constraints are **frame differencing** (cheap, local, ordered — a good trigger) and **wide perceptual hashing** (stateless and order-independent — the only thing here that can answer "have I already captured this slide?" after a cutaway). Background subtraction fails the determinism preference by construction, and histogram comparison fails discrimination by construction, and in both cases the primary sources say why: a learning-rate background model exists to *forget* what you are trying to capture, and every `compareHist` formula is a sum over bins with no position term.

## 6. What the reference implementations actually do

Constants below were read from source in September 2026, not from READMEs. This section exists because the reference projects have already made the design choices this ticket is investigating, and their code states the answers more precisely than their documentation does.

### 6.1 `larry-xue/video-slide-extractor` — block diff + Otsu calibration + activity mask

Active (last push 2026-09-06). Zero-dependency JS library; the CLI adds only `ffmpeg`/`ffprobe` as external binaries. Source: [`index.js`](https://github.com/larry-xue/video-slide-extractor/blob/master/index.js), [`cli.js`](https://github.com/larry-xue/video-slide-extractor/blob/master/cli.js).

| Knob | Default | Meaning |
|---|---|---|
| `blockSize` | `8` px | block edge at the downsampled diff resolution |
| `blockDelta` | `14` | mean `|ΔRGB|` per channel for a block to count as changed |
| `changedRatio` | `0.02` | fraction of scored blocks that flags a new slide |
| `--fps` | `1` | frames sampled per second |
| `--width` (`DIFF_WIDTH`) | `320` px | detector working width |
| `MAX_CALIBRATION_FRAMES` | `150` | bounded sample buffered for calibration |
| `activeFrac` | `0.5` | a block changing in more than 50% of frame pairs is masked out |
| `maxMaskFrac` | `0.35` | a mask covering more than 35% of the frame is discarded |
| Otsu clamp | `min 0.005`, `max 0.15` | bounds on the calibrated threshold |

Three mechanisms matter:

1. **The reference frame is the last *kept* frame, not the previous frame** (`createSlideDetector`), giving hysteresis so slow drift never accumulates into a detection.
2. **`buildActivityMask`** finds blocks that keep changing across sampled pairs and excludes them from both the numerator and the denominator of the ratio. The source names the exact targets: "a webcam bubble, a cursor, or an animated logo … or embedded video — not slide content". It refuses to mask when the mask would cover more than 35% of the frame, on the stated grounds that if most of the picture is moving, the moving part *is* the subject. **This is the clearest deterministic answer to the embedded-video case found anywhere in the survey.**
3. **`chooseThreshold`** classifies footage into three regimes from the distribution of diff ratios: `bimodal` (deck-like, uses a 1-D Otsu split between the "same slide" noise cluster and the "slide changed" cluster, with a bimodality guard), `static`, and `motion` (talking-head/camera footage, threshold = `median + 2·MAD` clamped to `[0.25, 0.65]`). The regime decider is `staticFrac`, the fraction of frame pairs with ratio < 0.02; `>= 0.6` means deck-like. The mask is kept only when masking turns the footage back into deck-like content.

CLI architecture, worth copying: three ffmpeg passes — `ffprobe` for geometry, a bounded calibration pass, then a streaming detection pass (`-vf fps=N,scale=W:H` piped raw) — after which kept timestamps are re-extracted from the source at full resolution with `ffmpeg -ss t -i file -frames:v 1 -q:v 2`. Memory stays flat regardless of video length. `grabPoint` deliberately grabs one sample interval *into* the slide's dwell rather than at the detected timestamp, so the exported image is not a half-faded transition frame.

### 6.2 `patrickmineault/vid2slides` — global HMM assignment

Orphan (last push 2020-11-23), but the most interesting design in the set. Source: [`vid2slides.py`](https://github.com/patrickmineault/vid2slides/blob/master/vid2slides/vid2slides.py).

- Sampling: `extract_thumbnails` shells out to `ffmpeg -s WxH -r 0.5` → one 360×202 JPEG every `thumb_interval = 2` s. Detection never touches full-resolution frames; only the chosen timestamps are re-decoded at 1920×1080.
- Candidate templates: `heuristic_frames(sizes, ban_time=5)` picks thumbnails by **largest JPEG file size** (least compressible ⇒ most content) and bans ±5 thumbnails (±10 s) around each pick.
- Speaker rejection: OpenCV Haar cascade `haarcascade_frontalface_default.xml`, `detectMultiScale(1.1, 4)`. A face wider than 25% of the frame height marks the thumbnail as a full-screen face; those thumbnails are removed from the candidate pool **and** from the observation sequence. Small faces are k-means clustered to locate the PiP.
- Detector: a **left-to-right HMM decoded with Viterbi** in log space. States = candidate templates; emission `log_B = -SSE / mean(SSE)` where SSE is the sum of squared differences between thumbnail and template; transition matrix `A = (1 - jump_probability)·I + jump_probability·T/rowsum` with `jump_probability = 0.2` and `T` strictly upper triangular (forward jumps only), last state absorbing, uniform initial distribution.

Consequences, straight from the model:

- **Camera cutaway:** full-face thumbnails are deleted from the sequence, and the state persists across the gap through the 0.8 self-transition, so a slide returning to screen continues the same state instead of starting a new one. This is the only reference project whose *detector* — rather than a later dedupe pass — is structurally incapable of re-emitting a slide it already emitted.
- **Cost of that:** the strict left-to-right constraint means a genuine backward revisit ("let me go back two slides") cannot be represented at all.
- **Progressive builds:** candidate selection prefers the least-compressible (fullest) state and bans ±10 s around it, so a build sequence usually collapses into one template — the final, most complete state. Good for precision; the wrong bias for a recall-first pipeline unless `ban_time` is lowered.

### 6.3 `kovitking/video2slides` — pHash + stability window + median-diff PiP mask

Active (last push 2026-07-28). Source: [`webapp/static/app.js`](https://github.com/kovitking/video2slides/blob/main/video2slides/webapp/static/app.js).

- Two passes: pass 1 seeks every `SAMPLE_INTERVAL_SEC = 2.0` s and stores only a 256-bit pHash per sample (`HASH_SIZE = 16`, hashed image 64×64, i.e. `highfreq_factor = 4`, explicitly matching Python `imagehash.phash`); pass 2 re-runs detection over the cached hashes, so changing sensitivity is instant and needs no re-seeking. That two-phase split — expensive sweep once, cheap re-decision many times — is exactly what a threshold-tuning spike wants.
- Sensitivity presets (Hamming distance out of 256 bits, stability seconds): `sparse {14, 3.0}`, `default {10, 1.5}`, `dense {6, 0.5}`. `DETECT_WIDTH = 1280` caps the exported image width.
- Detection loop: a candidate hash accumulates `stableCount` while consecutive samples stay within `hashThreshold`; on a break the candidate is accepted only if `stableCount >= minStableFrames` **and** it differs from the last confirmed hash by more than `hashThreshold`. `minStableFrames = round(minStableSeconds / SAMPLE_INTERVAL_SEC)`, which at the default preset is **1 frame** — so the stability window only really bites on `sparse` (2 frames).
- The accepted frame is the **middle** sample of the stable run, a clean-frame selection trick equivalent in spirit to `larry-xue`'s `grabPoint`.
- PiP/webcam mask: `PIP_SAMPLE_N = 60` samples at `PIP_WORK_WIDTH = 240`; a pixel is "moving" when the **median** of its consecutive-frame absolute differences exceeds `PIP_DIFF_THRESHOLD = 4.0`. Median rather than mean/max is deliberate, so the single huge whole-frame jump of a real slide change does not enter the mask. The box is accepted only if `0.01·frameArea < area < 0.35·frameArea` and `boxW < 0.6·W`, `boxH < 0.6·H`. The mask is applied for hashing only; the saved frame is unmasked.
- Cutaway behaviour, worth stating precisely because it is a *partial* answer: comparing against the last **confirmed** hash means a cutaway that never stabilises (a moving camera on a speaker) leaves the confirmed hash untouched, so returning to the same slide is correctly rejected as a duplicate. But a **static** speaker or audience shot held longer than the stability window confirms itself as a "slide", after which the returning real slide differs from the new confirmed hash and *is* re-captured. Dedupe is against one hash, not a set.

### 6.4 `sumerene/video2slides` — the global double-hash dedupe

Active (last push 2026-04-20). Source: [`scripts/extract_slides.py`](https://github.com/sumerene/video2slides/blob/master/scripts/extract_slides.py).

- Sampling: `--interval` default `1.0` s, implemented as `cap.set(cv2.CAP_PROP_POS_FRAMES, int(sec*fps))` plus one `read()` — seeking, not full decode.
- Non-slide gate: `cv2.Laplacian(gray, CV_64F).var() < --laplacian` (default `300`) skips the frame outright. This is the cheapest deterministic "is this a crisp slide rather than a soft camera shot" filter in the set.
- Dedupe: `imagehash.phash` and `imagehash.dhash`, thresholds `--phash 10` and `--dhash 10`, in **two layers** — layer 1 against the previous sampled frame, layer 2 (`is_duplicate`) against **every hash already saved**. A frame is rejected only when *both* hashes agree it is a duplicate (`and`), which biases toward keeping frames: the correct bias for a recall-first pipeline.
- Layer 2 is precisely the mechanism the cutaway case needs: a slide returning at minute 40 is matched against the full set of already-saved slides, not just against the previous frame.
- Progressive builds: at 10 bits out of 64, one added bullet line is very likely to fall *below* the distance threshold and be discarded as a duplicate. Builds collapse; the knobs are `--phash`/`--dhash`.

### 6.5 `binh234/video2slides` — the "wait for motion to stop" framing

Stale (last push 2024-03-14), MIT. Source: [`frame_differencing.py`](https://github.com/binh234/video2slides/blob/main/frame_differencing.py), [`bg_modeling.py`](https://github.com/binh234/video2slides/blob/main/bg_modeling.py), [`config.py`](https://github.com/binh234/video2slides/blob/main/config.py), [`post_process.py`](https://github.com/binh234/video2slides/blob/main/post_process.py).

- Frame-differencing path: `absdiff` on greyscale → `threshold(80, 255, THRESH_BINARY)` → `dilate` with a 7×7 ellipse kernel → percentage of non-zero pixels. `MIN_PERCENT_THRESH = 0.06` in the function signature (`config.py` carries `MIN_PERCENT = 0.15`, `MAX_PERCENT = 0.01`), and `ELAPSED_FRAME_THRESH = 85` frames must elapse after motion is first seen before a frame is written — a crude fixed settling delay.
- Background-modeling path: resizes each frame to width 640, then `cv2.bgsegm.createBackgroundSubtractorGMG(initializationFrames=history, decisionThreshold=threshold)` or `cv2.createBackgroundSubtractorKNN(history=history, dist2Threshold=threshold, detectShadows=False)`, with `config.py` defaults `FRAME_BUFFER_HISTORY = 15`, `DEC_THRESH = 0.75`, `DIST_THRESH = 100`. It captures **when the foreground percentage drops below `MAX_PERCENT_THRESH`** (motion has stopped) and re-arms when it rises above `MIN_PERCENT_THRESH` (motion/animation in progress). That is the inverse framing with two-threshold hysteresis, and it is the closest thing in the reference set to a principled answer for embedded video and animated builds.
- Dedupe: `imagehash.dhash`, `HASH_SIZE = 12`, `HASH_BUFFER_HISTORY = 5` (a deque of the last five unique hashes — **not** global), threshold derived from a similarity percentage as `int(hash_size² · (100 − SIM_THRESHOLD)/100)` = `int(144 · 4/100)` = **5** bits at the default `SIM_THRESHOLD = 96`. A slide revisited more than five distinct slides later is re-captured.
- A cost trap worth not copying: both paths call `cap.read()` on **every** frame and only then `if frame_no % frame_rate != 0: continue`. The decode cost is paid in full; only the analysis is skipped.

### 6.6 `m2kar/video2slides` — PySceneDetect, tuned for slides

Stale (last push 2024-12-01). Source: [`video2slides/main.py`](https://github.com/m2kar/video2slides/blob/master/video2slides/main.py). Shells out to the PySceneDetect CLI:

```
scenedetect -i <video> -o <tmp> -fs <skip_frames> \
  detect-hash --size 16 --threshold 0.1 --lowpass 2 --min-scene-len 1.0 \
  list-scenes --filename scenes_info.csv
```

`skip_frames = int((fps − 1) · 0.15)`, i.e. roughly a 0.15 s cadence, falling back to `5`. The screenshot is taken at `screenshot_position = 0.95` of the scene's duration (margins 0.05–0.5 s) via `ffmpeg -ss t -i video -frames:v 1 -q:v 2` — late in the dwell, again to avoid transition frames. Transcription is `whisper.load_model("turbo")`.

Notable as the one prior-art data point that chose **`detect-hash` over `detect-content`/`detect-adaptive` for slides**, with `--min-scene-len 1.0` as its flood suppressor, and with the threshold set to `0.1` — far more sensitive than either released default (see 4.0).

### 6.7 `AnuragSingh2101/Video2Slides` — HSV histogram correlation

Active (last push 2026-08-05). Source: [`backend/app/services/video_proc.py`](https://github.com/AnuragSingh2101/Video2Slides/blob/main/backend/app/services/video_proc.py). `extract_keyframes` samples at `interval_frames = int(fps)` (1 s), computes `cv2.calcHist([hsv], [0,1], None, [180,256], [0,180,0,256])` and compares consecutive samples with `cv2.compareHist(prev, cur, cv2.HISTCMP_CORREL)`, flagging a new slide when the correlation drops below `hist_threshold = 0.92`. The code comment claims "0.85 to 0.95 is standard for slide decks". A hue/saturation histogram discards all spatial information, so of every technique surveyed this is the least likely to notice a single added bullet line.

### 6.8 Cross-project comparison of the things that matter

| Project | Sampling | Detection metric | Stability window | Dedupe scope | Non-slide frame rejection |
|---|---|---|---|---|---|
| larry-xue | 1 fps, width 320 | block MAD, ratio 0.02 | none (hysteresis via last-kept ref) | consecutive only | none (activity mask instead) |
| vid2slides | 0.5 fps, 360×202 | SSE to templates, Viterbi | HMM self-transition 0.8 | **global by construction** | Haar face > 25% of height |
| kovitking | 0.5 fps (2 s seek) | pHash 256-bit, dist 10 | 1.5 s (= 1 sample at default) | last confirmed hash only | none (PiP mask instead) |
| sumerene | 1 fps (seek) | pHash + dHash, dist 10 each | none | **global (all saved hashes)** | Laplacian variance < 300 |
| binh234 | every frame decoded | absdiff % / bg-sub foreground % | 85 frames / settle-to-quiet | last 5 unique dhashes | none |
| m2kar | ~0.15 s (`-fs`) | PySceneDetect `detect-hash` 0.1 | `--min-scene-len 1.0` | none | none |
| AnuragSingh2101 | 1 fps | HSV hist correlation < 0.92 | none | none | none |

**Nothing in the set handles all three hard cases.** Two projects handle the cutaway (`vid2slides` structurally, `sumerene` by global hash set); two handle embedded video well (`larry-xue`'s activity mask, `binh234`'s settle-to-quiet); **none handles progressive builds as a recall problem** — every one of them either collapses builds silently or fires on each reveal with no way to relate the reveals to their parent slide. That gap is the single most important thing this research found.

## 7. The one published benchmark, and the protocol the spike should adopt

`larry-xue/video-slide-extractor` ships [`bench/`](https://github.com/larry-xue/video-slide-extractor/blob/master/bench/README.md) and [`docs/evaluation.md`](https://github.com/larry-xue/video-slide-extractor/blob/master/docs/evaluation.md), and they answer a question nothing else in this survey answers: **how do you score a detector on a progressive build at all?**

### 7.1 Its protocol

- Label at **event granularity**: one row per visible frame change, typed `slide` or `build`, with `parent_slide` pointing a build at its slide. The protocol explicitly forbids collapsing builds into their parent at labelling time, on the grounds that whether a build detection is a success is a property of the downstream task, not of the video — "encoding it into the labels forces a relabel whenever the task changes, and hides the decision from anyone reading your numbers."
- Declare a `count_builds` policy alongside every metric:

  | Policy | Expected transitions | Detections near a `build` event |
  |---|---|---|
  | `events` | every labelled row | true positives |
  | `collapse-ignore` | `slide` rows only | discarded before matching (neither TP nor FP) |
  | `collapse-strict` | `slide` rows only | false positives |

  `collapse-ignore` is the one that matches this project: a later temporal-cleanup stage discards near-duplicates, so build detections are harmless.
- Match detections 1:1 to expected transitions inside a tolerance window (±2 s in the protocol, ±2.5 s in the shipped run).
- Report precision, recall, F1, **slide coverage** (fraction of ground-truth slides that got at least one capture) and **duplicate rate** (extra captures of an already-captured slide ÷ all captures). Report transition-frame captures separately, "because a timestamp can be close to the correct transition while still producing an unusable half-faded image".
- Tag every FP/FN with a failure class: incremental builds or animations; crossfades and wipes; cursor or webcam motion; camera footage around a projected screen; compression noise; **slides revisited later in the recording**; sampling interval too wide.

Two of those seven failure classes are exactly the hard cases in this ticket, and the metric pair (coverage, duplicate rate) is precisely the recall-over-precision framing the map already asked for. Adopting this protocol wholesale in spike #11 costs nothing and makes the spike's numbers comparable to a published baseline.

### 7.2 Its numbers

Fixtures are rendered from known slide sequences ("ground truth by construction"): a 30-slide synthetic deck (265.4 s) and a 46-slide deck re-rendered from stills extracted from MIT OCW 6.0001 Lecture 1 (366.6 s, CC BY-NC-SA 4.0), each in three variants — `clean` (960×540, hard cuts, crf 23), `noisy` (heavy compression, down/upscale), `overlay` (clean plus an animated "webcam" box bottom-right). Slide durations from a seeded PRNG (4–12 s, seed 60001), so every machine renders byte-identical timelines. Sampling frozen for all methods at one 160×90 RGBA frame every 2 s via ffmpeg. Environment recorded in `results.json` (Node v22.22.3, FFmpeg 6.1.1).

Selected results from [`bench/RESULTS.md`](https://github.com/larry-xue/video-slide-extractor/blob/master/bench/RESULTS.md):

| Fixture / variant | Method | Precision | Recall | Coverage | Duplicate rate |
|---|---|---|---|---|---|
| synthetic clean | fixed interval 10 s | 0.63 | 0.567 | 0.80 | 0.111 |
| synthetic clean | naive pixel diff (2%) | 1.00 | 0.700 | 0.70 | 0 |
| synthetic clean | block diff, ratio 0.02 | 1.00 | 0.900 | 0.90 | 0 |
| synthetic overlay | block diff, ratio 0.02 | **0.37** | 1.00 | 1.00 | **0.63** |
| synthetic overlay | block diff, ratio 0.10 | 0.962 | 0.833 | 0.867 | 0 |
| mit clean | block diff, ratio 0.02 | 1.00 | 0.935 | 0.935 | 0 |
| mit overlay | block diff, ratio 0.02 | **0.368** | 1.00 | 1.00 | **0.632** |
| mit overlay | block diff, ratio 0.10 | 1.00 | 0.870 | 0.870 | 0 |

Three findings to treat as load-bearing:

1. **Fixed-interval sampling caps coverage at ~0.78–0.80** on these fixtures: any slide shorter than the interval is simply missed, and it is the only method whose numbers do not change with input quality. That is the honest floor for the recall metric and the baseline the spike should include.
2. **An animated overlay floods a 2%-ratio block detector**: precision 0.37, duplicate rate 0.63, because the overlay alone occupies more than 2% of the blocks so every sampled frame re-triggers. Raising `changedRatio` to 0.10 restores precision at a recall cost. (The library's own `buildActivityMask` is the intended fix; the benchmark deliberately measures methods, not the packaged pipeline.)
3. **Neither detector reaches recall 1.0 on the clean MIT deck**, in their own words: "a few consecutive slides differ by roughly one bullet line, and at 160×90 that change stays near the trigger floor — the incremental-build failure class … visible even in a synthetic re-rendering." **The progressive-build case is a resolution problem as much as a threshold problem** — a measured statement, not an inference, and it directly contradicts the instinct to sample small for speed.

Their own caveats: the fixtures use hard cuts at known times, not real recordings with crossfades, camera motion and in-slide builds; and the benchmark deliberately excludes duplicate collapse across revisited slides, clean-frame selection, cropping/masking and export quality, which are pipeline stages rather than change detection. The repo also points at a separate, manually-labelled product benchmark protocol in [`awesome-video-to-slides`](https://github.com/larry-xue/awesome-video-to-slides).

## 8. The slide-specific literature — where the three hard cases were actually solved

This is the most important section of this document, because the two deployed systems below are the only sources found anywhere that address all three hard cases *by name* and describe deterministic mechanisms for them. Neither is a library you can install; both are algorithms you would reimplement.

### 8.1 TalkMiner (FXPAL, 2010) — names all three cases in its abstract

Adcock, Cooper, Denoue, Pirsiavash, Rowe, *"TalkMiner: A Lecture Webcast Search Engine"*, Proceedings of the 18th ACM International Conference on Multimedia (MM '10), 2010 — [DOI 10.1145/1873951.1873986](https://doi.org/10.1145/1873951.1873986), author PDF at [web.cs.ucdavis.edu/~hpirsiav/papers/talkminer_acm_mm10.pdf](https://web.cs.ucdavis.edu/~hpirsiav/papers/talkminer_acm_mm10.pdf). The abstract states the problem in almost exactly this ticket's terms:

> "Several problems were discovered when trying to identify distinct slides in the video stream. For example, **picture-in-picture compositing of a speaker and a presentation slide, switching cameras, and slide builds confuse basic frame-differencing algorithms** for extracting keyframe slide images."

**Baseline** (adapted from ProjectorBox): process **one frame per second**, detect global pixel differences exceeding a threshold **relative to the last keyframe**; once **1%** of the frame's pixels exceed the change threshold, extract a new keyframe **after a period of three seconds during which the global change remains below the threshold**. In their words, "thus, we extract keyframes that represent only stable video segments, which are more likely to be frames that include slides as opposed to frames containing the speaker, audience, or other content."

They then state the recall hazard of that stability window explicitly, which is the single most useful negative result in this document:

> "In the latter two cases, **if the non-slide portions of the frame exhibit continuous motion, then slides can be missed (i.e. not extracted at all) as the scene never stabilizes for three seconds** as required in the baseline system."

So a naive stability window does not merely add duplicates — under a persistently moving webcam overlay it silently *drops* slides. That is the failure mode this project cannot accept, and it comes from a system that shipped.

**Their three deterministic extensions:**

1. **Spatial cues (the embedded-video / PiP answer).** Sample at 1 fps, spatially blur, threshold the per-pixel difference into a binary image, then threshold the total difference in the **centre block of a 5×5 spatial grid** — "motivated by the observation that the projector screen on which slides are displayed typically occupies the center of the frame". Next, compute the bounding box of all above-threshold differences: **if that box is smaller than a third of the frame's height and width, and does not occupy much of the centre block, it is not a new slide** — the change is attributed to an inserted speaker view or to speaker/audience motion. Their key observation: "after masking frame differences with limited spatial extent, the requirement for stable content for at least three seconds … no longer mistakenly overlooks slide keyframes due to continuous motion within an inserted, scaled-down secondary feed." **The spatial filter is what makes the stability window safe.**
2. **Speaker appearance modelling (the cutaway answer).** Sample 400 frames that exhibit at least 1% changed pixels from the preceding frame (these are the moving ones, so likely speaker or audience). Apply OpenCV face detection — which "reliably works for full-frame shots of a speaker" but where "picture-in-picture or 'back of the room' frames may lack sufficient resolution for successful detection" — then apply OCR to bootstrap slide vs non-slide training sets automatically. Features: the frame split into **two horizontal (top and bottom) blocks with a 64-bin colour histogram each**. Train an SVM (LibSVM) and discard candidate keyframes classified as non-slide. If training sets of at least five images cannot be found automatically, they abandon speaker modelling and keep the frame-differencing-plus-spatial-cues result. Note this classifies *frames*, so it removes the speaker shots rather than recognising a returning slide — deduplication of the returning slide itself still falls to the build-up merge and to the keyframe set being compared against the last keyframe.
3. **Build-up merging (the progressive-build answer, and it is deterministic).** This is the mechanism nothing else in the survey has:

   > "We first localize the difference between two temporally adjacent candidate slide keyframes. We take the thresholded pixel difference between two keyframes and find the bounding box of any change. This region represents the new content added. **If this region in the first slide lacks significant edges, we assume it was empty. If the region with significant edges in the first slide exhibits no edges in the difference frame, then this portion is common content in the two frames.** When the regions bounding detected edges in both the difference image and first keyframe mismatch in this manner, we detect elements of a built up sequence. This pairwise analysis is iterated, and the **last keyframe of such a sequence is used to represent the entire build-up sequence**."

   In other words: a build is detected as an **edge-localised superset relation** — new content appeared where the previous slide had nothing, and everything the previous slide *did* have is unchanged. That is a genuinely deterministic "is this the same slide, one step further?" test, and it needs no OCR: they note that "by using image analysis to judge whether the change has added content rather than relying on comparing the output of OCR on the two keyframes, we avoid problems with OCR accuracy and also handle the case where the added content is non-textual in nature."

   They then discard the partial versions and keep the final complete slide. For a recall-first pipeline the same test can be used the other way round — keep every state but *label* it as a build of its parent slide, which is exactly the `count_builds` labelling that section 7's protocol asks for.

**Full pipeline parameters, from their §4.2.5:** 1 Hz extraction; per-pixel difference threshold **24**; changed pixels > **1%** of total; bounding box must be **at least a third of the frame or overlapping the centre** to open a new segment; keyframe = **the last frame in the segment**, taken after the global inter-frame difference "stabilizes for at least three seconds"; then the SVM filter; then build-up merging. Implemented in Python with OpenCV and LibSVM.

**Measured results (their Table 2), 21 manually annotated videos** with ground-truth slide keyframes and segments, comparing basic frame differencing (Basic) to their extended algorithm (Ext.):

| Metric | Basic | Extended | Change |
|---|---|---|---|
| Precision (avg.) | 47.5 | **76.9** | +84.3% |
| Recall (avg.) | 91.7 | **94.0** | +3.3% |
| F1 (avg.) | 60.8 | **83.9** | +48.5% |
| Keyframes (avg.) | 106.4 | 63.7 | ground truth 52.7 |

**Recall went up, not down.** That is the strongest evidence in this whole survey that the deterministic extensions are not a precision-for-recall trade: they nearly doubled precision *while improving recall*, because the spatial filter stopped continuous motion from suppressing real slides. Their own summary: "the main drawbacks of basic frame differencing were duplicate keyframes mistakenly extracted due to intermittent motion and missed slides due to continuous small motion."

### 8.2 Yang, Sack and Meinel (HPI / tele-TASK, 2011) — the connected-component two-tier segmenter

Haojin Yang, Harald Sack, Christoph Meinel, *"Lecture Video Indexing and Analysis Using Video OCR Technology"*, Journal of Multimedia Processing and Technologies, 2011 — PDF at [fiz-karlsruhe.de/.../2011_Yang_JMPT.pdf](https://www.fiz-karlsruhe.de/sites/default/files/FIZ/Dokumente/Forschung/ISE/Publications/Journals/2011_Yang_JMPT.pdf), record on [Semantic Scholar](https://www.semanticscholar.org/paper/16c0c95eaf0c6b7db1e1c0276592ef596e392e55). Hasso Plattner Institute; test data announced at `yanghaojin.com/research/videoOCR.html`, corpus from the [tele-TASK](http://www.tele-task.de/) project. (A closely related conference version appeared at SITIS 2011, pp. 54-61.)

Their premise: "video contents such as texts, figures, tables etc. can all be considered as a collection of CC (Connected Component). Therefore, the difference between two frames can be determined by calculating the difference of the amount of CCs. **In this way, we are able to control the valid size of CCs so that the image noise can be removed from the comparison.**" They explicitly reject the global-pixel-difference metric on that ground: "one deficiency of this method is that the high-frequency image noise within video frames can still degrade the segmentation accuracy."

**The algorithm is two-tier, and the two tiers are exactly the two things this project needs.** Sampling is **one frame per second** ("for reasons of efficiency, we do not perform the analysis on every video frame").

- **Step 1 — every visible change (recall tier).** Build a pixel-based differential image **from the Canny edge maps** of two adjacent frames, run connected-component analysis on it, and count the differing CCs. A new *segment* is captured when that count exceeds `Ts1`. Their stated design goal is precisely the progressive build: "**in order to ensure that each newly emerging knowledge point or newly added figure within a slide can be detected**, we have identified the segmentation threshold value `Ts1`." They acknowledge the output "is too redundant for indexing, since there are many changes within the same slide".
- **Step 2 — actual page transitions (slide tier).** From a statistical analysis of slide layouts they define a title region `Rt` (**23% of frame height**) and a content region `Rc` (**70%**). Apply the same CC differencing to `Rt`: **if the CC count in the title region's differential edge image exceeds 1, a slide page transition is captured** — "because any changes within the title region may result the slide transition". If the title has not changed, detect the **first and last text lines in `Rc`** and run the CC differencing on those text-line regions; **if both differences exceed `Ts2`, a slide page transition is captured**.
- **Thresholds, from the paper:** "`Ts1` is defined to measure the CC-based differencing of the whole slide frame and the `Ts2` is defined for the single text line. In our study, **`Ts1` = 20 and `Ts2` = 5** have proven to serve best for our training data."

**Reported accuracy:** 20 randomly chosen tele-TASK lecture videos with varying layouts and font styles; 860 segments detected, 816 correct → **recall 98%, precision 95%**. Frame sizes 640×480 to 1024×768. Implemented in C++, run on "a Mac OS X, 2.4 GHz platform" — CPU-era numbers on 2011 hardware, and the paper reports no per-video runtime.

**The critical caveat, in their own words:** "Since this experiment is defined to evaluate our slide segmentation method, **videos embedded within slides are not considered in our evaluation**." And, immediately after presenting the algorithm: "**Since our slide segmentation method is not suitable for videos with varying genres that were embedded in slides or are played during the presentation, we have improved the method with a SVM classifier.**"

**That is a primary-source admission that the deterministic path fails on embedded video, from the canonical paper on deterministic slide segmentation.** Their fix is a classical, CPU-cheap classifier — not a deep model. They train an SVM with an RBF kernel (parameters by cross-validation) to separate slide frames from non-slide frames, comparing two features:

| Feature | Recall | Precision | F1 |
|---|---|---|---|
| HOG (8 gradient directions, 64×64 local region) | 0.996 | 0.648 | 0.785 |
| Image intensity histogram (256 bins, normalisation factor 1000) | 0.91 | 0.93 | **0.92** |

Training used ~2000 non-slide frames; the test set was 240 slide frames and 233 non-slide frames disjoint from training. Their conclusion: "both of two features achieve a good recall rate for slide frame recognition. However, comparing with HOG feature, **the intensity histogram feature can achieve a significant improvement in precision. Moreover, the processing speed is also much faster.**"

Note the shape of that result for a recall-first project: HOG gives recall 0.996 at precision 0.648, the intensity histogram gives a balanced 0.91/0.93. If the classifier's job is "don't throw away a slide", HOG is the one to measure.

**They also confirm the progressive-build case breaks the prior art.** Reviewing Wang et al. and Hunter et al.: "since **the animated content buildup of the slide has not been considered** in [6] and [9], their systems might not work robustly when these effects occur in the slide videos."

### 8.3 What the literature adds that the libraries do not

Three techniques exist in the published, deployed systems and in **none** of the libraries or reference repos surveyed in sections 3–6:

1. **An edge-localised superset test for builds** (TalkMiner §4.2.4): new content appeared where the previous frame was empty, and the previous frame's content is unchanged. Deterministic, OCR-free, and it produces the parent/child relation that the evaluation protocol in section 7 wants labelled.
2. **A spatial-extent filter on the difference region** (TalkMiner §4.2.2): reject changes whose bounding box is small and off-centre. Cheaper than `larry-xue`'s activity mask (no multi-frame accumulation needed) and it addresses the same failure. Its measured effect was to raise precision by 84% *and* recall by 3%.
3. **Region-scoped comparison** (Yang et al.): score the *title region* separately from the *body*, because a title change almost always means a new slide while a body change often means a build. This turns "is it one slide or five?" from a threshold question into a structural one.

All three are cheap CPU operations (Canny, connected components, bounding boxes, region crops) and all three are deterministic. None is available off the shelf.

## 9. Does anything actively maintained bundle slide-specific detection?

Answer: **almost nothing — but two finds are new relative to `docs/similar-tools.md` and one of them matters a great deal.** A GitHub search restricted to repositories pushed after 2025-09-01, plus a PyPI scan, produced these:

| Package / repo | Last activity | Licence | Slide-specific mechanism |
|---|---|---|---|
| [`liaw-boy/slide-extractor`](https://github.com/liaw-boy/slide-extractor) | 2026-05-18 | MIT | **Explicitly separates real slide transitions from in-slide animation steps** — see 9.1 |
| [`fit-lecture-indexer`](https://pypi.org/project/fit-lecture-indexer/) ([repo](https://github.com/jstorm31/fit-lecture-indexer)) | v0.2.0 | MIT | pHash dedupe **plus slide-title OCR**, transitions detected as *title changes* — the Yang et al. title-region idea, packaged |
| [`preyesh2002/Vision-Based-Slide-Transition-Detection-And-Automated-Lecture-PDF-Generator`](https://github.com/preyesh2002/Vision-Based-Slide-Transition-Detection-And-Automated-Lecture-PDF-Generator) | 2026-04-14 | MIT | vision-based transition detection → PDF; not examined in depth |
| [`lybhb8/video-to-pptx`](https://github.com/lybhb8/video-to-pptx) | 2026-08-09 | GPL-3.0 | ffmpeg frame extraction + perceptual-hash dedupe — nothing beyond `binh234` |
| [`bit-admin/AutoSlides-Extractor`](https://github.com/bit-admin/AutoSlides-Extractor) | 2026-08-12 | MIT | **SSIM + hardcoded 3-sample verification + two-phase pHash + a 3-class MobileNetV4 slide classifier** — see 9.2 |
| [`HHousen/lecture2notes`](https://github.com/HHousen/lecture2notes) | 2026-07-02 | AGPL-3.0 | deep-CNN slide-frame classifier, clustering + keypoint matching for unique slides, published frame dataset — see 9.3 |
| [`asindel/SliTraNet`](https://github.com/asindel/SliTraNet) | 2023-12-17 | none | two-stage CNN classifying **slide-slide vs slide-video** transitions — see 9.4 |
| [`SlideDetector`](https://pypi.org/project/SlideDetector/) | 2024-04-02, v0.1.0 | GPL-3.0 | single `--threshold` frame difference; nothing new |
| [`slide-extractor`](https://pypi.org/project/slide-extractor/) (PyPI) | 2023-12-10 | MIT | the `Slide-extractor-beta` repo already discarded in `docs/similar-tools.md` |

Two further actively maintained, slide-specific projects turned up on a second pass and deserve their own subsections: [`bit-admin/AutoSlides-Extractor`](https://github.com/bit-admin/AutoSlides-Extractor) (MIT, 17 stars, pushed **2026-08-12**) in 9.2, and [`HHousen/lecture2notes`](https://github.com/HHousen/lecture2notes) (AGPL-3.0, pushed **2026-07-02**) in 9.3. Stale but relevant: [`asindel/SliTraNet`](https://github.com/asindel/SliTraNet) (no licence file, pushed 2023-12-17), the CNN reference for this exact task, in 9.4.

Dead ends confirmed by upload date, for the record: PyPI `videoslides` (last upload 2023-07-29), PyPI `video-slide-extractor` (2022-03-11), PyPI `video-to-slides` (2021-08-31, [repo](https://github.com/0scarB/video-to-slides), MIT, dead).

**Scan caveat, stated so the negative finding is auditable:** GitHub repository/code search, the npm registry API and crates.io were queried; **PyPI was covered by name-probing its JSON API across 43 candidate names, not by exhaustive search**, because PyPI's HTML search sits behind a bot challenge. So the PyPI half of this claim is "no hits among 43 probed names", not "verified exhaustive".

**The honest summary, revised:** off-the-shelf *libraries* remain generic — PySceneDetect has no slide mode (4.10) and ffmpeg has no notion of slides at all — but there are now actively maintained slide-specific *applications*, and they have converged on a recognisable architecture: a cheap change metric, a hardcoded stability verification, perceptual-hash post-processing, and **a small CNN whose only job is to decide whether a frame is a slide at all**. What none of them ships is the section 8 mechanism set (edge-localised superset test, spatial-extent filter, title-region scoping). Those, this project still writes itself.

### 9.1 `liaw-boy/slide-extractor` — an independent rediscovery of the superset rule

Its [`docs/algorithm.md`](https://github.com/liaw-boy/slide-extractor/blob/main/docs/algorithm.md) is the most directly on-point document found in the entire survey, because its stated goal is "separat[ing] … transitions from in-slide animation steps in lecture videos", producing "one image per real slide, captured at the moment animations finish".

It first rules out, by name, four techniques this document has examined:

| Approach it rejects | Its stated reason |
|---|---|
| HSV colour histogram (PySceneDetect's default) | "Same template → same histogram. Cuts not detected." |
| pHash, raw distance threshold | "Same template fools pHash too." |
| OCR text Jaccard | "Slides on related topics share too many words." |
| pHash with a low threshold | "Now catches **every animation step** as well." |

That last line is the recall/precision tension of this ticket, stated by someone who hit it. Its rule, for every pair of consecutive sampled frames `(A, B)`, computes `pHash_dist(A, B)`, the OCR token Jaccard, `size_ratio = |B_tokens| / |A_tokens|` and `old_in_new = |A ∩ B| / |A|`, then:

```
if pHash_dist < PHASH_THR:                                       return SAME  # visually unchanged
if size_ratio >= SIZE_RATIO_GROW and old_in_new >= SUBSET_THR:   return SAME  # animation step
if old_in_new >= SUBSET_THR:                                     return SAME  # ambiguous subset, treat conservatively
```

with the rationale spelled out: "a within-slide animation only **adds** content, so `B_tokens ⊃ A_tokens`", whereas a real transition "**drops** content (`size_ratio < 0.6` — animations never remove text)". Animation noise that produces a spurious one-sample slide is filtered by `MIN_SLIDE_DURATION`, **default 9 s**. The document also reports that its thresholds "are not guessed … [they] are picked from real OCR + pHash data on a Mandarin cryptography lecture, where the ground truth was hand-verified", and shows a table in which a real transition and an animation step have "nearly identical pHash distance *and* near-identical jaccard" — its conclusion being that the two signals must be combined because "neither alone is enough".

**This is the same insight as TalkMiner's edge-localised superset test (8.1), reached independently and expressed in OCR-token space instead of edge space.** Two systems, sixteen years apart, converge on the same discriminator:

> **A progressive build ADDS content and preserves what was already there. A real slide transition DROPS content.**

That is the single most useful generalisable finding of this research, and it reframes the problem: the discriminator between a build and a new slide is the **subset/superset relation between consecutive states**, not the magnitude of the difference. Every magnitude-threshold technique in sections 3–5 is measuring the wrong quantity. And TalkMiner's version needs only Canny edges and bounding boxes — **no OCR, no model, no GPU**, which keeps it inside this project's deterministic budget while OCR does not (OCR is deferred as a future extension in `docs/idea.md`, and `liaw-boy`'s pipeline additionally expects GPU OCR).

Two further points from that README worth flagging to the map, because they independently validate decisions the map has already made: its "review mode runs in PARANOID settings (denser sampling, lower thresholds) so it always outputs MORE candidates than real slides. You glance through, uncheck the duplicates, click save" — recall-over-precision plus an optional review mode; and its honest scope table, which lists "slides containing embedded short video clips" and "slides with small speaker-camera overlay" as *borderline, use review mode*, and "Prezi-style smooth-zoom transitions" as **not designed for**.

### 9.2 `bit-admin/AutoSlides-Extractor` — the most complete actively maintained tool found

> **Corrected by [`reference-implementations.md`](reference-implementations.md), which read the source.**
> Five claims in this section do not survive contact with the code. It is **not SSIM** but a
> single-window *global* correlation using SSIM's constants, so the 0.999 / 0.9985 / 0.998 presets are
> meaningless for a windowed implementation; "3-sample verification" is an all-must-agree look-ahead
> over two subsequent scores, not a vote; the gate runs through ONNX Runtime over exported JPEGs in
> post-processing, never on video frames; and the repo also ships a complete tuned slide-bbox
> detector, which makes it a counter-example to the crop research's greenfield premise. Read
> [§B.0](reference-implementations.md#b0-corrections) before using anything below.

MIT, 17 stars, pushed **2026-08-12**. A C++/Qt desktop application ("A tool to automatically extract slides from presentation videos with computer vision and machine learning"), with hardware decoding, a chunk processor and a memory optimiser — i.e. engineered for long videos, which is unusual in this field. Not in `docs/similar-tools.md`.

Its detection stack, read from [`src/configmanager.cpp`](https://github.com/bit-admin/AutoSlides-Extractor/blob/main/src/configmanager.cpp) and [`src/clirunner.cpp`](https://github.com/bit-admin/AutoSlides-Extractor/blob/main/src/clirunner.cpp):

| Stage | Mechanism | Defaults |
|---|---|---|
| Change metric | **SSIM**, via presets | `Strict` 0.999, **`Normal` 0.9985 (default)**, `Loose` 0.998, or `Custom` (`--ssim-threshold`) |
| Stability | **`verificationCount = 3`, hardcoded** — the source comment reads "verification settings are now hardcoded (enableVerification=true, verificationCount=3)" | not configurable |
| Post-process phase 1 | `--phash-redundant` — "remove redundant slides via pHash"; result reason `phash_duplicate` | `hammingThreshold` configurable |
| Post-process phase 2 | `--phash-exclusion` — a persisted **pHash exclusion list**; result reason `phash_excluded` | list saved in GUI config, overridable with `--phash-exclusion-hashes` |
| ML classification | 3-class CNN with a hysteresis band: `mlNotSlideHigh/LowThreshold`, `mlMaybeSlideHigh/LowThreshold`, `mlSlideMaxThreshold` | see below |
| Auto-crop | YOLO detector, `autocrop/yolo/confidenceThreshold` | relevant to the crop stage, not detection |

Three things here are new to this survey:

1. **SSIM as the change metric.** No other project surveyed uses it, and the threshold scale is revealing: `Normal` is **0.9985**, i.e. it treats anything below 99.85% structural similarity as a change. That is an extremely tight threshold, consistent with the "recall first, then dedupe" posture, and it is a fourth distinct metric family to put in front of the spike alongside frame differencing, hashing and edge/CC counting.
2. **A pHash exclusion list.** A persisted set of hashes that are *always* rejected — for a recurring title card, station ident, or a habitual speaker shot. Nothing else in this survey has it, and it is a cheap, deterministic partial answer to the cutaway case for *known* recurring non-slide frames.
3. **A three-class slide-frame classifier with an explicit uncertainty bucket.** From [`resources/models/model_info.json`](https://github.com/bit-admin/AutoSlides-Extractor/blob/main/resources/models/model_info.json): classes `may_be_slide` / `not_slide` / `slide`; architecture `mobilenetv4_conv_medium.e500_r256_in1k`; input `[1, 3, 256, 256]`; ImageNet normalisation; `"quantization": "none"`; run through OpenCV DNN (`preprocessing: "opencv_inter_area"`, checkpoint named `slide_classifier_mobilenetv4_opencv.pth`); training info reports `best_val_acc` **99.27%** at epoch 4 (batch 64, lr 1e-3, weight decay 1e-4, early-stopping patience 10). The `may_be_slide` class plus the five-threshold hysteresis band is a deliberate "route this to human review" path — the same shape as the optional review mode the map already wants.

### 9.3 `HHousen/lecture2notes` — a deep CNN slide classifier plus a published dataset

AGPL-3.0 (note the licence before reusing any code), pushed **2026-07-02**, with a [paper](https://haydenhousen.com/media/lecture2notes-paper-v1.pdf), [docs](https://lecture2notes.readthedocs.io/en/latest) and a hosted service. Its pipeline is: extract frames → **classify frames to find those containing slides** (a deep CNN) → perspective-crop by matching temporal features → **"cluster slides to group transitions and remove duplicates"** → OCR slide structure analysis → figure extraction → STT → summarise.

Two parts matter here. The clustering-plus-keypoint-matching step is another instance of the global dedupe mechanism (8.3, 5.6) — "unique slides are determined using a combination of clustering and keypoint matching", per the abstract. And it documents a [dataset](https://lecture2notes.readthedocs.io/en/latest/dataset/general.html) built from video frames "sorted into correct classes", slide images converted from PDFs, and transcripts with WER metrics.

**Important scoping of that dataset, verified on the docs page:** it is a **per-frame categorisation** dataset (a `frames_sorted` directory grouped by class, with a confidence-thresholded `to-be-sorted.csv` for human review), **not** a set of labelled slide-transition timestamps. The page documents the construction workflow rather than class names, counts, or distribution terms. So it is directly useful for training or validating a slide-vs-non-slide frame gate — the cutaway case — and not usable as ground truth for transition detection.

### 9.4 `asindel/SliTraNet` — the CNN reference for this exact problem

> **Corrected by [`reference-implementations.md`](reference-implementations.md), which read the source.**
> The repo **does** carry a licence — MIT, © 2022 asindel — so the code is liftable, though the
> Google-Drive weights carry none. The cost verdict below is right and is now quantitative: 507 TFLOPs
> per 60-minute video against a host that peaks at 145 GFLOP/s, i.e. 2.4–7 h per hour of video, with
> **82 % of it in the stage that the paper's own ablation shows losing to frame differencing on
> recall**. See [§E.2](reference-implementations.md#e2-the-authors-own-ablation-beats-their-own-cnn)
> and [§E.6](reference-implementations.md#e6-cost-on-the-target-host).

Sindel, Hernandez, Yang, Christlein, Maier, *"SliTraNet: Automatic Detection of Slide Transitions in Lecture Videos using Convolutional Neural Networks"*, OAGM Workshop 2021 — [DOI 10.3217/978-3-85125-869-1-10](https://doi.org/10.3217/978-3-85125-869-1-10), [arXiv:2202.03540](https://arxiv.org/pdf/2202.03540.pdf), [code](https://github.com/asindel/SliTraNet) (pushed 2023-12-17, no licence file, so treat as unlicensed). Requires `torch >= 1.7`, `torchvision`, `decord`.

Worth knowing for one structural reason, visible in `test_SliTraNet.py`: it is **two-stage, and its two classes are "slide-slide" and "slide-video" transitions.** Stage 1 (`detect_initial_slide_transition_candidates_resnet2d`, a 2-D ResNet, also runnable standalone via `test_slide_detection_2d.py`) proposes candidates; stage 2 runs a 3-D CNN over video clips to **check the slide-video candidates**. In other words, the deep-learning state of the art for this task treats *video embedded in a slide* as an explicit class to be classified — which independently confirms that hard case 3 is where the deterministic path runs out (exactly as Yang et al. concluded in 8.2 when they added an SVM).

It also takes the slide region as an **input**, not an output: labels are supplied as `Videoname,x0,y0,x1,y1` bounding boxes per video. That is a dependency this project does not have at detection time.

Practical verdict for the target host: 3-D CNN clip inference over a 45-60 minute video on 4 CPU threads with no GPU is almost certainly out of budget, and pretrained weights are distributed via Google Drive. It belongs in this document as the ceiling reference and the "if the deterministic path provably fails" option, not as a spike candidate.

### 9.5 Ground-truth datasets — what a spike can actually measure against

| Source | Status |
|---|---|
| `larry-xue/video-slide-extractor` `bench/` fixtures | **The only usable option confirmed available.** Ground truth by construction, regenerated from two scripts (`generate-fixtures.mjs`, `run.mjs`), one deck drawn synthetically by ffmpeg and one re-rendered from MIT OCW 6.0001 Lecture 1 stills (CC BY-NC-SA 4.0, fetched at run time, not committed). Caveat: hard cuts at known times, so it contains no crossfades, no camera motion and only synthetic overlays. |
| tele-TASK test data (Yang et al.) | The paper points at `yanghaojin.com/research/videoOCR.html`; availability in 2026 was not verified in this research. The corpus is lecture recordings, and the published evaluation is 20 videos / 860 segments. |
| `lecture2notes` frame dataset (9.3) | Public and documented, but it labels **per-frame slide/non-slide categories, not transition timestamps** — useful for a slide-frame gate, not as transition ground truth. Class names, counts and distribution terms are not stated on the dataset page. |
| SliTraNet's dataset (9.4) | The repo defines the expected folder structure and per-video bounding-box label format, and publishes pretrained weights via Google Drive, but **the labelled videos themselves are not distributed**. |
| TalkMiner's 21 annotated videos | Not published. |
| PySceneDetect's benchmark datasets (BBC Planet Earth, AutoShot, ClipShots) | Public and used for its [published numbers](https://www.scenedetect.com/benchmarks/), but they are **generic shot-boundary** corpora — no slides, no builds. Useful for calibrating a detector's raw sensitivity, useless for the three hard cases. |
| `awesome-video-to-slides` product benchmark | `larry-xue/video-slide-extractor` refers to a "separate, manually-labeled product benchmark protocol" in [`awesome-video-to-slides`](https://github.com/larry-xue/awesome-video-to-slides); worth checking before the spike hand-labels from scratch. |

**Practical conclusion for spike #11: there is no public labelled slide-*transition* dataset covering the three hard cases** — the two public datasets that exist label frames, not transitions. The spike will have to hand-label its own reference videos, and the cheapest defensible way to do that is to adopt section 7's protocol verbatim — event-granularity labels typed `slide` / `build` with `parent_slide`, a declared `count_builds` policy of `collapse-ignore`, and the (coverage, duplicate-rate) metric pair — while using the `larry-xue` synthetic generator as a sanity fixture that any candidate must pass before being run on real video.

### 9.6 Where AI enters, if it enters — four systems, one answer

> **Sharpened by [`reference-implementations.md`](reference-implementations.md).** The convergent
> result below holds for the four systems in the table, but the hedge about SliTraNet being "the
> exception" is too weak: **all three** of its networks operate on the change and none is a
> slide-frame gate. The accurate statement is that every system which put its model at the gate did so
> to stay cheap, and the one system that pointed models at the change itself needed three networks and
> a GPU — and lost on recall to Gaussian-blurred frame differencing in its own Table I. See
> [§E.1](reference-implementations.md#e1-it-does-falsify-nobody-learns-the-change).

This is the clearest convergent result in the survey, and it bears directly on the map's "deterministic first, AI only if it is the only way" preference. Four independent systems across sixteen years all put a learned model in **exactly the same place — deciding whether a frame is a slide at all** — and none of them uses a model to detect the change itself:

| System | Where the model sits | What it is |
|---|---|---|
| TalkMiner, 2010 (8.1) | slide vs non-slide keyframe filter | SVM (LibSVM) on two-block 64-bin colour histograms, bootstrapped by face detection + OCR |
| Yang et al., 2011 (8.2) | slide vs non-slide frame classifier, added *because* the deterministic segmenter failed on embedded video | SVM with RBF kernel on HOG (R 0.996 / P 0.648) or intensity histogram (R 0.91 / P 0.93) |
| `lecture2notes`, 2026 (9.3) | "classify extracted frames to find frames containing slides" | deep CNN |
| `AutoSlides-Extractor`, 2026 (9.2) | 3-class frame classifier with an uncertainty bucket | MobileNetV4-medium at 256×256 via OpenCV DNN, 99.27% val acc |

The exception is `SliTraNet` (9.4), which *does* classify transitions — and it needs a 3-D CNN over video clips plus a supplied slide bounding box, which is out of budget on a 4-thread CPU with no GPU.

Two consequences worth handing to the map. First, the *change detection* itself has never needed a model: every system uses a cheap deterministic metric (pixel difference, connected components, SSIM) for that, which supports keeping detection deterministic. Second, if a model does turn out to be necessary, the evidence says it belongs at the **slide-frame gate**, it can be small (an SVM on histograms was competitive with HOG in 2011; MobileNetV4 at 256×256 is the 2026 equivalent), and it runs only on *sampled candidate frames* rather than every frame — which is what makes it affordable on this host at all.

## 10. Shortlist for the detection spike (#11)

Ranked. Each entry is a *pipeline shape*, not a single library, because no single library covers all three hard cases — that is the central finding of this research. Every candidate is deterministic; none requires a GPU or a vision model.

**Two design points that apply to every candidate**, established above and worth fixing before measurement so the numbers are comparable:

- **Detection runs on sampled, downscaled frames; export re-decodes the original at full resolution by timestamp.** Every reference project does this (`larry-xue` 1 fps at width 320; `vid2slides` 0.5 fps at 360×202; `kovitking` 2 s seeks; TalkMiner and Yang et al. both 1 fps), and the cost table in 5.9 says why: 3 minutes versus 34 for a 60-minute video. But sample *resolution* is a recall parameter, not just a cost parameter — `larry-xue`'s own benchmark shows one-bullet builds sitting "near the trigger floor" at 160×90, and PySceneDetect's default 7.5× downscale puts 1080p detection at 256×144. Measure at 2–3 resolutions.
- **Capture the frame from inside the dwell, not at the transition.** `larry-xue`'s `grabPoint`, `kovitking`'s middle-of-run sample, `m2kar`'s 95%-into-the-scene and TalkMiner's "last frame in the segment" are four independent implementations of the same fix for half-faded exports.

### 1. Frame differencing + spatial-extent filter + edge-superset build test + global hash dedupe

The TalkMiner shape (8.1), reimplemented on OpenCV primitives, with hashing bolted on for global dedupe.

- **Expected to do well:** it is the only candidate with a documented deterministic mechanism for all three hard cases, and the only one whose published numbers show precision nearly doubling *while recall rose* (47.5 → 76.9 precision, 91.7 → 94.0 recall over 21 hand-labelled videos). Frame differencing is the only primitive measured with a usable build-vs-transition margin (5–10×, 5.3) and it is the cheapest thing on the target CPU (0.82 ms/frame at 1080p, 0.04 ms at 480×270). The spatial-extent filter is what makes a stability window safe rather than a source of silent misses.
- **Expected to fail:** the 1%-of-pixels and 1/3-of-frame thresholds are tuned for a "projector screen in the centre of the frame" geometry and will misjudge a full-screen screencast, or a slide that genuinely occupies a corner box — which is precisely the layout `docs/idea.md` calls out. The centre-block assumption needs re-deriving from the crop stage rather than assumed. The edge-superset test also has to be validated on non-textual builds (a chart growing a series) and on dark-theme slides, where Canny behaviour differs.

### 2. PySceneDetect `detect-content` with edge weights, `-d 1`/`-d 2`, `min_scene_len` near zero + external global pHash dedupe

- **Expected to do well:** it is the highest-recall configuration reachable off the shelf, and the `--stats` CSV (4.7) makes it the only candidate that yields every metric in one decode pass for offline threshold fitting against ground truth — which is exactly what a spike needs. A text reveal is almost pure edge energy, and `delta_edges` is the one component documented as responding to it (docs' own starting point: `--weights 1.0 0.5 1.0 0.2 --threshold 32`).
- **Expected to fail:** it will flood on embedded video and on any moving overlay, because `min_scene_len` near zero disables the only suppression FlashFilter offers; it is the most expensive option (Canny + dilate per frame at `-d 1`, plus the trap that attaching `--stats` forces edge computation even at weight 0); and it has **no repeat memory whatsoever** (4.9), so the cutaway case is entirely on the external dedupe stage. Also note the version caveat in 4.0 before quoting any default.

### 3. PySceneDetect `detect-adaptive` at `-d 1`, `--min-content-val` lowered + external global pHash dedupe

- **Expected to do well:** the rolling average is the only mechanism any surveyed library *advertises* for sustained motion, and it is structurally right for embedded video — inside a clip every frame in the window scores high, so `adaptive_ratio` stays near 1.0 and is suppressed. It is the CLI default and has the best published F1 on two of three benchmark datasets.
- **Expected to fail:** on static slide content it degenerates to `content_val >= min_content_val` (15.0), i.e. plain ContentDetector with a fixed threshold (4.2) — so the adaptive machinery contributes nothing exactly where slides live, and build recall depends entirely on how far `--min-content-val` can be lowered before compression noise takes over. Same total absence of repeat memory.

### 4. Block-diff with Otsu calibration and activity mask — `larry-xue/video-slide-extractor` as-is, `calibrate: true`

- **Expected to do well:** the only candidate that ships an automatic per-video threshold and an automatic mask for a permanently moving region, both of which are directly aimed at the embedded-video and webcam cases; block-wise MAD absorbs codec noise by construction; memory is flat regardless of video length; it needs no Python at all. It also brings its own reproducible benchmark, so a spike gets a published baseline for free.
- **Expected to fail:** no global dedupe — it compares against the last kept frame only, so the cutaway case is untouched; its own benchmark shows a 2% ratio flooding to precision 0.37 on an animated overlay when the mask is *not* used, and the mask self-disables above 35% coverage; builds sit near the trigger floor at its benchmark resolution. It also adds ffmpeg and Node to the host.

### 5. SSIM + 3-sample verification + two-phase pHash post-processing

The `AutoSlides-Extractor` shape (9.2), reimplemented — it is a C++/Qt desktop app, so the value is the design, not the dependency.

- **Expected to do well:** SSIM is a fourth metric family this project has not otherwise considered, and it is structural rather than per-pixel, so it should be less noise-sensitive than `absdiff` at the very tight thresholds a build needs (its shipped default is `Normal` = **0.9985**). The hardcoded 3-sample verification is a stability window short enough not to swallow builds. The **pHash exclusion list** is a genuinely cheap partial answer to recurring non-slide frames (title cards, station idents, a habitual speaker shot) that nothing else in the survey offers.
- **Expected to fail:** SSIM is markedly more expensive than frame differencing and there is no measurement of it on this host — it needs a cost number before it can be ranked confidently. Its `verificationCount` is not configurable in the original, so the stability window has to be re-derived. And nothing in this shape addresses progressive builds beyond a very tight threshold, which means it will fire on every reveal — acceptable under recall-first, but only with a global dedupe stage behind it.

### 6. pHash (`hash_size >= 16`) + stability window + global hash set

The `kovitking`/`sumerene` shape, with the hash widened on the evidence in 5.5.

- **Expected to do well:** the only shape that answers the cutaway case *directly* — match each candidate against every slide already captured, which is stateless, order-independent and trivially cheap at O(100) slides. Two-phase operation (hash everything once at ~10 ms/frame, then re-decide instantly at any threshold) makes it the fastest candidate to *tune*. `sumerene`'s "both hashes must agree before declaring a duplicate" is the correct recall-first bias.
- **Expected to fail:** progressive builds, and silently. At the default `hash_size=8` a real content edit measured Hamming distance **exactly 0** (5.5); at `hash_size=16` the same edit is 6 bits, still inside plausible duplicate thresholds. The single threshold that dedupes a returning slide is the same threshold that swallows a build, and no primary source gives guidance on where to set it. Widening the hash is nearly free on this CPU but also raises sensitivity to codec noise, so the threshold has to be refitted as a fraction of bits. `cv::img_hash` cannot be used here at all — its PHash is hard-wired to 64 bits (5.7).

### 7. ffmpeg `scdet` score dump (or `freezedetect` stable islands) as a cheap first-pass trigger

- **Expected to do well:** no Python decode loop at all; scores harvestable as frame metadata in one pass with `metadata=mode=print` plus the `null` muxer; `min(mafd, diff)` suppresses steady motion for free (3.1); `-skip_frame nokey` genuinely avoids full decode if GOP-level localisation is acceptable; and `freezedetect` is the only stock filter with a real minimum-duration knob, with a pinned reference frame that does *not* suffer `scdet`'s crossfade blindness.
- **Expected to fail:** no minimum-scene-length on `scdet` at all, so burst suppression must be done by the caller (or via the `select` + `prev_selected_t` idiom, which merges by time and cannot tell a build from a real slide); a slide change *during* an embedded video is structurally suppressed by the same `min(mafd, diff)` term that suppresses the video — a silent miss; luma-only on YUV; `freezedetect` reports no freeze at all if a picture-in-picture webcam never stops moving, unless the frame is cropped first; and it adds ffmpeg as a system prerequisite the host does not currently have.

### 8. Baseline controls to measure alongside, not candidates

- **Fixed-interval capture + global dedupe.** Include it: `larry-xue`'s benchmark shows fixed interval caps *coverage* at ~0.78–0.80 because any slide shorter than the interval is missed outright, and it is the only method whose numbers do not move with input quality. It is the honest floor for the recall metric.
- **HSV histogram correlation** (`AnuragSingh2101`'s 0.92, PySceneDetect `detect-hist`). Include it as a control to confirm the structural claim in 5.2 on real video: a vertical flip of the same slide measured a *perfect* match on all four `compareHist` metrics, and no threshold separated a one-bullet build from a whole new slide.
- **OpenCV background subtraction as a change detector.** Do not shortlist it. It fails the determinism preference by construction (5.1): the same cutaway produced foreground `0.000000` at 40 s away and `1.000000` at 200 s away. Its one legitimate use is the inverse framing — capture when the foreground fraction settles — which is worth measuring only as an embedded-video mitigation, and at a downscale (23 ms → 2.1 ms per frame).

### What the spike should measure, beyond ranking

1. **The subset/superset discriminator itself** (8.1, 9.1), independent of any detector: given two consecutive candidate frames, how reliably does "new content appeared where the old frame was empty, and the old content is unchanged" separate a build from a transition on real video? This is the highest-value single experiment in this list, because two independent deployed systems converge on it and no library implements it.
2. **Sample resolution as a recall parameter.** At what working resolution does a one-bullet build stop being detectable? `larry-xue` measured it disappearing at 160×90; PySceneDetect's default is 256×144 for 1080p.
3. **Whether a stability window is safe.** TalkMiner's finding that continuous motion makes a 3-second stability requirement *drop* slides is the most dangerous documented failure in this document; the spike should reproduce it and confirm that a spatial-extent filter or activity mask removes it.
4. **Actual throughput on the target host**, not the indicative numbers in 5.9 — on a real 1080p H.264 talk, with the chosen sampling strategy, including whether `grab()`-without-`retrieve()` or `-skip_frame nokey` delivers its saving on inter-frame-predicted video.
5. **SSIM's cost and its build-vs-transition margin** on this host, against the `absdiff` baseline in 5.3. It is the one metric family with a shipped, actively maintained default (0.9985) and no measurement anywhere in this document.
6. **Whether a slide-frame gate is needed at all, and how cheap it can be.** Four systems put a classifier at exactly that point (9.6), and two deterministic gates exist that cost almost nothing — Laplacian variance (5.4) and Yang et al.'s intensity-histogram SVM at R 0.91 / P 0.93. Measure the deterministic gates before assuming a CNN is required; if one is, `lecture2notes`' dataset (9.3) is public and labelled for exactly this.
