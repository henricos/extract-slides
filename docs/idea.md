# Idea and requirements

## Problem

Given the URL of a YouTube video (or, more generally, any recorded video) of someone presenting slides, reconstruct the original presentation along two axes:

- **What was said** — the transcript of the speech.
- **What was shown** — a screenshot of every distinct slide, in order.

The slide doesn't always fill the whole frame: it sometimes appears in a smaller box, in a corner of the screen, next to a webcam feed of the speaker or a video-call UI. A raw full-frame screenshot is an acceptable baseline, but the useful output is the *slide region only*.

## Why revisit this now

This exact problem was already tackled by a handful of open-source scripts, but the open-source attempts tend to be old, several predate today's AI-era tooling entirely, and most rely on strategies that have since been superseded by better tools or better techniques for the same step (downloading, detecting a slide change, isolating the slide region, transcribing the speech). The idea is to rebuild this tool with what's available today, rather than adopt and patch an old codebase.

## Requirement

### 1. Transcript

- If the video has a YouTube caption (manual or auto-generated), use it directly.
- Otherwise, extract the audio and run it through a speech-to-text model (Whisper or an equivalent) to produce the transcript.

### 2. Slides (screenshots)

- Download the video.
- Detect when a new slide appears over the course of the video (monitor for slide changes over time).
- On every new slide, capture a screenshot. The resulting set of screenshots, in order, is what reconstructs the original slide deck.

### 3. Automatic crop (improvement over the baseline)

- Apply automatic cropping to each screenshot so that only the slide region remains — necessary whenever the slide occupies a smaller box within the frame rather than the full screen.
- A full-frame screenshot (no crop) is an acceptable fallback/baseline; the crop is what makes the output actually usable.

## Non-goals

These are explicitly **not** part of the core requirement:

- **Reconstructing an editable original file** (`.pptx`, `.key`, or similar) from the screenshots. The deliverable is the transcript plus the slide images, not a re-editable deck.
- **Summarization**, of the whole talk or per slide, is not a default output.

## Possible future extensions (out of scope for now)

If the core pipeline can be built with existing tools alone (no LLM required for detection, transcription or cropping), that's the preferred path. Once the structured output (transcript + slide screenshots) exists, some LLM-based extensions become possible on top of it, but they are deliberately deferred:

- **Reading the text on each slide** — a modern equivalent of OCR, using a vision-capable model instead of Tesseract-style OCR.
- **Summarizing the whole presentation.**
- **Summarizing per slide** — condensing only the speech that was said while that specific slide was on screen.
- For both summarization modes, **filtering out speech that isn't part of the presentation itself** (side comments, audience questions, banter) before summarizing.

## Deployment shape (open — to be decided later)

Two possible paths, depending on how heavy the tool ends up being:

- **Light** — trigger via a skill that calls a script running on the Hermes server itself. Input: a URL. Output: the result, produced locally.
- **Heavy** — a dedicated application running on the main server, with its own API/MCP interface to trigger the process from the outside.

## Open questions

- Exact slide-change detection strategy (frame differencing, OCR-based, content-change detection, timestamp-based).
- Exact slide-region cropping strategy (edge/rectangle detection of the slide frame, tracking across the video).
- Final output shape: paired (slide, corresponding transcript excerpt) records, or two separate artifacts (all screenshots + a single transcript file).
