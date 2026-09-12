# Ground truth

One file per reference video, `<video-id>.json`. The schema, and the rules that decide
what counts as one slide, are in
[`docs/adr/0003-correctness-metric-and-ground-truth.md`](../docs/adr/0003-correctness-metric-and-ground-truth.md).

The videos themselves are listed in [`docs/reference-set.md`](../docs/reference-set.md).

These files are the measuring stick for every detection and crop decision in the project.
Machine-proposed, human-corrected: the tooling proposes states and rectangles, and a
person goes through them. Nothing requires a signature -- git already records who changed
what.

[`proposals/`](proposals/) holds the machine half while the human half is pending: the
candidate states `tools/groundtruth/propose.py` found per video, before anyone has said
which of them carry content that must not be missed. [`tools/groundtruth/validate.py`](../tools/groundtruth/validate.py)
checks a finished file against the schema.
