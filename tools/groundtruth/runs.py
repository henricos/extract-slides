#!/usr/bin/env python3
"""Group candidate states into runs that share the same slide content.

A state is a settled frame. Two neighbouring states can be the same slide with
the speaker moved (a composed layout), or two different slides -- and telling
those apart is what the slide rectangle is for. Comparing only inside the
rectangle answers it directly:

    runs.py <video> --rect x y w h

Without a rectangle the whole frame is compared, which is right for a fixture
whose slides fill the frame and wrong for one with a presenter strip -- so pass
the rectangle you propose for the video.

The runs are what the review page asks about: one question per run, not per
state. On jqpdveK2XAU that is 9 questions instead of 88.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

from propose import cache_root, samples_dir  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("--rect", nargs=4, type=float, default=[0.0, 0.0, 1.0, 1.0],
                    metavar=("X", "Y", "W", "H"),
                    help="slide region as normalised floats; compare only inside it")
    ap.add_argument("--delta", type=int, default=25,
                    help="grey levels a pixel must move to count as changed")
    ap.add_argument("--threshold", type=float, default=0.01,
                    help="fraction of the region that must change to end a run")
    args = ap.parse_args()

    d = samples_dir(args.video)
    states = json.loads((d / "proposal.json").read_text())["states"]
    rx, ry, rw, rh = args.rect

    runs: list[list[int]] = []
    cur: list[int] = []
    prev = None
    for k, st in enumerate(states, start=1):
        hits = sorted((d / "frames").glob(f"{k:03d}_*.jpg"))
        if not hits:
            sys.exit(f"no frame for state {k}; run `propose.py frames {args.video}`")
        img = cv2.cvtColor(cv2.imread(str(hits[0])), cv2.COLOR_BGR2GRAY)
        h, w = img.shape
        reg = img[round(ry * h):round((ry + rh) * h), round(rx * w):round((rx + rw) * w)]
        if prev is None or reg.shape != prev.shape:
            frac = 1.0
        else:
            frac = float(np.count_nonzero(
                np.abs(reg.astype(np.int16) - prev.astype(np.int16)) > args.delta)) / reg.size
        if frac > args.threshold:
            if cur:
                runs.append(cur)
            cur = [k]
        else:
            cur.append(k)
        prev = reg
    if cur:
        runs.append(cur)

    payload = {
        "video": args.video,
        "rect": [rx, ry, rw, rh],
        "params": {"delta": args.delta, "threshold": args.threshold},
        "runs": [{"states": r,
                  "from_s": states[r[0] - 1]["at_s"],
                  "to_s": states[r[-1] - 1]["until_s"]}
                 for r in runs],
    }
    (d / "runs.json").write_text(json.dumps(payload, indent=2))
    print(f"{len(runs)} runs from {len(states)} states -> {d / 'runs.json'}",
          file=sys.stderr)
    for r in payload["runs"]:
        s = r["states"]
        print(f"  states {s[0]:>3}-{s[-1]:<3} ({len(s):>2})  "
              f"{r['from_s']:>8.2f}s -> {r['to_s']:>8.2f}s  "
              f"({r['to_s'] - r['from_s']:>6.2f}s on screen)")


if __name__ == "__main__":
    main()
