"""Pass 1 through the sampler seam: constructed frames in, captures out.

Grade 2 of the test strategy (#24). The detector is handed `(instant, frame)`
pairs and never opens a video, so nothing here decodes: a test that decoded
would pay for the one cost in the stage it is not testing (ADR 0005 measures
the analysis at 0.56 ms a sample, and decode is the rest).

Frames are 480 px wide, the analysis width, so what a test draws is exactly
what the signal measures. A slide here is a black screen carrying white bars;
the bars' edges are what the edge difference sees.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

import numpy as np

from extract_slides.detector import Capture, detect

WIDTH, HEIGHT = 480, 270

#: Seconds between samples at ADR 0005's two a second.
STEP = 0.5


def screen(*bars: tuple[int, int, int, int]) -> np.ndarray:
    """A black colour frame carrying white bars, each `(top, left, height, width)`."""
    frame = np.zeros((HEIGHT, WIDTH, 3), np.uint8)
    for top, left, height, width in bars:
        frame[top : top + height, left : left + width] = 255
    return frame


def held(
    frame: np.ndarray, seconds: float, *, start: float = 0.0
) -> Iterator[tuple[float, np.ndarray]]:
    """`frame`, sampled for `seconds` from `start`."""
    for index in range(round(seconds / STEP)):
        yield start + index * STEP, frame


def played(*shots: tuple[np.ndarray, float]) -> list[tuple[float, np.ndarray]]:
    """Each `(frame, seconds)` held in turn, as the sampler would yield them."""
    samples: list[tuple[float, np.ndarray]] = []
    clock = 0.0
    for frame, seconds in shots:
        samples.extend(held(frame, seconds, start=clock))
        clock += seconds
    return samples


def captures(samples: Iterable[tuple[float, np.ndarray]]) -> list[Capture]:
    kept: list[Capture] = []
    detect(samples, kept.append)
    return kept


def captured(samples: Iterable[tuple[float, np.ndarray]]) -> list[tuple[float, str]]:
    return [(capture.instant, capture.reason.value) for capture in captures(samples)]


def test_the_first_frame_is_always_emitted():
    assert captured(held(screen(), 1.0)) == [(0.0, "first")]


#: Three slides that share nothing, so any cut between two of them fires.
SLIDE_A = screen((30, 40, 40, 400))
SLIDE_B = screen((120, 40, 40, 180), (120, 260, 40, 180))
SLIDE_C = screen((200, 200, 50, 60), (30, 30, 20, 20))


def test_a_slide_that_held_and_then_changed_is_captured_at_the_instant_it_appeared():
    assert (3.0, "dwell") in captured(played((SLIDE_A, 3.0), (SLIDE_B, 3.0), (SLIDE_C, 3.0)))


def test_the_slide_still_on_screen_when_the_video_ends_is_captured():
    assert captured(played((SLIDE_A, 3.0), (SLIDE_B, 3.0))) == [(0.0, "first"), (3.0, "eof")]


# The trigger is 0.5 % of the analysis frame: 648 of its 129 600 pixels. A
# 4 px bar drawn on a blank screen changes the edge state of 11 rows of pixels
# per pixel of its length once both edge maps are dilated, so its length steps
# the difference 11 pixels at a time across the trigger: 52 px changes 644
# pixels and 53 px changes 655.


def test_a_difference_just_above_the_trigger_fires():
    blank, revealed = screen(), screen((100, 100, 4, 53))
    assert captured(played((blank, 3.0), (revealed, 3.0))) == [(0.0, "first"), (3.0, "eof")]


def test_a_difference_just_below_the_trigger_does_not():
    blank, revealed = screen(), screen((100, 100, 4, 52))
    assert captured(played((blank, 3.0), (revealed, 3.0))) == [(0.0, "first")]


def test_a_drift_too_slow_for_any_two_neighbours_to_differ_still_fires():
    # A bar growing 20 px a sample: every neighbour differs by under 300
    # pixels, well below the trigger, but the third step is 732 pixels away
    # from the blank screen the anchor is still holding.
    growing = [screen((100, 100, 4, length)) for length in (20, 40, 60)]
    samples = played((screen(), 3.0), (growing[0], STEP), (growing[1], STEP), (growing[2], 3.0))
    assert captured(samples) == [(0.0, "first"), (4.0, "eof")]


def test_a_slide_that_held_for_exactly_the_dwell_is_captured():
    samples = played((SLIDE_A, 3.0), (SLIDE_B, 1.5), (SLIDE_C, 3.0))
    assert captured(samples) == [(0.0, "first"), (3.0, "dwell"), (4.5, "eof")]


def test_a_slide_that_held_for_just_less_than_the_dwell_is_not():
    # Off the half-second grid on purpose: the seam takes any instant, and
    # 1.4 s is closer to the dwell than any two samples at 2 a second can be.
    samples = [*held(SLIDE_A, 3.0), (3.0, SLIDE_B), *held(SLIDE_C, 3.0, start=4.4)]
    assert captured(samples) == [(0.0, "first"), (4.4, "eof")]


def churning(seconds: float, *, start: float = 0.0) -> list[tuple[float, np.ndarray]]:
    """A screen that never holds still: every sample differs from the last.

    What a camera filming a screen in a dark auditorium looks like to the
    signal (ADR 0005's `X3uFwLj2u7Q`), and what burned-in subtitles look like.
    """
    # A bar that jumps across the screen, never landing twice in one place,
    # so no two samples are duplicates of each other either.
    return [
        (start + index * STEP, screen((100, (index * 37) % 420, 40, 60)))
        for index in range(round(seconds / STEP))
    ]


def test_a_screen_that_never_holds_still_is_captured_by_the_watchdog():
    reasons = [reason for _, reason in captured(churning(25.0))]
    assert reasons == ["first", "watchdog", "watchdog", "eof"]


def test_the_watchdog_waits_the_whole_interval_since_the_last_capture():
    assert [instant for instant, _ in captured(churning(25.0))] == [0.0, 10.0, 20.0, 24.5]


def test_a_slide_returned_to_is_dropped_against_every_capture_kept_not_only_the_last():
    # A camera cutting away from the slide and back: the return is a copy of
    # the first capture, with a different slide kept in between.
    samples = played((SLIDE_A, 3.0), (SLIDE_B, 3.0), (SLIDE_A, 3.0), (SLIDE_C, 3.0))
    kept: list[Capture] = []
    detection = detect(samples, kept.append)
    assert [(c.instant, c.reason.value) for c in kept] == [
        (0.0, "first"),
        (3.0, "dwell"),
        (9.0, "eof"),
    ]
    assert detection.duplicates == 1


def test_a_slide_that_differs_is_kept_however_alike_its_layout_is():
    # Same title bar, a different body: two slides of one deck.
    title = (20, 40, 30, 400)
    first, second = screen(title, (120, 40, 100, 150)), screen(title, (120, 290, 100, 150))
    assert [reason for _, reason in captured(played((first, 3.0), (second, 3.0)))] == [
        "first",
        "eof",
    ]


def test_a_capture_is_the_anchor_s_own_full_resolution_colour_frame():
    # 720p, so the analysis has to scale it down; and the bar changes colour
    # sample by sample while its edges stay put, so each sample is a frame of
    # its own that the signal cannot tell apart. The capture must be the one
    # the slide appeared with, at full size, not a later one nor the grey copy
    # the signal measured.
    def slide(colour: tuple[int, int, int], *, left: int) -> np.ndarray:
        frame = np.zeros((720, 1280, 3), np.uint8)
        frame[200:400, left : left + 500] = colour
        return frame

    tints = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 0, 255), (0, 255, 255), (255, 255, 0)]
    shown = [slide(tint, left=100) for tint in tints]
    samples = [
        *held(slide((255, 255, 255), left=700), 3.0),
        *((3.0 + index * STEP, frame) for index, frame in enumerate(shown)),
    ]
    last = captures(samples)[-1]
    assert last.instant == 3.0
    assert np.array_equal(last.frame, shown[0])
