"""Seam 1: the CLI, in process, argv in and an exit code out.

Every test here enters through the framework's own runner rather than a
subprocess, so the whole surface stays as cheap to assert on as a function
call. No stage exists yet, so what is under test is the shell: how a token is
dispatched, how help reads, and which stream carries what.
"""

import json

import pytest
import typer

from extract_slides.cli import RootGroup, app

#: Every stage command, and what it wants when it is given nothing.
STAGE_COMMANDS = ["transcribe", "detect", "crop", "pair", "drop", "prune"]



def test_help_renders_in_the_plain_two_column_form(cli, borders):
    result = cli.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert not (borders & set(result.output)), "no bordered panels in --help"
    assert "Options:" in result.output
    assert "Commands:" in result.output
    # Two columns, indented: the flag on the left, its description on the right.
    assert any(
        line.startswith("  --help") and len(line.split()) > 1
        for line in result.output.splitlines()
    )


def test_help_lists_every_command_of_the_surface(cli):
    result = cli.invoke(app, ["--help"])

    for command in ["fetch", *STAGE_COMMANDS, "prepare", "self-update"]:
        assert f"  {command}" in result.output, f"{command} is missing from --help"


def test_help_does_not_list_the_hidden_default_command(cli):
    result = cli.invoke(app, ["--help"])

    assert "_default" not in result.output


def test_help_shows_both_ways_of_invoking_the_tool(cli):
    result = cli.invoke(app, ["--help"])

    assert "URL | DIR" in result.output, "the verbless default path is the common case"
    assert "COMMAND [ARGS]..." in result.output


def test_a_first_token_that_is_not_a_subcommand_is_the_target(cli):
    result = cli.invoke(app, ["https://youtu.be/jqpdveK2XAU", "--report", "json"])

    document = json.loads(result.stdout)
    assert document["target"] == "https://youtu.be/jqpdveK2XAU"


def test_a_local_directory_is_a_target_too(cli):
    result = cli.invoke(app, ["./out/a-talk-jqpdveK2XAU", "--report", "json"])

    assert json.loads(result.stdout)["target"] == "./out/a-talk-jqpdveK2XAU"


@pytest.mark.parametrize("command", STAGE_COMMANDS)
def test_a_bare_token_colliding_with_a_subcommand_fails_loudly(cli, command):
    result = cli.invoke(app, [command])

    assert result.exit_code == 2, f"{command} with no directory must not be guessed at"
    assert "DIR" in result.output + result.stderr, "the failure names what it wants"


def test_the_collision_failure_also_names_the_way_out(cli):
    result = cli.invoke(app, ["crop"])

    assert "./crop" in result.stderr, "the operator is told how to mean the file"


def test_fetch_collides_the_same_way_but_asks_for_a_url(cli):
    result = cli.invoke(app, ["fetch"])

    assert result.exit_code == 2
    assert "URL" in result.output + result.stderr
    assert "./fetch" in result.stderr


def test_a_real_mistake_gets_no_collision_hint(cli):
    result = cli.invoke(app, ["crop", "./out/a-talk", "--nonsense"])

    assert result.exit_code == 2
    assert "./crop" not in result.stderr, "the hint is for the ambiguity, not every error"


def test_a_usage_error_under_json_writes_a_machine_readable_object(cli):
    result = cli.invoke(app, ["crop", "--report", "json"])

    assert result.exit_code == 2
    document = json.loads(result.stdout)
    assert document["status"] == "error"
    assert document["error"] == "usage"
    assert "DIR" in document["message"]


def test_a_usage_error_under_text_leaves_stdout_empty(cli):
    result = cli.invoke(app, ["crop"])

    assert result.exit_code == 2
    assert result.stdout == ""


def test_a_failure_exits_two_and_says_so_on_stderr(cli):
    result = cli.invoke(app, ["https://youtu.be/jqpdveK2XAU"])

    assert result.exit_code == 2
    assert result.stdout == "", "an error is never part of the document"
    assert "not implemented" in result.stderr.lower()


def test_a_failure_under_json_writes_a_machine_readable_object(cli):
    result = cli.invoke(app, ["https://youtu.be/jqpdveK2XAU", "--report", "json"])

    assert result.exit_code == 2
    document = json.loads(result.stdout)
    assert document["status"] == "error"
    assert document["error"]
    assert document["message"]
    assert "not implemented" in result.stderr.lower(), "narration is on stderr under json"


def test_no_arguments_prints_help_rather_than_guessing(cli):
    result = cli.invoke(app, [])

    assert "Commands:" in result.output
    assert result.exit_code == 2, "being told nothing is a usage failure, not a success"


def test_a_root_level_parse_failure_honours_the_contract_too(cli):
    # The collision and the missing argument both fail inside a subcommand.
    # This one fails before any subcommand is chosen, which is a different
    # path through the group, and the caller is owed the same object.
    result = cli.invoke(app, ["--bogus", "--report", "json"])

    assert result.exit_code == 2
    assert json.loads(result.stdout)["error"] == "usage"


def test_version_is_reported(cli):
    result = cli.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert "extract-slides" in result.output


def test_the_attached_form_of_the_report_flag_is_read_too(cli):
    # The flag has to be found on a command line that never finished parsing,
    # so both spellings are read off the argv by hand and both need proving.
    result = cli.invoke(app, ["crop", "--report=json"])

    assert result.exit_code == 2
    assert json.loads(result.stdout)["error"] == "usage"


def test_an_interrupted_prompt_exits_without_a_traceback(cli):
    """Nothing prompts yet; the confirmation `prune --apply` owes arrives with it.

    Handling the interrupt is not optional in the meantime: taking the
    framework out of standalone mode is what lets a parsing failure reach
    the JSON contract, and it also hands back the interrupt the framework
    used to absorb. Left alone it would reach the operator as a traceback.
    """
    aborting = typer.Typer(cls=RootGroup, rich_markup_mode=None, add_completion=False)

    @aborting.callback()
    def root() -> None:
        """A callback keeps the group a group; typer collapses a lone command."""

    @aborting.command()
    def confirm() -> None:
        raise typer.Abort()

    result = cli.invoke(aborting, ["confirm"])

    assert result.exit_code == 1
    assert "Traceback" not in result.stderr
    assert "Aborted" in result.stderr


@pytest.mark.skip(reason="No command can succeed yet; #26 is the first that can.")
def test_a_successful_run_under_json_puts_the_document_on_stdout(cli):
    """The half of ADR 0002's two-stream rule that #25 could not prove here.

    The split itself is asserted above, but over a *failure* document,
    because every command in this build reports that it is not implemented
    and exits 2. The success document's shape is covered directly against
    the reporting module, with its streams injected, in `test_reporting.py`
    — which proves the writer and not the wiring.

    #26 is the first ticket whose commands finish, so it is the first that
    can assert this the way the ADR states it: invoke a run that succeeds,
    parse stdout whole, and find every human word on stderr. Write that
    body and delete this marker.
    """
