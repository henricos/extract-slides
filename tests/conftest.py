"""Shared fixtures and vocabulary for the suite."""

#: Box-drawing characters. ADR 0001 bans them from `--help` and ADR 0002
#: bans them from the running log, while the final report is the one place
#: a border earns its keep — so several tests need to ask the same question.
BORDERS = set("╭╮╰╯│─┌┐└┘═║")
