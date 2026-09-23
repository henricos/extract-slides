"""How the tool talks: two streams, a block per stage, a line per reuse.

ADR 0002 fixes the shape and this module is the only place that knows it:

- **A stage that ran is a block** — a blank line, a head carrying the stage's
  position in the pipeline, then indented fields. **A stage that was reused is
  one line**, and it names `--force`, because resuming by default is only
  honest if it is never silent.
- **The running log has no borders.** The final report does: it is a discrete
  block of result, read at a glance, distinct from the log above it. ADR 0001's
  ban on bordered panels is scoped to `--help`.
- **Under `--report json` the document owns stdout** and every word meant for a
  person goes to stderr. The prototype printed progress to stdout and corrupted
  the JSON, which made the unattended invocation unusable.

Errors are on stderr under both formats — an error is never part of the
document — with a machine-readable object joining them on stdout under JSON.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from enum import Enum
from typing import Any, TextIO

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

#: Fields sit under the head rather than beside it, so a stage that ran is
#: impossible to confuse with one that did not.
INDENT = " " * 7


class ReportFormat(str, Enum):
    """`--report`. `json` is for unattended and agent runs."""

    text = "text"
    json = "json"


class StageLog:
    """The inside of one stage's block. Handed out by `Reporter.stage`."""

    def __init__(self, console: Console) -> None:
        self._console = console

    def field(self, label: str, value: str) -> None:
        """One `label   value` row of the block."""
        self._console.print(f"{INDENT}[dim]{label:<10}[/dim] {value}")

    def note(self, message: str, hint: str | None = None) -> None:
        """Something the operator should see but that is not a failure."""
        self._console.print(f"{INDENT}[bold yellow]![/bold yellow] {message}")
        if hint:
            self._console.print(f"{INDENT}  [dim]{hint}[/dim]")

    def done(self, message: str) -> None:
        """Closes the block."""
        self._console.print(f"{INDENT}[green]✓[/green] [dim]{message}[/dim]")


class Reporter:
    """Everything the tool prints, over the two streams ADR 0002 separates."""

    def __init__(
        self,
        report_format: ReportFormat = ReportFormat.text,
        *,
        stdout: TextIO | None = None,
        stderr: TextIO | None = None,
        width: int | None = None,
    ) -> None:
        self.format = report_format
        self._out = Console(file=stdout, highlight=False, soft_wrap=True, width=width)
        self._err = Console(
            file=stderr, stderr=stderr is None, highlight=False, soft_wrap=True, width=width
        )
        self._last_was_block = False

    @property
    def _narration(self) -> Console:
        """Where human words go. Under JSON, stdout is reserved for the document."""
        return self._err if self.format is ReportFormat.json else self._out

    @contextmanager
    def stage(self, name: str, *, position: int, of: int) -> Iterator[StageLog]:
        """A stage that is actually running: a block, with air around it."""
        console = self._narration
        console.print(f"\n[bold cyan]{position}/{of}[/bold cyan]  [bold]{name}[/bold]")
        yield StageLog(console)
        self._last_was_block = True

    def reused(self, name: str, *, position: int, of: int, gist: str) -> None:
        """A stage whose earlier work still stands: one line, naming `--force`.

        Reuse lines stack against each other, so a fully resumed run stays
        five compact lines rather than five spaced-out ones; the blank line
        only appears where a block ended.
        """
        if self._last_was_block:
            self._narration.print("")
            self._last_was_block = False
        self._narration.print(
            f"[dim]{position}/{of}[/dim]  {name:<11}[blue]reused[/blue]   "
            f"[dim]{gist} · recompute with --force[/dim]"
        )

    def report(
        self, *, rows: Sequence[tuple[str, str]], payload: Mapping[str, Any]
    ) -> None:
        """The final report: the JSON document, or the one bordered panel."""
        if self.format is ReportFormat.json:
            self._write_document(payload)
            return
        grid = Table.grid(padding=(0, 2))
        grid.add_column(style="dim", justify="left", min_width=10)
        grid.add_column(overflow="fold")
        for label, value in rows:
            grid.add_row(label, value)
        self._out.print("")
        self._out.print(
            Panel(
                grid,
                title="[bold]Done[/bold]",
                title_align="left",
                border_style="dim",
                padding=(1, 2),
                expand=False,
            )
        )

    def failure(
        self,
        message: str,
        *,
        code: str,
        hint: str | None = None,
        details: Mapping[str, Any] | None = None,
        narrate: bool = True,
    ) -> None:
        """A failed run. Never part of the document; always on stderr.

        `details` name what was being worked on — the target, the
        directory — so an unattended caller learns which run failed
        without parsing the message written for a person.

        `narrate=False` is for a failure somebody else has already put on
        stderr, such as a parsing error the CLI framework reports itself.
        The machine-readable object still has to be written, and the shape
        of it should be defined in one place only.
        """
        if narrate:
            self._err.print(f"\n[bold red]✗[/bold red] {message}")
            if hint:
                self._err.print(f"  [dim]{hint}[/dim]")
        if self.format is ReportFormat.json:
            document: dict[str, Any] = {
                "status": "error",
                "error": code,
                "message": message,
            }
            if hint:
                document["hint"] = hint
            document.update(details or {})
            self._write_document(document)

    def _write_document(self, payload: Mapping[str, Any]) -> None:
        self._out.file.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
