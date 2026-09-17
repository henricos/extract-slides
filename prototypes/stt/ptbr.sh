#!/bin/bash
# PROTOTYPE (issue #22) — the pt-BR round. Strictly sequential: two cores, no contention.
set -u
V=${1:-vmRfO2uULfw}
P=.venv/bin/python
for M in small medium; do
  echo "### $M on $V" >&2
  $P run_one.py --runtime fw --model $M --threads 2 --vad --language pt --audio "$V" \
    || echo "FAILED: $M" >&2
done
