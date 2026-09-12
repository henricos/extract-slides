#!/usr/bin/env python3
"""PROTOTYPE — pass 1 of extract-slides: capture the screens, drop the easy duplicates.

Throwaway spike for issue #11. Not the implementation; it exists to be run on the sweep
fixtures and looked at. See ADR 0004: this pass must not lose a capture, and leaving too
much is the expected outcome.

    python3 pass1.py <video-id-or-path> [--fps 2] [--thresh 0.5] ...

Reads from the fixture cache by video id, writes images plus a review page under
out/spike-pass1/<id>/.
"""

import argparse
import html
import os
import sys
import time

import cv2
import numpy as np

CACHE = "/home/developer/github/henricos/extract-slides-cache/videos"
OUT_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "out", "spike-pass1")

# The four knobs.
SAMPLE_FPS = 2.0  # how often we look at the video, in samples per second
WIDTH = 480  # analysis width; sample resolution is a recall parameter (research §A.4)
THRESH = 0.5  # edge-change threshold: 0.0 on a static frame, ~1.2 on a one-bullet reveal
DWELL = 1.5  # seconds a screen must hold still before it counts as a screen
WATCHDOG = 10.0  # never go longer than this without emitting something, whatever happens
DUPE = 0.02  # fraction of differing hash bits below which two images are "the same"


def edge_map(gray):
    """Auto-Canny off the luma median, then dilate.

    The dilation makes a 1-2 px shift (camera wobble, a filmed screen, re-encode ringing)
    stop registering as a change. Thresholds derived per frame from the median make the
    signal immune to a global brightness ramp (projector AGC).
    """
    median = float(np.median(gray))
    low = int(max(0, (1.0 - 1.0 / 3.0) * median))
    high = int(min(255, (1.0 + 1.0 / 3.0) * median))
    edges = cv2.Canny(gray, low, high)
    size = 4 + round(np.sqrt(gray.shape[0] * gray.shape[1]) / 192)
    if size % 2 == 0:
        size += 1
    return cv2.dilate(edges, np.ones((size, size), np.uint8))


def edge_delta(a, b):
    """Percent of pixels whose edge state differs. 0.0 when nothing moved."""
    return 100.0 * float(np.mean(cv2.absdiff(a, b))) / 255.0


def phash(bgr, size=16):
    """256-bit DCT perceptual hash. Thresholds are fractions of bits, never raw counts."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(gray, (size * 4, size * 4), interpolation=cv2.INTER_AREA)
    dct = cv2.dct(np.float32(small))[:size, :size]
    flat = dct.flatten()[1:]  # drop DC
    return flat > np.median(flat)


def hash_distance(a, b):
    return float(np.count_nonzero(a != b)) / a.size


def analysis_frame(bgr):
    h, w = bgr.shape[:2]
    scale = WIDTH / float(w)
    small = cv2.resize(bgr, (WIDTH, max(1, int(round(h * scale)))), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)


def run(video_path, video_id, out_dir):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        sys.exit(f"cannot open {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, int(round(fps / SAMPLE_FPS)))

    slides_dir = os.path.join(out_dir, "slides")
    os.makedirs(slides_dir, exist_ok=True)
    for stale in os.listdir(slides_dir):
        os.remove(os.path.join(slides_dir, stale))

    kept = []  # (index, seconds, reason, hash)
    hashes = []
    dropped = 0
    deltas = []

    def emit(frame, seconds, reason):
        nonlocal dropped
        h = phash(frame)
        for prev in hashes:
            if hash_distance(h, prev) < DUPE:
                dropped += 1
                return False
        hashes.append(h)
        idx = len(kept) + 1
        cv2.imwrite(os.path.join(slides_dir, f"{idx:03d}.jpg"), frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
        thumb_w = 480
        th, tw = frame.shape[:2]
        thumb = cv2.resize(frame, (thumb_w, max(1, int(round(th * thumb_w / tw)))), interpolation=cv2.INTER_AREA)
        cv2.imwrite(os.path.join(slides_dir, f"{idx:03d}.thumb.jpg"), thumb, [cv2.IMWRITE_JPEG_QUALITY, 80])
        kept.append((idx, seconds, reason, h))
        return True

    anchor_frame = None
    anchor_edges = None
    anchor_seconds = 0.0
    anchor_emitted = False
    last_emit_seconds = 0.0
    samples = 0
    i = 0
    t0 = time.time()

    while True:
        if not cap.grab():
            break
        if i % step == 0:
            ok, frame = cap.retrieve()
            if not ok:
                break
            seconds = i / fps
            samples += 1
            edges = edge_map(analysis_frame(frame))

            if anchor_frame is None:
                # Always save the first frame.
                anchor_frame, anchor_edges, anchor_seconds = frame, edges, seconds
                emit(frame, seconds, "first")
                anchor_emitted = True
                last_emit_seconds = seconds
            else:
                delta = edge_delta(anchor_edges, edges)
                deltas.append(delta)
                if delta >= THRESH:
                    if not anchor_emitted and (seconds - anchor_seconds) >= DWELL:
                        # The anchor held still long enough to be a screen. It is by
                        # construction a settled frame: never mid-transition, and on a
                        # slow fade it is the clean slide from before the fade.
                        emit(anchor_frame, anchor_seconds, "dwell")
                        # The anchor covered everything up to now, so that is how far
                        # the video is accounted for (also when the image was a dupe:
                        # a dupe means an identical screen is already in the output).
                        last_emit_seconds = seconds
                    anchor_frame, anchor_edges, anchor_seconds = frame, edges, seconds
                    anchor_emitted = False
                    if (seconds - last_emit_seconds) >= WATCHDOG:
                        # Continuous churn: the anchor never settles. Emit anyway rather
                        # than go silent for the whole span.
                        emit(frame, seconds, "watchdog")
                        last_emit_seconds = seconds
                        anchor_emitted = True
        i += 1

    if anchor_frame is not None and not anchor_emitted:
        # Flush at EOF, or the closing slide of every talk is lost.
        emit(anchor_frame, anchor_seconds, "eof")

    cap.release()
    elapsed = time.time() - t0
    return {
        "kept": kept,
        "dropped": dropped,
        "samples": samples,
        "elapsed": elapsed,
        "deltas": np.array(deltas) if deltas else np.array([0.0]),
        "duration": i / fps,
    }


def write_review_page(video_id, out_dir, result):
    rows = []
    for idx, seconds, reason, _ in result["kept"]:
        mm, ss = divmod(int(seconds), 60)
        yt = f"https://youtu.be/{video_id}?t={int(seconds)}"
        rows.append(
            f'<figure><a href="slides/{idx:03d}.jpg"><img src="slides/{idx:03d}.thumb.jpg" loading="lazy"></a>'
            f'<figcaption>{idx:03d} &middot; <a href="{html.escape(yt)}">{mm}:{ss:02d}</a> &middot; {reason}</figcaption></figure>'
        )
    d = result["deltas"]
    summary = (
        f'{len(result["kept"])} imagens, {result["dropped"]} descartadas como duplicata, '
        f'{result["samples"]} amostras em {result["elapsed"]:.0f}s '
        f'({result["duration"] / 60:.1f} min de v&iacute;deo)'
    )
    knobs = (
        f"amostragem {SAMPLE_FPS}/s &middot; an&aacute;lise {WIDTH}px &middot; limiar {THRESH} &middot; "
        f"parada {DWELL}s &middot; watchdog {WATCHDOG}s &middot; duplicata {DUPE}"
    )
    page = f"""<!doctype html><meta charset="utf-8"><title>pass1 {video_id}</title>
<style>body{{font:14px system-ui;margin:24px;background:#111;color:#eee}}
h1{{font-size:18px}} .meta{{color:#aaa;margin-bottom:16px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:12px}}
figure{{margin:0}} img{{width:100%;display:block;border:1px solid #333}}
figcaption{{color:#aaa;padding:4px 0}} a{{color:#6cf}}</style>
<h1>pass 1 &mdash; {video_id}</h1>
<div class="meta">{summary}<br>{knobs}<br>
delta de bordas: mediana {float(np.median(d)):.2f}, p90 {float(np.percentile(d, 90)):.2f}, m&aacute;x {float(d.max()):.2f}</div>
<div class="grid">{"".join(rows)}</div>
"""
    path = os.path.join(out_dir, "index.html")
    with open(path, "w") as fh:
        fh.write(page)
    return path


def main():
    global SAMPLE_FPS, WIDTH, THRESH, DWELL, WATCHDOG, DUPE
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--fps", type=float, default=SAMPLE_FPS)
    ap.add_argument("--width", type=int, default=WIDTH)
    ap.add_argument("--thresh", type=float, default=THRESH)
    ap.add_argument("--dwell", type=float, default=DWELL)
    ap.add_argument("--watchdog", type=float, default=WATCHDOG)
    ap.add_argument("--dupe", type=float, default=DUPE)
    args = ap.parse_args()

    SAMPLE_FPS, WIDTH, THRESH = args.fps, args.width, args.thresh
    DWELL, WATCHDOG, DUPE = args.dwell, args.watchdog, args.dupe

    if os.path.exists(args.video):
        path, video_id = args.video, os.path.splitext(os.path.basename(args.video))[0]
    else:
        video_id = args.video
        path = os.path.join(CACHE, f"{video_id}.mp4")

    out_dir = os.path.normpath(os.path.join(OUT_ROOT, video_id))
    os.makedirs(out_dir, exist_ok=True)
    result = run(path, video_id, out_dir)
    page = write_review_page(video_id, out_dir, result)

    by_reason = {}
    for _, _, reason, _ in result["kept"]:
        by_reason[reason] = by_reason.get(reason, 0) + 1
    print(
        f'{video_id}: {len(result["kept"])} kept {by_reason}, {result["dropped"]} dupes dropped, '
        f'{result["samples"]} samples, {result["elapsed"]:.0f}s -> {page}'
    )


if __name__ == "__main__":
    main()
