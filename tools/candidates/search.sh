#!/usr/bin/env bash
# Search YouTube for reference-set candidates, filtered by duration, without
# downloading anything. Prints "id<TAB>seconds<TAB>title".
#
# Usage:  search.sh <min_seconds> <max_seconds> <results_per_query> <query>...
# Example: search.sh 200 720 8 "lightning talk kubernetes" "fosdem talk rust"
#
# Read tools/candidates/CALIBRATION.md BEFORE writing queries. Queries that
# contain "how to", "record", "create" or "presentation" return tutorials about
# producing slides, not talks that use them.
set -euo pipefail
MIN="$1"; MAX="$2"; N="$3"; shift 3
for q in "$@"; do
  timeout 150 yt-dlp "ytsearch${N}:${q}" \
    --skip-download --flat-playlist --no-warnings \
    --match-filter "duration>${MIN} & duration<${MAX}" \
    --print "%(id)s	%(duration)s	%(title).70s" 2>/dev/null || true
done | sort -u -k1,1
