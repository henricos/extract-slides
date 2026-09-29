"""Build YouTube `json3` caption files by hand, quirks included.

The shape is YouTube's, not `yt-dlp`'s — `yt-dlp` rewrites the timedtext URL
and saves the bytes — and `docs/research/youtube-captions.md` records it. The
builders emit each quirk the parser has to survive as a separate event kind,
so a test states which one it is exercising rather than hiding it in a blob.
"""

from __future__ import annotations

import json
from collections.abc import Sequence


def window(duration_ms: int) -> dict:
    """Event 0 of a real track: a caption window spanning the whole video, no text."""
    return {"tStartMs": 0, "dDurationMs": duration_ms, "id": 1, "wpWinPosId": 1, "wsWinStyleId": 1}


def spoken(start_ms: int, duration_ms: int | None, words: Sequence[tuple[int, str]]) -> dict:
    """An ASR event: each word carries its offset from the event's start.

    The first word's offset is omitted, as YouTube omits it. `duration_ms=None`
    leaves out `dDurationMs`, which some real events do.
    """
    segs = []
    for index, (offset, text) in enumerate(words):
        seg: dict = {"utf8": text if index == 0 else f" {text}", "acAsrConf": 0}
        if index:
            seg["tOffsetMs"] = offset
        segs.append(seg)
    event: dict = {"tStartMs": start_ms, "wWinId": 1, "segs": segs}
    if duration_ms is not None:
        event["dDurationMs"] = duration_ms
    return event


def scroll(start_ms: int) -> dict:
    """A rolling-window scroll marker. Roughly half of a real ASR track."""
    return {"tStartMs": start_ms, "dDurationMs": 10, "wWinId": 1, "aAppend": 1, "segs": [{"utf8": "\n"}]}


def line(start_ms: int, duration_ms: int, text: str) -> dict:
    """A human caption event: one segment, no word offsets."""
    return {"tStartMs": start_ms, "dDurationMs": duration_ms, "segs": [{"utf8": text}]}


def track(*events: dict) -> str:
    return json.dumps({"wireMagic": "pb3", "events": list(events)})


def asr_track(duration_s: float, cues: Sequence[tuple[float, float, str]]) -> str:
    """A plausible ASR track: a window event, then each cue with a scroll marker after it.

    Words in a cue are spread evenly across it, a tenth of a second apart at
    least, which is all a test that is not about word timing needs.
    """
    events = [window(int(duration_s * 1000))]
    for start, end, text in cues:
        start_ms, end_ms = int(start * 1000), int(end * 1000)
        words = text.split()
        step = max(100, (end_ms - start_ms) // max(1, len(words)))
        events.append(spoken(start_ms, end_ms - start_ms, [(i * step, w) for i, w in enumerate(words)]))
        events.append(scroll(end_ms - 5))
    return track(*events)


def human_track(cues: Sequence[tuple[float, float, str]]) -> str:
    return track(*(line(int(s * 1000), int((e - s) * 1000), text) for s, e, text in cues))
