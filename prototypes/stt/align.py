"""PROTOTYPE (issue #22) — put small, medium and YouTube's own ASR side by side in time.

Throwaway. There is no ground truth and none is wanted (ADR 0004): this exists so the
operator can *read* the three and say whether `small` would make him unhappy. The
divergence number is a reading aid — it ranks windows by how much small and medium
disagree, so the hardest passages get read first. It is not a score.
"""

import json
import re
import sys
from pathlib import Path

CACHE = Path("/home/developer/github/henricos/extract-slides-cache")
OUT = Path("/home/developer/github/henricos/extract-slides/out/spike-stt")
WINDOW = 30.0


def norm_words(text):
    t = text.lower().replace(" ", " ")
    t = re.sub(r"[^\wáàâãéêíóôõúüç ]+", " ", t)
    return [w for w in t.split() if w]


def load_spike(vid, tag):
    d = json.loads((OUT / vid / f"{tag}.json").read_text())
    return [(s["start"], s["end"], s["text"].strip()) for s in d["segments"]], d["metrics"]


def load_caption(path):
    d = json.loads(Path(path).read_text())
    cues = []
    for ev in d.get("events", []):
        if "segs" not in ev:
            continue
        t = ev.get("tStartMs", 0) / 1000.0
        txt = "".join(s.get("utf8", "") for s in (ev.get("segs") or []))
        txt = txt.strip()
        if txt:
            cues.append((t, t + ev.get("dDurationMs", 0) / 1000.0, txt))
    return cues


def bucket(items, n):
    rows = [[] for _ in range(n)]
    for start, _end, txt in items:
        i = min(int(start // WINDOW), n - 1)
        rows[i].append(txt)
    return [" ".join(r).strip() for r in rows]


def divergence(a, b):
    """Jaccard distance on the window's word bags. Cheap, symmetric, no alignment."""
    wa, wb = set(norm_words(a)), set(norm_words(b))
    if not wa and not wb:
        return 0.0
    return round(1 - len(wa & wb) / len(wa | wb), 3)


def main():
    vid = sys.argv[1]
    cap_lang = sys.argv[2] if len(sys.argv) > 2 else "pt-orig"
    small, m_small = load_spike(vid, "fw-small-t2-vad")
    medium, m_medium = load_spike(vid, "fw-medium-t2-vad")
    yt = load_caption(CACHE / "captions" / f"{vid}.{cap_lang}.json3")

    dur = max(m_small["audio_s"], m_medium["audio_s"])
    n = int(dur // WINDOW) + 1
    rows = []
    for i, (s, m, y) in enumerate(zip(bucket(small, n), bucket(medium, n), bucket(yt, n))):
        rows.append(
            {
                "t": i * WINDOW,
                "small": s,
                "medium": m,
                "yt": y,
                "div": divergence(s, m),
            }
        )

    print(
        json.dumps(
            {"video": vid, "window": WINDOW, "small": m_small, "medium": m_medium, "rows": rows},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
