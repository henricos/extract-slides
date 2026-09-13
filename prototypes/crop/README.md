# PROTOTYPE — the crop stage (issue #12)

Throwaway. Run it, look at the output, throw it away. The decision it settles belongs in
an ADR, not here.

    python3 prototypes/crop/crop.py <video-id>                  # the activity recipe
    python3 prototypes/crop/crop.py <video-id> --recipe panel    # the prior art, for contrast

Reads `out/spike-pass1/<id>/slides/*.jpg` (pass 1's output, issue #11) plus the source
video from the fixture cache. Writes `out/spike-crop/<id>/slides/*.jpg` and an
`index.html` review page showing every capture **before and after**, side by side, with
the rule that produced its rectangle and whether the second duplicate test killed it.

## The question

Where is the slide in the frame, and what happens when that cannot be answered?

## What it does

**Three pixel populations, separated by time.**

| population | between two samples half a second apart | between two captures |
|---|---|---|
| chrome — branding, background, furniture | still | still |
| **slide** | still | changes |
| presenter — a speaker, a webcam tile, an embedded video | moves | moves |

The presenter is what the crop exists to remove, and continuous movement is what finds
him. The slide is what changes when the slide changes.

**Computed per layout, not per video and not per image.** A layout is a cluster of
captures that agree on their static pixels: two captures of the same composed layout share
their chrome, two captures across a layout change share nothing. So `b9dBJnQ_kpo`, whose
layout changes mid-talk, comes out as three layouts with three different rectangles, and
no segmentation pass had to be written.

**The rectangle starts as the whole frame and only loses a side to the presenter.** The
content mask marks pixels that *change* when the slide changes, and a slide's static
furniture — a repeated title, a logo, a footer — never does, so cropping to the content's
own bounding box slices through the header of every deck that has one. The box only says
how far a cut *could* go. A side is cut when a whole blob of continuous movement lives in
the strip between the frame edge and the content, and the cut lands halfway between the
presenter's edge and the content's. **Where there is nothing to cut away, there is no
crop.**

**Then the duplicate test runs again**, on the cropped images, where the moving part of
the frame is gone — and the *later* of two duplicates survives, not the first.

Knobs: `--layout-sim --move-frac --jump-frac --blob-in --pad --dupe --min-members`.

## Run over the sweep fixtures (45m55, 2026-09-12)

| fixture | class | in → out | rectangle | what happened |
|---|---|---|---|---|
| `pJc0l2DASpo` | C1+C3 | 38 → 38 | full frame | no presenter in shot, so nothing to cut |
| `jqpdveK2XAU` | C2b | 19 → 9 | 73 % of frame, cut right | speaker strip gone, 9 distinct slides, nothing lost |
| `b9dBJnQ_kpo` | C2b unstable | 31 → 17 | 3 layouts, 3 rectangles | cuts bottom, bottom, left; 17 complete slides |
| `2AWv_nIfp-U` | C4 | 53 → 53 | full frame | corner webcam cannot be cut without cutting slide |
| `YBH8rQv4aTQ` | C5 | 78 → 78 | full frame | whole frame moves, no separable region |
| `X3uFwLj2u7Q` | C7 | 22 → 21 | full frame | screen filmed at an angle, no straight cut exists |

241 images in, 216 out, ~3 minutes of wall clock. Every cut was checked by eye against the
source, which is the whole protocol under ADR 0004.

## What the other recipe did

`--recipe panel` is `bit-admin/AutoSlides-Extractor`'s `AutoCropDetector`, the complete
tuned recipe `docs/research/reference-implementations.md` §B.7 recommended adopting: strip
black borders, Canny(20/60), dilate, four-vertex contours, five gates, score
`areaRatio × aspectScore` against 16:9 and 4:3.

It fails on exactly the fixtures the crop stage exists for.

- On `jqpdveK2XAU` it finds **nothing at all** on every one of the 19 captures. The
  dilated edge map merges the slide's border with its own text and with the surrounding
  chrome, so no contour survives the four-vertex and 0.85-fill gates.
- On `b9dBJnQ_kpo` it finds something worse than nothing: the top-scoring rectangle is
  `(12, 273, 940, 532)` — four vertices, fill 1.00, aspect **1.77** — which is the
  **speaker's video panel**, not the slide. In a composed layout the webcam feed is a
  cleaner 16:9 rectangle than the slide is, so the aspect prior actively prefers it.

That is `sumerene`'s documented negative result reproduced first-hand: *"meeting
decorations (logos, title bars, separator lines) have brightness/edge characteristics
similar to PPT content, so they cannot be distinguished."*

## What was tried and cut

- **Cropping to the content's bounding box.** Cut the title off every slide of
  `pJc0l2DASpo`, because a header that is identical on every slide never registers as
  content. This is what turned the rule inside out: start from the whole frame.
- **Cutting at the content's edge.** Shaved the first letter off four titles on
  `b9dBJnQ_kpo`. Cutting at the presenter's edge instead left a sliver of him in shot and
  weakened the duplicate test (19 → 13 instead of 19 → 9 on `jqpdveK2XAU`). The midpoint
  is what shipped.
- **Black-bar removal as the fallback below the recipe.** The research ranked it first and
  called it recall-safe by construction. It is not: on `YBH8rQv4aTQ`, a deck of white text
  on near-black slides, the walk hit its 10 % cap on all four sides of 77 images and cut
  content out of four of them. A letterbox bar and a dark slide's margin are the same
  pixels. The chain now falls from the recipe straight to the full frame.
- **Sixty-second windows** instead of layout clusters. Too few slide changes per window to
  build a content mask; three of `jqpdveK2XAU`'s five windows found nothing.
