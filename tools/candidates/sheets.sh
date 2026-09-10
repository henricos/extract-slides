#!/usr/bin/env bash
# Fetch N storyboard contact sheets for a YouTube id, without downloading video.
# A sheet is a 3x3 grid of 320x180 frames, ~70 KiB. Sheets are immutable inputs,
# so they are cached and never refetched.
# Usage: sheets.sh <video_id> [n_sheets]
set -euo pipefail
ID="$1"; N="${2:-3}"
C="${EXTRACT_SLIDES_CACHE:-$(cd "$(dirname "$0")/../.." && pwd)/../extract-slides-cache}"
D="$C/storyboards/$ID"
mkdir -p "$D"
[ -f "$D/sheet1.jpg" ] && { echo "$ID cached"; exit 0; }

M="$D/meta.json"
[ -s "$M" ] || timeout 120 yt-dlp --skip-download --dump-single-json \
  "https://youtu.be/$ID" 2>/dev/null > "$M" || { echo "$ID META_FAIL"; exit 2; }

ES_CACHE="$C" python3 - "$ID" "$N" <<'PY'
import json, os, subprocess, sys
vid, n = sys.argv[1], int(sys.argv[2])
D = f"{os.environ['ES_CACHE']}/storyboards/{vid}"
d = json.load(open(f"{D}/meta.json"))
sbs = [f for f in d.get("formats", []) if f.get("format_id", "").startswith("sb")]
sb = next((f for f in sbs if f["format_id"] == "sb0"), sbs[0] if sbs else None)
if sb is None:
    print(f"{vid} NO_STORYBOARD"); sys.exit(3)
frags = sb["fragments"]
# Evenly spaced over the timeline with integer math, so picks stay distinct.
picks = sorted({min(len(frags) - 1, i * len(frags) // (n + 1)) for i in range(1, n + 1)})
json.dump(dict(id=vid, duration=d.get("duration"), title=d.get("title"),
               width=d.get("width"), height=d.get("height"), fps=d.get("fps"),
               uploader=d.get("uploader"), sb=sb["format_id"],
               grid=[sb["columns"], sb["rows"]], frame=[sb["width"], sb["height"]],
               frags=len(frags), picks=picks),
          open(f"{D}/info.json", "w"), indent=2)
for k, i in enumerate(picks, start=1):
    subprocess.run(["curl", "-sS", "--max-time", "60",
                    "-o", f"{D}/sheet{k}.jpg", frags[i]["url"]], check=True)
PY
echo "$ID ok"
