"""`extract-slides detect DIR`, through seam 1: what the directory holds after.

Grade 3 of the test strategy (#24) — a real video file, because a file path
flowing end to end is what is under test. The video is a few seconds of two
constructed slides; what pass 1 makes of a real talk is checked by watching
one, never here (ADR 0004).
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from extract_slides.cli import app
from videos import damage, write_video

#: Two slides of two seconds each, on a grey ground so the codec's noise in a
#: flat area is not mistaken for an edge.
WIDTH, HEIGHT = 480, 270
DURATION = 4.0


def _slide(*bars: tuple[int, int, int, int]) -> np.ndarray:
    frame = np.full((HEIGHT, WIDTH, 3), 60, np.uint8)
    for top, left, height, width in bars:
        frame[top : top + height, left : left + width] = 220
    return frame


TITLE = _slide((30, 40, 40, 400))
BODY = _slide((120, 40, 40, 180), (120, 260, 40, 180))


@pytest.fixture
def run_with_video(output_directory):
    """A run that has acquired and transcribed a two-slide talk, and no more."""
    directory = output_directory(
        instants=(), duration=DURATION, completed=("acquire", "transcribe"), cropped=False
    )
    write_video(directory / "source.mp4", [(TITLE, 2.0), (BODY, 2.0)])
    return directory


def _manifest(directory):
    return json.loads((directory / "manifest.json").read_text(encoding="utf-8"))


def test_detect_writes_one_jpeg_per_capture_and_a_row_for_each(cli, run_with_video):
    cli.invoke(app, ["detect", str(run_with_video)])
    rows = _manifest(run_with_video)["slides"]
    assert [(row["file"], row["change_at"], row["reason"]) for row in rows] == [
        ("001.jpg", 0.0, "first"),
        ("002.jpg", 2.0, "eof"),
    ]
    assert sorted(path.name for path in (run_with_video / "slides").iterdir()) == [
        "001.jpg",
        "002.jpg",
    ]


def test_detection_is_kept_when_the_crop_after_it_cannot_run(cli, run_with_video):
    # `detect` chains into the crop, which this build does not have yet. The
    # run stops there and says so; what pass 1 finished stays recorded, so
    # the next run reuses it rather than decoding the video again.
    result = cli.invoke(app, ["detect", str(run_with_video)])
    assert result.exit_code == 2
    assert "crop is not implemented yet" in result.stderr
    assert _manifest(run_with_video)["run"]["stages"]["detect"]["gist"] == "2 captures"


def test_detecting_again_leaves_none_of_the_earlier_captures_behind(cli, output_directory):
    directory = output_directory(instants=(0.0, 1.0, 3.0), duration=DURATION)
    write_video(directory / "source.mp4", [(TITLE, 2.0), (BODY, 2.0)])
    cli.invoke(app, ["detect", str(directory)])
    assert sorted(path.name for path in (directory / "slides").iterdir()) == ["001.jpg", "002.jpg"]
    assert [row["file"] for row in _manifest(directory)["slides"]] == ["001.jpg", "002.jpg"]


def test_a_file_the_manifest_does_not_know_is_left_where_it_is(cli, run_with_video):
    stranger = run_with_video / "slides" / "notes.jpg"
    stranger.write_bytes(b"the operator's, not the tool's")
    cli.invoke(app, ["detect", str(run_with_video)])
    assert stranger.read_bytes() == b"the operator's, not the tool's"


def test_a_file_the_manifest_does_not_know_is_never_overwritten(cli, run_with_video):
    stranger = run_with_video / "slides" / "002.jpg"
    stranger.write_bytes(b"the operator's, not the tool's")
    result = cli.invoke(app, ["detect", str(run_with_video)])
    assert result.exit_code == 2
    assert "002.jpg" in result.stderr
    assert stranger.read_bytes() == b"the operator's, not the tool's"
    assert sorted(path.name for path in run_with_video.iterdir() if path.name.startswith(".")) == []


def test_detect_without_the_source_video_says_which_file_is_missing(cli, run_with_video):
    (run_with_video / "source.mp4").unlink()
    result = cli.invoke(app, ["detect", str(run_with_video)])
    assert result.exit_code == 2
    assert "source.mp4" in result.stderr
    assert "detect" not in _manifest(run_with_video)["run"]["stages"]
    assert sorted(path.name for path in run_with_video.iterdir() if path.name.startswith(".")) == []


def test_a_video_that_opens_but_decodes_nothing_keeps_the_previous_detection(cli, output_directory):
    # A corrupt download must not pass for a talk with no slides: that would
    # delete the images the last detection left and record the stage done.
    directory = output_directory(instants=(0.0, 1.0, 3.0), duration=DURATION)
    damage(write_video(directory / "source.mp4", [(TITLE, 2.0), (BODY, 2.0)]))
    result = cli.invoke(app, ["detect", str(directory)])
    assert result.exit_code == 2
    assert "source.mp4" in result.stderr
    assert sorted(path.name for path in (directory / "slides").iterdir()) == [
        "001.jpg",
        "002.jpg",
        "003.jpg",
    ]
