#!/usr/bin/env python3
"""Check a ground-truth file against the schema in ADR 0003.

The ground truth is the measuring stick for every detection and crop decision in
this project, so a malformed file is worse than a missing one: it would silently
mis-score a spike. Run this before committing.

    validate.py ground-truth/*.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

CLASSES = {"C1", "C2a", "C2b", "C3", "C4", "C5", "C7"}
ROLES = {"fixture", "target"}


def fail(errs: list[str], msg: str) -> None:
    errs.append(msg)


def check_rect(errs: list[str], where: str, rect) -> None:
    if not (isinstance(rect, list) and len(rect) == 4):
        return fail(errs, f"{where}: rect must be [x, y, w, h]")
    x, y, w, h = rect
    for name, v in zip("xywh", rect):
        if not isinstance(v, (int, float)):
            return fail(errs, f"{where}: rect.{name} is not a number")
        if not 0.0 <= float(v) <= 1.0:
            fail(errs, f"{where}: rect.{name}={v} outside [0, 1]; "
                       f"rects are normalised floats (ADR 0001 --roi convention)")
    if w <= 0 or h <= 0:
        fail(errs, f"{where}: rect has non-positive size")
    if x + w > 1.0001 or y + h > 1.0001:
        fail(errs, f"{where}: rect runs past the frame edge")


def check_file(path: Path) -> list[str]:
    errs: list[str] = []
    try:
        doc = json.loads(path.read_text())
    except Exception as exc:  # noqa: BLE001
        return [f"{path}: not valid JSON: {exc}"]

    for key in ("video", "class", "role", "duration_s", "resolution",
                "layout_segments", "slides", "provenance"):
        if key not in doc:
            fail(errs, f"missing top-level key {key!r}")
    if errs:
        return [f"{path}: {e}" for e in errs]

    if doc["video"] != path.stem:
        fail(errs, f"video {doc['video']!r} does not match filename {path.stem!r}")
    if not isinstance(doc["class"], list) or not doc["class"]:
        fail(errs, "class must be a non-empty list")
    else:
        for c in doc["class"]:
            if c not in CLASSES:
                fail(errs, f"unknown class {c!r} (docs/reference-set.md defines "
                           f"{sorted(CLASSES)})")
    if doc["role"] not in ROLES:
        fail(errs, f"role must be one of {sorted(ROLES)}")

    dur = doc["duration_s"]
    if not isinstance(dur, (int, float)) or dur <= 0:
        fail(errs, "duration_s must be a positive number")
        dur = float("inf")

    segs = doc["layout_segments"]
    if not isinstance(segs, list) or not segs:
        fail(errs, "layout_segments must be a non-empty list")
    else:
        prev_to = 0.0
        for k, s in enumerate(segs):
            w = f"layout_segments[{k}]"
            for key in ("from_s", "to_s", "slide_rect"):
                if key not in s:
                    fail(errs, f"{w}: missing {key!r}")
            if "slide_rect" in s:
                check_rect(errs, w, s["slide_rect"])
            if {"from_s", "to_s"} <= s.keys():
                if s["from_s"] >= s["to_s"]:
                    fail(errs, f"{w}: from_s >= to_s")
                if abs(s["from_s"] - prev_to) > 0.001:
                    fail(errs, f"{w}: starts at {s['from_s']} but previous segment "
                               f"ended at {prev_to}; segments must tile the video "
                               f"with no gap and no overlap")
                prev_to = s["to_s"]
        if segs and abs(prev_to - dur) > 1.0:
            fail(errs, f"layout_segments end at {prev_to} but duration_s is {dur}")

    slides = doc["slides"]
    if not isinstance(slides, list) or not slides:
        fail(errs, "slides must be a non-empty list")
    else:
        for k, s in enumerate(slides):
            w = f"slides[{k}]"
            for key in ("n", "from_s", "to_s", "complete_from_s"):
                if key not in s:
                    fail(errs, f"{w}: missing {key!r}")
            if s.get("n") != k + 1:
                fail(errs, f"{w}: n={s.get('n')} but should be {k + 1} "
                           f"(slides are numbered from 1, in order)")
            if {"from_s", "to_s"} <= s.keys():
                if s["from_s"] >= s["to_s"]:
                    fail(errs, f"{w}: from_s >= to_s")
                if s["to_s"] > dur + 1.0:
                    fail(errs, f"{w}: to_s={s['to_s']} past duration_s={dur}")
            cf = s.get("complete_from_s")
            if cf is not None and {"from_s", "to_s"} <= s.keys():
                if not s["from_s"] - 0.001 <= cf <= s["to_s"]:
                    fail(errs, f"{w}: complete_from_s={cf} outside "
                               f"[{s['from_s']}, {s['to_s']}]")
            for j, gap in enumerate(s.get("offscreen", []) or []):
                gw = f"{w}.offscreen[{j}]"
                if not (isinstance(gap, list) and len(gap) == 2):
                    fail(errs, f"{gw}: must be [from_s, to_s]")
                    continue
                if gap[0] >= gap[1]:
                    fail(errs, f"{gw}: from_s >= to_s")
                if "from_s" in s and "to_s" in s and not (
                        s["from_s"] <= gap[0] and gap[1] <= s["to_s"]):
                    fail(errs, f"{gw}: outside the slide's own interval")
        # The metric matches a capture to the expected slide whose interval
        # contains it, so overlapping intervals would make a match ambiguous.
        for a, b in zip(slides, slides[1:]):
            if {"to_s"} <= a.keys() and {"from_s"} <= b.keys():
                if b["from_s"] < a["to_s"] - 0.001:
                    fail(errs, f"slides {a.get('n')} and {b.get('n')} overlap in "
                               f"time; the timestamp match would be ambiguous")

    prov = doc["provenance"]
    if not isinstance(prov, dict):
        fail(errs, "provenance must be an object")
    else:
        if not prov.get("proposed_by"):
            fail(errs, "provenance.proposed_by is empty")
        if not prov.get("verified_by"):
            fail(errs, "provenance.verified_by is empty: a file without a human "
                       "signature is a proposal, not ground truth "
                       "(ground-truth/README.md)")
        if not prov.get("verified_at"):
            fail(errs, "provenance.verified_at is empty")

    return [f"{path}: {e}" for e in errs]


def main(argv: list[str]) -> int:
    paths = [Path(a) for a in argv[1:]]
    if not paths:
        root = Path(__file__).resolve().parents[2] / "ground-truth"
        paths = sorted(root.glob("*.json"))
    if not paths:
        print("no ground-truth files found", file=sys.stderr)
        return 1
    all_errs: list[str] = []
    for p in paths:
        errs = check_file(p)
        all_errs += errs
        n_slides = n_segs = "?"
        if not errs:
            doc = json.loads(p.read_text())
            n_slides, n_segs = len(doc["slides"]), len(doc["layout_segments"])
        status = "OK  " if not errs else "FAIL"
        print(f"{status} {p}  slides={n_slides} layout_segments={n_segs}")
    for e in all_errs:
        print(f"  {e}", file=sys.stderr)
    return 1 if all_errs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
