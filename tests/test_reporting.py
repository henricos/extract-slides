"""The shape of the tool's output, per ADR 0002.

An executed stage is an indented block; a reused stage is one line naming
`--force`; the running log carries no borders and the final report does;
under `--report json` the document is the only thing on stdout.
"""

import io
import json

import pytest

from extract_slides.reporting import ReportFormat, Reporter


@pytest.fixture
def streams():
    return io.StringIO(), io.StringIO()


def reporter(fmt, streams):
    out, err = streams
    return Reporter(fmt, stdout=out, stderr=err, width=100)


def test_an_executed_stage_renders_as_an_indented_block(streams):
    out, err = streams
    r = reporter(ReportFormat.text, streams)
    with r.stage("acquire", position=1, of=5) as log:
        log.field("source", "https://youtu.be/abc")
        log.done("acquired in 38s")

    lines = out.getvalue().split("\n")
    assert lines[0] == "", "a stage block opens with a blank line"
    assert lines[1].strip() == "1/5  acquire"
    assert lines[2].startswith("       "), "fields are indented under the head"
    assert "source" in lines[2] and "https://youtu.be/abc" in lines[2]
    assert "acquired in 38s" in lines[3]
    assert err.getvalue() == ""


def test_a_reused_stage_renders_as_one_line_naming_force(streams):
    out, _ = streams
    r = reporter(ReportFormat.text, streams)
    r.reused("transcribe", position=2, of=5, gist="YouTube caption")

    body = out.getvalue().strip()
    assert body.count("\n") == 0, "a reused stage is one line, not a block"
    assert "2/5" in body
    assert "transcribe" in body
    assert "reused" in body
    assert "YouTube caption" in body
    assert "--force" in body, "resuming is never silent about how to undo it"


def test_a_block_and_the_line_after_it_are_kept_apart(streams):
    out, _ = streams
    r = reporter(ReportFormat.text, streams)
    with r.stage("acquire", position=1, of=5) as log:
        log.done("acquired in 38s")
    r.reused("transcribe", position=2, of=5, gist="YouTube caption")

    lines = out.getvalue().split("\n")
    assert lines[3] == "", "a block does not run straight into the line below it"
    assert "2/5" in lines[4]


def test_reuse_lines_stack_against_each_other(streams):
    out, _ = streams
    r = reporter(ReportFormat.text, streams)
    for position, name in enumerate(["acquire", "transcribe", "detect"], start=1):
        r.reused(name, position=position, of=5, gist="already done")

    body = out.getvalue().strip()
    assert body.count("\n") == 2, "a fully resumed run stays compact"


def test_the_running_log_carries_no_borders(streams, borders):
    out, _ = streams
    r = reporter(ReportFormat.text, streams)
    with r.stage("detect", position=3, of=5) as log:
        log.field("kept", "216 captures")
        log.note("11 flagged as possible duplicates", hint="remove them with drop")
        log.done("detected in 2m 51s")
    r.reused("crop", position=4, of=5, gist="auto")

    assert not (borders & set(out.getvalue()))


def test_the_final_report_is_a_bordered_panel(streams, borders):
    out, _ = streams
    r = reporter(ReportFormat.text, streams)
    r.report(rows=[("slides", "216"), ("output", "./out/talk-abc")], payload={"status": "ok"})

    body = out.getvalue()
    assert borders & set(body), "the final report is the one place a border earns its keep"
    assert "slides" in body and "216" in body


def test_under_json_the_document_is_the_only_thing_on_stdout(streams):
    out, err = streams
    r = reporter(ReportFormat.json, streams)
    with r.stage("acquire", position=1, of=5) as log:
        log.field("source", "https://youtu.be/abc")
        log.done("acquired in 38s")
    r.reused("transcribe", position=2, of=5, gist="YouTube caption")
    r.report(rows=[("slides", "216")], payload={"status": "ok", "slides": 216})

    assert json.loads(out.getvalue()) == {"status": "ok", "slides": 216}
    narration = err.getvalue()
    assert "acquire" in narration and "reused" in narration


def test_under_json_a_failure_writes_a_machine_readable_object(streams):
    out, err = streams
    r = reporter(ReportFormat.json, streams)
    r.failure(
        "yt-dlp could not download the video",
        code="download_failed",
        hint="Run extract-slides self-update --yt-dlp",
    )

    assert json.loads(out.getvalue()) == {
        "status": "error",
        "error": "download_failed",
        "message": "yt-dlp could not download the video",
        "hint": "Run extract-slides self-update --yt-dlp",
    }
    assert "yt-dlp could not download the video" in err.getvalue()


def test_under_text_a_failure_stays_off_stdout(streams):
    out, err = streams
    r = reporter(ReportFormat.text, streams)
    r.failure("yt-dlp could not download the video", code="download_failed")

    assert out.getvalue() == "", "an error is never part of the document"
    assert "yt-dlp could not download the video" in err.getvalue()


def test_a_failure_object_names_what_was_being_worked_on(streams):
    out, _ = streams
    r = reporter(ReportFormat.json, streams)
    r.failure(
        "The default path is not implemented yet.",
        code="not_implemented",
        details={"target": "https://youtu.be/jqpdveK2XAU"},
    )

    document = json.loads(out.getvalue())
    assert document["target"] == "https://youtu.be/jqpdveK2XAU"
    assert document["status"] == "error"


def test_empty_details_add_nothing_to_the_failure_object(streams):
    out, _ = streams
    r = reporter(ReportFormat.json, streams)
    r.failure("prepare is not implemented yet.", code="not_implemented", details={})

    assert set(json.loads(out.getvalue())) == {"status", "error", "message"}
