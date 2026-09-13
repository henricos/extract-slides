#!/usr/bin/env python3
"""PROTOTYPE — the crop stage of extract-slides: find the slide region, never cut content.

Throwaway spike for issue #12. Not the implementation; it exists to be run over the images
pass 1 left in out/spike-pass1/ and looked at. See ADR 0004: the only failure that costs
anything is losing content, and keeping extra is the expected outcome.

    python3 crop.py <video-id> [--recipe activity|panel] [...]

Reads out/spike-pass1/<id>/slides/*.jpg plus the source video, writes cropped images and a
review page under out/spike-crop/<id>/.

Two recipes, because the one the research expected to win does not.

  --recipe panel    AutoSlides-Extractor's AutoCropDetector, per image: strip black
                    borders, Canny, dilate, four-vertex contours, five gates, and a score
                    that prefers the large rectangle nearest 16:9 or 4:3.
                    (reference-implementations.md B.7.1)

  --recipe activity (default) The activity-complement crop nobody has built. Three pixel
                    populations, separated temporally:
                      - chrome    never changes
                      - slide     changes when the slide changes, still in between
                      - presenter changes continuously
                    The slide region is what changes at a slide boundary and is still in
                    between. Computed per *layout*, where a layout is a cluster of captures
                    that share their static pixels, so a mid-video layout change is handled
                    without a segmentation pass.

Every fallback goes outward, to more pixels: panel/activity rectangle, then the
de-letterboxed frame, then the full frame. The stage never returns "no crop".
"""

import argparse
import html
import os
import re
import sys
import time

import cv2
import numpy as np

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
IN_ROOT = os.path.join(ROOT, "out", "spike-pass1")
OUT_ROOT = os.path.join(ROOT, "out", "spike-crop")
CACHE = "/home/developer/github/henricos/extract-slides-cache/videos"

WORK_W = 480        # working width for every map and every comparison
SAMPLE_FPS = 2.0    # same sampling rate as pass 1, so the move map costs one decode pass

# --- activity recipe knobs
T_MOVE = 12         # grey levels between two 0.5 s samples that count as "it moved"
T_JUMP = 45         # grey levels between two captures that count as "the content changed"
T_SAME = 16         # grey levels below which two captures' pixels are "the same pixel"
LAYOUT_SIM = 0.50   # share of identical pixels that puts two captures in one layout
MIN_MEMBERS = 3     # a layout with fewer captures than this gets no rectangle
MOVE_FRAC = 0.06    # a pixel moving in this share of sample pairs is the presenter
JUMP_FRAC = 0.08    # a pixel jumping in this share of capture pairs is slide content
SPECK_FRAC = 0.10   # a content blob smaller than this share of the biggest one is a speck

BLOB_MIN = 0.005    # a movement blob smaller than this share of the frame is ignored
BLOB_IN = 0.80      # a blob this much inside a side strip belongs to that strip
PAD = 0.015         # grow the rectangle outward by this share of the frame
AREA_MIN = 0.10     # below this the rectangle is not believable
AREA_MAX = 0.98     # above this it is the full frame, and is reported as such

# --- panel recipe knobs (AutoCropDetector's tuned constants, carried over as-is)
BLACK_THRESH = 20.0
MAX_BORDER_FRAC = 0.10
CANNY_LOW, CANNY_HIGH = 20, 60
P_AREA_MIN, P_AREA_MAX = 0.08, 0.95
MARGIN_FRAC = 0.02
FILL_MIN = 0.85
ASPECT_TOL = 0.05
ASPECTS = (16.0 / 9.0, 4.0 / 3.0)

DUPE = 0.02         # fraction of differing hash bits below which two crops are "the same"


# --- shared -----------------------------------------------------------------------

def work(bgr):
    h, w = bgr.shape[:2]
    small = cv2.resize(bgr, (WORK_W, max(1, int(round(h * WORK_W / w)))), interpolation=cv2.INTER_AREA)
    return cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (5, 5), 0)


def strip_black_border(gray):
    """Walk inward while the row/column mean reads as a black bar. The recall-safe floor:
    it can only ever remove uniformly black margins."""
    h, w = gray.shape[:2]
    max_y, max_x = int(h * MAX_BORDER_FRAC), int(w * MAX_BORDER_FRAC)
    top, bottom, left, right = 0, h, 0, w
    while top < max_y and gray[top, :].mean() <= BLACK_THRESH:
        top += 1
    while bottom > h - max_y and gray[bottom - 1, :].mean() <= BLACK_THRESH:
        bottom -= 1
    while left < max_x and gray[:, left].mean() <= BLACK_THRESH:
        left += 1
    while right > w - max_x and gray[:, right - 1].mean() <= BLACK_THRESH:
        right -= 1
    if bottom - top < 16 or right - left < 16:
        return (0.0, 0.0, 1.0, 1.0)
    return (left / w, top / h, (right - left) / w, (bottom - top) / h)


def clamp_rect(r):
    x, y, w, h = r
    x, y = max(0.0, x), max(0.0, y)
    return (x, y, min(1.0 - x, w), min(1.0 - y, h))


def pad_rect(r, pad=PAD):
    x, y, w, h = r
    return clamp_rect((x - pad, y - pad, w + 2 * pad, h + 2 * pad))


def union(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x0, y0 = min(ax, bx), min(ay, by)
    return (x0, y0, max(ax + aw, bx + bw) - x0, max(ay + ah, by + bh) - y0)


def overlap_area(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x0, y0 = max(ax, bx), max(ay, by)
    x1, y1 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)


# --- the panel recipe (per image) --------------------------------------------------

def aspect_score(w, h):
    if h <= 0:
        return 0.0
    dev = min(abs(w / h - ar) / ar for ar in ASPECTS)
    return max(0.0, 1.0 - dev / ASPECT_TOL)


def find_panel(gray, inner):
    h, w = gray.shape[:2]
    ix, iy = int(inner[0] * w), int(inner[1] * h)
    iw, ih = int(inner[2] * w), int(inner[3] * h)
    patch = gray[iy:iy + ih, ix:ix + iw]
    inner_area = float(max(1, iw * ih))

    edges = cv2.dilate(cv2.Canny(patch, CANNY_LOW, CANNY_HIGH), np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

    rejected = {"vertices": 0, "area": 0, "margin": 0, "fill": 0, "aspect": 0}
    best, best_score = None, 0.0
    for cnt in contours:
        approx = cv2.approxPolyDP(cnt, 0.02 * cv2.arcLength(cnt, True), True)
        if len(approx) != 4:
            rejected["vertices"] += 1
            continue
        x, y, bw, bh = cv2.boundingRect(approx)
        area_ratio = (bw * bh) / inner_area
        if not (P_AREA_MIN <= area_ratio <= P_AREA_MAX):
            rejected["area"] += 1
            continue
        if (y / ih) < MARGIN_FRAC and ((ih - y - bh) / ih) < MARGIN_FRAC:
            rejected["margin"] += 1
            continue
        if cv2.contourArea(approx) / float(max(1, bw * bh)) < FILL_MIN:
            rejected["fill"] += 1
            continue
        score = area_ratio * aspect_score(bw, bh)
        if score <= 0.0:
            rejected["aspect"] += 1
            continue
        if score > best_score:
            best = ((x + ix) / w, (y + iy) / h, bw / w, bh / h)
            best_score = score
    return best, best_score, rejected


# --- the activity recipe (per layout) ----------------------------------------------

def cluster_layouts(grays):
    """Group captures that share their static pixels. Two captures of the same layout agree
    everywhere the chrome is; two different layouts disagree nearly everywhere."""
    labels = [-1] * len(grays)
    clusters = []
    for i, g in enumerate(grays):
        for c, members in enumerate(clusters):
            sim = np.mean([np.mean(cv2.absdiff(g, grays[m]) <= T_SAME) for m in members[-8:]])
            if sim >= LAYOUT_SIM:
                labels[i] = c
                members.append(i)
                break
        else:
            clusters.append([i])
            labels[i] = len(clusters) - 1
    return labels, clusters


def move_maps(video_path, seconds, shape):
    """One decode pass. Per capture, the share of consecutive 0.5 s samples in which each
    pixel moved — the presenter, the webcam tile, an embedded video, a burned-in caption."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        sys.exit(f"cannot open {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, int(round(fps / SAMPLE_FPS)))
    acc = [np.zeros(shape, np.float32) for _ in seconds]
    n = [0] * len(seconds)
    prev, i, k = None, 0, 0
    while True:
        if not cap.grab():
            break
        if i % step == 0:
            ok, frame = cap.retrieve()
            if not ok:
                break
            sec = i / fps
            while k + 1 < len(seconds) and sec >= seconds[k + 1]:
                k += 1
            g = work(frame)
            if prev is not None:
                acc[k] += (cv2.absdiff(g, prev) > T_MOVE)
                n[k] += 1
            prev = g
        i += 1
    cap.release()
    return [a / max(1, c) for a, c in zip(acc, n)], n


def activity_rect(members, grays, moves, counts):
    """The rectangle for one layout, and the diagnostics that say why."""
    diag = {"members": len(members)}
    if len(members) < MIN_MEMBERS:
        return None, "thin-layout", diag

    shape = grays[0].shape
    h, w = shape

    jump = np.zeros(shape, np.float32)
    for a, b in zip(members, members[1:]):
        jump += (cv2.absdiff(grays[a], grays[b]) > T_JUMP)
    jump /= max(1, len(members) - 1)

    total = sum(counts[m] for m in members)
    move = np.zeros(shape, np.float32)
    for m in members:
        move += moves[m] * counts[m]
    move /= max(1, total)

    k3 = np.ones((3, 3), np.uint8)
    movem_raw = cv2.morphologyEx((move > MOVE_FRAC).astype(np.uint8), cv2.MORPH_OPEN, k3)
    movem = cv2.dilate(movem_raw, np.ones((9, 9), np.uint8))
    jumpm = cv2.morphologyEx((jump > JUMP_FRAC).astype(np.uint8), cv2.MORPH_OPEN, k3)
    slidem = cv2.morphologyEx((jumpm & (1 - movem)).astype(np.uint8), cv2.MORPH_CLOSE,
                              np.ones((15, 15), np.uint8))

    diag.update({"move%": round(100 * float(movem.mean()), 1),
                 "jump%": round(100 * float(jumpm.mean()), 1),
                 "slide%": round(100 * float(slidem.mean()), 1)})

    # The bounding box of the content blobs, specks excluded. One stray blob on the far
    # side of the presenter is enough to stretch a raw bbox across the whole frame.
    n_c, _, c_stats, _ = cv2.connectedComponentsWithStats(slidem, 8)
    areas = [c_stats[c][4] for c in range(1, n_c)]
    if not areas or sum(areas) < 0.01 * w * h:
        return None, "no-content", diag
    biggest = max(areas)
    keep = [c for c in range(1, n_c) if c_stats[c][4] >= SPECK_FRAC * biggest]
    diag["blobs"] = f"{len(keep)}/{n_c - 1}"
    cx0 = min(c_stats[c][0] for c in keep)
    cy0 = min(c_stats[c][1] for c in keep)
    cx1 = max(c_stats[c][0] + c_stats[c][2] for c in keep)
    cy1 = max(c_stats[c][1] + c_stats[c][3] for c in keep)

    # Start from the whole frame and cut away only what the presenter occupies.
    #
    # The content mask marks the pixels that *change* when the slide changes, and a slide's
    # static furniture - a repeated title, a logo, a footer - never does. Cropping to the
    # content's own bounding box therefore slices through the title of every deck whose
    # header is the same on every slide, which is most of them. So the box is not the
    # answer: it only says how far a cut *could* go. A side is cut only when the strip
    # between the frame edge and the content is full of movement, which is the presenter
    # and nothing else. Where there is nothing to cut away, there is no crop.
    blobs = []
    n_b, _, b_stats, _ = cv2.connectedComponentsWithStats(movem_raw, 8)
    for b in range(1, n_b):
        bx, by, bw, bh, area = b_stats[b]
        if area >= BLOB_MIN * w * h:
            blobs.append((bx, by, bx + bw, by + bh, area))
    diag["move_blobs"] = len(blobs)

    def strip_owns(bx0, by0, bx1, by1, edge):
        """Where does this side's cut go? Halfway between the presenter's own edge and
        the content's. Cutting at the content's edge shaves the first letter off every
        title, because the content mask stops at the ink; cutting at the presenter's edge
        leaves a sliver of him in shot. The midpoint is the margin a human would leave.
        Returns None when no whole blob of continuous movement lives in the strip, which
        means there is nothing on this side to cut away."""
        best = None
        for mx0, my0, mx1, my1, area in blobs:
            ox = max(0, min(mx1, bx1) - max(mx0, bx0))
            oy = max(0, min(my1, by1) - max(my0, by0))
            if ox * oy < BLOB_IN * (mx1 - mx0) * (my1 - my0):
                continue
            cut = {"left": mx1, "right": mx0, "top": my1, "bottom": my0}[edge]
            if best is None:
                best = cut
            elif edge in ("left", "top"):
                best = max(best, cut)
            else:
                best = min(best, cut)
        return best

    x0, y0, x1, y1 = 0, 0, w, h
    cuts = []
    c = strip_owns(0, 0, cx0, h, "left") if cx0 > 0 else None
    if c is not None:
        x0 = (min(cx0, c) + cx0) // 2; cuts.append("left")
    c = strip_owns(cx1, 0, w, h, "right") if cx1 < w else None
    if c is not None:
        x1 = (max(cx1, c) + cx1 + 1) // 2; cuts.append("right")
    c = strip_owns(0, 0, w, cy0, "top") if cy0 > 0 else None
    if c is not None:
        y0 = (min(cy0, c) + cy0) // 2; cuts.append("top")
    c = strip_owns(0, cy1, w, h, "bottom") if cy1 < h else None
    if c is not None:
        y1 = (max(cy1, c) + cy1 + 1) // 2; cuts.append("bottom")
    diag["cuts"] = cuts or ["none"]
    if not cuts:
        return None, "nothing-to-cut", diag

    rect = (x0 / w, y0 / h, (x1 - x0) / w, (y1 - y0) / h)
    rect = pad_rect(rect)
    area = rect[2] * rect[3]
    diag["area"] = round(area, 3)
    diag["aspect"] = round(rect[2] * w / max(1e-6, rect[3] * h), 2)
    if area < AREA_MIN:
        return None, "too-small", diag
    if area > AREA_MAX:
        return None, "whole-frame", diag
    return rect, "activity", diag


# --- duplicates, again ------------------------------------------------------------

def phash(bgr, size=16):
    """256-bit DCT perceptual hash, same as pass 1: thresholds are fractions of bits."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(gray, (size * 4, size * 4), interpolation=cv2.INTER_AREA)
    dct = cv2.dct(np.float32(small))[:size, :size]
    flat = dct.flatten()[1:]
    return flat > np.median(flat)


def dedupe_keeping_later(images):
    """Drop duplicates, and let the *later* of the pair survive.

    Pass 1 keeps the first, which is right when it compares whole frames. After the crop
    the test bites on a progressive build, and keeping the first would drop the complete
    slide and keep a half-built one. That is content loss, the one failure ADR 0004 says
    costs anything, so here the run's last state is the one that stays.
    """
    kept, superseded = [], {}
    for i, img in enumerate(images):
        h = phash(img)
        hit = next((p for p, (_, prev) in enumerate(kept)
                    if float(np.count_nonzero(h != prev)) / h.size < DUPE), None)
        if hit is None:
            kept.append((i, h))
        else:
            superseded[kept[hit][0]] = i
            kept[hit] = (i, h)
    return [i for i, _ in kept], superseded


# --- running it -------------------------------------------------------------------

def read_pass1_index(video_id):
    path = os.path.join(IN_ROOT, video_id, "index.html")
    meta = {}
    if os.path.exists(path):
        text = open(path).read()
        for m in re.finditer(r"slides/(\d{3})\.jpg.*?\?t=(\d+)\".*?&middot; ([a-z]+)</figcaption>",
                             text, re.S):
            meta[int(m.group(1))] = (int(m.group(2)), m.group(3))
    return meta


def run(video_id, recipe):
    in_dir = os.path.join(IN_ROOT, video_id, "slides")
    if not os.path.isdir(in_dir):
        sys.exit(f"no pass-1 output at {in_dir}")
    names = sorted(n for n in os.listdir(in_dir) if n.endswith(".jpg") and ".thumb." not in n)
    meta = read_pass1_index(video_id)
    seconds = [meta.get(int(n[:3]), (0, ""))[0] for n in names]

    t0 = time.time()
    frames = [cv2.imread(os.path.join(in_dir, n)) for n in names]
    grays = [work(f) for f in frames]
    letterbox = [strip_black_border(g) for g in grays]

    rects, rules, layouts, diags = [None] * len(names), [""] * len(names), [0] * len(names), {}

    if recipe == "panel":
        for i, g in enumerate(grays):
            panel, score, rej = find_panel(g, letterbox[i])
            layouts[i] = i
            if panel is not None:
                rects[i], rules[i] = pad_rect(panel), "panel"
                diags[i] = {"score": round(score, 3)}
            else:
                rects[i], rules[i] = None, "no-panel"
                diags[i] = rej
    else:
        labels, clusters = cluster_layouts(grays)
        layouts = labels
        moves, counts = move_maps(os.path.join(CACHE, f"{video_id}.mp4"), seconds, grays[0].shape)
        for c, members in enumerate(clusters):
            rect, rule, diag = activity_rect(members, grays, moves, counts)
            diags[f"L{c}"] = diag
            for m in members:
                rects[m], rules[m] = rect, rule

    # The chain, outward: the recipe's rectangle, then the whole frame. Never "no crop".
    #
    # There is no black-bar step between the two, though the research ranked it first and
    # called it recall-safe by construction. It is not. A deck of white text on near-black
    # slides has row means below any "this is a letterbox bar" threshold all the way in,
    # and on `YBH8rQv4aTQ` the walk ate its 10 % cap on every side of 77 images and sliced
    # the title off four of them. A black bar and a dark slide's margin are the same pixels.
    # Keeping a letterbox bar costs nothing (ADR 0004); cutting a title costs everything.
    for i in range(len(names)):
        if rects[i] is None:
            rects[i], rules[i] = (0.0, 0.0, 1.0, 1.0), "full"

    crops = []
    for f, r in zip(frames, rects):
        fh, fw = f.shape[:2]
        x, y = int(round(r[0] * fw)), int(round(r[1] * fh))
        cw, ch = max(8, int(round(r[2] * fw))), max(8, int(round(r[3] * fh)))
        crops.append(f[y:y + ch, x:x + cw])

    kept_idx, superseded = dedupe_keeping_later(crops)
    elapsed = time.time() - t0

    kept_set = set(kept_idx)
    out_dir = os.path.join(OUT_ROOT, video_id)
    slides_dir = os.path.join(out_dir, "slides")
    os.makedirs(slides_dir, exist_ok=True)
    for stale in os.listdir(slides_dir):
        os.remove(os.path.join(slides_dir, stale))

    records, out_n = [], 0
    for i, name in enumerate(names):
        src = int(name[:3])
        alive = i in kept_set
        if alive:
            out_n += 1
            stem = f"{out_n:03d}"
        else:
            stem = f"d{src:03d}"
        cv2.imwrite(os.path.join(slides_dir, stem + ".jpg"), crops[i], [cv2.IMWRITE_JPEG_QUALITY, 92])
        # The "before" frame is copied in rather than linked across to out/spike-pass1/,
        # so the review page works from any document root.
        cv2.imwrite(os.path.join(slides_dir, stem + ".before.jpg"), frames[i],
                    [cv2.IMWRITE_JPEG_QUALITY, 85])
        bh, bw = frames[i].shape[:2]
        cv2.imwrite(os.path.join(slides_dir, stem + ".before.thumb.jpg"),
                    cv2.resize(frames[i], (420, max(1, int(round(bh * 420 / bw)))),
                               interpolation=cv2.INTER_AREA), [cv2.IMWRITE_JPEG_QUALITY, 80])
        ch, cw = crops[i].shape[:2]
        thumb = cv2.resize(crops[i], (420, max(1, int(round(ch * 420 / cw)))), interpolation=cv2.INTER_AREA)
        cv2.imwrite(os.path.join(slides_dir, stem + ".thumb.jpg"), thumb, [cv2.IMWRITE_JPEG_QUALITY, 80])
        fh, fw = frames[i].shape[:2]
        records.append({
            "src": src, "stem": stem, "alive": alive, "seconds": seconds[i],
            "reason": meta.get(src, (0, ""))[1], "rule": rules[i], "layout": layouts[i],
            "rect": rects[i], "area": rects[i][2] * rects[i][3],
            "aspect": (rects[i][2] * fw) / max(1e-6, rects[i][3] * fh),
            "superseded_by": superseded.get(i),
        })

    return {"video_id": video_id, "recipe": recipe, "records": records, "diags": diags,
            "n_in": len(names), "n_out": out_n, "elapsed": elapsed}


def write_review_page(result):
    vid = result["video_id"]
    by_rule = {}
    for r in result["records"]:
        by_rule[r["rule"]] = by_rule.get(r["rule"], 0) + 1

    cards = []
    for r in result["records"]:
        mm, ss = divmod(r["seconds"], 60)
        x, y, w, h = r["rect"]
        note = ""
        if not r["alive"]:
            note = (f'<div class="dead-note">duplicata depois do recorte &rarr; '
                    f'substitu&iacute;da por {result["records"][r["superseded_by"]]["stem"]}</div>')
        cards.append(f"""<figure class="{'alive' if r['alive'] else 'dead'}">
<div class="pair">
 <a href="slides/{r['stem']}.before.jpg"><img src="slides/{r['stem']}.before.thumb.jpg" loading="lazy"></a>
 <a href="slides/{r['stem']}.jpg"><img src="slides/{r['stem']}.thumb.jpg" loading="lazy"></a>
</div>
<figcaption>{r['stem']} &middot; <a href="https://youtu.be/{vid}?t={r['seconds']}">{mm}:{ss:02d}</a>
 &middot; {r['reason']} &middot; <b class="r-{r['rule']}">{r['rule']}</b>
 &middot; layout {r['layout']} &middot; {r['area'] * 100:.0f}% do frame &middot; {r['aspect']:.2f}:1<br>
<span class="rect">x {x:.3f} y {y:.3f} w {w:.3f} h {h:.3f}</span>{note}</figcaption>
</figure>""")

    dl = "<br>".join(f"{k}: {v}" for k, v in result["diags"].items())
    page = f"""<!doctype html><meta charset="utf-8"><title>crop {vid}</title>
<style>body{{font:14px system-ui;margin:24px;background:#111;color:#eee}}
h1{{font-size:18px}} .meta{{color:#aaa;margin-bottom:16px;line-height:1.6}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(480px,1fr));gap:16px}}
figure{{margin:0;border:1px solid #333;padding:6px;background:#181818}}
figure.dead{{opacity:.4;border-color:#733}}
.pair{{display:grid;grid-template-columns:1fr 1fr;gap:6px;align-items:start}}
img{{width:100%;display:block;background:#000}}
figcaption{{color:#aaa;padding:6px 2px;font-size:12px;line-height:1.5}}
.rect{{color:#666;font-family:ui-monospace,monospace}} .dead-note{{color:#e77}}
a{{color:#6cf}} b.r-activity,b.r-panel{{color:#7d7}} b.r-letterbox{{color:#dd7}}
b.r-full,b.r-no-content,b.r-whole-frame,b.r-thin-layout,b.r-too-small,b.r-no-panel{{color:#d77}}</style>
<h1>crop &mdash; {vid} &mdash; receita <b>{result['recipe']}</b></h1>
<div class="meta">
{result['n_in']} imagens da passada 1 &rarr; <b>{result['n_out']}</b> depois da segunda limpeza
de duplicatas ({result['n_in'] - result['n_out']} descartadas, mostradas apagadas)<br>
regra: {' &middot; '.join(f'{k} {v}' for k, v in sorted(by_rule.items()))} &middot; {result['elapsed']:.0f}s<br>
{dl}<br>
esquerda = frame inteiro da passada 1, direita = recorte
</div>
<div class="grid">{''.join(cards)}</div>
"""
    path = os.path.join(OUT_ROOT, vid, "index.html")
    with open(path, "w") as fh:
        fh.write(page)
    return path


def main():
    global LAYOUT_SIM, MOVE_FRAC, JUMP_FRAC, PAD, DUPE, MIN_MEMBERS, BLOB_IN
    ap = argparse.ArgumentParser()
    ap.add_argument("video_id")
    ap.add_argument("--recipe", choices=("activity", "panel"), default="activity")
    ap.add_argument("--layout-sim", type=float, default=LAYOUT_SIM)
    ap.add_argument("--move-frac", type=float, default=MOVE_FRAC)
    ap.add_argument("--jump-frac", type=float, default=JUMP_FRAC)
    ap.add_argument("--pad", type=float, default=PAD)

    ap.add_argument("--dupe", type=float, default=DUPE)
    ap.add_argument("--blob-in", type=float, default=BLOB_IN)
    ap.add_argument("--min-members", type=int, default=MIN_MEMBERS)
    args = ap.parse_args()
    LAYOUT_SIM, MOVE_FRAC, JUMP_FRAC = args.layout_sim, args.move_frac, args.jump_frac
    PAD, DUPE, MIN_MEMBERS, BLOB_IN = args.pad, args.dupe, args.min_members, args.blob_in

    result = run(args.video_id, args.recipe)
    page = write_review_page(result)
    by_rule = {}
    for r in result["records"]:
        by_rule[r["rule"]] = by_rule.get(r["rule"], 0) + 1
    print(f"{args.video_id} [{args.recipe}]: {result['n_in']} -> {result['n_out']} images, "
          f"{by_rule}, {result['elapsed']:.0f}s -> {page}")
    for k, v in result["diags"].items():
        if isinstance(k, str):
            print(f"   {k}: {v}")


if __name__ == "__main__":
    main()
