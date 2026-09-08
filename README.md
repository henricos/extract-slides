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

## Explicitly out of scope

- **Reconstructing an editable original file** (e.g. rebuilding a `.pptx`/`.key` from the screenshots). The output is the transcript plus the slide images — not a re-editable deck.
- **Summarization** (of the whole talk or per slide) is not a default step. If it gets added later, it's an optional, LLM-based extension on top of the structured output above — not a requirement of the core tool.

## License

MIT.
