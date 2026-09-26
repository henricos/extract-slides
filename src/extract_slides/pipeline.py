"""The stage registry: who depends on whom, and what that implies.

ADR 0002 decided three things about running stages, and all three fall out of
one declaration:

- **A stage command chains forward** into the stages that depend on it.
- **Resume by default, never silently.** A stage whose work still stands is
  reused and says so, naming `--force`.
- **`--force` works per stage**, so one stage can be recomputed without
  discarding the rest.

Rather than writing those rules three times, each stage declares what it needs
finished before it can run (`DEPENDS_ON`) and the rest is read off that graph.
The graph is built now, before any stage exists, because it changes shape every
time a stage is born: a `detect` written before `crop` existed would chain into
nothing, and adding the edge afterwards is the kind of rework nobody remembers.

**What a command invalidates is what distinguishes it.** The verbless default
path and `fetch` resume: they invalidate nothing, and their `--force`
invalidates everything they cover. A stage command names a stage to redo, so it
invalidates that one — which is also why `pair DIR` is the command to run after
editing the transcript by hand, and why it cannot be a stage that reuses.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import Enum

from extract_slides.reporting import Reporter, StageLog


class Stage(str, Enum):
    """The five stages, in the order they run."""

    acquire = "acquire"
    transcribe = "transcribe"
    detect = "detect"
    crop = "crop"
    pair = "pair"


#: The pipeline, in order. Positions in the reporter's `n/5` head are positions
#: in this tuple, so a stage command that touches only the tail still says where
#: in the run it is.
ORDER: tuple[Stage, ...] = tuple(Stage)

#: What each stage needs finished before it can run. Every rule this module
#: offers is read off this mapping and nothing else.
#:
#: `pair` depends on `crop` and not only on `detect` because ADR 0006 puts the
#: second duplicate test inside the crop, which deletes: 241 images to 216
#: across the sweep set. A pairing made before that runs describes slides that
#: are about to stop existing.
DEPENDS_ON: dict[Stage, tuple[Stage, ...]] = {
    Stage.acquire: (),
    Stage.transcribe: (Stage.acquire,),
    Stage.detect: (Stage.acquire,),
    Stage.crop: (Stage.detect,),
    Stage.pair: (Stage.transcribe, Stage.detect, Stage.crop),
}


class StageNotImplemented(NotImplementedError):
    """A stage that has to run, in a build that cannot run it yet.

    The shell is real — dispatch, resume, chaining, streams and exit codes are
    what they will be — so a caller wiring against it is wiring against the
    final contract. What is missing is the work itself, and saying which stage
    is missing beats a stub that returns something plausible.
    """

    def __init__(self, stage: Stage) -> None:
        super().__init__(f"{stage.value} is not implemented yet")
        self.stage = stage


@dataclass(frozen=True)
class Step:
    """One stage's place in a planned run."""

    stage: Stage
    position: int
    of: int
    reused: bool
    #: What the reuse line says about the work being kept. Empty on a step that
    #: is going to run, which has nothing to describe yet.
    gist: str = ""


def completed_from(recorded: Mapping[str, str]) -> dict[Stage, str]:
    """Read a manifest's stage records as stages this build knows.

    A name this build does not know is carried by the manifest and ignored
    here: a directory written by a newer version should not become unreadable,
    and a stage that does not exist cannot be reused anyway.
    """
    known: dict[Stage, str] = {}
    for name, gist in recorded.items():
        try:
            known[Stage(name)] = gist
        except ValueError:
            continue
    return known


def plan(
    *,
    completed: Mapping[Stage, str],
    invalidated: Iterable[Stage] = (),
    through: Stage | None = None,
) -> list[Step]:
    """Decide, stage by stage, what runs and what is reused.

    A stage runs when it was invalidated, when nothing recorded it as finished,
    or when anything it depends on is running. That last clause is the whole
    forward chain ADR 0002 requires — `detect` re-runs `crop` and `pair`,
    `pair` stops at itself — applied without being stated anywhere, because
    the stages are walked in order and a stage that runs is marked stale for
    the ones behind it.

    `through` stops the plan after a stage, which is what makes `fetch` the
    first two stages of the pipeline rather than a sixth stage of its own.
    """
    stale = set(invalidated)
    steps: list[Step] = []
    for position, stage in enumerate(ORDER, start=1):
        runs = (
            stage in stale
            or stage not in completed
            or any(dependency in stale for dependency in DEPENDS_ON[stage])
        )
        if runs:
            stale.add(stage)
        steps.append(
            Step(
                stage=stage,
                position=position,
                of=len(ORDER),
                reused=not runs,
                gist="" if runs else completed[stage],
            )
        )
        if stage is through:
            break
    return steps


#: What a stage does when it runs: narrate into its block and return the gist
#: the next run's reuse line will print.
StageRunner = Callable[[Stage, StageLog], str]


def execute(
    steps: Iterable[Step],
    *,
    reporter: Reporter,
    run_stage: StageRunner,
    on_complete: Callable[[Stage, str], None] = lambda stage, gist: None,
) -> None:
    """Walk the plan: a line per reused stage, a block per stage that runs.

    `on_complete` is called the moment a stage returns, not when the walk ends,
    so that a run which fails at stage four keeps what stages one to three
    finished. Collecting the gists and handing them back at the end would lose
    exactly the case resume exists for: ADR 0002's interrupted run that must
    not start over.
    """
    for step in steps:
        if step.reused:
            reporter.reused(
                step.stage.value, position=step.position, of=step.of, gist=step.gist
            )
            continue
        with reporter.stage(step.stage.value, position=step.position, of=step.of) as log:
            on_complete(step.stage, run_stage(step.stage, log))
