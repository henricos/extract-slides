# extract-slides

Reconstruct a presentation from a recorded talk video: the transcript of what was said, and a screenshot of every slide that was shown.

## Why

Given a video of someone presenting slides (a YouTube talk, a recorded Zoom/Meet session, a lecture), the goal is to get back:

- **The transcript** of the speech.
- **A screenshot of every distinct slide**, in the order it appeared — ideally cropped to just the slide region, since the slide often occupies only part of the frame (a smaller box in a corner, next to the speaker's webcam) rather than the full screen.

This class of tool already exists, but the open-source attempts tend to be old, several predate today's AI-era tooling entirely, and most rely on strategies that have since been superseded by better tools or better techniques for the same step (downloading, detecting a slide change, isolating the slide region, transcribing the speech). `extract-slides` revisits the same problem with what is available now, rather than adopting and patching an old codebase.

## Scope

What the tool is meant to do, in order:

1. **Get the transcript** — the YouTube caption when one is available, or a local speech-to-text pass over the extracted audio otherwise.
2. **Get one screenshot per slide** — detect when a new slide appears over the course of the video, and capture it.
3. **Crop each screenshot to the slide region** — when the slide doesn't fill the whole frame, isolate just that region (the part that actually matters).

Step 2 runs in **two passes**, and only the first is automatic: it captures generously and deliberately leaves too much, then the excess is deleted afterwards — by hand, or by an AI pass over the captured images. Losing a slide is the only failure that costs anything; a duplicate costs one deletion. See [ADR 0004](docs/adr/0004-capture-generously-delete-afterwards.md).

## Explicitly out of scope

- **Reconstructing an editable original file** (e.g. rebuilding a `.pptx`/`.key` from the screenshots). The output is the transcript plus the slide images — not a re-editable deck.
- **Summarization** (of the whole talk or per slide) is not a default step. If it gets added later, it's an optional, LLM-based extension on top of the structured output above — not a requirement of the core tool.

## Where the detail lives

The technical strategy is being settled decision by decision on the
[strategy map](https://github.com/henricos/extract-slides/issues/1), with an ADR per
hard decision.

- [`docs/idea.md`](docs/idea.md) — the idea and requirements.
- [`docs/adr/`](docs/adr/) — the decisions taken, and why. Start with
  [0004, the two passes](docs/adr/0004-capture-generously-delete-afterwards.md) and
  [0002, the CLI surface](docs/adr/0002-cli-surface.md).
- [`docs/research/`](docs/research/) — primary-source research behind the decisions:
  caption acquisition, CPU-only speech-to-text, slide-change detection, slide-region
  cropping, and what twelve reference implementations actually do in their source.
- [`docs/reference-set.md`](docs/reference-set.md) — the fixed set of real videos the tool
  is watched against, spanning the cases that break naive detectors, and
  [`docs/reference-set-method.md`](docs/reference-set-method.md) for how to find more.
- [`docs/similar-tools.md`](docs/similar-tools.md) — prior-art scan.

## Tools

- [`tools/candidates/`](tools/candidates/) — find and screen candidate videos for the
  reference set without downloading them. Read
  [`CALIBRATION.md`](tools/candidates/CALIBRATION.md) before writing search queries.

## License

MIT.
