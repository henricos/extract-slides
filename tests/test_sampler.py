"""The sampler: the production side of seam 2, and the one place that decodes.

Grade 3 of the test strategy (#24): a real video file, because the decode is
what is under test. Videos are generated with OpenCV, a few seconds long, and
built once per session. They prove the sampler reads what it should — the
sampling rate, the rotation flag — and nothing about a real codec: a video
written and read by the same library says nothing about a phone recording.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from extract_slides.sampler import samples
from videos import rotate_90, write_video

WIDTH, HEIGHT = 64, 32
SECONDS = 3


def _write_video(path: Path) -> Path:
    """Three seconds of a frame whose left quarter is white."""
    frame = np.zeros((HEIGHT, WIDTH, 3), np.uint8)
    frame[:, : WIDTH // 4] = 255
    return write_video(path, [(frame, SECONDS)])


@pytest.fixture(scope="session")
def video(tmp_path_factory) -> Path:
    return _write_video(tmp_path_factory.mktemp("sampler") / "upright.mp4")


@pytest.fixture(scope="session")
def rotated_video(tmp_path_factory) -> Path:
    path = _write_video(tmp_path_factory.mktemp("sampler") / "rotated.mp4")
    rotate_90(path)
    return path


def test_a_video_is_sampled_twice_a_second(video):
    assert [instant for instant, _ in samples(video)] == [0.0, 0.5, 1.0, 1.5, 2.0, 2.5]


def test_each_sample_is_the_colour_frame_at_full_size(video):
    _, frame = next(iter(samples(video)))
    assert frame.shape == (HEIGHT, WIDTH, 3)


def test_rotation_metadata_is_honoured(rotated_video):
    # Turned a quarter, the 64×32 frame stands 64 tall and 32 wide.
    _, frame = next(iter(samples(rotated_video)))
    assert frame.shape[:2] == (WIDTH, HEIGHT)
