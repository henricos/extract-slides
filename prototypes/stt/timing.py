"""PROTOTYPE (issue #13) — are the word timestamps good enough to pair speech with slides?

The human caption is the reference clock: each of its cues carries a start time and the
words spoken from it. Find each cue's opening trigram in the STT word stream and compare
the two clocks.

    python timing.py <video-id> <tag>
"""

import json
import sys
from pathlib import Path

import wer as W


def caption_cues(path, limit_s):
    d = json.loads(Path(path).read_text())
    cues = []
    for ev in d.get("events", []):
        if "segs" not in ev:
            continue
        t = ev.get("tStartMs", 0) / 1000.0
        if t > limit_s:
            continue
        words = W.norm(" ".join(s.get("utf8", "") for s in ev["segs"]))
        if len(words) >= 3:
            cues.append((t, words[:3]))
    return cues


def main():
    vid, tag = sys.argv[1], sys.argv[2]
    j = json.loads((W.OUT / vid / f"{tag}.json").read_text())
    audio_s = j["metrics"]["audio_s"]

    stream = []  # (normalised word, start time)
    for s in j["segments"]:
        for w in s.get("words", []):
            n = W.norm(w["w"])
            if n:
                stream.append((n[0], w["s"]))
    words = [w for w, _ in stream]

    cues = caption_cues(W.CACHE / "captions" / f"{vid}.en.json3", audio_s)
    offsets, matched, cursor = [], 0, 0
    for t, tri in cues:
        # search forward from the last match: the two streams run in the same order
        for i in range(cursor, len(words) - 2):
            if words[i : i + 3] == tri:
                offsets.append(stream[i][1] - t)
                cursor = i + 1
                matched += 1
                break

    offsets.sort()
    if not offsets:
        print("no cue matched — the transcripts disagree too much to compare clocks")
        return
    n = len(offsets)
    med = offsets[n // 2]
    p90 = offsets[int(n * 0.9)]
    p10 = offsets[int(n * 0.1)]
    within = lambda s: sum(1 for o in offsets if abs(o) <= s) / n * 100
    print(f"{vid} / {tag}")
    print(f"  {matched} of {len(cues)} caption cues matched ({matched/len(cues)*100:.0f} %)")
    print(f"  offset  median {med:+.2f} s   p10 {p10:+.2f} s   p90 {p90:+.2f} s")
    print(f"  within 0.25 s: {within(0.25):.0f} %   0.5 s: {within(0.5):.0f} %   1.0 s: {within(1.0):.0f} %")


if __name__ == "__main__":
    main()
