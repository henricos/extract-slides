"""Shared fixtures for the suite.

`BORDERS` lives here as a fixture rather than a module constant because
importing `conftest` from a test file only works when the project root
happens to be on `sys.path`, which depends on where pytest was started.

`output_directory` is the harness the rest of the suite is built on: a run
assembled **by hand**, with no video decoded and no stage run. Grade 1 of the
test strategy — a manifest, images that are a few pixels of solid colour, a
transcript — which is what lets the tests that matter most here run in
milliseconds and stay about the contract rather than about pixels.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest
from typer.testing import CliRunner

from extract_slides import __version__
from extract_slides.manifest import (
    CaptureReason,
    Manifest,
    Rect,
    RectRule,
    RunHeader,
    Slide,
    TranscriptFidelity,
    TranscriptOrigin,
    slide_filename,
    slides_directory,
)
from extract_slides.pipeline import ORDER

#: Box-drawing characters. ADR 0001 bans them from `--help` and ADR 0002
#: bans them from the running log, while the final report is the one place
#: a border earns its keep — so several tests ask the same question.
_BORDERS = set("╭╮╰╯│─┌┐└┘═║")

#: What a finished run records. Named here so a test that wants a half-finished
#: one can say which stages it is taking away.
ALL_STAGES = tuple(stage.value for stage in ORDER)

#: The source video a finished `acquire` leaves behind. Nothing in grade 1
#: opens it; it is here so a hand-built directory is not missing a file the
#: crop would later need.
VIDEO_FILENAME = "source.mp4"


@pytest.fixture
def borders() -> set[str]:
    return _BORDERS


@pytest.fixture
def cli() -> CliRunner:
    return CliRunner()


def _write_slide_image(path: Path, shade: int) -> None:
    """A JPEG of four pixels. Encoding is not decoding, and nothing reads it."""
    import cv2
    import numpy as np

    cv2.imwrite(str(path), np.full((2, 2, 3), shade, dtype=np.uint8))


@pytest.fixture
def output_directory(tmp_path: Path):
    """Build a run by hand and return its directory."""

    def build(
        name: str = "a-talk-jqpdveK2XAU",
        *,
        instants: Sequence[float] = (0.0, 10.0, 25.0),
        duration: float = 40.0,
        completed: Sequence[str] = ALL_STAGES,
        cropped: bool = True,
        write_images: bool = True,
    ) -> Path:
        directory = tmp_path / name
        slides_directory(directory).mkdir(parents=True, exist_ok=True)

        count = len(instants)
        slides = [
            Slide(
                file=slide_filename(number, of=count),
                change_at=instant,
                reason=CaptureReason.first if number == 1 else CaptureReason.dwell,
                rect=Rect.full(),
                rect_rule=RectRule.full,
                layout=0 if cropped else None,
            )
            for number, instant in enumerate(instants, start=1)
        ]
        document = Manifest(
            run=RunHeader(
                tool_version=__version__,
                duration=duration,
                video_id="jqpdveK2XAU",
                url="https://youtu.be/jqpdveK2XAU",
                transcript_origin=TranscriptOrigin.asr_caption,
                transcript_fidelity=TranscriptFidelity.cue,
                cropped=cropped,
            ),
            slides=slides,
        )
        for stage in completed:
            document.record_stage(stage, f"{stage} done")
        document.write(directory)

        if write_images:
            for offset, slide in enumerate(slides):
                _write_slide_image(slides_directory(directory) / slide.file, 40 * offset)

        (directory / VIDEO_FILENAME).write_bytes(b"not a video, and nothing opens it")
        cues = [
            {"start": start, "end": end, "text": f"speech over slide {number}"}
            for number, (start, end) in enumerate(
                zip([*instants], [*instants[1:], duration], strict=True), start=1
            )
        ]
        # A placeholder, not the contract: the normalised transcript shape is
        # #27's to fix, and nothing in this ticket reads these two files.
        (directory / "transcript.json").write_text(
            json.dumps(
                {
                    "origin": TranscriptOrigin.asr_caption.value,
                    "fidelity": TranscriptFidelity.cue.value,
                    "duration": duration,
                    "cues": cues,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        (directory / "transcript.md").write_text(
            "\n\n".join(cue["text"] for cue in cues) + "\n", encoding="utf-8"
        )
        return directory

    return build
