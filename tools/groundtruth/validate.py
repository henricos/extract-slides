#!/usr/bin/env python3
"""Check a ground-truth file against the schema in ADR 0003.

The ground truth is the measuring stick for every detection and crop decision in
this project, so a malformed file is worse than a missing one: it would silently
mis-score a spike. Run this before committing.

    validate.py ground-truth/*.json

The schema is deliberately small. It records only the contents that must appear
in the output, each with the windows in which a capture of it counts and the
rectangle it should be cropped to. Everything else a tool captures is surplus,
which the metric counts and never classifies, so there is nothing here to
describe it with.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

CLASSES = {"C1", "C2a", "C2b", "C3", "C4", "C5", "C7"}
ROLES = {"fixture", "target"}
# Fields from the two superseded versions of the metric. Seeing one means the
# file predates the rewrite, which is worth saying plainly rather than reporting
# as a missing key.
RETIRED = {
    "slides": "renamed to `required`, and it now holds only the contents that must appear",
    "layout_segments": "removed: each required content carries its own slide_rect",
    "repeats": "removed: a content that comes back gets a second window, not an entry",
}


def fail(errs: list[str], msg: str) -> None:
    errs.append(msg)


def check_rect(errs: list[str], where: str, rect) -> None:
    if not (isinstance(rect, list) and len(rect) == 4):
        return fail(errs, f"{where}: slide_rect must be [x, y, w, h]")
    x, y, w, h = rect
    for name, v in zip("xywh", rect):
        if not isinstance(v, (int, float)):
            return fail(errs, f"{where}: slide_rect.{name} is not a number")
        if not 0.0 <= float(v) <= 1.0:
            fail(errs, f"{where}: slide_rect.{name}={v} outside [0, 1]; rects are "
                       f"normalised floats (the --roi convention, ADR 0001)")
    if w <= 0 or h <= 0:
        fail(errs, f"{where}: slide_rect has non-positive size")
    if x + w > 1.0001 or y + h > 1.0001:
        fail(errs, f"{where}: slide_rect runs past the frame edge")


def check_file(path: Path) -> list[str]:
    errs: list[str] = []
    try:
        doc = json.loads(path.read_text())
    except Exception as exc:  # noqa: BLE001
        return [f"{path}: not valid JSON: {exc}"]

    for old, why in RETIRED.items():
        if old in doc:
            fail(errs, f"`{old}` is from a superseded version of ADR 0003: {why}")
    for key in ("video", "class", "role", "duration_s", "resolution", "required"):
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

    required = doc["required"]
    if not isinstance(required, list) or not required:
        fail(errs, "required must be a non-empty list")
        required = []

    spans: list[tuple[float, float, int]] = []
    for k, r in enumerate(required):
        w = f"required[{k}]"
        for key in ("n", "windows", "slide_rect"):
            if key not in r:
                fail(errs, f"{w}: missing {key!r}")
        if r.get("n") != k + 1:
            fail(errs, f"{w}: n={r.get('n')} but should be {k + 1} "
                       f"(required contents are numbered from 1, in order)")
        if "slide_rect" in r:
            check_rect(errs, w, r["slide_rect"])

        wins = r.get("windows")
        if not isinstance(wins, list) or not wins:
            fail(errs, f"{w}: windows must be a non-empty list of [from_s, to_s]; "
                       f"a content with no window can never be captured, so it "
                       f"would be a guaranteed miss")
            continue
        for j, win in enumerate(wins):
            ww = f"{w}.windows[{j}]"
            if not (isinstance(win, list) and len(win) == 2):
                fail(errs, f"{ww}: must be [from_s, to_s]")
                continue
            a, b = win
            if not all(isinstance(v, (int, float)) for v in win):
                fail(errs, f"{ww}: bounds must be numbers")
                continue
            if a >= b:
                fail(errs, f"{ww}: from_s >= to_s")
            if b > dur + 1.0:
                fail(errs, f"{ww}: to_s={b} past duration_s={dur}")
            spans.append((float(a), float(b), r.get("n", k + 1)))

    # A capture matches the content whose window contains it, so overlapping
    # windows would make a match ambiguous. Windows may leave gaps -- a capture
    # in a gap is surplus, which is exactly what the metric wants.
    spans.sort()
    for (a1, b1, n1), (a2, b2, n2) in zip(spans, spans[1:]):
        if a2 < b1 - 0.001:
            fail(errs, f"windows of required {n1} and {n2} overlap "
                       f"([{a1}, {b1}] and [{a2}, {b2}]); a capture in the overlap "
                       f"would match both")

    # `provenance` is informational. There is deliberately no signature check:
    # a file is reviewed when someone has been through it, and demanding a name
    # in a field proves nothing a commit does not already record.
    if "provenance" in doc and not isinstance(doc["provenance"], dict):
        fail(errs, "provenance must be an object")

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
        n_req = n_win = "?"
        if not errs:
            doc = json.loads(p.read_text())
            n_req = len(doc["required"])
            n_win = sum(len(r["windows"]) for r in doc["required"])
        print(f"{'OK  ' if not errs else 'FAIL'} {p}  required={n_req} windows={n_win}")
    for e in all_errs:
        print(f"  {e}", file=sys.stderr)
    return 1 if all_errs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
