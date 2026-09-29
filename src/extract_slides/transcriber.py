"""The transcript: captions parsed, guarded, and normalised into one shape.

Stage 2. The caption is the primary path, not an optimisation: a ready caption
existed on 9 of 9 sampled talks (ADR 0007). Local speech-to-text is the
fall-through when no caption survives, and it belongs to #32.

**The parser is the hard part.** A `json3` track is YouTube's own format and
carries quirks every reader has to survive (`docs/research/youtube-captions.md`):

- event 0 is a caption *window* spanning the whole video, with no text;
- roughly half the events of an ASR track are rolling-window scroll markers,
  whose only text is a newline;
- some events carry no duration at all;
- human tracks open with non-speech metadata — "Transcriber: …".

**The media's duration is the authority on time.** A caption whose last cue
ends more than `CAPTION_OVERRUN_TOLERANCE_SECONDS` past the end of the video is
rejected, however it was made: the measured case is a *manual* caption 676 s
long on a 300 s talk, carrying the next speaker from 293 s on.

**`transcript.json` is one shape across the three origins** (ADR 0009): cues,
each with its words where the origin has them. Word timings are the one loss
the contract cannot undo, so they are kept even though nothing reads them yet.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from extract_slides import constants
from extract_slides.acquirer import captions_in
from extract_slides.manifest import (
    TRANSCRIPT_JSON_FILENAME,
    TRANSCRIPT_MD_FILENAME,
    TranscriptFidelity,
    TranscriptOrigin,
)


@dataclass(frozen=True)
class Word:
    start: float
    #: Where the origin states only onsets — a `json3` ASR track — a word ends
    #: where the next one starts, and the last where its cue does.
    end: float
    text: str

    def as_json(self) -> dict[str, Any]:
        return {"start": self.start, "end": self.end, "text": self.text}


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    text: str
    #: Empty on an origin that carries only cue timings, such as a human caption.
    words: tuple[Word, ...] = ()

    def as_json(self) -> dict[str, Any]:
        return {
            "start": self.start,
            "end": self.end,
            "text": self.text,
            "words": [word.as_json() for word in self.words],
        }


@dataclass(frozen=True)
class Transcript:
    origin: TranscriptOrigin
    fidelity: TranscriptFidelity
    duration: float
    #: The raw file the cues were read from, kept beside the transcript.
    source: str
    cues: tuple[Cue, ...] = field(default_factory=tuple)

    def as_json(self) -> dict[str, Any]:
        return {
            "origin": self.origin.value,
            "fidelity": self.fidelity.value,
            "duration": self.duration,
            "source": self.source,
            "cues": [cue.as_json() for cue in self.cues],
        }


def _seconds(milliseconds: float) -> float:
    return milliseconds / 1000


#: The credit lines a human track opens with, in the languages the reference
#: set carries: "Transcriber: …", "Revisor: …". Matched only at the start of a
#: track, because further in, a line that happens to begin "Reviewer:" is speech.
CREDIT = re.compile(
    r"^\s*(transcri(ber|ption|ptor|ção|tor|tora)|translat(or|ion)|review(er)?"
    r"|tradu(tor|tora|ção|ctor|ctora)|revis(or|ora|ão))\s*:",
    re.IGNORECASE,
)


def parse_json3(raw: str, *, human: bool = False) -> list[Cue]:
    """Every cue a `json3` track carries speech in, in order."""
    events = json.loads(raw).get("events") or []
    spoken: list[tuple[int, int | None, list[tuple[int, str]], str]] = []
    for event in events:
        segs = event.get("segs")
        if not segs:
            continue  # the whole-video window, among others
        start_ms = int(event.get("tStartMs", 0))
        parts = [(start_ms + int(seg.get("tOffsetMs", 0)), str(seg.get("utf8", ""))) for seg in segs]
        text = " ".join("".join(part for _, part in parts).split())
        if not text:
            continue  # a scroll marker: its only text is a newline
        duration = event.get("dDurationMs")
        spoken.append((start_ms, None if duration is None else int(duration), parts, text))

    if human:
        while spoken and CREDIT.match(spoken[0][3]):
            spoken.pop(0)

    # Word timing is a property of the track, not of the event: YouTube omits
    # the first word's offset, so a one-word ASR cue carries none at all and
    # would otherwise lose its word.
    timed = any(
        "tOffsetMs" in seg for event in events for seg in event.get("segs") or ()
    )
    cues: list[Cue] = []
    for index, (start_ms, duration, parts, text) in enumerate(spoken):
        if duration is not None:
            end_ms = start_ms + duration
        elif index + 1 < len(spoken):
            end_ms = spoken[index + 1][0]
        else:
            end_ms = max(onset for onset, _ in parts)
        end = _seconds(max(end_ms, start_ms))
        words = _words(parts, end) if timed else ()
        cues.append(Cue(start=_seconds(start_ms), end=end, text=text, words=words))
    return cues


def _words(parts: list[tuple[int, str]], cue_end: float) -> tuple[Word, ...]:
    spoken = [(onset, part.strip()) for onset, part in parts if part.strip()]
    words = []
    for index, (onset, text) in enumerate(spoken):
        end = _seconds(spoken[index + 1][0]) if index + 1 < len(spoken) else cue_end
        words.append(Word(start=_seconds(onset), end=end, text=text))
    return tuple(words)


class NoUsableCaption(Exception):
    """Every caption acquire left was rejected, or there was none.

    The fall-through is local speech-to-text, which is not in this build.
    """


def overrun(cues: list[Cue], duration: float) -> float | None:
    """Where the caption's last cue ends, if that is past what the video allows."""
    last = max((cue.end for cue in cues), default=0.0)
    return last if last > duration + constants.CAPTION_OVERRUN_TOLERANCE_SECONDS else None


def transcribe(directory: Path, *, duration: float, log: Any) -> Transcript:
    """Stage 2 from the captions acquire left, tried in order: human, then ASR.

    A caption that fails a guard is reported and the next one is tried, so
    a human caption carrying another talk still leaves the ASR one standing.
    """
    # An earlier transcript must not outlive a run that could not replace it:
    # it would describe captions that are no longer the ones on disk.
    for earlier in (TRANSCRIPT_JSON_FILENAME, TRANSCRIPT_MD_FILENAME):
        (directory / earlier).unlink(missing_ok=True)
    captions = captions_in(directory)
    if not captions:
        log.note("No caption to read.")
    for path in captions:
        human = path.name.startswith("caption.human.")
        cues = parse_json3(path.read_text(encoding="utf-8"), human=human)
        if not cues:
            log.note(f"Rejected {path.name}: it carries no speech.")
            continue
        ends_at = overrun(cues, duration)
        if ends_at is not None:
            log.note(
                f"Rejected {path.name}: its last cue ends at {ends_at:.1f} s, "
                f"past the video's {duration:.1f} s.",
                "A caption that runs on past its video carries another talk's speech.",
            )
            continue
        timed = any(cue.words for cue in cues)
        transcript = Transcript(
            origin=TranscriptOrigin.human_caption if human else TranscriptOrigin.asr_caption,
            fidelity=TranscriptFidelity.word if timed else TranscriptFidelity.cue,
            duration=duration,
            source=path.name,
            cues=tuple(cues),
        )
        write(transcript, directory)
        return transcript
    raise NoUsableCaption()


def write(transcript: Transcript, directory: Path) -> None:
    (directory / TRANSCRIPT_JSON_FILENAME).write_text(
        json.dumps(transcript.as_json(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (directory / TRANSCRIPT_MD_FILENAME).write_text(prose(transcript), encoding="utf-8")


#: A paragraph closes at the first sentence end past this many words, or at
#: twice this many whatever the punctuation: an ASR caption has almost none.
#: A reading convenience, not a measured value, so it is not in `constants`.
PARAGRAPH_WORDS = 120
SENTENCE_END = (".", "?", "!", "…")


def prose(transcript: Transcript) -> str:
    """The talk as text: paragraphs, no timestamps, every cue in order."""
    paragraphs: list[str] = []
    current: list[str] = []
    words = 0
    for cue in transcript.cues:
        current.append(cue.text)
        words += len(cue.text.split())
        sentence_ends = cue.text.endswith(SENTENCE_END)
        if (words >= PARAGRAPH_WORDS and sentence_ends) or words >= 2 * PARAGRAPH_WORDS:
            paragraphs.append(" ".join(current))
            current, words = [], 0
    if current:
        paragraphs.append(" ".join(current))
    return "\n\n".join(paragraphs) + "\n"
