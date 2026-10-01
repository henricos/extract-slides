"""Yields `(instant, frame)` pairs from a video. The second seam (#24).

The detector and the crop consume what this yields and never open a video
themselves. Decode is the whole cost of pass 1 — ADR 0005 measures the
analysis at 0.56 ms a sample against a stage that costs ~6 % of the video's
duration — so keeping it here is what lets the suite feed them constructed
frames and pay nothing for a decode it is not testing.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import cv2
import numpy as np

from extract_slides import constants


class VideoUnreadable(Exception):
    """The video is missing, or nothing in it can be decoded."""


def samples(
    video: Path, *, rate: float = constants.SAMPLE_RATE_PER_SECOND
) -> Iterator[tuple[float, np.ndarray]]:
    """Every `1 / rate` seconds of `video`: its instant, and the colour frame.

    The instant is the frame's own position on the media clock — its index
    over the frame rate — so a sample is stamped where the frame is, not
    where an ideal grid says it should have been.

    **Rotation metadata is honoured** (`docs/stack.md` §14). Without the flag a
    phone-recorded talk decodes sideways and both detection and the crop
    break; it is set explicitly rather than trusted to a default that has
    moved between OpenCV releases (opencv/opencv#26795).
    """
    if not video.is_file():
        raise VideoUnreadable(f"{video} does not exist")
    capture = cv2.VideoCapture(str(video))
    try:
        if not capture.isOpened():
            raise VideoUnreadable(f"{video} cannot be opened as a video")
        capture.set(cv2.CAP_PROP_ORIENTATION_AUTO, 1.0)
        fps = capture.get(cv2.CAP_PROP_FPS)
        if not fps or fps <= 0:
            raise VideoUnreadable(f"{video} states no frame rate")
        # A whole number of frames between samples, as the spike measured:
        # every frame is grabbed, and only these are decoded into pixels.
        step = max(1, round(fps / rate))
        index = 0
        sampled = 0
        while capture.grab():
            if index % step == 0:
                ok, frame = capture.retrieve()
                # A frame that will not decode costs that one sample. Ending
                # the stream there would pass the rest of the talk off as
                # its end, and every slide after it would go missing.
                if ok:
                    sampled += 1
                    yield index / fps, frame
            index += 1
        if not sampled:
            # Not a talk with no slides: a stream that decodes nothing would
            # otherwise replace the last detection with an empty one.
            raise VideoUnreadable(f"{video} opens, but not one frame of it decodes")
    finally:
        capture.release()
