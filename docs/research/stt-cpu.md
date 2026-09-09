# CPU-only STT for English and pt-BR

Research for [issue #5](https://github.com/henricos/extract-slides/issues/5). Facts gathered September 2026.

**This document gathers facts only.** The choice is made by the STT spike ([issue #13](https://github.com/henricos/extract-slides/issues/13)), which measures on the real host. Every claim below cites its source. Numbers that are arithmetic on top of a published figure are marked **[derived]**; data published in a project's own tracker but submitted by users rather than maintainers is marked **[community-submitted]**.

## Target host (from the map, issue #1)

Intel i3-4170 — Haswell, **2 physical cores / 4 threads**, AVX2 + FMA + F16C, **no AVX512, no VNNI** — no GPU, 15 GB RAM (~10 GB free), 112 GB free disk. Python 3.12 + uv, Node 22, Docker, yt-dlp installed. **ffmpeg not installed.** Audio mostly English, but pt-BR must be supported. Long waits acceptable but bounded.

Two host facts turn out to be non-binding, and one turns out to bind harder than expected:

- **RAM is not the constraint.** The largest model considered (Whisper `large-v3` f16) is reported at ~3.9 GB of runtime memory ([whisper.cpp README, Memory usage](https://github.com/ggml-org/whisper.cpp/blob/master/README.md#memory-usage)), against ~10 GB free. Every candidate fits with headroom.
- **The missing ffmpeg does not block STT.** Both leading runtimes vendor their own decoder — see [Audio input](#audio-input-the-missing-ffmpeg-is-not-an-stt-problem).
- **2 physical cores binds harder than thread count suggests.** CTranslate2's own performance guidance is to *"Avoid the total number of threads `inter_threads * intra_threads` to be larger than the number of physical cores"* ([CTranslate2 performance tips](https://opennmt.net/CTranslate2/performance.html)), which caps the useful product at **2**, not 4. whisper.cpp's maintainer states the workload is memory-bound: *"going beyond 8 threads does not help regardless of how many cores you have. My guess is that the computation is memory-bound"* ([whisper.cpp issue #89](https://github.com/ggml-org/whisper.cpp/issues/89#issuecomment-1297449187)).

---

## 1. The pt-BR quality cliff

This is the finding that sets the model-size floor, and it is **not** what the map assumed.

### Portuguese vs English WER by model size (Whisper paper, verified)

Extracted from the paper PDF ([arXiv:2212.04356](https://arxiv.org/abs/2212.04356), also at [cdn.openai.com/papers/whisper.pdf](https://cdn.openai.com/papers/whisper.pdf)), Appendix D.2 — Table 13 *"WER (%) on Fleurs"* (p. 24), Table 11 *"WER (%) on CommonVoice9"* (p. 23), Table 10 *"WER (%) on MLS"* (p. 23). WER %, lower is better.

| Model | FLEURS pt | FLEURS en | CV9 pt | CV9 en | MLS pt | MLS en |
|---|---|---|---|---|---|---|
| tiny | 20.1 | 12.4 | 35.2 | 28.8 | 31.3 | 15.7 |
| base | 13.0 | 8.9 | 23.7 | 21.9 | 21.9 | 11.7 |
| **small** | **7.3** | 6.1 | **12.5** | 14.5 | **13.0** | 8.3 |
| **medium** | **5.0** | 4.4 | **8.1** | 11.2 | **9.0** | 6.8 |
| large | 4.8 | 4.5 | 7.1 | 10.1 | 9.2 | 6.3 |
| large-v2 | 4.3 | 4.2 | 6.3 | 9.4 | 6.8 | 6.2 |

Independent corroboration of the Common Voice column: the model card for [pierreguillou/whisper-medium-portuguese](https://huggingface.co/pierreguillou/whisper-medium-portuguese) cites OpenAI's published Portuguese normalized WER as **8.1** for medium and **7.1** for large — matching Table 11 exactly.

### What the numbers actually say

**Portuguese is a strong language for Whisper, not a weak one.** On the `large-v3` language breakdown published in the repo README, Portuguese is **8th best of 57 languages** on Common Voice 15 and **4th best of 61** on FLEURS: `large-v3` scores **pt 5.9 / en 9.3** on Common Voice 15 and **pt 4.1 / en 4.1** on FLEURS ([openai/whisper README](https://github.com/openai/whisper/blob/main/README.md); numeric bar labels are embedded as text in the repo's own chart, [language-breakdown.svg](https://github.com/openai/whisper/blob/main/language-breakdown.svg)). From `small` upward, **Portuguese beats English on Common Voice** (12.5 vs 14.5 at small; 8.1 vs 11.2 at medium).

This is consistent with the training mix: Portuguese has **8,573 hours** of transcription supervision, the 6th-largest non-English language (paper Appendix E dataset-statistics figure, p. 27, embedded label `Portuguese8573`). The paper reports *"a strong squared correlation coefficient of 0.83 between the log of the word error rate and the log of the amount of training data per language"* and estimates *"WER halves for every 16× increase in training data"* (§3.2, p. 7).

**Where the cliff actually sits: `small` → `base`.** Portuguese error roughly doubles across that one step — FLEURS 7.3 → 13.0 (+78% relative), CV9 12.5 → 23.7 (+90%), MLS 13.0 → 21.9 (+68%) **[derived]** from the table above. `tiny` and `base` are 3–4× the `medium` error rate and should be treated as unusable for pt-BR.

**Where the knee sits: `medium`.** `medium` is close to `large` on Portuguese (FLEURS 5.0 vs 4.8; MLS 9.0 vs 9.2 — medium actually *beats* large-v1 there), so the marginal quality of jumping from medium to large-class is small, while the CPU cost roughly doubles (§2). The larger remaining gap is to `large-v2` on Common Voice (8.1 → 6.3) and MLS (9.0 → 6.8).

**Correction to the map's premise.** Issue #1 states that pt-BR "sets the floor on model size because small Whisper models degrade badly there". The degradation is real but it is *not* pt-BR-specific: relative to English, Portuguese converges *toward* English as size grows (FLEURS pt/en ratio 1.62× at tiny → 1.02× at large-v2 **[derived]**) and *overtakes* English on Common Voice from `small` up. So the floor is set by the absolute WER the pipeline can tolerate, not by a pt-BR-specific weakness — and that floor lands at **`small` as a minimum, `medium` as the quality knee**, not at large.

The paper's own framing: *"With the exception of English speech recognition, performance continues to increase with model size across multilingual speech recognition, speech translation, and language identification."* (§4.1).

### large-v3, turbo and distil

- `large-v3` claims *"10% to 20% reduction of errors"* vs `large-v2` across languages; architecture is unchanged except 128 mel bins (from 80) and a Cantonese token ([openai/whisper-large-v3 model card](https://huggingface.co/openai/whisper-large-v3)). `pt` is in the card's supported-language list.
- `large-v3-turbo` is *"a finetuned version of a pruned Whisper large-v3 … the number of decoding layers have reduced from 32 to 4 … at the expense of a minor quality degradation"*, **809 M** parameters ([turbo model card](https://huggingface.co/openai/whisper-large-v3-turbo)). The official release statement: *"Across languages, the `turbo` model performs similarly to `large-v2`, though it shows larger degradation on some languages like Thai and Cantonese"* ([openai/whisper discussion #2363](https://github.com/openai/whisper/discussions/2363)). **Portuguese is not among the named degraded languages**, so turbo's pt quality can be treated as ≈ large-v2 (FLEURS 4.3 / CV9 6.3 / MLS 6.8). Turbo is *not* trained for translation ([README](https://github.com/openai/whisper/blob/main/README.md)).
- **distil-whisper is disqualified.** *"Distil-Whisper is only available for English speech recognition. For multilingual speech recognition, we recommend using the Whisper Turbo checkpoint"* ([distil-whisper README](https://github.com/huggingface/distil-whisper/blob/main/README.md)); `distil-large-v3` declares `language: en` only and is *"the third and final installment of the Distil-Whisper English series"* ([model card](https://huggingface.co/distil-whisper/distil-large-v3)). No official multilingual distil variant exists. The repo's last push was 2025-01-08 (GitHub API), ~20 months stale.

**Gap:** no primary source publishes per-language WER for the `large-v3`/turbo lineage at sizes *below* large. The paper's per-size tables stop at `large-v2`; the README figure covers only `large-v3`/`large-v2`. So "small-v3" pt quality is unmeasured territory.

### pt-BR fine-tunes (community models; each card is primary for its own claim)

A fine-tune lets a smaller model reach a bigger model's pt quality — relevant because CPU cost scales with size.

| Model | Base | pt WER (own claim) | License |
|---|---|---|---|
| [jlondonobo/whisper-medium-pt](https://huggingface.co/jlondonobo/whisper-medium-pt) | whisper-medium | **6.579** (CV11) vs 8.100 for stock medium | Apache-2.0 |
| [pierreguillou/whisper-medium-portuguese](https://huggingface.co/pierreguillou/whisper-medium-portuguese) | whisper-medium | **6.5987** (CV11 test) | Apache-2.0 |
| [freds0/distil-whisper-large-v3-ptbr](https://huggingface.co/freds0/distil-whisper-large-v3-ptbr) | distil-large-v3, 0.8B | **8.221%** (CV16 val), explicitly pt-BR | MIT |
| [jonatasgrosman/wav2vec2-large-xlsr-53-portuguese](https://huggingface.co/jonatasgrosman/wav2vec2-large-xlsr-53-portuguese) | XLSR-53 | **11.310** WER / 3.740 CER; **9.010** / 3.210 with LM | Apache-2.0 |

Note [Gustrd/whisper-medium-portuguese-ggml-model](https://huggingface.co/Gustrd/whisper-medium-portuguese-ggml-model): a ggml conversion of `pierreguillou/whisper-medium-portuguese` made with whisper.cpp's own `convert-h5-to-ggml.py`, i.e. a pt fine-tune loadable directly by whisper.cpp (Apache-2.0). Both medium fine-tunes are trained/evaluated on Common Voice (read speech), so the claimed WER is an optimistic ceiling for spontaneous conference speech.

---

## 2. Runtimes on CPU

### whisper.cpp

Code and ggml weights are **MIT** ([LICENSE](https://github.com/ggml-org/whisper.cpp/blob/master/LICENSE); the model repo declares `license: mit`, [ggerganov/whisper.cpp](https://huggingface.co/ggerganov/whisper.cpp)). Last push 2026-09-08, latest release v1.9.3 (2026-08-20) — actively maintained (GitHub API).

**Model sizes** ([models/README.md](https://github.com/ggml-org/whisper.cpp/blob/master/models/README.md), quantized variants from the [project's HF model repo README](https://huggingface.co/ggerganov/whisper.cpp/blob/main/README.md)):

| Model | f16 disk | q5_0/q5_1 | q8_0 | Runtime mem (f16) |
|---|---|---|---|---|
| tiny | 75 MiB | 31 MiB (q5_1) | 42 MiB | ~273 MB |
| base | 142 MiB | 57 MiB (q5_1) | 78 MiB | ~388 MB |
| small | 466 MiB | 181 MiB (q5_1) | 252 MiB | ~852 MB |
| medium | 1.5 GiB | 514 MiB (q5_0) | 785 MiB | ~2.1 GB |
| large-v3 | 2.9 GiB | 1.1 GiB (q5_0) | — | ~3.9 GB (large) |
| large-v3-turbo | 1.5 GiB | 547 MiB (q5_0) | 834 MiB | not published |

*"Models are multilingual unless the model name includes `.en`."* Every size has an `.en` twin **except** `large-v1/v2/v3` and `large-v3-turbo`. Portuguese is language 8 of 100 in `g_lang` (`src/whisper.cpp`); the CLI default is `-l en`, so **pt-BR requires an explicit `-l pt`** (or `-l auto`).

**Published x86 CPU benchmarks.** The project's own release notes give maintainer-run figures on a Ryzen 9 5950X, AVX2, no GPU — `Enc.` is milliseconds for **one encoder pass over one 30-second window** (verified in [examples/bench/bench.cpp](https://github.com/ggml-org/whisper.cpp/blob/master/examples/bench/bench.cpp); `WHISPER_CHUNK_SIZE 30`):

| Model | 8 threads ([v1.6.0](https://github.com/ggml-org/whisper.cpp/releases/tag/v1.6.0)) | 16 threads ([v1.7.0](https://github.com/ggml-org/whisper.cpp/releases/tag/v1.7.0)) |
|---|---|---|
| base | 424.85 ms | 293.81 ms |
| small | 1458.32 ms | 1005.64 ms |
| medium | 4333.87 ms | 3004.36 ms |
| large-v2 | 8056.16 ms | — |
| large-v3-turbo | — | 5302.64 ms |

**Finding: on x86 CPU, quantization makes the encoder *slower*, not faster.** From the same v1.7.0 table (5950X, AVX2, 16 threads): `base` 293.81 vs `base-q5_0` **311.95**; `small` 1005.64 vs `small-q5_0` **1110.41**; `large-v3-turbo` 5302.64 vs `-q5_0` **5984.73**. Decode gets faster, encode gets slower. The README's own claim is careful about this: *"Quantized models require less memory and disk space and depending on the hardware can be processed more efficiently."* So for this host, whisper.cpp quantization buys **disk and RAM, not time** — and RAM is not the constraint.

**Quantization quality is explicitly unquantified by the project.** v1.4.0 release notes: *"The transcription quality is degraded to some extend - **not quantified at the moment**."* v1.5.0: *"It's still unclear how the quality is affected from the quantization"* ([v1.4.0](https://github.com/ggml-org/whisper.cpp/releases/tag/v1.4.0), [v1.5.0](https://github.com/ggml-org/whisper.cpp/releases/tag/v1.5.0)). No WER figure for any quantization has ever been published.

**Closest datapoints to the target host.** There is **no 2-core/4-thread Haswell row anywhere** in the project's benchmark thread. The best structural proxy is an **i3-7100T (Kaby Lake, 2C/4T, AVX2, no GPU)** at 4 threads **[community-submitted]** ([issue #89](https://github.com/ggml-org/whisper.cpp/issues/89#issuecomment-1523299503)):

| Model | Enc. (ms / 30 s window) | Encoder-only RTF **[derived]** | Encoder-only time for a 60-min talk **[derived]** |
|---|---|---|---|
| tiny | 1 125 | 0.038× | ~2 min |
| base | 2 616 | 0.087× | ~5 min |
| small | 10 127 | 0.34× | ~20 min |
| medium | 39 383 | 1.31× | ~79 min |
| large | 74 488 | 2.48× | ~149 min |

RTF = `Enc.` ÷ 30 000 ms. These are **hard floors**: decode, prompt processing and the sliding-window logic all add on top. The maintainer explicitly declines to publish an end-to-end mapping: *"there is no point in comparing the 2 implementations by measuring the total time to transcribe an audio… It only makes sense to benchmark the transformer evaluation in isolation"* ([issue #89](https://github.com/ggml-org/whisper.cpp/issues/89#issuecomment-1352233809)). Corroborating scale, also **[community-submitted]**: an i3-8100 (4C/4T) shows sub-linear thread scaling (`base` 1t 4692.04 / 2t 2756.52 / 4t 2023.16 ms), and an unnamed Xeon reports **4.44× real time** for `medium.en` at 8 threads over ~1-hour files.

**Build and threads.** `GGML_NATIVE` defaults ON → `-march=native` picks up AVX2/FMA/F16C automatically; `AVX512` defaults OFF ([ggml/CMakeLists.txt](https://github.com/ggml-org/whisper.cpp/blob/master/ggml/CMakeLists.txt)). `-t` defaults to `min(4, hardware_concurrency())`, i.e. already 4 on this box. **OpenBLAS is a trap here**: `GGML_BLAS` defaults OFF, one 2C/4T Broadwell datapoint measured it **~1.6× slower** (`base.en` 3823.34 ms → 6197.29 ms with `AVX2 BLAS`) **[community-submitted]**, and the maintainer states OpenBLAS on x86 *"is not faster compared to hand-written AVX2 + FP16"* ([issue #89](https://github.com/ggml-org/whisper.cpp/issues/89#issuecomment-1323431516)). `-p N` (chunk parallelism) carries an accuracy warning in the header: *"the transcription accuracy can be worse at the beginning and end of each chunk"* (`include/whisper.h`).

**Two CPU levers the project does document:**
- **VAD** — `--vad` with a Silero model (`download-vad-model.sh silero-v6.2.0`, ~864 KB, from [ggml-org/whisper-vad](https://huggingface.co/ggml-org/whisper-vad)): *"only the speech segments that are detected are extracted from the original audio input and passed to whisper for processing. This reduces the amount of audio data that needs to be processed by whisper and can significantly speed up the transcription process."* For a recorded talk with pauses, this is the single largest documented saving.
- **OpenVINO** — *"the Encoder inference can be executed on OpenVINO-supported devices including x86 CPUs… This can result in significant speedup in encoder performance."* Build `-DWHISPER_OPENVINO=1`; requires a per-model Python conversion step and a first-run compile delay. No CPU numbers published, but note faster-whisper's own table measured whisper.cpp+OpenVINO as its fastest non-batched CPU row (§ below).

**Docker.** Official image `ghcr.io/ggml-org/whisper.cpp:main` — *"This image includes the main executable file as well as `curl` and `ffmpeg`."* ([README](https://github.com/ggml-org/whisper.cpp/blob/master/README.md)). Relevant given the host has no ffmpeg.

**Python binding:** [pywhispercpp](https://github.com/absadiki/pywhispercpp) — MIT, *"Basic Pre-built CPU wheels are available on PYPI"*, automatic model download, exposes `token_timestamps`.

### faster-whisper / CTranslate2

Both **MIT** ([faster-whisper LICENSE](https://github.com/SYSTRAN/faster-whisper/blob/master/LICENSE), [CTranslate2 LICENSE](https://github.com/OpenNMT/CTranslate2/blob/master/LICENSE)); the converted `Systran/faster-whisper-*` weights declare `license: mit`.

**Maintenance signal, per this repo's own activity criterion (`docs/similar-tools.md`):** faster-whisper's last push is **2025-11-19** — ~9.5 months before this scan, i.e. approaching the ~12-month "stale" threshold; latest release v1.2.1 (2025-10-31), 30 open PRs. Not archived. CTranslate2 underneath it *is* active: last push 2026-08-31, v4.8.2 released 2026-08-31 (GitHub API).

**Headline claim:** *"This implementation is up to 4 times faster than openai/whisper for the same accuracy while using less memory. The efficiency can be further improved with 8-bit quantization on both CPU and GPU."* ([README](https://github.com/SYSTRAN/faster-whisper/blob/master/README.md)).

**The only CPU benchmark table any of these projects publishes** — 13 minutes of audio, `openai/whisper@v20240930` / `whisper.cpp@v1.7.2` / `faster-whisper@v1.1.0`, *"Executed with 8 threads on an Intel Core i7-12700K"*, **small model only** ([README](https://github.com/SYSTRAN/faster-whisper/blob/master/README.md)):

| Implementation | Precision | Beam | Time | RAM | RTF **[derived]** |
|---|---|---|---|---|---|
| openai/whisper | fp32 | 5 | 6m58s | 2335 MB | 1.87× faster than RT |
| whisper.cpp | fp32 | 5 | 2m05s | 1049 MB | 6.24× |
| whisper.cpp (OpenVINO) | fp32 | 5 | 1m45s | 1642 MB | 7.43× |
| faster-whisper | fp32 | 5 | 2m37s | 2257 MB | 4.97× |
| **faster-whisper** | **int8** | 5 | **1m42s** | 1477 MB | **7.65×** |
| faster-whisper (`batch_size=8`) | int8 | 5 | 51s | 3608 MB | 15.3× |

Read carefully: **int8 CTranslate2 is the fastest non-batched CPU configuration in this table**, and whisper.cpp+OpenVINO is close behind. Stock `openai/whisper` is ~4× slower than both. The comparison caveats are in the README's own *"Comparing performance against other implementations"* section (same beam size, same thread count).

**No CPU table exists for medium, large-v3, turbo or distil** — the only published CPU figures are `small`. And both CPU tables in this ecosystem use far stronger CPUs than the target (8 threads on an i7-12700K here; 4 threads on a Xeon 8275CL in [CTranslate2's own benchmarks](https://github.com/OpenNMT/CTranslate2#benchmarks)). **Nothing in a primary source lets you extrapolate to a 2-core Haswell.** That is exactly what spike #13 must measure.

**int8 on this specific CPU works, and gets the good code path.** CTranslate2 lists int8 as *"Supported on: … x86-64 CPU with the Intel MKL or oneDNN backends"* with **no AVX512 or VNNI requirement stated** ([quantization docs](https://opennmt.net/CTranslate2/quantization.html)). Prebuilt binaries *"automatically select the best backend and instruction set architecture for the platform (AVX, AVX2, or AVX512) … compiled with both Intel MKL and oneDNN so that Intel MKL is only used on Intel processors where it performs best"*; CPU floor is *"x86-64 processors supporting at least SSE 4.1"* ([hardware support](https://opennmt.net/CTranslate2/hardware_support.html)). Source confirms AVX512 is never even auto-selected — [`src/cpu/cpu_isa.cc`](https://github.com/OpenNMT/CTranslate2/blob/master/src/cpu/cpu_isa.cc) auto-selects only `AVX2 → AVX → GENERIC` with the comment *"Note that AVX512 can only be enabled with the environment variable at this time"*, and [`src/cpu/backend.cc`](https://github.com/OpenNMT/CTranslate2/blob/master/src/cpu/backend.cc) routes int8 GEMM to MKL on genuine Intel. **So the i3-4170 gets MKL + AVX2 int8, the top auto-selected path.** Counterweight: the official CPU tip list still says *"Use an Intel CPU supporting AVX512"* ([performance tips](https://opennmt.net/CTranslate2/performance.html)) — a recommendation this host cannot satisfy, and no primary source quantifies the penalty of AVX2-without-VNNI int8.

Also note the implicit type conversion table: on x86-64 Intel, `float16 → float32` and `int8_float16 → int8_float32`. Since the Systran weights are stored float16, **the default `compute_type` runs as float32 on this host** — int8 must be requested explicitly ([quantization docs](https://opennmt.net/CTranslate2/quantization.html)).

**Accuracy impact of int8** — *"Quantization is a technique that can reduce the model size and accelerate its execution with little to no degradation in accuracy"*, and CTranslate2's own CPU benchmark shows BLEU essentially unchanged (WMT14 float32 BLEU 26.77 → int8 **26.78**; OPUS-MT 27.92 → **27.65**) ([benchmarks](https://github.com/OpenNMT/CTranslate2#benchmarks)). **Gap: these are translation BLEU numbers, not Whisper WER.** No primary source publishes Whisper int8-vs-fp32 WER, on CPU or otherwise.

**Threading.** `cpu_threads` → CT2 `intra_threads` (*"Number of threads to use when running on CPU (4 by default). A non zero value overrides the OMP_NUM_THREADS environment variable"*), `num_workers` → `inter_threads` ([transcribe.py](https://github.com/SYSTRAN/faster-whisper/blob/master/faster_whisper/transcribe.py)). Default `intra_threads` is 4 ([parallel docs](https://opennmt.net/CTranslate2/parallel.html)). Combined with the "≤ physical cores" rule, the configuration to test on this host is `cpu_threads=2, num_workers=1` — and 4 as the counter-test.

**Model sizes** (`model.bin` byte counts from the HF repos faster-whisper itself downloads from, float16): [tiny](https://huggingface.co/Systran/faster-whisper-tiny) ~72 MB, [base](https://huggingface.co/Systran/faster-whisper-base) ~138 MB, [small](https://huggingface.co/Systran/faster-whisper-small) ~461 MB, [medium](https://huggingface.co/Systran/faster-whisper-medium) ~1.42 GB, [large-v3](https://huggingface.co/Systran/faster-whisper-large-v3) ~2.88 GB, turbo ~1.51 GB. **Gap:** no per-model-size runtime-memory table is published; the only RAM figures are the `small` row above.

**Batched inference** (`BatchedInferencePipeline`) does claim CPU benefit — the CPU table's batched rows are ~2–2.4× faster at ~2.4× the RAM. But those were measured on 8 threads of an i7-12700K; **no primary source covers batching on a low-core-count CPU**, and batching wins by widening GEMMs, which needs cores. Treat as unproven here. Note the batched path also flips defaults: `without_timestamps=True` and `vad_filter=True`.

**VAD.** *"The library integrates the Silero VAD model to filter out parts of the audio without speech"* via `vad_filter=True`; *"The default behavior is conservative and only removes silence longer than 2 seconds"* (`min_silence_duration_ms=2000`, [vad.py](https://github.com/SYSTRAN/faster-whisper/blob/master/faster_whisper/vad.py)). Bundled as a 1.25 MB `silero_vad_v6.onnx` asset run through `onnxruntime` with `CPUExecutionProvider`. Timestamps are correctly remapped back to the original timeline by `restore_speech_timestamps()` / `SpeechTimestampsMap` at 10 ms granularity — so **VAD does not corrupt the slide-pairing timeline**.

**Model resolution.** `WhisperModel("large-v3")` downloads from the [Systran](https://huggingface.co/Systran) org via a hardcoded `_MODELS` dict ([utils.py](https://github.com/SYSTRAN/faster-whisper/blob/master/faster_whisper/utils.py)); anything matching `*/*` is treated as a repo id. Offline is supported three ways: a local directory path, `local_files_only=True`, or `files=` in-memory; plus `download_root`, `revision`. **Gotcha:** the id hardcoded for `turbo`/`large-v3-turbo` is `mobiuslabsgmbh/faster-whisper-large-v3-turbo`, which now redirects to `dropbox-dash/faster-whisper-large-v3-turbo` — still MIT, but pin a revision or vendor the files.

**Python 3.12 is covered:** faster-whisper 1.2.1 and ctranslate2 4.8.2 both declare `requires_python >=3.9`, and ctranslate2 publishes a `cp312 manylinux_2_28_x86_64` wheel (PyPI), so `uv` will resolve on this host provided glibc ≥ 2.28.

### Stock openai/whisper

**MIT**, code and weights ([README](https://github.com/openai/whisper/blob/main/README.md)). Model table: tiny 39 M / base 74 M / small 244 M / medium 769 M / large 1550 M / turbo 809 M, with "Required VRAM" ~1/1/2/5/10/6 GB and "Relative speed" ~10×/7×/4×/2×/1×/~8× — but the README states these *"are measured by transcribing English speech on a A100, and the real-world speed may vary significantly depending on many factors including the language, the speaking speed, and the available hardware."*

**On CPU it is float32 only.** `transcribe.py` warns *"FP16 is not supported on CPU; using FP32 instead"* and forces `dtype = torch.float32` ([transcribe.py](https://github.com/openai/whisper/blob/main/whisper/transcribe.py)). There is **no quantization path**, and the repo publishes **no CPU benchmark whatsoever**. Combined with faster-whisper's measured 6m58s vs 1m42s on the same 13-minute clip, stock Whisper is the reference implementation for quality, not a runtime candidate for this host. Models download from `openaipublic.azureedge.net` with SHA-256 verification; `download_root` / a direct file path support offline use ([__init__.py](https://github.com/openai/whisper/blob/main/whisper/__init__.py)).

---

## 3. Non-Whisper families

### NVIDIA Parakeet TDT 0.6B v3 — the serious non-Whisper candidate

[nvidia/parakeet-tdt-0.6b-v3](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3): **25 European languages, Portuguese explicitly included**; **CC-BY-4.0**; **600 M parameters**; *"At least 2GB RAM for model to load"*. NVIDIA's own published Portuguese WER: **FLEURS 4.76%, MLS 7.50%, CoVoST 3.96%** — i.e. FLEURS pt better than Whisper `medium` (5.0) and near `large-v2` (4.3), at 600 M parameters instead of 769 M / 1550 M. It produces *"accurate word-level and segment-level timestamps"* natively.

Two **first-party CPU paths** exist:
- NVIDIA's own [NeMo-Speech.cpp](https://github.com/NVIDIA/NeMo-Speech.cpp), *"a lightweight native C++ runtime for local inference"* (ggml-based, CPU backend, Apache-2.0 for NVIDIA-authored code), with an official quant in the model repo: `parakeet-tdt-0.6b-v3.q8_0.gguf`, **714 MB**.
- [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) (Apache-2.0, CPU-first: x86/ARM/RISC-V, Python API) ships `sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8` — encoder.int8.onnx **622 MB** + decoder 12 MB + joiner 6.1 MB. The docs' own example output shows **RTF 0.325** (host unspecified), and the English v2 equivalent reports **RTF 0.118 on an RK3588 with 4 threads** — a weak ARM SoC ([nemo-transducer models](https://k2-fsa.github.io/sherpa/onnx/pretrained_models/offline-transducer/nemo-transducer-models.html)).

**The pt-BR-specific risk, flagged by NVIDIA itself:** the card states its Portuguese training data is **European** Portuguese while most benchmarks are Brazilian Portuguese, and names this as a source of degradation. For a pt-BR project this must be measured, not assumed.

Independent placement on Portuguese, from the Open ASR Leaderboard owners' own paper (HF/NVIDIA co-authored, [arXiv:2510.06961](https://arxiv.org/abs/2510.06961), Table 4, CoVoST-2 + FLEURS): **Whisper large-v3 4.38 · Voxtral Mini 3B 4.80 · Phi-4-multimodal 5.15 · Parakeet TDT 0.6B v3 5.95 · Canary 1B v2 6.23 · ElevenLabs Scribe v1 22.8**. So on a like-for-like harness, Whisper large-v3 still leads Parakeet on Portuguese — Parakeet's appeal is quality *per unit of CPU*, not peak quality. The leaderboard's multilingual track covers only **de/fr/it/es/pt**, and its RTFx figures are measured on 1× H200, so they say nothing about CPU.

### Others

- **NVIDIA Canary 1B v2** ([card](https://huggingface.co/nvidia/canary-1b-v2)): 25 languages incl. pt, CC-BY-4.0, 978 M params, word + segment timestamps, pt FLEURS WER 8.16%. But *"At least 6GB RAM for model to load"*, *"designed and/or optimized to run on NVIDIA GPU-accelerated systems"*, **no documented CPU path**, and worse published pt WER than Parakeet v3 at 1.6× the parameters. `canary-1b-flash` and `canary-180m-flash` cover **only en/de/fr/es** — disqualified for pt.
- **Vosk** ([models](https://alphacephei.com/vosk/models), [vosk-api](https://github.com/alphacep/vosk-api), Apache-2.0): the "runs on a potato" floor — *"Works offline, even on lightweight devices - Raspberry Pi, Android, iOS"*, with word-level timestamps and per-word confidence in the C API (`vosk_recognizer_set_words`). Only two Portuguese models exist: `vosk-model-small-pt-0.3` (**31 MB**, WER **68.92** on CORAA dev / **32.60** on Common Voice test, Apache-2.0) and `vosk-model-pt-fb-v0.1.1` (**1.6 GB**, WER **54.34** / **27.70**, **GPLv3**). Those are the owner's own figures. At 27–69% WER this is a keyword/liveness tool, not a transcription tool for this pipeline — and the better model's GPLv3 is incompatible with an MIT project.
- **wav2vec2 XLSR-53 Portuguese** ([jonatasgrosman](https://huggingface.co/jonatasgrosman/wav2vec2-large-xlsr-53-portuguese), Apache-2.0): WER 11.31 / 9.01 with LM, cheap on CPU (no autoregressive decode). But **output is UPPERCASE with no punctuation** (the card's own prediction examples show this), and the card documents no timestamps. Usable as a *fallback*, at the cost of needing separate punctuation/truecasing.
- **Disqualified — no Portuguese:** Parakeet TDT 0.6B **v2** (English only, GPU-only hardware section), Moonshine (STT covers en/es/zh/ja/ko/vi/uk/ar — [no pt model in the org listing](https://huggingface.co/moonshine-ai)), Kyutai STT (en/fr), Dolphin (Eastern languages), FunASR core (zh/en/ja/ko/yue), Qwen2-Audio (pt not listed).
- **Disqualified — license:** SeamlessM4T v2 ([card](https://huggingface.co/facebook/seamless-m4t-v2-large)) supports `por` but is **CC-BY-NC-4.0**, non-commercial.
- **Disqualified — too heavy / no CPU path:** IBM Granite Speech 3.3 (2B–8B, `device_map="auto"`), Phi-4-multimodal (5.6B; its own ONNX repo offers CUDA/DirectML instructions but for CPU says *"stay tuned or follow this tutorial to generate your own ONNX models for CPU"*), Voxtral-Mini-3B (owner states ~9.5 GB GPU RAM in bf16/fp16).
- **Blocked on timestamps:** Qwen3-ASR-0.6B (Apache-2.0, 30 languages incl. pt, attractive size — but timestamps need a second model, `Qwen3-ForcedAligner-0.6B`); Fun-ASR-MLT-Nano-2512 (Apache-2.0, 31 languages incl. pt, ships a no-GPU/no-Python GGUF binary — but its own TODO still reads *"Support returning timestamps"*).

**No official pt-BR-only ASR leaderboard exists.** The reference pt-BR corpus is [CORAA-ASR](https://github.com/nilc-nlp/CORAA) (290.77 h, 400k+ segments, primarily Brazilian Portuguese) — note that Vosk's grim numbers are on CORAA dev, spontaneous speech, which is much closer to a real recorded talk than Common Voice read speech. **Any WER figure quoted on Common Voice in this document is an optimistic ceiling for conference audio.**

---

## 4. Timestamps

The pipeline pairs speech with slides, so it needs timestamps on a reliable absolute timeline. **Segment-level is sufficient for slide pairing; word-level is a bonus.** Good news: segment timestamps are the default everywhere.

| Option | Segment ts | Word ts | Mechanism | Notes |
|---|---|---|---|---|
| faster-whisper | always | `word_timestamps=True` | *"cross-attention pattern and dynamic time warping"* | Per-word `probability`; alignment heads baked into each model's `config.json`; VAD remaps to original timeline at 10 ms granularity |
| whisper.cpp | default (`-nt` to disable) | `-ml 1` (+ `-sow`), or `--dtw` | DTW port of OpenAI `timing.py` | Both labelled **experimental**; see caveats below |
| openai/whisper | always | `--word_timestamps True` | DTW on cross-attention | Help string still reads *"(experimental)"* |
| Parakeet v3 / Canary v2 | yes | yes (also char-level) | native to the model | Model-native, not a bolt-on |
| Vosk | yes | yes + confidence | Kaldi lattice | `"conf"/"start"/"end"/"word"` per word |
| wav2vec2 pt | not documented | not documented | — | CTC offsets exist as a *library* feature, not a card claim |

**whisper.cpp caveats (important).** `--dtw` gives **token-level `t_dtw`, not OpenAI-equivalent word timestamps** — the merging PR says so explicitly: *"my intention is to implement token-level only as a first step that can be used to implement word timestamps in the future"* ([PR #1485](https://github.com/ggml-org/whisper.cpp/pull/1485)). It is `[EXPERIMENTAL]` in three places in `include/whisper.h`, `t_dtw` is documented only as *"Roughly corresponds to the moment in audio in which the token was output"*, it costs **128 MiB** of extra RAM (`dtw_mem_size` default), it requires naming an alignment-head preset that matches the model (accepted strings use dots: `large.v3.turbo`, not the dashes in filenames — a mismatched or absent preset is a hard error), **no preset exists for any distilled or `-tdrz` model**, and `t_dtw` surfaces only via `-ojf/--output-json-full`, not in SRT/VTT. The README documents `-ml 1` but never documents `--dtw`. **No accuracy or reliability figure for whisper.cpp timestamps has ever been published.**

**Bolt-on aligners, and a license hazard:**
- [WhisperX](https://github.com/m-bain/whisperX) — BSD-2-Clause, *"Accurate word-level timestamps using wav2vec2 alignment"*, CPU documented (`--compute_type int8 --device cpu`). Its torch default alignment models cover only `{en, fr, de, es, it}`; **Portuguese comes from the HF dict as `"pt": "jonatasgrosman/wav2vec2-large-xlsr-53-portuguese"`** ([alignment.py](https://raw.githubusercontent.com/m-bain/whisperX/main/whisperx/alignment.py)) — so pt word-alignment means downloading and running a *second* XLSR-53 model on the same 2 cores. Also needs ffmpeg.
- [whisper-timestamped](https://github.com/linto-ai/whisper-timestamped) — DTW on cross-attention with **no per-language alignment model** (*"avoids the need to find one wav2vec model per language to support, which does not scale well with the multi-lingual capabilities of Whisper"*), per-word confidence, VAD. **But it is AGPL-3.0** (confirmed via GitHub API) — a license hazard for an MIT-licensed project if vendored or linked; safe only as a separately-invoked external process, and worth avoiding.
- [stable-ts](https://github.com/jianfch/stable-ts) — MIT, CPU, multiple backends, but the repo is **archived** (GitHub API `archived: true`) and its README says development is *"indefinitely paused"*.

**Hallucination control interacts with timestamps.** `openai/whisper` exposes `hallucination_silence_threshold` — *"(requires --word_timestamps True) skip silent periods longer than this threshold (in seconds) when a possible hallucination is detected"* — and faster-whisper mirrors it (default `None`). OpenAI's model card warns *"the predictions may include texts that are not actually spoken in the audio input (i.e. hallucination)"* ([model-card.md](https://github.com/openai/whisper/blob/main/model-card.md)). For a talk with long silent stretches over a slide, VAD + this threshold matter.

---

## 5. Audio input: the missing ffmpeg is not an STT problem

- **whisper.cpp needs no ffmpeg.** CLI help line 2: `supported audio formats: flac, mp3, ogg, wav`. Decoding is vendored in-tree — [common-whisper.cpp](https://github.com/ggml-org/whisper.cpp/blob/master/examples/common-whisper.cpp) compiles [miniaudio](https://github.com/mackron/miniaudio) plus `stb_vorbis.c`, decoding to f32 at 16 kHz mono internally. FFmpeg is *optional*, via `WHISPER_COMMON_FFMPEG` (**not** `WHISPER_FFMPEG`, which no longer exists on master), and is only genuinely required for `-owts` karaoke video and `make samples`. Caveat: the Quick-start section of the README still claims *"whisper-cli … currently runs only with 16-bit WAV files"* with an ffmpeg conversion example — the CLI's own `--help` and the miniaudio code contradict it; the code is newer.
- **faster-whisper needs no ffmpeg.** README, verbatim: *"Unlike openai-whisper, FFmpeg does **not** need to be installed on the system. The audio is decoded with the Python library PyAV which bundles the FFmpeg libraries in its package."* Confirmed in [audio.py](https://github.com/SYSTRAN/faster-whisper/blob/master/faster_whisper/audio.py) (`av.open`, `AudioResampler(format="s16", layout="mono", rate=16000)`). PyAV itself: *"Since release 8.0.0 binary wheels are provided on PyPI for Linux, Mac and Windows linked against FFmpeg"* ([PyAV install docs](https://pyav.org/docs/develop/overview/installation.html)).
- **openai/whisper does need ffmpeg** on the system, and WhisperX's README says the same.

**But the pipeline still needs ffmpeg for the slide track** (decoding/frame extraction from video). So the map's `ffmpeg NOT installed` item stays a real gap — it just does not constrain the STT choice.

---

## 6. Licensing and download mechanics summary

| Component | Code license | Weights license | Model host | Offline |
|---|---|---|---|---|
| whisper.cpp | MIT | MIT (ggml repo `license: mit`) | [ggerganov/whisper.cpp](https://huggingface.co/ggerganov/whisper.cpp) via `download-ggml-model.sh` (accepts a target dir) | yes |
| faster-whisper / CTranslate2 | MIT / MIT | MIT (`Systran/faster-whisper-*`) | [Systran](https://huggingface.co/Systran) via `huggingface_hub.snapshot_download` | yes (`local_files_only`, dir path, `files=`) |
| openai/whisper | MIT | MIT | `openaipublic.azureedge.net`, SHA-256 verified | yes (`download_root`, file path) |
| Parakeet TDT 0.6B v3 | Apache-2.0 (NeMo-Speech.cpp) / Apache-2.0 (sherpa-onnx) | **CC-BY-4.0** (attribution required) | HF + sherpa-onnx GitHub releases | yes |
| Vosk | Apache-2.0 | small-pt Apache-2.0; **pt-fb GPLv3** | alphacephei.com | yes |
| whisper-timestamped | **AGPL-3.0** | n/a | n/a | yes |

Everything shortlisted is MIT or Apache/CC-BY, i.e. compatible with this repo's MIT license. The two license landmines are **whisper-timestamped (AGPL-3.0)** and **`vosk-model-pt-fb` (GPLv3)**; CC-BY-4.0 on Parakeet means attribution is required.

---

## 7. Shortlist for the STT spike (#13)

Ranked by likelihood of being the answer, not by certainty. The spike measures wall-clock, peak RSS and pt-BR/English transcript quality on the real host.

1. **faster-whisper `medium`, `compute_type="int8"`, `cpu_threads=2`, `vad_filter=True`.**
   Best-understood quality-per-CPU point for pt-BR: Whisper `medium` scores **pt FLEURS 5.0 / CV9 8.1** (paper Tables 13/11) — the quality knee, within 0.2 of `large` on FLEURS — and int8 CTranslate2 is the **fastest non-batched CPU configuration in the only published CPU comparison** (1m42s vs whisper.cpp fp32 2m05s and openai/whisper 6m58s on 13 min of audio). On this exact CPU it gets the MKL + AVX2 int8 path. Native segment + word timestamps, no ffmpeg needed.

2. **sherpa-onnx + `sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8`.**
   The candidate that could be both faster *and* more accurate: NVIDIA publishes **pt FLEURS WER 4.76** at **600 M parameters** with native word + segment timestamps, and sherpa-onnx's own docs report **RTF 0.118 on a 4-thread RK3588 ARM SoC** for the English equivalent. Measure it because if it holds, it dominates Whisper `medium` on both axes. Two risks to test explicitly: NVIDIA's own caveat that its pt data is **European** Portuguese, and its 5.95 vs large-v3's 4.38 pt WER on the leaderboard's like-for-like harness.

3. **whisper.cpp `ggml-small` (f16, `-t 4`, `-l pt`, `--vad`).**
   The guaranteed-to-finish floor and the honest baseline. Closest published 2C/4T AVX2 datapoint gives `small` **Enc. 10 127 ms per 30 s window ≈ 0.34× real time encoder-only** — roughly 20 min of encoder work for a 60-min talk, versus 79 min at `medium` and 149 min at `large` **[derived, community-submitted proxy]**. MIT code *and* MIT weights, official Docker image with ffmpeg, no Python runtime. Quality cost: pt CV9 12.5 vs 8.1 at medium. **Do not bother quantizing it** — the project's own tables show q5_0 *slower* on the encoder on x86.

4. **faster-whisper `large-v3-turbo`, int8** — include only to bound the ceiling.
   pt quality ≈ `large-v2` (**FLEURS 4.3 / CV9 6.3 / MLS 6.8**) at 809 M params. But turbo prunes only the **decoder** (32 → 4 layers); the encoder is `large-v3`'s, and whisper.cpp's own bench confirms turbo encode (5302.64 ms) sits in the `large-v2` class (8056.16 ms) rather than the `medium` class. On 2 cores where encode dominates, turbo's win may largely evaporate. Measure it to find out whether the quality ceiling is affordable at all; if it is, it supersedes #1.

**Also worth one measurement each, cheaply:** `--vad` / `vad_filter` on vs off on real talk audio (the largest documented CPU lever, and talks are full of pauses); `cpu_threads=2` vs `4` (CTranslate2's "≤ physical cores" rule vs the 4 hardware threads); and whisper.cpp + **OpenVINO**, which was the fastest non-batched CPU row in faster-whisper's own table and targets exactly this Intel CPU.

**Not worth the spike's time:** stock `openai/whisper` (fp32-only on CPU, ~4× slower than both alternatives in the published comparison — keep it as the quality reference); anything `tiny`/`base` for pt-BR (13.0–35.2% WER); distil-whisper (English-only); Vosk (27–69% pt WER); Canary v2 (no CPU path, 6 GB RAM floor, worse pt WER than Parakeet); and the 3–9B audio-LLMs.

---

## 8. What no primary source answers

These are the holes the spike exists to fill:

1. **No CPU benchmark at all for `medium`, `large-v3` or `turbo`** in any of these projects — the only published CPU table is `small`.
2. **No benchmark on a low-core-count, pre-VNNI CPU.** Published CPU figures use 8 threads on an i7-12700K, 16 threads on a 5950X, or 4 threads on a Xeon 8275CL. The only 2C/4T AVX2 datapoints are community-submitted, and none is a Haswell i3.
3. **No end-to-end real-time factor for whisper.cpp** — the maintainer declines to publish one on principle. Every RTF in this document is `Enc. ÷ 30 000 ms`, an encoder-only floor.
4. **No Whisper int8-vs-fp32 WER comparison**, and no WER figure for any whisper.cpp quantization (*"not quantified at the moment"* is the project's own position).
5. **No per-language WER for the `large-v3`/turbo lineage below `large`**, and no Portuguese-specific turbo number.
6. **No accuracy or reliability figure for word/token timestamps** in any implementation; all three Whisper runtimes label the feature experimental.
7. **No vendor states CPU instruction-set requirements** for NeMo-Speech.cpp or sherpa-onnx, so int8 on AVX2-without-VNNI is undocumented territory. ONNX Runtime's own compatibility page likewise does not state x86 ISA requirements.
8. **No per-model-size runtime-memory table** for faster-whisper, and none for any quantized whisper.cpp model or for `large-v3-turbo`.
9. **No pt-BR WER on spontaneous speech** for any Whisper size from the owner. Every pt figure here is FLEURS/Common Voice/MLS (read or prepared speech); CORAA-style spontaneous pt-BR is measurably harder, as Vosk's 68.92 (CORAA) vs 32.60 (Common Voice) spread on the same model shows.

---

## Appendix: findings that may affect the map (issue #1)

Recorded here for the map's owner; this document does not change the map.

1. **The pt-BR premise needs rewording.** Portuguese is a *high-resource* language for Whisper (8,573 h; 4th–8th best of ~60 languages on the official breakdown) and beats English on Common Voice from `small` up. The size floor is set by absolute tolerable WER, and lands at **small minimum / medium knee** — not at large.
2. **`ffmpeg NOT installed` does not constrain STT.** whisper.cpp vendors miniaudio; faster-whisper vendors FFmpeg via PyAV wheels. ffmpeg is still needed for the *slide* track.
3. **Quantization is not a speed lever on this CPU for whisper.cpp** — the project's own x86 tables show q5_0 encoding *slower* than f16. It is a disk/RAM lever, and RAM is not the constraint.
4. **The effective parallelism budget is 2, not 4.** CTranslate2's own guidance caps `inter_threads × intra_threads` at physical cores.
5. **A non-Whisper candidate is genuinely competitive**: Parakeet TDT 0.6B v3 has first-party CPU artifacts (NVIDIA q8_0 GGUF, sherpa-onnx int8), native word+segment timestamps, 600 M params, and NVIDIA-published pt FLEURS WER better than Whisper `medium` — with a pt-BR-specific caveat (European Portuguese training data) that only measurement can settle. Worth having in the map as a real branch, not a footnote.
6. **Two maintenance/licensing flags.** `faster-whisper` upstream has not been pushed since 2025-11-19 (~9.5 months, approaching this repo's own ~12-month stale threshold), though CTranslate2 beneath it is active; and `whisper-timestamped` is **AGPL-3.0**, which should be excluded from an MIT project's dependency set.
7. **VAD deserves to be a first-class pipeline step, not a flag.** It is the largest CPU saving either project documents, it is bundled in both, and faster-whisper remaps timestamps back to the original timeline so it does not break slide pairing.
