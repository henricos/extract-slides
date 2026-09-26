"""The output contract, per ADR 0009: a current-state table of instants.

Grade 1 of the test strategy — a directory built by hand, nothing decoded.
What is asserted here is the structural contract and the safety property the
project is built on, never the quality of anything: the intervals tile the
media, a row carries what the crop and pass 2 need, and a manifest that would
make the tool mis-read a directory is refused rather than accepted.
"""

import json

import pytest

from extract_slides import __version__
from extract_slides.manifest import (
    CaptureReason,
    Manifest,
    ManifestError,
    Rect,
    RectRule,
    RunHeader,
    Slide,
    TranscriptFidelity,
    TranscriptOrigin,
    slide_filename,
    slide_number_width,
)


def slide(number: int, change_at: float, **overrides) -> Slide:
    row = {
        "file": slide_filename(number, of=number),
        "change_at": change_at,
        "reason": CaptureReason.dwell,
        "rect": Rect.full(),
        "rect_rule": RectRule.full,
        "layout": 0,
    }
    return Slide(**{**row, **overrides})


def manifest(*instants: float, duration: float = 40.0, **header) -> Manifest:
    return Manifest(
        run=RunHeader(tool_version=__version__, duration=duration, **header),
        slides=[slide(number, at) for number, at in enumerate(instants, start=1)],
    )


# --- the run header --------------------------------------------------------


def test_the_run_header_survives_a_round_trip_through_disk(tmp_path):
    written = manifest(
        0.0,
        12.5,
        video_id="jqpdveK2XAU",
        url="https://youtu.be/jqpdveK2XAU",
        transcript_origin=TranscriptOrigin.stt,
        transcript_fidelity=TranscriptFidelity.word,
        stt_model="small",
        cropped=True,
    )
    written.record_stage("detect", "216 captures")
    written.write(tmp_path)

    read = Manifest.read(tmp_path)

    assert read.run.tool_version == __version__
    assert read.run.video_id == "jqpdveK2XAU"
    assert read.run.url == "https://youtu.be/jqpdveK2XAU"
    assert read.run.duration == 40.0
    assert read.run.transcript_origin is TranscriptOrigin.stt
    assert read.run.transcript_fidelity is TranscriptFidelity.word
    assert read.run.stt_model == "small"
    assert read.run.cropped is True
    assert read.completed_stages() == {"detect": "216 captures"}


def test_the_header_records_the_detection_parameters(tmp_path):
    manifest(0.0).write(tmp_path)

    detection = Manifest.read(tmp_path).run.detection

    # Read off constants rather than restated, so a manifest never claims a
    # value the run did not use.
    from extract_slides import constants

    assert detection["sample_rate_per_second"] == constants.SAMPLE_RATE_PER_SECOND
    assert detection["edge_difference_trigger"] == constants.EDGE_DIFFERENCE_TRIGGER
    assert detection["watchdog_seconds"] == constants.WATCHDOG_SECONDS


def test_a_stage_record_carries_the_words_its_reuse_line_will_say(tmp_path):
    written = manifest(0.0)
    written.record_stage("transcribe", "YouTube caption")
    written.write(tmp_path)

    record = Manifest.read(tmp_path).run.stages["transcribe"]

    assert record.gist == "YouTube caption"
    assert record.completed_at.startswith("20"), "a stage says when it finished"


def test_a_stage_this_build_does_not_know_is_carried_rather_than_rejected(tmp_path):
    written = manifest(0.0)
    written.record_stage("summarise", "a stage from a later version")
    written.write(tmp_path)

    assert "summarise" in Manifest.read(tmp_path).completed_stages()


# --- a slide row -----------------------------------------------------------


def test_a_slide_row_carries_the_instant_the_reason_and_the_rectangle(tmp_path):
    written = manifest(0.0)
    written.slides = [
        slide(
            1,
            3.5,
            reason=CaptureReason.watchdog,
            rect=Rect(0.1, 0.0, 0.6, 0.9),
            rect_rule=RectRule.activity,
            layout=2,
        )
    ]
    written.write(tmp_path)

    row = Manifest.read(tmp_path).slides[0]

    assert row.change_at == 3.5
    assert row.reason is CaptureReason.watchdog
    assert row.rect == Rect(0.1, 0.0, 0.6, 0.9)
    assert row.rect_rule is RectRule.activity
    assert row.layout == 2


def test_a_row_written_before_the_crop_clustered_has_no_layout(tmp_path):
    written = manifest(0.0)
    written.slides = [slide(1, 0.0, layout=None)]
    written.write(tmp_path)

    assert Manifest.read(tmp_path).slides[0].layout is None


def test_a_rectangle_is_four_normalised_numbers_on_disk(tmp_path):
    written = manifest(0.0)
    written.slides = [slide(1, 0.0, rect=Rect(0.25, 0.1, 0.5, 0.8))]
    written.write(tmp_path)

    document = json.loads((tmp_path / "manifest.json").read_text())

    assert document["slides"][0]["rect"] == [0.25, 0.1, 0.5, 0.8]


def test_a_capture_reason_outside_the_closed_set_is_refused(tmp_path):
    manifest(0.0).write(tmp_path)
    path = tmp_path / "manifest.json"
    document = json.loads(path.read_text())
    document["slides"][0]["reason"] = "vibes"
    path.write_text(json.dumps(document))

    with pytest.raises(ManifestError, match="capture reason"):
        Manifest.read(tmp_path)


def test_a_rectangle_running_past_the_frame_is_refused(tmp_path):
    written = manifest(0.0)
    written.slides = [slide(1, 0.0, rect=Rect(0.6, 0.0, 0.6, 1.0))]

    with pytest.raises(ManifestError, match="past the frame"):
        written.write(tmp_path)


# --- the intervals, which are derived and never stored ---------------------


def test_intervals_are_derived_from_the_instants(tmp_path):
    assert manifest(0.0, 10.0, 25.0, duration=40.0).intervals() == [
        (0.0, 10.0),
        (10.0, 25.0),
        (25.0, 40.0),
    ]


def test_the_last_interval_runs_to_the_media_duration():
    assert manifest(0.0, 10.0, duration=40.0).intervals()[-1] == (10.0, 40.0)


def test_derived_intervals_tile_the_media_with_no_gap_and_no_overlap():
    document = manifest(0.0, 3.25, 3.5, 19.0, 31.75, duration=40.0)

    intervals = document.intervals()

    assert intervals[0][0] == 0.0, "the first interval opens at zero"
    assert intervals[-1][1] == document.run.duration
    for (_, ends), (starts, _) in zip(intervals, intervals[1:]):
        assert ends == starts, "no gap, and no overlap"


def test_the_first_interval_opens_at_zero_even_after_the_opening_slide_is_gone():
    # Deleting the first row is deleting the line: what it covered merges
    # forward into the slide that now opens the deck, and no cue lands nowhere.
    assert manifest(10.0, 25.0, duration=40.0).intervals()[0] == (0.0, 25.0)


def test_deleting_an_interior_row_gives_its_span_to_the_row_before_it():
    """The one thing the representation does not do for free.

    ADR 0009 claimed the forward merge ADR 0008 requires "stops being a rule
    and becomes a property of the representation". It does at the two ends and
    not in between: with `[change_at[i], change_at[i+1])`, a deleted row frees
    its span to the row *before* it, which is the "merge into the previous
    slide" ADR 0008 calls intuitive and wrong. Asserted here so that the rule
    `drop` owes (#33) is visible as work rather than assumed to be free.
    """
    before = manifest(0.0, 10.0, 25.0, duration=40.0)
    after = manifest(0.0, 25.0, duration=40.0)

    assert before.intervals()[1] == (10.0, 25.0)
    assert after.intervals()[0] == (0.0, 25.0), "the freed span went backward"


def test_no_interval_is_stored_on_disk(tmp_path):
    manifest(0.0, 10.0).write(tmp_path)

    row = json.loads((tmp_path / "manifest.json").read_text())["slides"][0]

    assert set(row) == {"file", "change_at", "reason", "rect", "rect_rule", "layout"}


def test_a_manifest_with_no_slides_has_no_intervals():
    assert manifest(duration=40.0).intervals() == []


def test_instants_that_do_not_increase_are_refused(tmp_path):
    written = manifest(0.0, 10.0)
    written.slides = [slide(1, 10.0), slide(2, 5.0)]

    with pytest.raises(ManifestError, match="strictly increasing"):
        written.write(tmp_path)


def test_an_instant_at_the_media_duration_is_refused(tmp_path):
    with pytest.raises(ManifestError, match="no interval"):
        manifest(0.0, 40.0, duration=40.0).write(tmp_path)


def test_two_rows_for_one_file_are_refused(tmp_path):
    written = manifest(0.0, 10.0)
    written.slides = [slide(1, 0.0, file="001.jpg"), slide(2, 10.0, file="001.jpg")]

    with pytest.raises(ManifestError, match="appears twice"):
        written.write(tmp_path)


# --- numbering -------------------------------------------------------------


def test_numbering_is_three_digits_up_to_nine_hundred_and_ninety_nine():
    assert slide_filename(1, of=7) == "001.jpg"
    assert slide_filename(42, of=210) == "042.jpg"
    assert slide_filename(999, of=999) == "999.jpg"
    assert slide_number_width(0) == 3


def test_numbering_widens_only_past_nine_hundred_and_ninety_nine():
    assert slide_filename(1, of=1000) == "0001.jpg"
    assert slide_number_width(1000) == 4


def test_a_slide_number_starts_at_one():
    with pytest.raises(ValueError):
        slide_filename(0, of=10)


# --- a manifest the tool cannot act on -------------------------------------


def test_a_missing_manifest_says_which_path_it_looked_at(tmp_path):
    with pytest.raises(ManifestError, match="manifest.json does not exist"):
        Manifest.read(tmp_path)


def test_a_manifest_that_is_not_json_is_refused(tmp_path):
    (tmp_path / "manifest.json").write_text("{not json")

    with pytest.raises(ManifestError, match="not readable JSON"):
        Manifest.read(tmp_path)


def test_a_schema_this_build_does_not_read_stops_rather_than_guessing(tmp_path):
    manifest(0.0).write(tmp_path)
    path = tmp_path / "manifest.json"
    document = json.loads(path.read_text())
    document["schema_version"] = 99
    path.write_text(json.dumps(document))

    with pytest.raises(ManifestError, match="schema"):
        Manifest.read(tmp_path)


def test_a_duration_of_zero_is_refused(tmp_path):
    with pytest.raises(ManifestError, match="duration"):
        manifest(duration=0.0).write(tmp_path)
