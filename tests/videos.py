"""Real video files, written with OpenCV, for the grade 3 tests (#24).

Kept to a few seconds and tiny frames: they exist to put a file path through
the decoder, not to stand in for a talk. A video written and read by the same
library proves nothing about a phone recording, and nothing here pretends to.
"""

from __future__ import annotations

import struct
from collections.abc import Sequence
from pathlib import Path

import cv2
import numpy as np

FPS = 10


def write_video(
    path: Path, shots: Sequence[tuple[np.ndarray, float]], *, fps: int = FPS
) -> Path:
    """Each `(frame, seconds)` held in turn. Every frame must share one size."""
    height, width = shots[0][0].shape[:2]
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    for frame, seconds in shots:
        for _ in range(round(seconds * fps)):
            writer.write(frame)
    writer.release()
    return path


def rotate_90(path: Path) -> None:
    """Stamp a 90° display matrix into the track header, as a phone does.

    OpenCV cannot write rotation metadata, so the `tkhd` box of the file it
    wrote is edited in place: its 3×3 matrix in 16.16 and 2.30 fixed point.
    """
    data = bytearray(path.read_bytes())
    box = data.find(b"tkhd")
    version = data[box + 4]
    # Version and flags, the times, the track id and the duration, then eight
    # reserved bytes, then layer, group, volume and two more reserved.
    matrix = box + 8 + (32 if version == 1 else 20) + 8 + 8
    data[matrix : matrix + 36] = struct.pack(
        ">9i", 0, 0x10000, 0, -0x10000, 0, 0, 0, 0, 0x40000000
    )
    path.write_bytes(bytes(data))


def damage(path: Path) -> None:
    """Zero the coded frames, leaving the container whole.

    What a corrupt download looks like to the decoder: the file opens and
    states its frame rate, and not one frame decodes.
    """
    data = bytearray(path.read_bytes())
    box = data.find(b"mdat")
    size = struct.unpack(">I", data[box - 4 : box])[0]
    data[box + 4 : box - 4 + size] = bytes(size - 8)
    path.write_bytes(bytes(data))
