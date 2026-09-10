#!/usr/bin/env python3
"""Propose slide states for a reference video, for human verification.

This is the machine-proposal half of the ground truth required by
docs/adr/0003-correctness-metric-and-ground-truth.md. It deliberately does NOT
use any configuration from the detection shortlist in
docs/research/slide-change-detection.md section 10, so that the ground truth does
not favour the candidate a spike is about to measure:

  * sampling is dense (4 fps by default) at a large working resolution (long side
    960), where every shortlist candidate samples at 0.5-2 fps and 160-360 px;
  * the change signal is a per-pixel count against the *last emitted state*, not
    a block-wise MAD, a perceptual hash or SSIM;
  * nothing here decides whether two states are one slide. That is the
    accumulation rule from the ADR, applied by eye in the review step.

Run it in two stages, because decoding is the expensive part and thresholds want
tuning:

    propose.py sample  <id>        decode once, cache grayscale samples
    propose.py propose <id>        emit candidate states from the cache (instant)
    propose.py frames  <id>        write native-resolution JPEGs for the states
    propose.py sheet   <id>        write contact sheets of those JPEGs
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

import cv2
import numpy as np

WORKING_LONG_SIDE = 960
SAMPLE_FPS = 4.0
# A pixel counts as changed when it moves by more than this many grey levels.
# Deliberately small: the proposal must over-trigger, never miss.
PIXEL_DELTA = 12


def cache_root() -> Path:
    env = os.environ.get("EXTRACT_SLIDES_CACHE")
    if env:
        return Path(env)
    # Sibling of the repo, matching tools/candidates/sheets.sh.
    return Path(__file__).resolve().parents[2].parent / "extract-slides-cache"


def video_path(vid: str) -> Path:
    for ext in ("mp4", "webm", "mkv"):
        p = cache_root() / "videos" / f"{vid}.{ext}"
        if p.exists():
            return p
    sys.exit(f"no video for {vid} under {cache_root() / 'videos'}")


def samples_dir(vid: str) -> Path:
    return cache_root() / "samples" / vid


# --------------------------------------------------------------------------- #
# stage 1: decode once, cache samples
# --------------------------------------------------------------------------- #

def cmd_sample(args: argparse.Namespace) -> None:
    vid = args.video
    src = video_path(vid)
    out = samples_dir(vid)
    out.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(src))
    if not cap.isOpened():
        sys.exit(f"OpenCV cannot open {src}")
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    scale = min(1.0, WORKING_LONG_SIDE / max(w, h))
    ww, wh = max(1, round(w * scale)), max(1, round(h * scale))
    step = max(1, round(src_fps / args.fps))
    n_expected = math.ceil(n_frames / step) if n_frames else 0

    print(f"{vid}: {w}x{h} @{src_fps:.3f} fps, {n_frames} frames "
          f"({n_frames / src_fps / 60:.2f} min)", file=sys.stderr)
    print(f"  working {ww}x{wh}, every {step}th frame "
          f"(~{src_fps / step:.2f} fps), ~{n_expected} samples", file=sys.stderr)

    frames: list[np.ndarray] = []
    times: list[float] = []
    idx = 0
    while True:
        ok = cap.grab()
        if not ok:
            break
        if idx % step == 0:
            ok, bgr = cap.retrieve()
            if ok and bgr is not None:
                g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
                if scale < 1.0:
                    g = cv2.resize(g, (ww, wh), interpolation=cv2.INTER_AREA)
                frames.append(g)
                times.append(idx / src_fps)
            if len(frames) % 500 == 0 and frames:
                print(f"  {len(frames)} samples...", file=sys.stderr)
        idx += 1
    cap.release()

    arr = np.stack(frames) if frames else np.zeros((0, wh, ww), np.uint8)
    np.save(out / "samples.npy", arr)
    meta = {
        "video": vid, "source": str(src), "source_fps": src_fps,
        "source_frames": idx, "width": w, "height": h,
        "working_width": ww, "working_height": wh,
        "frame_step": step, "sample_fps": src_fps / step,
        "n_samples": len(times), "times_s": times,
        "duration_s": idx / src_fps if src_fps else None,
    }
    (out / "samples.json").write_text(json.dumps(meta, indent=2))
    print(f"  wrote {len(times)} samples to {out}", file=sys.stderr)


# --------------------------------------------------------------------------- #
# stage 2: propose candidate states from the cache
# --------------------------------------------------------------------------- #

def load_samples(vid: str) -> tuple[np.ndarray, dict]:
    d = samples_dir(vid)
    if not (d / "samples.npy").exists():
        sys.exit(f"no sample cache for {vid}; run `propose.py sample {vid}` first")
    meta = json.loads((d / "samples.json").read_text())
    return np.load(d / "samples.npy", mmap_mode="r"), meta


def activity_map(arr: np.ndarray, delta: int) -> np.ndarray:
    """Fraction of consecutive sample pairs in which each pixel changed.

    Kept as a diagnostic only (written out as activity.png). Measured on the six
    fixtures it is useless as a mask: on 2AWv_nIfp-U, which plays video *inside*
    the slide, the highest per-pixel activity over the whole video is 0.051,
    because the clip runs for a small fraction of an 11-minute talk. A global
    activity fraction cannot see a region that is violently active for one minute
    and still for ten, which is the shape every one of these videos has.
    """
    counts = np.zeros(arr.shape[1:], np.int32)
    prev = arr[0].astype(np.int16)
    for i in range(1, arr.shape[0]):
        cur = arr[i].astype(np.int16)
        counts += (np.abs(cur - prev) > delta)
        prev = cur
    return counts / max(1, arr.shape[0] - 1)


def cmd_propose(args: argparse.Namespace) -> None:
    """Emit candidate slide states.

    The change signal is a per-pixel count against the *last emitted state*,
    evaluated only over pixels that are still at both instants:

      * a pixel is **still** at sample i when it has not moved by more than
        `delta` in any of the last `still_window_s` seconds of samples;
      * `drift` is the fraction of pixels still both now and when the last state
        was recorded that differ from that state.

    Local stillness replaces the global activity mask. A presenter moving in an
    inset strip, a video playing inside the slide and a burned-in subtitle band
    are all excluded for exactly as long as they are moving, and counted again
    once they stop -- which a mask computed once per video cannot do.
    """
    vid = args.video
    arr, meta = load_samples(vid)
    times = meta["times_s"]
    n = arr.shape[0]
    if n == 0:
        sys.exit("empty sample cache")

    size = arr.shape[1] * arr.shape[2]
    win = max(1, round(args.still_window_s * meta["sample_fps"]))
    force_after = max(1, round(args.force_after_s * meta["sample_fps"]))
    min_still = args.min_still_frac * size

    def changed(a: np.ndarray, b: np.ndarray) -> np.ndarray:
        return np.abs(a.astype(np.int16) - b.astype(np.int16)) > args.delta

    recent: list[np.ndarray] = []
    ref = arr[0]
    ref_still = np.ones(arr.shape[1:], bool)
    ref_i = 0
    last_match_i = 0
    pending_onset: int | None = None
    states: list[dict] = [
        {"i": 0, "at_s": round(times[0], 3), "change_after_s": 0.0,
         "drift_from_prev_state": None, "still_frac": None,
         "reason": "first-sample"}
    ]
    signal: list[tuple] = []

    def emit(i: int, onset_i: int, drift: float, still: np.ndarray,
             reason: str) -> None:
        nonlocal ref, ref_still, ref_i, last_match_i, pending_onset
        states.append({
            "i": i,
            "at_s": round(times[i], 3),
            "change_after_s": round(times[onset_i], 3),
            "drift_from_prev_state": round(drift, 5),
            "still_frac": round(float(still.sum()) / size, 4),
            "reason": reason,
        })
        ref, ref_still, ref_i = arr[i], still, i
        last_match_i, pending_onset = i, None

    for i in range(1, n):
        ch = changed(arr[i], arr[i - 1])
        recent.append(ch)
        if len(recent) > win:
            recent.pop(0)
        active = recent[0].copy()
        for m in recent[1:]:
            active |= m
        still = ~active

        denom = still & ref_still
        nd = int(denom.sum())
        local = float(np.count_nonzero(ch)) / size
        if nd < min_still:
            # Too little of the frame is holding still to judge anything.
            drift = 0.0
            evaluable = False
        else:
            # Normalised by the whole frame, not by `nd`: dividing by the
            # still subset lets a small still region produce a large quotient,
            # which on the vision-mixed fixture emitted 843 states for 11
            # minutes, 711 of them transient. See METHOD.md.
            drift = float(np.count_nonzero(changed(arr[i], ref) & denom)) / size
            evaluable = True
        signal.append((round(times[i], 3), round(local, 5), round(drift, 5),
                       round(nd / size, 4)))

        if evaluable and drift < args.drift:
            last_match_i, pending_onset = i, None
            continue
        if pending_onset is None:
            pending_onset = last_match_i
        if evaluable and drift >= args.drift:
            emit(i, pending_onset, drift, still, "settled")
        elif i - pending_onset >= force_after:
            # Never go blind: a frame that never holds still enough to judge
            # still gets a state, so a missed slide cannot hide here.
            emit(i, pending_onset, drift, still, "forced")

    for a, b in zip(states, states[1:]):
        a["until_s"] = b["change_after_s"]
    states[-1]["until_s"] = round(meta["duration_s"] or times[-1], 3)
    for st in states:
        st["dwell_s"] = round(max(0.0, st["until_s"] - st["at_s"]), 3)

    out = samples_dir(vid)
    payload = {
        "video": vid,
        "params": {"delta": args.delta, "drift": args.drift,
                   "still_window_s": args.still_window_s,
                   "min_still_frac": args.min_still_frac,
                   "force_after_s": args.force_after_s,
                   "sample_fps": meta["sample_fps"],
                   "working": [meta["working_width"], meta["working_height"]]},
        "n_states": len(states),
        "states": states,
    }
    (out / "proposal.json").write_text(json.dumps(payload, indent=2))
    with (out / "signal.csv").open("w") as fh:
        fh.write("t_s,local,drift,still_frac\n")
        for row in signal:
            fh.write(",".join(str(v) for v in row) + "\n")
    if args.activity_png:
        act = activity_map(arr, args.delta)
        cv2.imwrite(str(out / "activity.png"),
                    (255 * np.clip(act / max(1e-9, act.max()), 0, 1)).astype(np.uint8))
    n_transient = sum(1 for st in states if st["dwell_s"] < 0.5)
    print(f"  {len(states)} candidate states "
          f"({n_transient} transient, dwell < 0.5 s) -> {out / 'proposal.json'}",
          file=sys.stderr)
    if args.verbose:
        for st in states:
            print(f"    {st['at_s']:9.2f}s  dwell={st['dwell_s']:7.2f}  "
                  f"drift={st['drift_from_prev_state']}  still={st['still_frac']}  "
                  f"{st['reason']}")


def cmd_frames(args: argparse.Namespace) -> None:
    """Write one native-resolution JPEG per candidate state.

    Decoding sequentially rather than seeking: OpenCV's POS_MSEC seek lands on a
    keyframe boundary on some builds, and a review frame that is not the frame
    the proposal measured would make the review unsound.
    """
    vid = args.video
    d = samples_dir(vid)
    proposal = json.loads((d / "proposal.json").read_text())
    meta = json.loads((d / "samples.json").read_text())
    out = d / "frames"
    out.mkdir(exist_ok=True)
    for old in out.glob("*.jpg"):
        old.unlink()

    step = meta["frame_step"]
    fps = meta["source_fps"]
    wanted = {}
    for k, st in enumerate(proposal["states"], start=1):
        wanted[int(round(st["at_s"] * fps / step)) * step] = (k, st["at_s"])

    cap = cv2.VideoCapture(str(video_path(vid)))
    if not cap.isOpened():
        sys.exit("cannot open video")
    idx = written = 0
    while wanted:
        if not cap.grab():
            break
        if idx in wanted:
            k, at_s = wanted.pop(idx)
            ok, bgr = cap.retrieve()
            if ok and bgr is not None:
                cv2.imwrite(str(out / f"{k:03d}_{at_s:09.2f}.jpg"), bgr,
                            [cv2.IMWRITE_JPEG_QUALITY, args.quality])
                written += 1
        idx += 1
    cap.release()
    if wanted:
        print(f"  {len(wanted)} states had no frame: {sorted(wanted.values())}",
              file=sys.stderr)
    print(f"  wrote {written} frames to {out}", file=sys.stderr)


def cmd_sheet(args: argparse.Namespace) -> None:
    """Contact sheets of the state frames, for the human review pass.

    States superseded within `--min-dwell` seconds are held back into a separate
    set of sheets: they are cross-fade frames and mid-animation grabs. Nothing is
    discarded -- every state stays in proposal.json, so recall is untouched and
    only the review load is bounded.
    """
    vid = args.video
    d = samples_dir(vid)
    proposal = json.loads((d / "proposal.json").read_text())
    dwell = {f"{k:03d}": st.get("dwell_s", 0.0)
             for k, st in enumerate(proposal["states"], start=1)}
    all_frames = sorted((d / "frames").glob("*.jpg"))
    if not all_frames:
        sys.exit("no frames; run `propose.py frames` first")
    frames = [f for f in all_frames
              if (dwell.get(f.stem.split("_")[0], 0.0) < args.min_dwell)
              == bool(args.transient)]
    if not frames:
        print("  nothing to sheet", file=sys.stderr)
        return
    out = d / ("sheets-transient" if args.transient else "sheets")
    out.mkdir(exist_ok=True)
    for stale in out.glob("*.jpg"):
        stale.unlink()
    print(f"  {len(frames)}/{len(all_frames)} states "
          f"({'dwell < ' if args.transient else 'dwell >= '}{args.min_dwell}s)",
          file=sys.stderr)
    cols, rows = args.cols, args.rows
    per = cols * rows
    cell_w = args.cell
    for page in range(math.ceil(len(frames) / per)):
        chunk = frames[page * per:(page + 1) * per]
        tiles = []
        for p in chunk:
            img = cv2.imread(str(p))
            h, w = img.shape[:2]
            cell_h = round(cell_w * h / w)
            img = cv2.resize(img, (cell_w, cell_h), interpolation=cv2.INTER_AREA)
            label = p.stem.split("_")[0] + "  " + p.stem.split("_")[1].lstrip("0") + "s"
            bar = np.zeros((22, cell_w, 3), np.uint8)
            cv2.putText(bar, label, (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                        (255, 255, 255), 1, cv2.LINE_AA)
            tiles.append(np.vstack([bar, img]))
        th = max(t.shape[0] for t in tiles)
        tiles = [np.vstack([t, np.zeros((th - t.shape[0], cell_w, 3), np.uint8)])
                 if t.shape[0] < th else t for t in tiles]
        blank = np.zeros((th, cell_w, 3), np.uint8)
        while len(tiles) % cols:
            tiles.append(blank)
        grid = np.vstack([np.hstack(tiles[r * cols:(r + 1) * cols])
                          for r in range(len(tiles) // cols)])
        p = out / f"sheet-{page + 1:02d}.jpg"
        cv2.imwrite(str(p), grid, [cv2.IMWRITE_JPEG_QUALITY, 82])
        print(f"  {p}  ({len(chunk)} frames)", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("sample", help="decode once and cache grayscale samples")
    s.add_argument("video")
    s.add_argument("--fps", type=float, default=SAMPLE_FPS)
    s.set_defaults(func=cmd_sample)

    p = sub.add_parser("propose", help="emit candidate states from the cache")
    p.add_argument("video")
    p.add_argument("--delta", type=int, default=PIXEL_DELTA)
    p.add_argument("--drift", type=float, default=0.002,
                   help="fraction of jointly-still pixels that must differ from "
                        "the last emitted state to record a new one")
    p.add_argument("--still-window-s", type=float, default=1.0,
                   help="a pixel is still if it has not moved for this long")
    p.add_argument("--min-still-frac", type=float, default=0.20,
                   help="below this much still frame, drift is not evaluable")
    p.add_argument("--force-after-s", type=float, default=6.0,
                   help="emit a state anyway if nothing settles for this long")
    p.add_argument("--activity-png", action="store_true",
                   help="also write the (diagnostic-only) global activity map")
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(func=cmd_propose)

    f = sub.add_parser("frames", help="write native-resolution JPEGs per state")
    f.add_argument("video")
    f.add_argument("--quality", type=int, default=88)
    f.set_defaults(func=cmd_frames)

    h = sub.add_parser("sheet", help="write contact sheets of the state frames")
    h.add_argument("video")
    h.add_argument("--cols", type=int, default=3)
    h.add_argument("--rows", type=int, default=4)
    h.add_argument("--cell", type=int, default=440)
    h.add_argument("--min-dwell", type=float, default=0.5,
                   help="hold back states superseded within this many seconds")
    h.add_argument("--transient", action="store_true",
                   help="sheet the held-back states instead of the kept ones")
    h.set_defaults(func=cmd_sheet)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
