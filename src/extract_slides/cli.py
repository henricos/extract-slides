"""The `typer` application: parsing, dispatch and exit codes. No logic.

The surface is ADR 0002's stage pipeline behind a verbless default path:

    extract-slides URL              the whole pipeline, resuming
    extract-slides detect DIR       one stage of it, against an existing run

What makes the common case one word and a URL is that **a first token which is
not a known subcommand is the target**, dispatched to a hidden default command.
The measured cost of that is a bare token colliding with a subcommand name —
`extract-slides crop` meaning a local file called `crop` — and it fails
loudly asking for `DIR` rather than guessing. Write `./crop` for that case.

Every command that touches an output directory ends in the same three calls:
read the manifest, ask `pipeline` for a plan, walk it. What distinguishes them
is only which stages they invalidate — nothing for the resuming paths, the
named stage for a stage command — so the chaining and the resume semantics are
decided in one place rather than once per command.

`rich_markup_mode=None` is what keeps `--help` in click's plain two-column
form. Note that `typer` vendors click privately, so the group subclass below
goes through `typer.core.TyperGroup` and overrides only standard `Group`
methods.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, NoReturn

import typer

from extract_slides import __version__, pipeline
from extract_slides.manifest import Manifest, ManifestError
from extract_slides.pipeline import Stage
from extract_slides.reporting import ReportFormat, Reporter, StageLog

PROG = "extract-slides"

#: Hidden, so that `--help` shows the two ways of invoking the tool rather
#: than a command nobody types.
DEFAULT_COMMAND = "_default"

#: ADR 0002 names one failing exit code, and click already uses it for a
#: usage error. Keeping a single one means an unattended caller has one
#: number to check.
EXIT_FAILURE = 2

#: click's own base class for every parsing failure. It has no public import
#: path here, because `typer` vendors click as a private module — and the
#: `click` that *is* importable in this environment, pulled in transitively
#: by `huggingface-hub` and `httpx`, is a different module object whose
#: exception classes would catch nothing. Reaching it through a public
#: `typer` symbol avoids both traps.
UsageError = typer.BadParameter.__bases__[0]


def _requested_format(argv: Sequence[str]) -> ReportFormat:
    """Read `--report` straight off the argv, for when parsing never finished."""
    for index, token in enumerate(argv):
        if token == "--report" and index + 1 < len(argv):
            value = argv[index + 1]
        elif token.startswith("--report="):
            value = token.split("=", 1)[1]
        else:
            continue
        if value == ReportFormat.json.value:
            return ReportFormat.json
    return ReportFormat.text


def _collision_hint(argv: Sequence[str], commands: dict[str, Any]) -> str | None:
    """The one ambiguity the verbless default path costs, named out loud.

    `extract-slides crop` is a command missing its directory, but it is also
    what someone means who has a local file called `crop`. ADR 0002 accepts
    the ambiguity and requires the failure to be loud; click already names
    `DIR`, and this adds the escape. Exactly one bare token is the whole
    scenario, so the test is that narrow and never fires on a real mistake.
    """
    if len(argv) != 1:
        return None
    token = argv[0]
    if token.startswith("-") or token not in commands:
        return None
    return (
        f"If you meant a file or directory called {token!r}, write ./{token} — "
        f"a bare {token} is this tool's {token} command."
    )


class RootGroup(typer.core.TyperGroup):
    """Makes the bare root a target rather than a missing subcommand."""

    def parse_args(self, ctx, args: list[str]) -> list[str]:
        if args and not args[0].startswith("-") and args[0] not in self.commands:
            args = [DEFAULT_COMMAND, *args]
        return super().parse_args(ctx, args)

    def list_commands(self, ctx) -> list[str]:
        return [name for name in super().list_commands(ctx) if name != DEFAULT_COMMAND]

    def format_usage(self, ctx, formatter) -> None:
        formatter.write_usage(ctx.command_path, "[OPTIONS] URL | DIR")
        formatter.write_usage(ctx.command_path, "COMMAND [ARGS]...", prefix="       ")

    def main(self, *args: Any, **kwargs: Any) -> Any:
        """Put a parsing failure through the same contract a run failure uses.

        Left to click, a bad command line prints a message and exits 2 —
        which under `--report json` leaves an unattended caller with exit 2
        and nothing on stdout to parse, although ADR 0002 promises a
        machine-readable object on failure. So the framework still does the
        parsing and still writes the message a person reads; only the
        handling of what it raises is ours.
        """
        if not kwargs.get("standalone_mode", True):
            return super().main(*args, **kwargs)
        argv = self._invoked_with(args, kwargs)
        kwargs["standalone_mode"] = False
        try:
            result = super().main(*args, **kwargs)
        except UsageError as error:
            self._report_usage_error(error, argv)
            sys.exit(EXIT_FAILURE)
        except typer.Abort:
            typer.echo("Aborted.", err=True)
            sys.exit(1)
        sys.exit(result if isinstance(result, int) else 0)

    @staticmethod
    def _invoked_with(args: tuple[Any, ...], kwargs: dict[str, Any]) -> list[str]:
        """What was actually typed, however the caller handed it over."""
        argv = kwargs.get("args", args[0] if args else None)
        return list(sys.argv[1:] if argv is None else argv)

    def _report_usage_error(self, error: Any, argv: Sequence[str]) -> None:
        error.show()
        hint = _collision_hint(argv, self.commands)
        if hint:
            typer.echo(hint, err=True)
        # click has already narrated; this only adds the document the JSON
        # contract owes an unattended caller, and does nothing under text.
        Reporter(_requested_format(argv)).failure(
            error.format_message(), code="usage", hint=hint, narrate=False
        )


app = typer.Typer(
    name=PROG,
    cls=RootGroup,
    rich_markup_mode=None,
    add_completion=False,
    no_args_is_help=True,
    help=(
        "Reconstruct a presentation from a recorded talk: the transcript of what "
        "was said, plus one screenshot of every distinct slide that was shown.\n"
        "\n"
        "Given a URL, runs the whole pipeline and resumes whatever an earlier run "
        "already finished. The stage commands redo one step against an existing "
        "output directory without repeating the expensive ones."
    ),
    epilog=(
        "Stages, in order: acquire, transcribe, detect, crop, pair. "
        "A run captures generously and leaves surplus behind on purpose; "
        "drop and prune are the second pass that removes it."
    ),
)

# Flags shared across commands. They are declared per command rather than on
# the root, because the documented form puts them after the target
# (`extract-slides URL --force`) and a root option would have to come before it.
OUTPUT = typer.Option(
    Path("./out"),
    "--out",
    "-o",
    metavar="DIR",
    help="Where to create the output directory.",
)
FORCE = typer.Option(
    False, "--force", help="Ignore what an earlier run finished and recompute."
)
REPORT = typer.Option(
    ReportFormat.text,
    "--report",
    help="Final report format. Use json for unattended and agent runs.",
)
NO_CROP = typer.Option(
    False, "--no-crop", help="Keep the full frame. Always safe, never degraded."
)
ROI = typer.Option(
    None,
    "--roi",
    metavar="X,Y,W,H",
    help="Crop to this region, as four normalised floats, instead of deriving one.",
)
DIRECTORY = typer.Argument(
    ..., metavar="DIR", help="Output directory from an earlier run."
)


def _not_implemented_yet(reporter: Reporter, what: str, **details: str) -> NoReturn:
    """Every command body until the ticket that fills it in.

    The shell is real — dispatch, resume, chaining, streams and exit codes are
    what they will be — so a caller wiring against it now is wiring against the
    final contract. What is missing is the work itself, and saying so is better
    than a stub that returns something plausible.
    """
    reporter.failure(
        f"{what} is not implemented yet.",
        code="not_implemented",
        hint="This build carries the output directory and the stage registry; "
        "the stages themselves are not in it yet.",
        details=details,
    )
    raise typer.Exit(code=EXIT_FAILURE)


def _no_stage_yet(stage: Stage, log: StageLog) -> str:
    """The stage runner this build hands the registry.

    Every stage is registered and every stage refuses. What the registry then
    does around that refusal — which stages it reused first, which it would
    have chained into — is the part this build is here to get right.
    """
    raise pipeline.StageNotImplemented(stage)


def _existing_run(reporter: Reporter, directory: Path) -> Manifest:
    """The manifest of the run a command was pointed at.

    Every command but the two that take a URL is handed a directory, so a
    directory holding no run is a mistake worth naming: the alternative is
    starting the pipeline at `acquire` against a target nobody supplied.
    """
    if not Manifest.path_in(directory).exists():
        reporter.failure(
            f"There is no run in {directory} to work on.",
            code="no_run",
            hint="Run extract-slides URL to create one.",
            details={"directory": str(directory)},
        )
        raise typer.Exit(code=EXIT_FAILURE)
    try:
        return Manifest.read(directory)
    except ManifestError as error:
        reporter.failure(
            f"The manifest in {directory} cannot be read: {error}",
            code="manifest_invalid",
            hint="It is the tool's own file. A hand edit that breaks it is not "
            "recoverable here, and guessing at what it meant would lose a slide.",
            details={"directory": str(directory)},
        )
        raise typer.Exit(code=EXIT_FAILURE) from error


def _run_pipeline(
    reporter: Reporter,
    *,
    directory: Path | None,
    invalidated: Sequence[Stage] = (),
    through: Stage | None = None,
    target: str | None = None,
) -> None:
    """Plan the run, walk it, and report — the one path every command takes.

    `directory` is `None` when there is no run yet, which is every invocation
    that starts from a URL. Nothing is then recorded as finished, so the plan
    begins at `acquire`, which is the right answer for a target nobody has
    fetched.

    Each stage is recorded as it finishes rather than at the end of the walk,
    so a run that fails at stage four keeps what the first three did.
    """
    document = _existing_run(reporter, directory) if directory else None

    def record(stage: Stage, gist: str) -> None:
        if document is None or directory is None:
            return
        document.record_stage(stage.value, gist)
        document.write(directory)

    completed = pipeline.completed_from(document.completed_stages()) if document else {}
    steps = pipeline.plan(completed=completed, invalidated=invalidated, through=through)
    try:
        pipeline.execute(
            steps, reporter=reporter, run_stage=_no_stage_yet, on_complete=record
        )
    except pipeline.StageNotImplemented as error:
        details = {"directory": str(directory)} if directory else {"target": target or ""}
        _not_implemented_yet(reporter, error.stage.value, **details)

    slides = len(document.slides) if document else 0
    rows = [("slides", str(slides))]
    if directory:
        rows.append(("output", str(directory)))
    reporter.report(
        rows=rows,
        payload={
            "status": "ok",
            "directory": str(directory) if directory else None,
            "slides": slides,
            "duration": document.run.duration if document else None,
            "stages": {
                step.stage.value: "reused" if step.reused else "ran" for step in steps
            },
        },
    )


def _redo(report: ReportFormat, directory: Path, stage: Stage) -> None:
    """Every stage command: name a stage to redo, and chain forward from it."""
    _run_pipeline(Reporter(report), directory=directory, invalidated=(stage,))


def _version(value: bool) -> None:
    if value:
        typer.echo(f"{PROG} {__version__}")
        raise typer.Exit()


@app.callback()
def root(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version,
        is_eager=True,
        help="Show the version and exit.",
    ),
) -> None:
    pass


@app.command(DEFAULT_COMMAND, hidden=True)
def default_path(
    target: str = typer.Argument(
        ...,
        metavar="URL | DIR",
        help="A video URL, a local video file, or an output directory to continue.",
    ),
    output: Path = OUTPUT,
    force: bool = FORCE,
    no_crop: bool = NO_CROP,
    roi: str | None = ROI,
    report: ReportFormat = REPORT,
) -> None:
    """Run every stage, resuming whatever an earlier run already finished."""
    _run_pipeline(
        Reporter(report),
        directory=Path(target) if Path(target).is_dir() else None,
        invalidated=pipeline.ORDER if force else (),
        target=target,
    )


@app.command()
def fetch(
    url: str = typer.Argument(
        ..., metavar="URL", help="A video URL or a local video file."
    ),
    output: Path = OUTPUT,
    force: bool = FORCE,
    report: ReportFormat = REPORT,
) -> None:
    """Step 1: download the video and produce the transcript."""
    # `directory=None` because resolving a URL to an output directory is the
    # acquirer's job (#27), so there is nothing here to read a manifest from
    # yet. Until then `fetch` cannot resume what an earlier `fetch` finished,
    # although the surface says it does.
    _run_pipeline(
        Reporter(report),
        directory=None,
        invalidated=(Stage.acquire,) if force else (),
        through=Stage.transcribe,
        target=url,
    )


@app.command()
def transcribe(
    directory: Path = DIRECTORY,
    force: bool = FORCE,
    report: ReportFormat = REPORT,
) -> None:
    """Redo the transcript without re-downloading; re-runs pair.

    The video and the raw caption stay where they are, so this costs
    the transcription and nothing else.
    """
    _redo(report, directory, Stage.transcribe)


@app.command()
def detect(
    directory: Path = DIRECTORY,
    force: bool = FORCE,
    report: ReportFormat = REPORT,
) -> None:
    """Redo slide detection; re-runs crop and pair.

    Detection changes which slides exist, so the crop and the manifest
    have to follow it rather than be left describing images that are no
    longer there.
    """
    _redo(report, directory, Stage.detect)


@app.command()
def crop(
    directory: Path = DIRECTORY,
    force: bool = FORCE,
    no_crop: bool = NO_CROP,
    roi: str | None = ROI,
    report: ReportFormat = REPORT,
) -> None:
    """Redo the crop; re-runs pair.

    The crop measures movement between samples half a second apart, so
    it re-reads the source video rather than the captures, and needs
    that video still in the output directory. It deletes duplicates the
    first test could not see, which is why it re-runs pair.
    """
    _redo(report, directory, Stage.crop)


@app.command()
def pair(
    directory: Path = DIRECTORY,
    force: bool = FORCE,
    report: ReportFormat = REPORT,
) -> None:
    """Regenerate presentation.md from the manifest.

    The command to run after editing the transcript by hand. There is
    no stored assignment to redo: the manifest holds an instant per
    slide and every interval is derived at read time.
    """
    _redo(report, directory, Stage.pair)


@app.command()
def drop(
    directory: Path = DIRECTORY,
    slides: list[int] = typer.Argument(
        None, metavar="[N]...", help="Slide numbers to delete. Omit to reconcile."
    ),
    report: ReportFormat = REPORT,
) -> None:
    """Delete slides and renumber, or reconcile against disk.

    With no numbers it reconciles the output against whatever is on disk,
    which is what to run after deleting images in a file manager. Either
    way it prints the old-to-new mapping, because a slide number is not a
    stable identity across a deletion.
    """
    _not_implemented_yet(Reporter(report), "drop", target=str(directory))


@app.command()
def prune(
    directory: Path = DIRECTORY,
    apply: bool = typer.Option(
        False, "--apply", help="Delete what the model names, instead of only listing it."
    ),
    yes: bool = typer.Option(
        False, "--yes", help="Skip the confirmation --apply would otherwise ask for."
    ),
    report: ReportFormat = REPORT,
) -> None:
    """Ask a vision model to name the surplus; lists by default.

    Without --apply it writes the list and deletes nothing. A key being
    configured enables this command and enables nothing else: no run
    deletes anything because credentials happen to exist.
    """
    _not_implemented_yet(Reporter(report), "prune", target=str(directory))


@app.command()
def prepare(report: ReportFormat = REPORT) -> None:
    """Download the speech-to-text model now, not on the first run.

    The weights are hundreds of megabytes and otherwise arrive during
    the first real run, where the wait looks like a hang. They live in
    the shared Hugging Face cache, so a machine that already holds them
    downloads nothing.
    """
    _not_implemented_yet(Reporter(report), "prepare")


@app.command("self-update")
def self_update(
    yt_dlp: bool = typer.Option(
        False,
        "--yt-dlp",
        help="Update only the downloader, leaving the rest of the stack pinned.",
    ),
    report: ReportFormat = REPORT,
) -> None:
    """Update the tool and its dependencies.

    Everything ships pinned except the downloader, which must not be:
    YouTube changes on its own schedule and a pin there stops working in
    an unpredictable number of weeks. --yt-dlp updates that alone,
    leaving the stack the spikes measured where it is.
    """
    _not_implemented_yet(Reporter(report), "self-update")


def main() -> None:
    app(prog_name=PROG)
