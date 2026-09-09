# YouTube caption acquisition in 2026

Research for [issue #6](https://github.com/henricos/extract-slides/issues/6). Answers one question: is the "use the YouTube caption when one exists, fall back to local STT" branch from [`docs/idea.md`](../idea.md) worth building, and what does it cost?

## Verdict

**Build it.** For recorded conference talks the caption branch is not a marginal optimization — it is the default path, and local STT is the fallback for the minority of videos that have no caption.

| Question | Answer |
|---|---|
| Are captions dependably obtainable? | Yes for talks. 9/9 sampled conference talks had an ASR ("auto-generated") caption in the original spoken language. 0/9 had a human caption. |
| Cost in reliability? | Low, on one condition: **never request a machine-translated track**. Original-language ASR tracks fetched 35+ times without a single failure; translated tracks returned HTTP 429 on 4 of 5 consecutive attempts. |
| Cookies / PO tokens needed from a server IP? | Not for the videos sampled. No cookies, no PO token, no browser, no impersonation, no JS runtime. The PO-token gate for subtitles exists but is a partial rollout and none of the sampled videos were in it. |
| Are auto-caption timestamps precise enough for slide pairing? | Yes, and by a wide margin — **if you use `--sub-format json3`**. ASR tracks carry real per-word timings at 1 ms resolution; median distance from an arbitrary instant to the nearest word boundary was 90–131 ms. Cue-level timing (what `youtube-transcript-api` and every non-json3 format give you) is 5–8× coarser. |
| Is pt-BR auto-caption quality good enough to skip STT? | Good enough for pairing speech to slides, and for a readable transcript. ~14.5% raw word error against a human-edited pt-BR reference, concentrated in proper nouns and technical terms. Not good enough to be called authoritative — treat it as the default output with STT as an opt-in upgrade, not as a "fast preview only". |

Two findings change the shape of the pipeline more than the yes/no answer:

1. **`json3` is not one format among seven — it is the only usable one.** It is the only format that gives clean non-duplicated text *and* real per-word timings. The default (`--sub-format best` → `vtt` for YouTube) produces ~3× duplicated text.
2. **Auto-captions are more temporally precise than human captions.** Human caption tracks have no word timings at all. If a video has both, the ASR track is the better input for slide pairing.

## Method and honesty about scope

Two source classes are mixed below and always labelled:

- **[DOC]** — a claim from yt-dlp's README/wiki/source, `youtube-transcript-api`'s README/source, or YouTube's own responses. URL cited.
- **[EMPIRICAL]** — measured on this machine. **All empirical observations were made on 2026-09-08**, from the target home-server IP, with **yt-dlp 2026.07.04** and **youtube-transcript-api 1.2.4**. Single IP, single day, small sample. YouTube changes monthly (see [Breakage cadence](#breakage-cadence)), so every empirical number here is a snapshot, not a guarantee.

The reference set ([issue #4](https://github.com/henricos/extract-slides/issues/4)) does not exist yet, so the question "is the caption available for the same videos in the reference set" could not be answered directly. A stand-in sample was used instead:

| Group | Count | IDs |
|---|---|---|
| English conference talks | 5 | `X2vr81CJ934` (ADC 2025), `RUIguklWwx0` (OpenSSL Conf 2025), `hQVREBSYx7E` (PyCon Taiwan 2025), `iwOn71Vki74` (PyCon Estonia 2025), `AUQDHZMLZAU` (ACCU 2025) |
| pt-BR conference talks | 4 | `CaRFhW9rNXY` (PyLadies SP 2025), `Llz92eVThMo` (Python Brasil), `7JbOagrwysE`, `D0-titxfVZo` (Conferências Irmãs) |
| pt-BR talk with a human caption | 1 | `C38xlWnkezQ` (TEDxSãoPaulo) — used as the quality reference |
| Negative controls (music videos) | 4 | `3sB4Iv_tM7U`, `e68F6n0pIqs`, `INX8G-q4pgk`, `ex6qyu8e-o0` |

When the reference set is assembled, re-run the availability check on it; the numbers below are indicative, not measured on the real corpus.

## Availability

**[EMPIRICAL]** All 9 conference talks (5 EN, 4 pt) exposed an ASR caption in the original spoken language, in all 7 formats. None had a human-authored caption.

```
7JbOagrwysE  lang=pt  manual: ['live_chat']  auto tracks: 157  original: pt-orig
AUQDHZMLZAU  lang=en  manual: NONE           auto tracks: 157  original: en-orig
CaRFhW9rNXY  lang=pt  manual: NONE           auto tracks: 157  original: pt-orig
D0-titxfVZo  lang=pt  manual: ['live_chat']  auto tracks: 157  original: pt-orig
Llz92eVThMo  lang=pt  manual: NONE           auto tracks: 157  original: pt-orig
RUIguklWwx0  lang=en  manual: NONE           auto tracks: 157  original: en-orig
X2vr81CJ934  lang=en  manual: NONE           auto tracks: 157  original: en-orig
hQVREBSYx7E  lang=en  manual: NONE           auto tracks: 157  original: en-orig
iwOn71Vki74  lang=en  manual: NONE           auto tracks: 157  original: en-orig
```

The "157 auto tracks" are 1 real ASR track plus 156 machine translations of it. **All 156 are traps** — see [Rate limits](#rate-limits-and-the-429-on-translated-captions).

**[EMPIRICAL]** Caption-less videos are real: 3 of the 4 negative-control music videos had zero automatic captions.

### Gotcha: `live_chat` lives in the `subtitles` dict

**[DOC + EMPIRICAL]** yt-dlp files a live-chat replay under `subtitles` as if it were a caption ([`_video.py`](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/youtube/_video.py): `info.setdefault('subtitles', {})['live_chat'] = [...]`). The README documents the consequence — *"Live chats (if available) are considered as subtitles. Use `--sub-langs all,-live_chat` to download all subtitles except live chat"* ([README, Differences in default behavior](https://github.com/yt-dlp/yt-dlp#differences-in-default-behavior)).

Two of the sampled talks (`7JbOagrwysE`, `D0-titxfVZo`) had `subtitles == {'live_chat': ...}` and nothing else. A naive `if info['subtitles']: use_manual_caption()` would pick a chat log over a perfectly good ASR transcript. **The presence check must be per-language, never "is the dict non-empty".**

## Formats, and why `json3` is the only correct choice

**[DOC]** YouTube serves 7 subtitle formats and yt-dlp passes all of them through untouched ([`_video.py`](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/youtube/_video.py)):

```python
_SUBTITLE_FORMATS = ('json3', 'srv1', 'srv2', 'srv3', 'ttml', 'srt', 'vtt')
```

yt-dlp never parses json3/srv\* — it rewrites the `timedtext` URL with `fmt=` and downloads the bytes. So the structure below is YouTube's, not yt-dlp's.

**[EMPIRICAL]** Shape of the ASR original for `X2vr81CJ934`:

```json
{
 "tStartMs": 3280,
 "dDurationMs": 5640,
 "wWinId": 1,
 "segs": [
  {"utf8": "So,"},
  {"utf8": " real-time", "tOffsetMs": 360},
  {"utf8": " audio",     "tOffsetMs": 880},
  {"utf8": " in",        "tOffsetMs": 1160},
  {"utf8": " Python.",   "tOffsetMs": 1280}
 ]
}
```

- `tStartMs` / `dDurationMs` — absolute integer milliseconds.
- `segs[].tOffsetMs` — **per-word offset relative to `tStartMs`**, integer milliseconds, omitted on the first segment (= 0).
- Observed seg keys across samples: `utf8`, `tOffsetMs`, `isSpeakerChange`, `acAsrConf` (ASR confidence — present on some tracks, absent on others; always `0` where present, so not usable as a signal).
- Events with `aAppend: 1` and `segs == [{"utf8": "\n"}]` are the rolling-window scroll markers. Roughly half of all events. Skip them.
- Event 0 is a caption-window definition with no `segs` and `dDurationMs` spanning the whole video. Skip it.
- Some events lack `dDurationMs` entirely — do not assume the key exists.

### The rolling-window duplication, measured

YouTube ASR captions scroll: two lines on screen, the top one being the previous cue. Formats disagree on how they express it.

**[EMPIRICAL]** For `X2vr81CJ934` (18-minute talk):

| Format | Text quality | Timing |
|---|---|---|
| `json3` | Clean. Concatenating `segs[].utf8` in order gives 16,035 chars of non-duplicated text. | Per-word, 1 ms |
| `srv3` | Clean (same append-marker model, `<s t="...">` children) | Per-word, 1 ms |
| `srv2` | Clean | Per-word, absolute ms |
| `vtt` | **2.99× inflated.** Naive cue concatenation gives 47,877 chars against json3's 16,035. Also 483 of 967 cues are sub-50 ms filler cues. | Per-word via inline `<00:00:03.640>` tags, but you must parse around the duplication |
| `srt` / `ttml` / `srv1` | No text duplication, but **cue time ranges overlap** — each cue's duration spans the whole time it stays visible in the 2-line window | Cue-level only |

**[EMPIRICAL]** In json3, 479 of 483 text-bearing cues overlap the next one. Cue boundaries are therefore *not* speech boundaries in any format. Only the word offsets are.

**[DOC]** yt-dlp has no fix for this. The tracking issue [#1734 "Fix YouTube's autogenerated subtitles"](https://github.com/yt-dlp/yt-dlp/issues/1734) has been open since 2021-11-21, labelled `PR-needed`. The only dedup code in the tree (`CueBlock.hinges()` in [`webvtt.py`](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/webvtt.py)) is used solely by the HLS downloader for live fragments and requires exact text equality, which the rolling window does not produce. **Do not plan on a postprocessor; parse `json3` directly.**

**[DOC]** `--sub-format` defaults to `best`, which resolves to `formats[-1]` — the last entry of `_SUBTITLE_FORMATS`, i.e. `vtt` ([`YoutubeDL.process_subtitles`](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/YoutubeDL.py)). The default is the worst option. Always pass `--sub-format json3` explicitly.

**[DOC]** `--convert-subs` is not an escape route: it only supports `ass, lrc, srt, vtt` ([README, Post-processing Options](https://github.com/yt-dlp/yt-dlp#post-processing-options)), needs ffmpeg, and `ass`/`lrc` quantize timestamps to 10 ms (`ass_subtitles_timecode` divides milliseconds by 10 in [`utils/_utils.py`](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/utils/_utils.py)). Its guard against converting JSON tests `ext == 'json'`, which does **not** match YouTube's `json3` — so ffmpeg would be invoked on a json3 file rather than refused.

## Timestamp precision for slide pairing

The pairing question: a slide transition is detected at time `T`; how accurately can the transcript be cut at `T`?

**[EMPIRICAL]** For 20,000 uniformly random instants `T` per video, distance to the nearest available timestamp:

| Video | Nearest **word** boundary (json3 ASR) | Nearest **cue** boundary |
|---|---|---|
| `X2vr81CJ934` (EN) | p50 113 ms · p90 444 ms · p99 1005 ms | p50 563 ms · p90 1169 ms · p99 1781 ms |
| `CaRFhW9rNXY` (pt-BR) | p50 96 ms · p90 332 ms · p99 555 ms | p50 603 ms · p90 1262 ms · p99 1873 ms |
| `7JbOagrwysE` (pt-BR, 63 min) | p50 131 ms · p90 449 ms · p99 956 ms | p50 764 ms · p90 1607 ms · p99 2342 ms |
| `C38xlWnkezQ` (pt-BR, ASR track) | p50 90 ms · p90 306 ms · p99 539 ms | p50 533 ms · p90 1097 ms · p99 1615 ms |
| `C38xlWnkezQ` (**human** track) | — (no word timings) | p50 697 ms · p90 1610 ms · p99 2641 ms |

Word-level is 5–8× tighter than cue-level. **p99 under ~1 second is far better than the pairing problem needs**, because the real error source is human, not technical: speakers routinely talk about the next slide before advancing it. That ambiguity is seconds wide and is [explicitly left open in the map](https://github.com/henricos/extract-slides/issues/1) ("Temporal precision required when pairing a slide with the speech said over it"). Caption timing is not the limiting factor.

**[EMPIRICAL]** Human caption tracks carry **no** word timings: `man_C38xlWnkezQ.pt-BR.json3` had 258 cues, 258 segs, **0** segs with `tOffsetMs`, and 0/257 overlapping cues. Clean, non-overlapping, but coarse — and its first cue is `"Transcriber: Maurício Kakuei Tanaka"`, i.e. human tracks carry non-speech metadata lines that must be filtered.

### Machine-translated tracks have fake word timings

**[EMPIRICAL]** This is worth knowing even though translated tracks are ruled out for other reasons. Counting multi-word events whose word offsets are perfectly uniformly spaced:

| Track | Multi-word events | Uniformly spaced |
|---|---|---|
| `hQVREBSYx7E` `en-orig` (ASR original) | 832 | **1** |
| `hQVREBSYx7E` `es` (translated) | 805 | **805** |
| `X2vr81CJ934` `en-orig` | 429 | **0** |

Translated tracks divide each event's duration evenly across its words. The `tOffsetMs` values are present and look real; they are interpolation. **Never take word timings from a translated track.**

## Track selection: the `-orig` handle

**[DOC]** yt-dlp splits YouTube's tracks on one line in [`_video.py`](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/youtube/_video.py):

```python
is_manual_subs = caption_track.get('kind') != 'asr'
```

Manual tracks go to `info['subtitles']`; the ASR track **and all its machine translations** go to `info['automatic_captions']`. The ASR track is additionally exposed under a `-orig` key:

```python
if lang_code == f'a-{orig_trans_code}':
    set_audio_lang_from_orig_subs_lang(orig_trans_code)
    # Add an "-orig" label to the original language so that it can be distinguished.
    # The subs are returned without "-orig" as well for compatibility
    process_language(
        automatic_captions, base_url, f'{trans_code}-orig',
        f'{trans_name} (Original)', client_name, pot_params)
```

Consequences, all confirmed empirically:

- **`<lang>-orig` is the only unambiguous handle on the ASR original.** **[EMPIRICAL]** For `X2vr81CJ934`, `automatic_captions['en']` and `automatic_captions['en-orig']` produced byte-equivalent content (16,035 chars each, 2,374 word offsets each).
- **The bare `<lang>` key is ambiguous.** For the spoken language it *is* the ASR original; for any other language it is a translation with `tlang=` on the URL. Asking for `en` on a pt-BR talk silently gets you a machine translation with interpolated timings.
- **[DOC]** `--sub-langs` entries are `re.fullmatch` patterns with `re.I`, not globs ([`orderedSet_from_options`](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/utils/_utils.py)). **[EMPIRICAL]** `--sub-langs "*-orig"` fails with `ERROR: Wrong regex for subtitlelangs: *-orig`; **`--sub-langs ".*-orig"` works** and resolves to exactly `pt-orig` / `en-orig`. This is the language-agnostic selector the CLI should use.
- **[DOC]** With `--write-subs --write-auto-subs` and a language present in both dicts, the **manual** track wins (`process_subtitles` fills `available_subs` from `normal_subtitles` first and only adds auto-caption langs `if lang not in available_subs`). Since manual tracks have no word timings, "prefer the human caption" costs you the per-word precision. Decide deliberately.
- **[DOC + EMPIRICAL]** `--extractor-args "youtube:skip=translated_subs"` does *not* prune the 156 ASR translations in 2026.07.04. Reading the source, `get_translated_subs` gates only translations *of manual tracks* (`if is_manual_subs and trans_code != 'und': if not get_translated_subs: continue`); ASR translations are added unconditionally. Measured: with the flag, `automatic_captions` still listed 157 keys. The flag is still worth passing (the source notes *"NB: Constructing the full subtitle dictionary is slow"*) but it is not a safety net — selecting `.*-orig` is what protects you.
- **[DOC]** A translated code derived from a *manual* track has the shape `<target>-<source>` (e.g. `ab-en`, `th-es-419`), so splitting such a code on `-` is ambiguous. This is why `--list-subs` on a video with manual captions shows `ab-en "Abkhazian from English"` while the ASR-only talks show bare codes.

## Reliability from a home-server IP

### PO tokens for subtitles: the gate exists, and it is partial

**[DOC]** Subtitles are a first-class PO-token context, not just media. The [yt-dlp PO Token Guide](https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide) lists three contexts — GVS, Player, and **Subs** — and the enforcement table currently marks only the `web` client as needing a Subs token. This matches the code: `PoTokenContext` is exactly `GVS / PLAYER / SUBS` ([`pot/provider.py`](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/youtube/pot/provider.py)).

**[DOC]** Enforcement is detected per video, via an experiment flag on the caption URL ([`_video.py`](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/youtube/_video.py), verified in the locally installed 2026.07.04):

```python
requires_pot = (
    # We can detect the experiment for now
    any(e in traverse_obj(qs, ('exp', ...)) for e in ('xpe', 'xpv'))
    or (pot_policy.required and not (pot_policy.not_required_for_premium and is_premium_subscriber)))
```

If a token is required and none is available, **yt-dlp discards the track** rather than failing loudly. The declared policy in 2026.07.04 is still `SubsPoTokenPolicy(required=False)` with the comment `# In rollout, currently detected via experiment` ([`_base.py`](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/youtube/_base.py)).

**[EMPIRICAL]** None of the 9 sampled talks were in the experiment — every ASR caption URL had **no `exp` parameter at all**:

```
7JbOagrwysE  exp=None  kind=['asr']  caps=['asr']  potc=None
X2vr81CJ934  exp=None  kind=['asr']  caps=['asr']  potc=None  variant=['gemini']
... (all 9 identical apart from variant)
```

**[DOC]** yt-dlp cannot mint PO tokens itself — [wiki, Extractors → YouTube](https://github.com/yt-dlp/yt-dlp/wiki/Extractors#youtube): *"Due to the nature of these tokens, yt-dlp cannot generate them and they must be provided externally."* Token minting needs a plugin (`bgutil-ytdlp-pot-provider`, `yt-dlp-getpot-wpc`), and the wiki notes tokens are now bound to the video ID with a lifespan possibly as short as 12 hours. Verified locally: `extractor/youtube/pot/_builtin/` contains only cache code, no generator.

**Planning consequence:** the caption branch works token-free today for ordinary talks, but there is a documented, expanding gate, and yt-dlp's escape hatch (`--extractor-args "youtube:po_token=CLIENT.subs+XXX"` plus a provider plugin) is the only route if it closes. Budget for that as a known future cost, not a current one.

### No cookies, no browser, no impersonation, no JS runtime needed

**[EMPIRICAL]** This machine has **no ffmpeg, no `curl_cffi`, and no Deno**. yt-dlp warned about all three and fetched every caption successfully:

```
WARNING: [youtube] No supported JavaScript runtime could be found. Only deno is enabled by default...
WARNING: The extractor specified to use impersonation for this download, but no impersonate target is available.
[download] Destination: cap_X2vr81CJ934.en-orig.json3
[download] 100% of  249.76KiB
```

**[DOC]** The impersonation warning is expected: every subtitle URL is flagged `'impersonate': True` in [`_video.py`](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/youtube/_video.py) (added 2025.07.21, [#13786](https://github.com/yt-dlp/yt-dlp/issues/13786)). It is a preference, not a hard requirement, today. Installing `curl_cffi` is cheap insurance.

**[EMPIRICAL]** yt-dlp 2026.07.04 served all captions via the `android_vr` client (`[youtube] X2vr81CJ934: Downloading android vr player API JSON`) — its JS-less default (`_DEFAULT_JSLESS_CLIENTS = ('android_vr',)`). Node 22 is present on the machine but yt-dlp does not auto-detect it; `--js-runtimes node` would be needed.

**[DOC]** Cookies should be avoided. Both projects warn independently:

- yt-dlp, [wiki → Exporting YouTube cookies](https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies): *"By using your account with yt-dlp, you run the risk of it being banned (temporarily or permanently)... consider using a throwaway account."* Same page: cookies are *"only necessary for content that requires an account to access"*, and OAuth/password login no longer work.
- `youtube-transcript-api` ([`_errors.py`](https://github.com/jdepoix/youtube-transcript-api/blob/master/youtube_transcript_api/_errors.py)): *"(NOT RECOMMENDED) ... YouTube will eventually permanently ban the account that you have used to authenticate with!"*

**[DOC]** Recovery from a hard block is not automatable. [yt-dlp FAQ on 429/402](https://github.com/yt-dlp/yt-dlp/wiki/FAQ#http-error-429-too-many-requests-or-402-payment-required): *"Just open a browser and solve a CAPTCHA the service suggests you and after that pass cookies to yt-dlp"* — and if the machine has multiple external IPs, `--source-address` must match the one that solved it. An unattended CLI cannot do this. **Protecting the IP is the whole reliability strategy.**

**[DOC]** On datacenter vs residential: yt-dlp's README and wiki contain **zero** occurrences of "residential", "datacenter", or "not a bot" — it takes no documented position. The cloud-IP claim comes from `youtube-transcript-api`'s README: *"YouTube has started blocking most IPs that are known to belong to cloud providers (like AWS, Google Cloud Platform, Azure, etc.)... Same can happen to the IP of your self-hosted solution, if you are doing too many requests."* A residential home-server IP is therefore the **good** case; rate discipline is what keeps it that way.

### Rate limits and the 429 on translated captions

**[DOC]** The only hard numbers YouTube-side are in the [yt-dlp wiki](https://github.com/yt-dlp/yt-dlp/wiki/Extractors#this-content-isnt-available-try-again-later): *"With the default yt-dlp settings, the rate limit for guest sessions is ~300 videos/hour (~1000 webpage/player requests per hour). For accounts, it is ~2000 videos/hour."* The wiki recommends *"a delay of around 5-10 seconds between downloads"* via `-t sleep`, which expands to `--sleep-subtitles 5 --sleep-requests 0.75 --sleep-interval 10 --max-sleep-interval 20` ([`options.py`](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/options.py)).

**[DOC]** The captions-specific 429 has a maintainer diagnosis. In [#13831](https://github.com/yt-dlp/yt-dlp/issues/13831) (open since 2025-07-24, 95 comments), bashonly's [pinned comment of 2026-01-06](https://github.com/yt-dlp/yt-dlp/issues/13831#issuecomment-3712613129):

> **Manual subtitles and original language automatic captions are not affected by this HTTP Error 429 issue.** Only subtitles/captions that have been **automatically translated into another language** are affected.
>
> there are 2 known ways of avoiding this HTTP Error 429: Pass fresh cookies... / Wait ~60 seconds after extraction and before downloading the auto subs, e.g. `--sleep-subtitles 60`

**[EMPIRICAL] Reproduced exactly.** From this IP, with no cookies:

| Test | Result |
|---|---|
| 30 sequential `.*-orig` fetches, no sleep, cycling the 9 talks | **30/30 succeeded**, ~100 s total (~3.3 s per video, metadata + caption) |
| 30 sequential `youtube-transcript-api` fetches over the same 9 videos | **30/30 succeeded**, 63 s total (~2.1 s per video) |
| 5 sequential fetches of `--sub-langs "es"` (translated) on `hQVREBSYx7E` | **4 of 5 returned `ERROR: Unable to download video subtitles for 'es': HTTP Error 429: Too Many Requests`**, exit code 1 |
| Same request with `--sleep-subtitles 60` | Succeeded |
| `.*-orig` immediately after the 429s | Succeeded |

The 429 is scoped to the translation endpoint and does not poison the original-language path. **Requesting only `.*-orig` removes the single most likely cause of failure**, at zero cost — the tool never needs a translation anyway.

**[DOC]** A separate rate-limit failure mode exists on the *extraction* side, with the error text *"This content isn't available, try again later"* ([`_video.py`](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/youtube/_video.py)), recoverable only by waiting up to an hour. Not observed here, but a single-video-per-invocation CLI is nowhere near the threshold.

### Failure signalling: exit code 0 means nothing

**[DOC]** `_write_subtitles` in [`YoutubeDL.py`](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/YoutubeDL.py) prints an informational line and returns normally when nothing matched:

```python
elif not subtitles:
    self.to_screen('[info] There are no subtitles for the requested languages')
    return ret
```

**[EMPIRICAL]** Confirmed on two caption-less videos:

```
[info] 3sB4Iv_tM7U: Downloading 1 format(s): 18
[info] There are no subtitles for the requested languages
exit=0
```

**A caption-less video and a successful caption fetch are indistinguishable by exit code.** The CLI must decide the STT fallback from the metadata (`--skip-download -J` and inspect `automatic_captions` / `subtitles`, or `--print "%(automatic_captions.keys)s"`) or from the presence of the output file — never from the exit status. A real download failure (including the 429) does set exit code 1.

**[DOC]** Other yt-dlp CLI codes: `1` on download/extraction error, `100` on failed self-update, `101` on `DownloadCancelled` ([`__init__.py`](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/__init__.py)). Nothing about exit codes is documented in the README — it is source-only.

### Caption URLs expire

**[EMPIRICAL]** The `timedtext` URL is signed and time-limited: `...&expire=1788934981&sparams=ip,ipbits,expire,v,ei,caps,opi,xoaf&signature=904FFF6E...`. Metadata and caption fetch must happen in the same run; a cached URL is not reusable, and per the [yt-dlp FAQ](https://github.com/yt-dlp/yt-dlp/wiki/FAQ) such URLs are bound to the extracting IP.

### Breakage cadence

**[DOC]** From yt-dlp's [Changelog](https://github.com/yt-dlp/yt-dlp/blob/master/Changelog.md), the last ~12 months produced **17 releases, every one carrying a `youtube` extractor-changes block**. Events that would have broken a container built and forgotten:

| Date | Change |
|---|---|
| 2025-09-23 | `[Force player 0004de42]` ([#14398](https://github.com/yt-dlp/yt-dlp/issues/14398)) — emergency player pin |
| 2025-10-14 | `[Detect experiment binding GVS PO Token to video id]` ([#14471](https://github.com/yt-dlp/yt-dlp/issues/14471)) — killed reusable tokens |
| 2025-11-12 | *"An external JavaScript runtime is now required for full YouTube support"* ([#15012](https://github.com/yt-dlp/yt-dlp/issues/15012)) — a **container-image requirement** |
| 2026-01-29 | Default clients adjusted ([#15601](https://github.com/yt-dlp/yt-dlp/issues/15601)); `tv_embedded` ([#15787](https://github.com/yt-dlp/yt-dlp/issues/15787)) and `ios_downgraded` ([#15786](https://github.com/yt-dlp/yt-dlp/issues/15786)) removed |
| 2026-06-09 | JS runtime floors tightened: `deno<2.3.0`, `node<22`, `bun<1.2.11` dropped ([#16788](https://github.com/yt-dlp/yt-dlp/issues/16788), [#16787](https://github.com/yt-dlp/yt-dlp/issues/16787), [#16786](https://github.com/yt-dlp/yt-dlp/issues/16786)) |
| 2026-08-19 | `[Remove android_vr from default clients]` ([#17461](https://github.com/yt-dlp/yt-dlp/issues/17461)), `visionos` client added ([#17184](https://github.com/yt-dlp/yt-dlp/issues/17184)) — reacting to [#17456](https://github.com/yt-dlp/yt-dlp/issues/17456), *"HTTP Error 403: Forbidden (with `android_vr`)"*, 120 comments in ~24 h |

**[EMPIRICAL]** The installed version here is **2026.07.04**; the latest release is **2026.08.19** (published 2026-08-19T23:48:43Z, via `gh api repos/yt-dlp/yt-dlp/releases/latest`). 2026.07.04 defaults to `android_vr` — the exact client dropped from defaults on 2026-08-19. Captions still worked from it today, but **the version on this machine is one release behind across a known-breaking change**.

**Planning consequence:** yt-dlp is not a pin-once dependency. Whatever packaging [issue #15](https://github.com/henricos/extract-slides/issues/15) settles on needs a story for upgrading yt-dlp roughly monthly, independently of the rest of the tool.

**[DOC]** `youtube-transcript-api` moves far slower: v1.2.4 released 2026-01-29, last master commit 2026-05-13. Against a dependency YouTube changes monthly, that lag is itself a risk — and its `PoTokenRequired` dead-end ([#592](https://github.com/jdepoix/youtube-transcript-api/issues/592)) has been open since 2026-04-25.

## yt-dlp vs youtube-transcript-api

**[DOC]** `youtube-transcript-api` fetches transcripts in three steps ([`_transcripts.py`](https://github.com/jdepoix/youtube-transcript-api/blob/master/youtube_transcript_api/_transcripts.py)): GET the watch page to scrape `INNERTUBE_API_KEY`, POST `youtubei/v1/player` as `clientName: "ANDROID", clientVersion: "20.10.38"`, then GET each track's `timedtext` `baseUrl` with `fmt=srv3` **stripped** — so it parses YouTube's default XML, which is cue-level. Its README warns: *"This code uses an undocumented part of the YouTube API... there is no guarantee that it won't stop working tomorrow."*

**[EMPIRICAL]** Measured against yt-dlp on the same videos:

| | yt-dlp 2026.07.04 | youtube-transcript-api 1.2.4 |
|---|---|---|
| Tracks listed for `X2vr81CJ934` | 157 (1 ASR + 156 translations) | **1** (`en`, `is_generated=True`, `is_translatable=True`) — much cleaner model |
| Data returned | Raw `json3` bytes | `FetchedTranscriptSnippet(text, start, duration)` |
| Per-word timings | **Yes**, via `json3` `tOffsetMs` | **No** — cue-level only |
| Overlapping cues | Yes (must be handled) | Yes — its own docstring: *"there can be overlaps between snippets!"* |
| Caption-less video | `[info] There are no subtitles...`, exit 0 | Raises `TranscriptsDisabled` — a **distinguishable** signal |
| 30-fetch burst from this IP | 30/30 OK, ~100 s | 30/30 OK, 63 s |
| PO-token path | `--extractor-args "youtube:po_token=CLIENT.subs+XXX"` + provider plugin | **None.** Hard-raises `PoTokenRequired` when it sees `&exp=xpe` — and it does not check `xpv`, which yt-dlp does |
| Cookies | Supported (discouraged) | **Broken/disabled** — README: *"this feature is currently not available"*; the `cookie_path` handling is commented out in [`_api.py`](https://github.com/jdepoix/youtube-transcript-api/blob/master/youtube_transcript_api/_api.py) |
| Proxies | `--proxy`, `--source-address` | `GenericProxyConfig`, `WebshareProxyConfig` (affiliate integration) |
| Thread safety | — | **Not thread-safe** — one instance per thread ([`_api.py`](https://github.com/jdepoix/youtube-transcript-api/blob/master/youtube_transcript_api/_api.py)) |

**Recommendation: yt-dlp only.** It is already a hard dependency for the video download, it is the only one of the two that yields per-word timings, it has a PO-token escape hatch, and it is maintained on YouTube's own cadence. `youtube-transcript-api` is nicer to call and faster, but no word timings makes it strictly worse for the one thing this project needs captions for. It stays worth knowing about as a second opinion when a yt-dlp release is mid-breakage — its `android` client path is independent of yt-dlp's client selection.

## pt-BR vs English quality

**[EMPIRICAL]** Direct comparison on `C38xlWnkezQ` (TEDxSãoPaulo, pt-BR), which has both a human-authored `pt-BR` track and an ASR `pt-orig` track. Text normalized (lowercased, accents and punctuation stripped), aligned with `difflib`, human track as reference:

```
human words 1979   auto words 2104
matching words 1838   substitutions 174   deletions 15   insertions 98
approx WER = 14.5%
substitution classes: colloquial-normalization 30, other 144  (of 174)
```

Sample disagreements:

```
H: ailton krenak  || A: aton krenc
H: ferrenhos      || A: ferrhos
H: bytes          || A: bites
H: 1997           || A: 97
H: pra            || A: para
H: ia             || A: inteligencia artificial
```

**Read the 14.5% as an upper bound.** The human TEDx track is an *edited* transcript: transcribers normalize `pra` → `para`, expand `IA` → `inteligência artificial`, and fix grammar. Those account for ~30 of the 174 substitutions and a large share of the 98 insertions. The residual real errors cluster in exactly two places: **proper nouns** (`Ailton Krenak` → `Aton Krenc`) and **technical/domain terms** (`bytes` → `bites`, and in another talk `list_geobr` → `list debr`).

**[EMPIRICAL]** Qualitatively, pt-BR output is fluent and correctly accented, with punctuation and natural discourse markers preserved:

> *"...algo que seja são, que faça sentido e que atendesse à necessidade que que nós tínhamos na época, eu criei o meu próprio flow baseado no git, tá? Então, eu peguei o o o Git Flow como base..."*

Note that disfluencies (`o o o`, `que que`) are transcribed verbatim, in both languages. Any downstream summarization step will want to clean them.

**[EMPIRICAL]** Volume is comparable across languages — 8,315 words / 44,513 chars for a 63-minute pt-BR talk, 2,858 words / 16,035 chars for an 18-minute English talk — with no sign of pt-BR being sparser or more heavily segmented. Cue and word-timing statistics for pt-BR sit in the same range as English (see [the precision table](#timestamp-precision-for-slide-pairing)); if anything the pt-BR tracks measured slightly tighter.

**[EMPIRICAL]** One English track (`X2vr81CJ934`) carried `variant=gemini` in its `timedtext` URL and, unlike the others, no `acAsrConf` field. The other 8 had no `variant` parameter. YouTube appears to be rolling out a new ASR backend selectively as of 2026-09-08; expect quality (and metadata shape) to be non-uniform across videos.

**Conclusion on the STT question:** pt-BR auto-captions are good enough to be the *default* transcript, not merely a preview. They are not good enough to be authoritative when proper nouns or API names matter. That argues for the structure the map already implies — caption by default, STT as the fallback for caption-less videos — plus a **flag to force STT** when the operator wants a better transcript on a talk full of domain jargon. It also means [issue #5](https://github.com/henricos/extract-slides/issues/5) (CPU-only STT) is still needed, but its priority is "handle the minority case and the quality opt-in", not "handle every video".

## Recommended invocation

```
yt-dlp --skip-download \
       --write-auto-subs --sub-langs ".*-orig" --sub-format json3 \
       --extractor-args "youtube:skip=translated_subs" \
       --sleep-requests 0.75 \
       -o "<outdir>/caption" \
       <URL>
```

Every element is load-bearing:

| Element | Why |
|---|---|
| `--sub-langs ".*-orig"` | The only unambiguous ASR-original selector; cannot be shadowed by a manual track; language-agnostic (works for EN and pt-BR without knowing which); avoids the translated tracks that cause the 429 |
| `--sub-format json3` | The only format with clean text *and* real per-word ms timings. The default resolves to `vtt` (~3× duplicated text) |
| `--write-auto-subs` without `--write-subs` | Deliberately prefers the ASR track for its word timings, and sidesteps the `live_chat`-in-`subtitles` trap |
| `--skip-download` | Caption fetch must not pull the video; the video download is a separate stage |
| `skip=translated_subs` | Skips building the (slow) manual-translation dictionary. Does *not* prune ASR translations in 2026.07.04 — belt, not braces |
| `--sleep-requests 0.75` | The wiki's own rate discipline. Cheap for a one-video-per-invocation CLI |

Parsing rules for the resulting `json3`:

1. Skip `events` without a `segs` key (window definitions).
2. Skip events whose `segs` are only `"\n"` (`aAppend: 1` scroll markers).
3. Absolute word time = `event.tStartMs + seg.tOffsetMs` (default `tOffsetMs` to 0).
4. Do **not** rely on `dDurationMs` — it is absent on some events and overlaps the next event on ~99% of ASR cues.
5. Concatenate `segs[].utf8` in order for clean text; leading spaces are already in the payload.
6. Expect `>>` speaker markers and `[applause]`-style non-speech tags in the text (3 and 4 occurrences respectively in one 18-minute English talk).

Deciding the STT fallback:

```
yt-dlp --skip-download -J --no-warnings <URL>
# -> inspect automatic_captions for a "<lang>-orig" key; fall back to STT if absent.
# Never infer this from the exit code: "no captions" exits 0.
```

## Things the map should account for

- **Caption is the primary transcript path, not a shortcut.** With 9/9 talks captioned, STT ([issue #5](https://github.com/henricos/extract-slides/issues/5)) becomes the minority path plus a quality opt-in, not the main engine.
- **The output contract ([issue #14](https://github.com/henricos/extract-slides/issues/14)) has two transcript fidelities to model**: word-level (ASR json3) and cue-level (human captions, or STT depending on model settings). A manifest that assumes word timings exist will break on human-captioned videos.
- **Auto beats human on timing.** "Prefer the manual caption when one exists" is the intuitive rule and the wrong one for this project.
- **yt-dlp needs its own upgrade cadence** (17 YouTube-touching releases in 12 months) — relevant to packaging ([issue #15](https://github.com/henricos/extract-slides/issues/15)).
- **The caption path is prerequisite-light** — no ffmpeg, no JS runtime, no `curl_cffi` needed today. The heavy container prerequisites (ffmpeg, a JS runtime for full format access) belong to the *video download* stage. If a "transcript only" mode is ever wanted, it can run on a much thinner image.
- **Re-verify availability on the real reference set** once [issue #4](https://github.com/henricos/extract-slides/issues/4) lands, and record the `exp=xpe|xpv` count as the PO-token exposure baseline.

## Sources

**yt-dlp**
- README: [Subtitle Options](https://github.com/yt-dlp/yt-dlp#subtitle-options) · [Verbosity and Simulation](https://github.com/yt-dlp/yt-dlp#verbosity-and-simulation-options) · [Post-processing](https://github.com/yt-dlp/yt-dlp#post-processing-options) · [Workarounds](https://github.com/yt-dlp/yt-dlp#workarounds) · [Extractor Arguments](https://github.com/yt-dlp/yt-dlp#extractor-arguments) · [Differences in default behavior](https://github.com/yt-dlp/yt-dlp#differences-in-default-behavior) · [Impersonation](https://github.com/yt-dlp/yt-dlp#impersonation)
- Wiki: [PO Token Guide](https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide) · [Extractors → YouTube](https://github.com/yt-dlp/yt-dlp/wiki/Extractors#youtube) · [Exporting YouTube cookies](https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies) · ["This content isn't available, try again later"](https://github.com/yt-dlp/yt-dlp/wiki/Extractors#this-content-isnt-available-try-again-later) · [FAQ — HTTP 429](https://github.com/yt-dlp/yt-dlp/wiki/FAQ#http-error-429-too-many-requests-or-402-payment-required) · [EJS / JS runtimes](https://github.com/yt-dlp/yt-dlp/wiki/EJS)
- Source: [`extractor/youtube/_video.py`](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/youtube/_video.py) · [`extractor/youtube/_base.py`](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/youtube/_base.py) · [`extractor/youtube/pot/provider.py`](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/youtube/pot/provider.py) · [`YoutubeDL.py`](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/YoutubeDL.py) · [`options.py`](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/options.py) · [`utils/_utils.py`](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/utils/_utils.py) · [`webvtt.py`](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/webvtt.py) · [`postprocessor/ffmpeg.py`](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/postprocessor/ffmpeg.py) · [`__init__.py`](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/__init__.py) · [Changelog](https://github.com/yt-dlp/yt-dlp/blob/master/Changelog.md)
- Issues: [#1734](https://github.com/yt-dlp/yt-dlp/issues/1734) (auto-sub duplication, open since 2021) · [#13831](https://github.com/yt-dlp/yt-dlp/issues/13831) (429 on translated subs) · [#13786](https://github.com/yt-dlp/yt-dlp/issues/13786) (impersonation for subtitles) · [#13654](https://github.com/yt-dlp/yt-dlp/issues/13654) (`xosf` position data) · [#14471](https://github.com/yt-dlp/yt-dlp/issues/14471) (PO token bound to video id) · [#15012](https://github.com/yt-dlp/yt-dlp/issues/15012) (JS runtime required) · [#17456](https://github.com/yt-dlp/yt-dlp/issues/17456) / [#17461](https://github.com/yt-dlp/yt-dlp/issues/17461) (`android_vr` 403, removed from defaults) · [#4090](https://github.com/yt-dlp/yt-dlp/issues/4090) (`skip=translated_subs`) · [#14889](https://github.com/yt-dlp/yt-dlp/issues/14889) (`-orig` for languages outside `translationLanguages`)

**youtube-transcript-api**
- [README](https://github.com/jdepoix/youtube-transcript-api#readme) · [`_transcripts.py`](https://github.com/jdepoix/youtube-transcript-api/blob/master/youtube_transcript_api/_transcripts.py) · [`_api.py`](https://github.com/jdepoix/youtube-transcript-api/blob/master/youtube_transcript_api/_api.py) · [`_errors.py`](https://github.com/jdepoix/youtube-transcript-api/blob/master/youtube_transcript_api/_errors.py) · [`proxies.py`](https://github.com/jdepoix/youtube-transcript-api/blob/master/youtube_transcript_api/proxies.py)
- Issues: [#592](https://github.com/jdepoix/youtube-transcript-api/issues/592) (`PoTokenRequired`, no workaround) · [#612](https://github.com/jdepoix/youtube-transcript-api/issues/612) / [#614](https://github.com/jdepoix/youtube-transcript-api/issues/614) (429 retry never rotates IP)

**YouTube**
- Live `https://www.youtube.com/api/timedtext` responses in all 7 formats for the video IDs listed under [Method](#method-and-honesty-about-scope), fetched 2026-09-08. YouTube publishes no documentation for this endpoint; its shape is only observable, which is itself a reason to treat the whole branch as revisitable.
