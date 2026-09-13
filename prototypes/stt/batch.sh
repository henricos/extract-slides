#!/bin/bash
# PROTOTYPE (issue #13) — the timed batch. Strictly sequential: two cores, no contention.
set -u
P=.venv/bin/python
V=${2:-b9dBJnQ_kpo}
run() { echo "### $* on $V" >&2; $P run_one.py --audio="$V" "$@" || echo "FAILED: $*" >&2; }

case "${1:-main}" in
main)
  run --runtime fw --model small          --threads 2 --vad
  run --runtime fw --model medium         --threads 2 --vad
  run --runtime fw --model medium         --threads 4 --vad
  run --runtime fw --model medium         --threads 2
  run --runtime fw --model large-v3-turbo --threads 2 --vad
  run --runtime sherpa --model sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8 --threads 2 --tag sherpa-parakeet-t2
  run --runtime fw --model medium         --threads 2 --vad --words
  ;;
winner)
  run --runtime fw --model medium --threads 2 --vad
  run --runtime fw --model small  --threads 2 --vad
  ;;
esac

# appended: the quality round, on the fixtures that carry a reference
case "${1:-}" in
quality)
  for V in -FOCpMAww28 YBH8rQv4aTQ; do
    echo "=== $V ===" >&2
    $P run_one.py --audio="$V" --runtime fw --model small  --threads 2 --vad
    $P run_one.py --audio="$V" --runtime fw --model medium --threads 2 --vad
    $P run_one.py --audio="$V" --runtime fw --model large-v3-turbo --threads 2 --vad
    $P run_one.py --audio="$V" --runtime sherpa --model sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8 --threads 2 --tag sherpa-parakeet-t2
  done
  echo "=== beam lever, on the TED talk ===" >&2
  $P run_one.py --audio=-FOCpMAww28 --runtime fw --model medium --threads 2 --vad --beam 1 --tag fw-medium-t2-vad-beam1
  echo "=== the hard one, no reference: read it ===" >&2
  for M in small medium; do $P run_one.py --audio=X3uFwLj2u7Q --runtime fw --model $M --threads 2 --vad; done
  $P run_one.py --audio=X3uFwLj2u7Q --runtime sherpa --model sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8 --threads 2 --tag sherpa-parakeet-t2
  ;;
esac

# appended: greedy decoding turned out to be both faster and better on the first fixture
case "${1:-}" in
beam)
  for V in -FOCpMAww28 YBH8rQv4aTQ b9dBJnQ_kpo; do
    $P run_one.py --audio="$V" --runtime fw --model small  --threads 2 --vad --beam 1 --tag fw-small-t2-vad-beam1
    $P run_one.py --audio="$V" --runtime fw --model medium --threads 2 --vad --beam 1 --tag fw-medium-t2-vad-beam1
  done
  ;;
esac
