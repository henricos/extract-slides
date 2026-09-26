"""The output directory: what is in it, and the table of instants describing it.

This module is the only place that knows the on-disk contract. ADR 0009 fixes
what the contract carries; the key names below are the part it left to the
implementation.

**`manifest.json` describes what is in `slides/` now, and nothing else.** It is
a current-state table, not a history: nothing deleted leaves a trace in it.

**A slide row stores an instant, not an interval.** Slide `i` is on screen for
`[change_at[i], change_at[i+1])` and the last runs to the media's duration, so
the intervals **tile the media** and are **derived at read time, never stored**.
One date per row cannot contradict itself, which is what makes deleting slide 7
nothing more than deleting the line.

The first interval opens at **zero** rather than at the first row's instant.
Pass 1 always emits the first frame, so on a manifest nobody has edited the two
are the same number; after a `drop` of the opening slide they are not, and
opening at zero is what keeps the tiling — and with it ADR 0009's promise that
there is no unassigned-cue bucket to diagnose.

**The run header carries the provenance, per run and never per slide.** It also
carries what each stage finished, which is the state `extract-slides` resumes
from: ADR 0002 puts that state inside the output directory rather than in a
global run index, and this file is the output directory's record of itself.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from extract_slides import constants

#: The directory's fixed furniture. ADR 0002 fixes the layout; these are its
#: spellings, and every other module reaches them through this one.
MANIFEST_FILENAME = "manifest.json"
SLIDES_DIRNAME = "slides"
SLIDE_SUFFIX = ".jpg"

#: Bumped when a field changes meaning rather than when one is added. A reader
#: that finds a number it does not know stops rather than guessing, because the
#: alternative is describing a directory it cannot actually read.
SCHEMA_VERSION = 1

#: Two instants closer together than this are the same instant. Timestamps come
#: off a media clock and go through JSON, so exact comparison is the wrong test
#: for "strictly increasing" and for the bounds of a normalised rectangle.
EPSILON = 1e-9


class ManifestError(Exception):
    """The manifest on disk is not one this tool can act on.

    Always the operator's problem to see, never a traceback: either the file is
    from a version that spells things differently, or it was edited by hand into
    a state that would make the tool lose something.
    """


class CaptureReason(str, Enum):
    """Why pass 1 took a capture. ADR 0005's closed set.

    A field rather than a footnote because **half the captures are not slide
    changes**: a `dwell` capture's instant is the moment the screen became that
    state, while a `watchdog` capture is the frame in the middle of continuous
    churn and corresponds to no transition at all.
    """

    first = "first"
    dwell = "dwell"
    watchdog = "watchdog"
    eof = "eof"


class RectRule(str, Enum):
    """How a slide's rectangle was arrived at. ADR 0006's closed set."""

    activity = "activity"
    full = "full"


class TranscriptOrigin(str, Enum):
    """Which of the three producers wrote the transcript. ADR 0009."""

    asr_caption = "asr-caption"
    human_caption = "human-caption"
    stt = "stt"


class TranscriptFidelity(str, Enum):
    """Whether the origin carried word timings or only cue timings."""

    word = "word"
    cue = "cue"


@dataclass(frozen=True)
class Rect:
    """A normalised rectangle: fractions of the frame, not pixels.

    Normalised because the crop is derived at ADR 0005's analysis width and
    applied to the full-resolution frame, and a manifest read months later
    should not need the decoder to say what it means.
    """

    x: float
    y: float
    width: float
    height: float

    @classmethod
    def full(cls) -> Rect:
        """The whole frame: what every stage that declines to cut returns."""
        return cls(0.0, 0.0, 1.0, 1.0)

    def validated(self) -> Rect:
        if self.width <= 0 or self.height <= 0:
            raise ManifestError(f"a rectangle has no area: {self.as_json()}")
        if self.x < -EPSILON or self.y < -EPSILON:
            raise ManifestError(f"a rectangle starts outside the frame: {self.as_json()}")
        if self.x + self.width > 1 + EPSILON or self.y + self.height > 1 + EPSILON:
            raise ManifestError(f"a rectangle runs past the frame: {self.as_json()}")
        return self

    def as_json(self) -> list[float]:
        """Four floats, in the order `--roi` takes them."""
        return [self.x, self.y, self.width, self.height]

    @classmethod
    def from_json(cls, value: Any) -> Rect:
        if not isinstance(value, list) or len(value) != 4:
            raise ManifestError(f"a rectangle is four numbers, not {value!r}")
        try:
            return cls(*(float(number) for number in value))
        except (TypeError, ValueError) as error:
            raise ManifestError(f"a rectangle is four numbers, not {value!r}") from error


@dataclass(frozen=True)
class Slide:
    """One row of the current-state table.

    `change_at` is the capture's own timestamp on the media clock, and it is the
    slide's identity: numbers renumber on every `drop`, the instant does not.
    There is no invented id.
    """

    file: str
    change_at: float
    reason: CaptureReason
    rect: Rect
    rect_rule: RectRule
    #: The layout cluster the rectangle was computed for, and `null` on a row
    #: pass 1 wrote, because before the crop has clustered anything there is no
    #: cluster to name and a zero would claim one.
    layout: int | None = None

    def as_json(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "change_at": self.change_at,
            "reason": self.reason.value,
            "rect": self.rect.as_json(),
            "rect_rule": self.rect_rule.value,
            "layout": self.layout,
        }

    @classmethod
    def from_json(cls, value: Any) -> Slide:
        if not isinstance(value, dict):
            raise ManifestError(f"a slide row is an object, not {value!r}")
        try:
            return cls(
                file=str(value["file"]),
                change_at=float(value["change_at"]),
                reason=_member(CaptureReason, value["reason"], "capture reason"),
                rect=Rect.from_json(value["rect"]),
                rect_rule=_member(RectRule, value["rect_rule"], "rectangle rule"),
                layout=None if value.get("layout") is None else int(value["layout"]),
            )
        except KeyError as error:
            raise ManifestError(f"a slide row has no {error.args[0]}") from error
        except (TypeError, ValueError) as error:
            raise ManifestError(f"a slide row is malformed: {error}") from error


@dataclass(frozen=True)
class StageRecord:
    """What a finished stage left behind, as the next run needs to read it.

    `gist` is the words the reuse line says — "YouTube caption", "216 captures".
    It is stored rather than recomputed because ADR 0002 requires every reused
    stage to announce itself, and a stage that is being skipped is precisely one
    that is not available to describe its own work.
    """

    gist: str
    completed_at: str

    def as_json(self) -> dict[str, Any]:
        return {"gist": self.gist, "completed_at": self.completed_at}

    @classmethod
    def from_json(cls, value: Any) -> StageRecord:
        if not isinstance(value, dict):
            raise ManifestError(f"a stage record is an object, not {value!r}")
        return cls(
            gist=str(value.get("gist", "")),
            completed_at=str(value.get("completed_at", "")),
        )


def detection_parameters() -> dict[str, float]:
    """The pass 1 constants, as the run header records them.

    ADR 0009 requires the detection parameters in the header so that an output
    directory read months later can say how it was produced. They are read off
    `constants` rather than restated, so a manifest never claims a value the run
    did not use.
    """
    return {
        "sample_rate_per_second": constants.SAMPLE_RATE_PER_SECOND,
        "analysis_width_px": constants.ANALYSIS_WIDTH_PX,
        "edge_difference_trigger": constants.EDGE_DIFFERENCE_TRIGGER,
        "anchor_dwell_seconds": constants.ANCHOR_DWELL_SECONDS,
        "watchdog_seconds": constants.WATCHDOG_SECONDS,
        "phash_bits": constants.PHASH_BITS,
        "duplicate_threshold": constants.DUPLICATE_THRESHOLD,
    }


@dataclass
class RunHeader:
    """Provenance, per run and never per slide.

    Everything here answers "how was this directory produced", which is the
    question an operator has months later and the one a re-run has to answer
    before it decides what to recompute.
    """

    tool_version: str
    duration: float
    video_id: str | None = None
    url: str | None = None
    transcript_origin: TranscriptOrigin | None = None
    transcript_fidelity: TranscriptFidelity | None = None
    #: The speech-to-text model, where one ran. Absent on a caption run, which
    #: is the common path.
    stt_model: str | None = None
    #: Whether the crop ran — not whether it cut. A crop that declined and a
    #: crop that never happened leave the same pixels and are not the same fact.
    cropped: bool | None = None
    detection: dict[str, float] = field(default_factory=detection_parameters)
    #: Stage name -> what it finished. Names are left as strings here because
    #: the manifest is JSON and the pipeline owns the vocabulary; a stage this
    #: build does not know is carried through rather than rejected.
    stages: dict[str, StageRecord] = field(default_factory=dict)

    def as_json(self) -> dict[str, Any]:
        return {
            "tool_version": self.tool_version,
            "video_id": self.video_id,
            "url": self.url,
            "duration": self.duration,
            "transcript_origin": _value(self.transcript_origin),
            "transcript_fidelity": _value(self.transcript_fidelity),
            "stt_model": self.stt_model,
            "cropped": self.cropped,
            "detection": dict(self.detection),
            "stages": {name: record.as_json() for name, record in self.stages.items()},
        }

    @classmethod
    def from_json(cls, value: Any) -> RunHeader:
        if not isinstance(value, dict):
            raise ManifestError("the run header is missing")
        stages = value.get("stages") or {}
        if not isinstance(stages, dict):
            raise ManifestError("the run header's stages are not an object")
        try:
            duration = float(value["duration"])
        except KeyError as error:
            raise ManifestError("the run header has no duration") from error
        except (TypeError, ValueError) as error:
            raise ManifestError(f"the run header's duration is malformed: {error}") from error
        return cls(
            tool_version=str(value.get("tool_version", "")),
            duration=duration,
            video_id=_optional_str(value.get("video_id")),
            url=_optional_str(value.get("url")),
            transcript_origin=_optional_member(
                TranscriptOrigin, value.get("transcript_origin"), "transcript origin"
            ),
            transcript_fidelity=_optional_member(
                TranscriptFidelity, value.get("transcript_fidelity"), "transcript fidelity"
            ),
            stt_model=_optional_str(value.get("stt_model")),
            cropped=None if value.get("cropped") is None else bool(value["cropped"]),
            detection=dict(value.get("detection") or {}),
            stages={name: StageRecord.from_json(record) for name, record in stages.items()},
        )


@dataclass
class Manifest:
    """The whole document: a run header and the table of what is in `slides/`."""

    run: RunHeader
    slides: list[Slide] = field(default_factory=list)

    # --- the contract on disk ---------------------------------------------

    @staticmethod
    def path_in(directory: Path) -> Path:
        return directory / MANIFEST_FILENAME

    @classmethod
    def read(cls, directory: Path) -> Manifest:
        path = cls.path_in(directory)
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise ManifestError(f"{path} does not exist") from error
        except json.JSONDecodeError as error:
            raise ManifestError(f"{path} is not readable JSON: {error}") from error
        return cls.from_json(document).validated()

    def write(self, directory: Path) -> Path:
        path = self.path_in(directory)
        directory.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.validated().as_json(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return path

    def as_json(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "run": self.run.as_json(),
            "slides": [slide.as_json() for slide in self.slides],
        }

    @classmethod
    def from_json(cls, document: Any) -> Manifest:
        if not isinstance(document, dict):
            raise ManifestError("a manifest is an object")
        version = document.get("schema_version")
        if version != SCHEMA_VERSION:
            raise ManifestError(
                f"this build reads manifest schema {SCHEMA_VERSION}, not {version!r}"
            )
        slides = document.get("slides")
        if slides is None:
            slides = []
        if not isinstance(slides, list):
            raise ManifestError("slides is a list of rows")
        return cls(
            run=RunHeader.from_json(document.get("run")),
            slides=[Slide.from_json(row) for row in slides],
        )

    def validated(self) -> Manifest:
        """Every rule the rest of the tool is then allowed to assume.

        A manifest that breaks one of these describes a directory the tool
        would silently mis-read — speech attributed to the wrong slide, a
        rectangle applied past the edge of a frame — so it stops here instead.
        """
        if self.run.duration <= 0:
            raise ManifestError("the media's duration is the authority on time and must be positive")
        previous: float | None = None
        seen: set[str] = set()
        for slide in self.slides:
            if not slide.file:
                raise ManifestError("a slide row has no file")
            if slide.file in seen:
                raise ManifestError(f"{slide.file} appears twice; a file has one row")
            seen.add(slide.file)
            if slide.change_at < -EPSILON:
                raise ManifestError(f"{slide.file} is stamped before the media begins")
            if slide.change_at >= self.run.duration:
                raise ManifestError(
                    f"{slide.file} is stamped at or past the media's duration, "
                    "which would give it no interval"
                )
            if previous is not None and slide.change_at <= previous + EPSILON:
                raise ManifestError(
                    f"{slide.file} does not come after the row before it; "
                    "instants are strictly increasing"
                )
            previous = slide.change_at
            slide.rect.validated()
        return self

    # --- what is derived rather than stored --------------------------------

    def intervals(self) -> list[tuple[float, float]]:
        """The span each slide is on screen for, derived and never stored.

        The first opens at zero and the last runs to the media's duration, so
        the result **tiles the media**: no gap, no overlap, and no cue that
        lands nowhere.
        """
        if not self.slides:
            return []
        boundaries = [slide.change_at for slide in self.slides[1:]]
        starts = [0.0, *boundaries]
        ends = [*boundaries, self.run.duration]
        return list(zip(starts, ends, strict=True))

    # --- what each stage left behind ---------------------------------------

    def completed_stages(self) -> dict[str, str]:
        """Stage name -> the gist of the work a re-run would be reusing."""
        return {name: record.gist for name, record in self.run.stages.items()}

    def record_stage(self, name: str, gist: str) -> None:
        """Mark a stage finished. This is the state a later run resumes from."""
        self.run.stages[name] = StageRecord(gist=gist, completed_at=_now())


def slide_number_width(count: int) -> int:
    """Fixed width, floored at three digits, widening only past 999.

    Not the adaptive width that rewrites every filename when the count crosses
    a power of ten: at the measured 4.7 images per minute the floor covers any
    talk under about three and a half hours.
    """
    return max(constants.SLIDE_NUMBER_MIN_DIGITS, len(str(max(count, 1))))


def slide_filename(number: int, *, of: int) -> str:
    """`001.jpg`. `number` is one-based; `of` is how many slides there are."""
    if number < 1:
        raise ValueError("slide numbers start at one")
    return f"{number:0{slide_number_width(of)}d}{SLIDE_SUFFIX}"


def slides_directory(directory: Path) -> Path:
    return directory / SLIDES_DIRNAME


def _now() -> str:
    """UTC, to the second. Provenance, never a clock the tool reasons with."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _value(member: Enum | None) -> str | None:
    return None if member is None else str(member.value)


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _member(enum: type[Enum], value: Any, what: str) -> Any:
    try:
        return enum(value)
    except ValueError as error:
        allowed = ", ".join(str(member.value) for member in enum)
        raise ManifestError(f"{value!r} is not a {what}; expected one of {allowed}") from error


def _optional_member(enum: type[Enum], value: Any, what: str) -> Any:
    return None if value is None else _member(enum, value, what)
