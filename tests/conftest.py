"""Shared fixtures for the suite.

`BORDERS` lives here as a fixture rather than a module constant because
importing `conftest` from a test file only works when the project root
happens to be on `sys.path`, which depends on where pytest was started.
"""

import pytest
from typer.testing import CliRunner

#: Box-drawing characters. ADR 0001 bans them from `--help` and ADR 0002
#: bans them from the running log, while the final report is the one place
#: a border earns its keep — so several tests ask the same question.
_BORDERS = set("╭╮╰╯│─┌┐└┘═║")


@pytest.fixture
def borders() -> set[str]:
    return _BORDERS


@pytest.fixture
def cli() -> CliRunner:
    return CliRunner()
