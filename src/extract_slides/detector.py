"""Pass 1: one capture for every state the screen settled into.

The detector consumes `(instant, frame)` pairs and **never opens a video**:
that is the sampler's job, and the split is the seam the suite tests at (#24).
Everything here is ADR 0005, and nothing else is:

- **The signal is the edge difference.** Auto-Canny with thresholds taken from
  each frame's own luma median, both edge maps dilated, and the fraction of
  pixels whose edge state differs. It sits at exactly zero on a static frame,
  the per-frame thresholds make it immune to a projector's gain ramp, and the
  dilation absorbs the pixel or two a filmed screen wobbles by.
- **Every sample is compared against a held anchor**, never against the sample
  before it, so a change too slow for any two neighbours to differ still fires.
  When one differs, the anchor is emitted if it had held for the dwell, and the
  anchor advances.
- **The first frame is always emitted, and the pending anchor is flushed at the
  end**, or every talk loses its opening and its closing slide.
- **The watchdog** emits the current frame when a whole interval passes with
  nothing emitted while the anchor keeps advancing. It is the load-bearing rule:
  under a pinned anchor a trigger-happy signal produces silence, not surplus,
  and on a camera filming a screen in a dark auditorium it supplied 20 of 22
  captures.
- **A near-identical capture is dropped against every capture already kept**,
  not only the last, which is what absorbs a camera cutting away and back.

There is no region, no mask, no exclusion list and no minimum scene length.
Every one of those is a miss generator, and a miss is the only failure that
costs anything (ADR 0004).
"""

from __future__ import annotations

import math
import shutil
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from extract_slides import constants
from extract_slides.manifest import (
    VIDEO_FILENAME,
    CaptureReason,
    Rect,
    RectRule,
    Slide,
    slide_filename,
    slides_directory,
)
from extract_slides.sampler import samples


@dataclass(frozen=True)
class Capture:
    """A kept state of the screen.

    `instant` is when the screen became this state for a `first`, `dwell` or
    `eof` capture, and the moment of the forcing for a `watchdog` one, which
    corresponds to no transition at all. `frame` is the full-resolution colour
    frame: the anchor's own, held since it was sampled, so writing it costs no
    second decode and no seek.
    """

    instant: float
    reason: CaptureReason
    frame: np.ndarray


#: Where a kept capture goes the moment it is kept. Captures are handed on
#: rather than collected: each is a full-resolution colour frame, and a
#: 45-minute talk keeps about 240 of them.
Keep = Callable[[Capture], None]


@dataclass
class Detection:
    """What a pass leaves besides the captures it handed on."""

    kept: Counter[CaptureReason] = field(default_factory=Counter)
    duplicates: int = 0


class _Keeper:
    """Hands on every capture that is not a near-copy of one already kept."""

    def __init__(self, keep: Keep) -> None:
        self._keep = keep
        self._hashes: list[np.ndarray] = []
        self.detection = Detection()

    def emit(self, capture: Capture) -> None:
        fingerprint = perceptual_hash(capture.frame)
        if any(
            hash_distance(fingerprint, kept) < constants.DUPLICATE_THRESHOLD
            for kept in self._hashes
        ):
            self.detection.duplicates += 1
            return
        self._hashes.append(fingerprint)
        self.detection.kept[capture.reason] += 1
        self._keep(capture)


def analysis_frame(frame: np.ndarray) -> np.ndarray:
    """The frame as the signal sees it: grey, at the analysis width."""
    height, width = frame.shape[:2]
    if width != constants.ANALYSIS_WIDTH_PX:
        scaled_height = max(1, round(height * constants.ANALYSIS_WIDTH_PX / width))
        frame = cv2.resize(
            frame, (constants.ANALYSIS_WIDTH_PX, scaled_height), interpolation=cv2.INTER_AREA
        )
    return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


def edge_map(grey: np.ndarray) -> np.ndarray:
    """Auto-Canny off the luma median, a third either side of it, then dilated.

    The kernel grows with the frame — 7 px at the analysis size — and is kept
    odd so that it dilates symmetrically.
    """
    median = float(np.median(grey))
    low = int(max(0, (2 / 3) * median))
    high = int(min(255, (4 / 3) * median))
    edges = cv2.Canny(grey, low, high)
    size = 4 + round(math.sqrt(grey.shape[0] * grey.shape[1]) / 192)
    if size % 2 == 0:
        size += 1
    return cv2.dilate(edges, np.ones((size, size), np.uint8))


def edge_difference(a: np.ndarray, b: np.ndarray) -> float:
    """Fraction of pixels whose edge state differs: 0.0 when nothing moved."""
    return float(np.mean(cv2.absdiff(a, b))) / 255.0


def perceptual_hash(frame: np.ndarray) -> np.ndarray:
    """The 256-bit DCT perceptual hash, one boolean per bit.

    The lowest 16×16 DCT coefficients of a 64×64 grey thumbnail, each set
    where it exceeds their median. The DC term is left out, as the spike
    measured it: it carries the frame's mean brightness, which says nothing
    about which slide is shown.
    """
    side = math.isqrt(constants.PHASH_BITS)
    grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(grey, (side * 4, side * 4), interpolation=cv2.INTER_AREA)
    coefficients = cv2.dct(np.float32(small))[:side, :side].flatten()[1:]
    return coefficients > np.median(coefficients)


def hash_distance(a: np.ndarray, b: np.ndarray) -> float:
    """Fraction of bits that differ — never a raw Hamming count."""
    return float(np.count_nonzero(a != b)) / a.size


def detect(samples: Iterable[tuple[float, np.ndarray]], keep: Keep) -> Detection:
    """Run pass 1 over `samples`, handing each kept capture to `keep`."""
    keeper = _Keeper(keep)
    #: The held anchor: its instant, its colour frame and its edge map.
    anchor: tuple[float, np.ndarray, np.ndarray] | None = None
    anchor_emitted = False
    last_emission = 0.0

    for instant, frame in samples:
        edges = edge_map(analysis_frame(frame))
        if anchor is None:
            keeper.emit(Capture(instant, CaptureReason.first, frame))
            anchor, anchor_emitted, last_emission = (instant, frame, edges), True, instant
            continue
        anchor_instant, anchor_frame, anchor_edges = anchor
        if edge_difference(anchor_edges, edges) < constants.EDGE_DIFFERENCE_TRIGGER:
            continue
        if not anchor_emitted and instant - anchor_instant >= constants.ANCHOR_DWELL_SECONDS:
            keeper.emit(Capture(anchor_instant, CaptureReason.dwell, anchor_frame))
            # The anchor accounted for the video up to now, so that is where
            # the watchdog starts counting again — also when the capture was
            # a duplicate, because then the same screen is already kept.
            last_emission = instant
        anchor, anchor_emitted = (instant, frame, edges), False
        if instant - last_emission >= constants.WATCHDOG_SECONDS:
            keeper.emit(Capture(instant, CaptureReason.watchdog, frame))
            anchor_emitted, last_emission = True, instant

    if anchor is not None and not anchor_emitted:
        anchor_instant, anchor_frame, _ = anchor
        keeper.emit(Capture(anchor_instant, CaptureReason.eof, anchor_frame))
    return keeper.detection


# --- the stage ---------------------------------------------------------------

#: Where captures are written while the pass runs. Their final names depend on
#: how many there are — the numbering widens past 999 — which is only known at
#: the end, and the previous detection's images stay in place until then.
STAGING_DIRNAME = ".slides.partial"


class StrangerInTheWay(Exception):
    """A file the manifest does not know holds a name a new capture needs."""


@dataclass(frozen=True)
class Detected:
    slides: list[Slide]
    gist: str


def run(directory: Path, *, previous: Iterable[Slide], log: Any) -> Detected:
    """Stage 3: pass 1 over the source video, into `slides/` and its rows.

    The images of the previous detection are replaced, and only those: a file
    in `slides/` the manifest does not know is the operator's, and it is left
    alone — or, when a new capture would need its name, the stage stops before
    anything is touched.
    """
    staging = directory / STAGING_DIRNAME
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir()
    kept: list[tuple[float, CaptureReason]] = []

    def write(capture: Capture) -> None:
        path = staging / f"{len(kept) + 1}.jpg"
        if not cv2.imwrite(
            str(path), capture.frame, [cv2.IMWRITE_JPEG_QUALITY, constants.JPEG_QUALITY]
        ):
            raise OSError(f"could not write {path}")
        kept.append((capture.instant, capture.reason))

    try:
        detection = detect(samples(directory / VIDEO_FILENAME), write)
    except BaseException:
        # A pass that stops halfway — an unreadable video, an interrupt —
        # leaves the previous detection exactly as it was.
        shutil.rmtree(staging, ignore_errors=True)
        raise

    slides = [
        Slide(
            file=slide_filename(number, of=len(kept)),
            change_at=instant,
            reason=reason,
            rect=Rect.full(),
            rect_rule=RectRule.full,
        )
        for number, (instant, reason) in enumerate(kept, start=1)
    ]
    _replace(directory, staging, previous=previous, slides=slides)

    counts = ", ".join(
        f"{detection.kept[reason]} {reason.value}"
        for reason in CaptureReason
        if detection.kept[reason]
    )
    log.field("captures", f"{len(slides)} ({counts})")
    log.field("duplicates", f"{detection.duplicates} dropped")
    gist = f"{len(slides)} captures"
    log.done(gist)
    return Detected(slides=slides, gist=gist)


def _replace(
    directory: Path, staging: Path, *, previous: Iterable[Slide], slides: list[Slide]
) -> None:
    """Swap the previous detection's images for the staged ones."""
    target = slides_directory(directory)
    target.mkdir(exist_ok=True)
    known = {slide.file for slide in previous}
    in_the_way = sorted(
        slide.file
        for slide in slides
        if slide.file not in known and (target / slide.file).exists()
    )
    if in_the_way:
        shutil.rmtree(staging, ignore_errors=True)
        raise StrangerInTheWay(", ".join(in_the_way))
    for name in known:
        (target / name).unlink(missing_ok=True)
    for number, slide in enumerate(slides, start=1):
        (staging / f"{number}.jpg").replace(target / slide.file)
    staging.rmdir()
