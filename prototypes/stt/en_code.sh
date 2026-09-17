#!/bin/bash
# PROTOTYPE (issue #22) — the confounder round. English, but the speaker reads code aloud,
# which is where `small` collapsed in Portuguese. Separates language from content.
set -u
V=${1:-WWQbatJ41Kc}
P=.venv/bin/python
for M in small medium; do
  echo "### $M on $V" >&2
  $P run_one.py --runtime fw --model $M --threads 2 --vad --language en --audio "$V" \
    || echo "FAILED: $M" >&2
done
