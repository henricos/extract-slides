#!/usr/bin/env bash
# Fetch the tier-1 sweep fixtures into the cache, video track only.
#
# Video-only: no muxing, so no system ffmpeg is needed, and ground-truth
# labelling needs no audio. The version is pinned because the yt-dlp installed on
# the target host (2026.07.04) returns HTTP 403 for every media format on every
# player client -- the GVS PO-token gate. See METHOD.md.
set -euo pipefail

CACHE="${EXTRACT_SLIDES_CACHE:-$(cd "$(dirname "$0")/../.." && pwd)/../extract-slides-cache}"
DEST="$CACHE/videos"
IDS=${*:-"pJc0l2DASpo jqpdveK2XAU b9dBJnQ_kpo 2AWv_nIfp-U YBH8rQv4aTQ X3uFwLj2u7Q"}

mkdir -p "$DEST"
for id in $IDS; do
  if compgen -G "$DEST/$id.mp4" > /dev/null || compgen -G "$DEST/$id.webm" > /dev/null; then
    echo "$id cached"; continue
  fi
  echo "=== $id ==="
  uv tool run --from 'yt-dlp==2026.8.19' yt-dlp \
    --no-progress --js-runtimes node \
    -f 'bv*[height<=1080][vcodec^=avc1]/bv*[height<=1080]' \
    -o "$DEST/%(id)s.%(ext)s" \
    "https://www.youtube.com/watch?v=$id"
done
