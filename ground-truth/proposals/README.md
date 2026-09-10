# Machine proposals, not ground truth

One file per reference video, straight out of
[`tools/groundtruth/propose.py`](../../tools/groundtruth/propose.py): the candidate
**states** it found, with the timestamp of each, the bracket in which the change
happened (`change_after_s`), how long the state survived (`dwell_s`), and the
parameters that produced it.

A state is a visually distinct, settled frame. It is **not** an expected slide.
Turning states into expected slides means applying the accumulation rule from
[ADR 0003](../../docs/adr/0003-correctness-metric-and-ground-truth.md) by eye,
grouping the additive runs, rejecting the frames that are not slides at all, and
drawing the slide rectangles by hand. That is the human half, and until it is done
and signed there is no ground truth — see [`../README.md`](../README.md).

These files are committed because they are the evidence base for the labelling
rules still being settled, and because they make the proposal reviewable in a diff.
They are fully regenerable: `propose.py sample <id>` then `propose.py propose <id>`,
given the video in the cache.

`tools/groundtruth/METHOD.md` explains how the states are found and what the
calibration measured.
