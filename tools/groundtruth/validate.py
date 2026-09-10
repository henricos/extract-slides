#!/usr/bin/env python3
"""Check a ground-truth file against the schema in ADR 0003, as amended.

The amended schema (ADR 0003, Amendments, 2026-09-11) drops `layout_segments`,
carries `slide_rect` and `rect_holds_s` on each expected slide, and adds a
top-level `repeats` list for content that comes back.

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
                "slides", "provenance"):
        if key not in doc:
            fail(errs, f"missing top-level key {key!r}")
    if "layout_segments" in doc:
        fail(errs, "layout_segments was removed by ADR 0003 decision 4; each slide "
                   "carries its own slide_rect and rect_holds_s")
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

    slides = doc["slides"]
    if not isinstance(slides, list) or not slides:
        fail(errs, "slides must be a non-empty list")
        slides = []
    for k, s_ in enumerate(slides):
        w = f"slides[{k}]"
        for key in ("n", "from_s", "to_s", "complete_from_s", "slide_rect",
                    "rect_holds_s"):
            if key not in s_:
                fail(errs, f"{w}: missing {key!r}")
        if s_.get("n") != k + 1:
            fail(errs, f"{w}: n={s_.get('n')} but should be {k + 1} "
                       f"(slides are numbered from 1, in order)")
        if "slide_rect" in s_:
            check_rect(errs, w, s_["slide_rect"])
        if {"from_s", "to_s"} <= s_.keys():
            if s_["from_s"] >= s_["to_s"]:
                fail(errs, f"{w}: from_s >= to_s")
            if s_["to_s"] > dur + 1.0:
                fail(errs, f"{w}: to_s={s_['to_s']} past duration_s={dur}")
        cf = s_.get("complete_from_s")
        if cf is not None and {"from_s", "to_s"} <= s_.keys():
            if not s_["from_s"] - 0.001 <= cf <= s_["to_s"]:
                fail(errs, f"{w}: complete_from_s={cf} outside "
                           f"[{s_['from_s']}, {s_['to_s']}]")
        # rect_holds_s says where the rectangle is valid; a capture outside it is
        # excluded from the crop metric (ADR 0003 decision 8), so an interval
        # that does not overlap the slide's own life would score nothing at all.
        rh = s_.get("rect_holds_s")
        if rh is not None:
            if not (isinstance(rh, list) and len(rh) == 2):
                fail(errs, f"{w}: rect_holds_s must be [from_s, to_s]")
            elif rh[0] >= rh[1]:
                fail(errs, f"{w}: rect_holds_s from_s >= to_s")
            elif {"from_s", "to_s"} <= s_.keys() and not (
                    rh[0] < s_["to_s"] and rh[1] > s_["from_s"]):
                fail(errs, f"{w}: rect_holds_s {rh} does not overlap the slide's "
                           f"own interval, so its rectangle scores nothing")
        for j, gap in enumerate(s_.get("offscreen", []) or []):
            gw = f"{w}.offscreen[{j}]"
            if not (isinstance(gap, list) and len(gap) == 2):
                fail(errs, f"{gw}: must be [from_s, to_s]")
                continue
            if gap[0] >= gap[1]:
                fail(errs, f"{gw}: from_s >= to_s")
            if {"from_s", "to_s"} <= s_.keys() and not (
                    s_["from_s"] <= gap[0] and gap[1] <= s_["to_s"]):
                fail(errs, f"{gw}: outside the slide's own interval")

    # The metric matches a capture to the expected slide whose interval contains
    # it, so overlapping intervals would make a match ambiguous. ADR 0003
    # decision 2 exists to keep this list disjoint and ordered.
    for a, b in zip(slides, slides[1:]):
        if "to_s" in a and "from_s" in b and b["from_s"] < a["to_s"] - 0.001:
            fail(errs, f"slides {a.get('n')} and {b.get('n')} overlap in time; "
                       f"the timestamp match would be ambiguous. A slide that "
                       f"comes back after other slides is a repeats entry, not "
                       f"an overlapping interval (ADR 0003 decision 2)")

    n_slides = len(slides)
    for k, r in enumerate(doc.get("repeats", []) or []):
        w = f"repeats[{k}]"
        for key in ("of_n", "from_s", "to_s"):
            if key not in r:
                fail(errs, f"{w}: missing {key!r}")
        of_n = r.get("of_n")
        if isinstance(of_n, int) and not 1 <= of_n <= n_slides:
            fail(errs, f"{w}: of_n={of_n} names no slide (1..{n_slides})")
        if {"from_s", "to_s"} <= r.keys():
            if r["from_s"] >= r["to_s"]:
                fail(errs, f"{w}: from_s >= to_s")
            if r["to_s"] > dur + 1.0:
                fail(errs, f"{w}: to_s={r['to_s']} past duration_s={dur}")
            # A repeat is a window where content already expected comes back, so
            # it must sit outside the slide it repeats -- otherwise it is that
            # slide's own life, or an offscreen gap inside it.
            src = next((x for x in slides if x.get("n") == of_n), None)
            if src and src.get("from_s") is not None and (
                    r["from_s"] < src.get("to_s", 0)
                    and r["to_s"] > src.get("from_s", 0)):
                fail(errs, f"{w}: overlaps slide {of_n}'s own interval; a gap "
                           f"inside a slide's life is `offscreen`, not a repeat "
                           f"(ADR 0003 decision 2)")

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
        n_slides = n_rep = "?"
        if not errs:
            doc = json.loads(p.read_text())
            n_slides = len(doc["slides"])
            n_rep = len(doc.get("repeats", []) or [])
        status = "OK  " if not errs else "FAIL"
        print(f"{status} {p}  slides={n_slides} repeats={n_rep}")
    for e in all_errs:
        print(f"  {e}", file=sys.stderr)
    return 1 if all_errs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
