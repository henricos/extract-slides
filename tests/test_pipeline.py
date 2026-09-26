"""The stage registry: the graph, and the three rules read off it.

ADR 0002 states the forward chain, resume-by-default and per-stage `--force`
as three separate consequences. They are one declaration here, so what is
asserted is that the declaration reproduces all three — including the chain
exactly as the ADR writes it, stage by stage.
"""

import io

import pytest

from extract_slides.pipeline import (
    DEPENDS_ON,
    ORDER,
    Stage,
    StageNotImplemented,
    completed_from,
    execute,
    plan,
)
from extract_slides.reporting import ReportFormat, Reporter

ALL = {stage: f"{stage.value} done" for stage in ORDER}


def stages_that_run(steps):
    return [step.stage for step in steps if not step.reused]


def stages_reused(steps):
    return [step.stage for step in steps if step.reused]


# --- the graph -------------------------------------------------------------


def chain_after(stage):
    """The stages a plan re-runs behind `stage`, on a run where all are done."""
    return tuple(
        step.stage
        for step in plan(completed=ALL, invalidated=[stage])
        if not step.reused and step.stage is not stage
    )


def test_the_chain_is_the_one_adr_0002_writes():
    assert chain_after(Stage.acquire) == (Stage.transcribe, Stage.detect, Stage.crop, Stage.pair)
    assert chain_after(Stage.transcribe) == (Stage.pair,)
    assert chain_after(Stage.detect) == (Stage.crop, Stage.pair)
    assert chain_after(Stage.crop) == (Stage.pair,)
    assert chain_after(Stage.pair) == (), "only pair stops at itself"


def test_every_stage_declares_dependencies_that_come_before_it():
    """The premise the whole registry rests on, so a sixth stage cannot break it.

    Plans are walked in pipeline order and decide each stage against what is
    already stale, which is only sound while a stage's dependencies precede it.
    """
    for position, stage in enumerate(ORDER):
        for dependency in DEPENDS_ON[stage]:
            assert ORDER.index(dependency) < position, f"{stage} needs {dependency} first"


# --- resume by default -----------------------------------------------------


def test_a_finished_run_reuses_every_stage():
    steps = plan(completed=ALL)

    assert stages_that_run(steps) == []
    assert [step.gist for step in steps] == [f"{stage.value} done" for stage in ORDER]


def test_a_stage_nothing_recorded_runs_and_so_does_everything_after_it():
    completed = {stage: "done" for stage in ORDER if stage is not Stage.detect}

    steps = plan(completed=completed)

    assert stages_that_run(steps) == [Stage.detect, Stage.crop, Stage.pair]
    assert stages_reused(steps) == [Stage.acquire, Stage.transcribe]


def test_a_stage_is_placed_by_its_position_in_the_whole_pipeline():
    steps = plan(completed=ALL)

    assert [(step.position, step.of) for step in steps] == [(1, 5), (2, 5), (3, 5), (4, 5), (5, 5)]


# --- what a command invalidates --------------------------------------------


def test_invalidating_a_stage_re_runs_the_stages_that_depend_on_it():
    steps = plan(completed=ALL, invalidated=[Stage.detect])

    assert stages_that_run(steps) == [Stage.detect, Stage.crop, Stage.pair]


def test_forcing_one_stage_leaves_the_rest_of_the_run_alone():
    # This is "--force works per stage": the crop is recomputed without
    # discarding the download, the transcript or the detection.
    steps = plan(completed=ALL, invalidated=[Stage.crop])

    assert stages_reused(steps) == [Stage.acquire, Stage.transcribe, Stage.detect]
    assert stages_that_run(steps) == [Stage.crop, Stage.pair]


def test_forcing_the_whole_run_reuses_nothing():
    assert stages_reused(plan(completed=ALL, invalidated=ORDER)) == []


def test_a_plan_can_stop_after_a_stage():
    # `fetch` is the first two stages of the pipeline, not a sixth stage.
    steps = plan(completed={}, through=Stage.transcribe)

    assert [step.stage for step in steps] == [Stage.acquire, Stage.transcribe]


def test_a_recorded_stage_this_build_does_not_know_is_ignored():
    assert completed_from({"detect": "216 captures", "summarise": "from later"}) == {
        Stage.detect: "216 captures"
    }


# --- walking the plan ------------------------------------------------------


def reporter_over(streams):
    out, err = streams
    return Reporter(ReportFormat.text, stdout=out, stderr=err, width=100)


def test_a_reused_stage_is_announced_and_a_running_stage_gets_a_block():
    streams = io.StringIO(), io.StringIO()
    completed = {stage: f"{stage.value} done" for stage in ORDER if stage is not Stage.pair}
    recorded = []

    execute(
        plan(completed=completed),
        reporter=reporter_over(streams),
        run_stage=lambda stage, log: "1 document",
        on_complete=lambda stage, gist: recorded.append((stage, gist)),
    )

    log = streams[0].getvalue()
    assert recorded == [(Stage.pair, "1 document")], "a stage hands back the gist of its work"
    assert "acquire" in log and "reused" in log
    assert "--force" in log, "resuming is never silent about how to undo it"
    assert "5/5" in log


def test_a_stage_is_recorded_when_it_finishes_not_when_the_run_does():
    """ADR 0002's interrupted run must not start over.

    Collecting the gists and handing them back at the end would throw away
    everything a run finished before the stage that failed, which is exactly
    the case resume exists for.
    """
    streams = io.StringIO(), io.StringIO()
    recorded = []

    def run_until_detect(stage, log):
        if stage is Stage.detect:
            raise StageNotImplemented(stage)
        return f"{stage.value} done"

    with pytest.raises(StageNotImplemented):
        execute(
            plan(completed={}),
            reporter=reporter_over(streams),
            run_stage=run_until_detect,
            on_complete=lambda stage, gist: recorded.append(stage),
        )

    assert recorded == [Stage.acquire, Stage.transcribe], "what finished is kept"


def test_a_stage_that_cannot_run_stops_the_walk_where_it_is():
    streams = io.StringIO(), io.StringIO()

    def refuse(stage, log):
        raise StageNotImplemented(stage)

    with pytest.raises(StageNotImplemented) as refused:
        execute(plan(completed={}), reporter=reporter_over(streams), run_stage=refuse)

    assert refused.value.stage is Stage.acquire
    assert "transcribe" not in streams[0].getvalue(), "nothing after it is attempted"
