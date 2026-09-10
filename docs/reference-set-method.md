# How to find reference-set candidates

The method that assembled [`docs/reference-set.md`](reference-set.md), kept so that
"find me a better candidate for class X" does not mean rebuilding any of this.

The rules for *writing the queries* are separate, in
[`tools/candidates/CALIBRATION.md`](../tools/candidates/CALIBRATION.md). Read that first;
it is where the hard-won parts are.

## The core trick: storyboards, not downloads

YouTube publishes **storyboards** — sprite sheets of frames sampled across the whole
video — and `yt-dlp` exposes their fragment URLs in the metadata. So the entire visual
pattern of a video can be inspected without fetching a single byte of video.

**Measured cost: ~192 KiB and a few seconds per candidate**, metadata included. Screening
35 candidates cost 21 MB. Downloading them would have cost several gigabytes.

The `sb0` format is a 3x3 grid of 320x180 frames per fragment. That resolution is ample
for judging layout, and 320x180 is enough to read most slide titles.

Two properties of the sampling, both useful:

- The 9 frames **within** one sheet are only seconds apart, so a single sheet reveals
  animation and bullet-by-bullet builds.
- The 3 sheets are spread **across** the video, so comparing sheets reveals camera cuts
  between speaker and slides, and layout changes.

### The trap: do not use `yt-dlp -f sb0`

That downloads the storyboard as an **`.mhtml`** container, and extracting the images
from it with Python's `email` parser yields **corrupted JPEGs** — only the first band of
each sheet decodes, the rest is noise. It looks like a resolution problem and is not.

Fetch the fragment URLs directly from `--dump-single-json` and `curl` them instead. That
also lets you take 3 fragments rather than all 16.

`tools/candidates/sheets.sh` does this. It caches, so a candidate is never refetched.

## The pipeline

```bash
# 1. Search. Read CALIBRATION.md before writing queries.
tools/candidates/search.sh 200 720 8 \
  "lightning talk kubernetes" "fosdem talk rust" > candidates.tsv

# 2. Screen. ~192 KiB each, parallel-safe.
cut -f1 candidates.tsv | while read id; do
  tools/candidates/sheets.sh "$id" 3 &
  while [ "$(jobs -r | wc -l)" -ge 5 ]; do wait -n; done
done; wait

# 3. Classify in bulk with cheap-model subagents, ~5 candidates each.
#    The prompt is tools/candidates/classify-prompt.md — substitute the ids.

# 4. Verify every finalist yourself. One sheet per video is enough.
```

Storyboard sheets are immutable inputs, so they live in the **cache**, a sibling of the
repo (`../extract-slides-cache/storyboards/<id>/`), never inside it. Override with
`EXTRACT_SLIDES_CACHE`.

## Why step 4 is not optional

Cheap-model screening is **triage, not verdict**. Measured on this project: excellent at
bulk rejection, right about gross layout most of the time, and **wrong on 3 of the 5
finalists that were checked**. The two failure modes:

- It called **editor screencasts** presentations — frames showing a ribbon, a thumbnail
  rail and "Click to add title" text.
- It called a speaker's **vertical side strip** an overlay, which confuses the class that
  needs cropping with the class that does not.

Both errors would have put a useless video into the set that governs every measurement
in the project. Reading one sheet per finalist costs almost nothing and catches them.

## Two axes to record, not one

A video has a **class** (its visual difficulty) and a **role**:

- a **fixture**, chosen to span difficulty classes, kept short because every spike
  re-runs it;
- **target corpus**, real material the tool exists to process, chosen for subject.

These two jobs conflict — the target corpus is whatever length and layout it happens to
be — so the record says which each video is. Fixtures are swept; target corpus is run
once at the end.

## Yield, measured

For calibration of expectations: 5 search rounds, ~55 queries, 190 raw results, 35
screened, **6 fixtures kept**. Roughly a 1-in-6 hit rate on screened candidates, and
most rejections were *not* wrong-class — they were **illegible slides** and **editor
screencasts**.
