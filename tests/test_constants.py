"""The measured constants hold the values docs/stack.md §13 records.

This test proves nothing about quality — there is no metric and no ground
truth (ADR 0004). Its whole job is to make moving a measured number
impossible to do by accident: whoever changes one has to change this file
too, and in doing so reads the ADR that chose it.
"""

from extract_slides import constants


def test_detection_constants_hold_their_measured_values():
    # ADR 0005 — pass 1: edge signal, pinned anchor, watchdog
    assert constants.SAMPLE_RATE_PER_SECOND == 2
    assert constants.ANALYSIS_WIDTH_PX == 480
    assert constants.EDGE_DIFFERENCE_TRIGGER == 0.005
    assert constants.ANCHOR_DWELL_SECONDS == 1.5
    assert constants.WATCHDOG_SECONDS == 10
    assert constants.PHASH_BITS == 256
    assert constants.DUPLICATE_THRESHOLD == 0.02


def test_crop_constants_hold_their_measured_values():
    # ADR 0006 — the crop cuts the presenter away and nothing else
    assert constants.PRESENTER_PIXEL_MOVEMENT_FRACTION == 0.06
    assert constants.CONTENT_PIXEL_GREY_LEVELS == 45
    assert constants.CONTENT_PIXEL_CAPTURE_FRACTION == 0.08
    assert constants.LAYOUT_CLUSTER_AGREEMENT == 0.50
    assert constants.MINIMUM_LAYOUT_CAPTURES == 3
    assert constants.BLOB_IN_STRIP_FRACTION == 0.80
    assert constants.SPECK_FILTER_FRACTION == 0.10
    assert constants.CUT_OUTWARD_MARGIN == 0.015
    assert constants.RECTANGLE_MIN_FRAME_FRACTION == 0.10
    assert constants.RECTANGLE_MAX_FRAME_FRACTION == 0.98


def test_transcribe_constants_hold_their_measured_values():
    # ADR 0007 — small/medium by language, the media clock as the authority
    assert constants.STT_THREADS == 2
    assert constants.STT_BEAM_SIZE == 5
    assert constants.CAPTION_OVERRUN_TOLERANCE_SECONDS == 2.0


def test_prune_constants_hold_their_measured_values():
    # ADR 0008 — pass 2: drop, prune, one vision request
    assert constants.PRUNE_IMAGE_LONG_EDGE_PX == 680
    assert constants.PRUNE_MAX_TOKENS == 65_536


def test_output_constants_hold_their_measured_values():
    # ADR 0009 — the manifest, the pairing rule, JPEG
    assert constants.SLIDE_NUMBER_MIN_DIGITS == 3


def test_every_constant_names_the_adr_that_chose_it():
    # A value without provenance is a value the next session will move
    # without reading why it is what it is.
    for name in constants.ADR_BY_CONSTANT:
        assert hasattr(constants, name), f"{name} is listed with an ADR but not defined"
        assert constants.ADR_BY_CONSTANT[name].startswith("ADR "), name


def test_every_public_constant_is_listed_with_its_adr():
    public = {
        name
        for name in vars(constants)
        if name.isupper() and name != "ADR_BY_CONSTANT"
    }
    assert public == set(constants.ADR_BY_CONSTANT)
