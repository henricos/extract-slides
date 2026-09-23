"""Every measured value in one place, each carrying the ADR that chose it.

None of these was tuned against a score, and none can be: there is no ground
truth and no correctness metric (ADR 0004). Where a constant had to be chosen
it was chosen toward over-capture, because losing a capture is the only
failure that costs anything.

`docs/stack.md` §13 is the table these values come from. Moving one means
moving `tests/test_constants.py` too — that is the point of the test, not an
inconvenience of it.
"""

# --- detect (pass 1) -------------------------------------------------------
# -> docs/adr/0005-pass-1-pinned-anchor-edge-signal-watchdog.md

#: Samples taken per second of media, in both video passes.
SAMPLE_RATE_PER_SECOND = 2

#: Width, in pixels, the frame is scaled to before anything is measured on it.
ANALYSIS_WIDTH_PX = 480

#: Fraction of analysis pixels whose edge state must change to call a
#: transition. The table reads "≥ 0.5 % of pixels".
EDGE_DIFFERENCE_TRIGGER = 0.005

#: How long the held anchor must already have stood when a sample differs
#: from it, for that anchor to be emitted. Note which way round this runs:
#: it gates the *emission of the anchor that is ending*, not the admission
#: of the sample that is starting. A minimum-scene-length reading of the
#: same number is a miss generator, which is the thing pass 1 exists to
#: avoid.
ANCHOR_DWELL_SECONDS = 1.5

#: Emit a capture anyway when this long passes with nothing emitted. This is
#: what keeps a camera filming a screen in a dark auditorium — where the frame
#: is never still — from yielding a single image.
WATCHDOG_SECONDS = 10

#: Size of the DCT perceptual hash. The research measured a real slide edit at
#: Hamming distance exactly 0 at 64 bits, which is why this is not smaller.
PHASH_BITS = 256

#: Fraction of differing hash bits under which two captures are the same
#: slide. Used by both duplicate tests.
DUPLICATE_THRESHOLD = 0.02

# --- crop ------------------------------------------------------------------
# -> docs/adr/0006-crop-by-cutting-the-presenter-away.md

#: A pixel is the presenter's when it moves in more than this fraction of the
#: samples.
PRESENTER_PIXEL_MOVEMENT_FRACTION = 0.06

#: Grey levels of spread above which a pixel counts as carrying content.
CONTENT_PIXEL_GREY_LEVELS = 45

#: A pixel is content when it clears CONTENT_PIXEL_GREY_LEVELS in more than
#: this fraction of the captures.
CONTENT_PIXEL_CAPTURE_FRACTION = 0.08

#: Two captures share a layout when their maps agree on at least this fraction
#: of pixels.
LAYOUT_CLUSTER_AGREEMENT = 0.50

#: A layout smaller than this gets no rectangle, so a very short video may get
#: no crop at all. That is the safe answer, not a defect.
MINIMUM_LAYOUT_CAPTURES = 3

#: A blob counts as living in a strip when this much of it is inside.
BLOB_IN_STRIP_FRACTION = 0.80

#: Blobs smaller than this fraction of the largest are specks, not presenters.
SPECK_FILTER_FRACTION = 0.10

#: The cut goes at the midpoint, then this much further outward — away from
#: the content, because cutting content is the failure that costs.
CUT_OUTWARD_MARGIN = 0.015

#: A derived rectangle smaller than this fraction of the frame is rejected and
#: the full frame kept.
RECTANGLE_MIN_FRAME_FRACTION = 0.10

#: A derived rectangle larger than this fraction of the frame is rejected too:
#: it is not cutting anything worth the risk.
RECTANGLE_MAX_FRAME_FRACTION = 0.98

# --- transcribe ------------------------------------------------------------
# -> docs/adr/0007-transcribe-with-small-and-trust-the-media-clock.md

#: CPU threads for local speech-to-text. Measured: 4 threads is 18 % *slower*
#: than 2 on the target host.
STT_THREADS = 2

#: Beam width for local speech-to-text. Greedy (1) is 40 % cheaper and
#: slightly worse; it is the lever to pull if a long video must finish sooner.
STT_BEAM_SIZE = 5

#: Reject a caption track whose last cue ends more than this far past the
#: end of the video. ADR 0007 writes the tolerance as "a couple of
#: seconds"; 2.0 is that phrase read against its own measurement, where
#: three of four caption files agreed with their video's duration to
#: within 2 s and the fourth overran by 376 s, carrying six minutes of a
#: different talk.
CAPTION_OVERRUN_TOLERANCE_SECONDS = 2.0

# --- prune -----------------------------------------------------------------
# -> docs/adr/0008-the-deletion-pass-two-ways-to-name-the-surplus.md

#: Long edge, in pixels, each image is resized to before it is sent.
PRUNE_IMAGE_LONG_EDGE_PX = 680

#: Output token ceiling for the single vision request.
PRUNE_MAX_TOKENS = 65_536

# --- output ----------------------------------------------------------------
# -> docs/adr/0009-the-output-contract-a-table-of-instants.md

#: Slide filenames are zero-padded to at least this width, widening only past
#: 999.
SLIDE_NUMBER_MIN_DIGITS = 3


#: Which ADR chose each value above. The section comments say the same
#: thing for a reader; this says it for the test, which walks the mapping
#: so that a constant added without an ADR fails the suite rather than
#: slipping in unsourced.
ADR_BY_CONSTANT: dict[str, str] = {
    "SAMPLE_RATE_PER_SECOND": "ADR 0005",
    "ANALYSIS_WIDTH_PX": "ADR 0005",
    "EDGE_DIFFERENCE_TRIGGER": "ADR 0005",
    "ANCHOR_DWELL_SECONDS": "ADR 0005",
    "WATCHDOG_SECONDS": "ADR 0005",
    "PHASH_BITS": "ADR 0005",
    "DUPLICATE_THRESHOLD": "ADR 0005",
    "PRESENTER_PIXEL_MOVEMENT_FRACTION": "ADR 0006",
    "CONTENT_PIXEL_GREY_LEVELS": "ADR 0006",
    "CONTENT_PIXEL_CAPTURE_FRACTION": "ADR 0006",
    "LAYOUT_CLUSTER_AGREEMENT": "ADR 0006",
    "MINIMUM_LAYOUT_CAPTURES": "ADR 0006",
    "BLOB_IN_STRIP_FRACTION": "ADR 0006",
    "SPECK_FILTER_FRACTION": "ADR 0006",
    "CUT_OUTWARD_MARGIN": "ADR 0006",
    "RECTANGLE_MIN_FRAME_FRACTION": "ADR 0006",
    "RECTANGLE_MAX_FRAME_FRACTION": "ADR 0006",
    "STT_THREADS": "ADR 0007",
    "STT_BEAM_SIZE": "ADR 0007",
    "CAPTION_OVERRUN_TOLERANCE_SECONDS": "ADR 0007",
    "PRUNE_IMAGE_LONG_EDGE_PX": "ADR 0008",
    "PRUNE_MAX_TOKENS": "ADR 0008",
    "SLIDE_NUMBER_MIN_DIGITS": "ADR 0009",
}
