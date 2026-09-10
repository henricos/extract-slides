# Ground truth

One file per reference video, `<video-id>.json`. The schema, and the rules that decide
what counts as one slide, are in
[`docs/adr/0003-correctness-metric-and-ground-truth.md`](../docs/adr/0003-correctness-metric-and-ground-truth.md).

The videos themselves are listed in [`docs/reference-set.md`](../docs/reference-set.md).

These files are hand-verified and are the measuring stick for every detection and crop
decision in the project. Machine-proposed, human-signed: a file without a `verified_by`
is a proposal, not ground truth.
