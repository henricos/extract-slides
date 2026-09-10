# Classification prompt for a screening subagent

Dispatch one subagent per batch of ~5 candidates, on a **cheap model**. Substitute the
video ids at the bottom. Screening is triage: see the last section.

---

You are classifying YouTube videos by their VISUAL LAYOUT, to build a reference set for
a tool that extracts slide screenshots from recorded talks.

For each video id below, the directory `<CACHE>/storyboards/<id>/` contains:
- `info.json` — duration, title, uploader
- `sheet1.jpg`, `sheet2.jpg`, `sheet3.jpg` — each is a 3x3 grid of 9 video frames
  (960x540 total, each frame 320x180). Read them with the Read tool, which displays
  images.

IMPORTANT about the sampling: the 9 frames WITHIN one sheet are only seconds apart, so a
sheet is good for spotting animation and bullet-by-bullet builds. The 3 sheets are spread
across the whole video, so comparing sheets is good for spotting camera cuts between
speaker and slides.

Classify each video into exactly ONE primary class, and list any secondary classes that
also clearly apply:

- `C1` — Slide fills the whole frame, no speaker visible over it. Clean baseline.
- `C2a` — Slide fills the frame BUT the speaker's webcam is overlaid ON TOP of it (a small
  box or circle in a corner, over the slide content).
- `C2b` — Slide occupies only PART of the frame: speaker video beside it, or the slide sits
  inside a branded frame/border with banners around it.
- `C3` — Progressive build: the same slide gaining bullets/elements one at a time across
  nearby frames.
- `C4` — A video, screen recording, animation or live demo playing INSIDE the slide.
- `C5` — The frame CUTS between a camera on the speaker/audience and the slide feed, so the
  slide leaves the screen and comes back.
- `C7` — A camera films the physical scene and the slide appears on a screen/wall in the
  BACKGROUND, at an angle, not captured from a projector feed.
- `XE` — **Editor screencast.** The frames show a slide being AUTHORED, not presented:
  a ribbon or toolbar, a thumbnail rail, tool panels, or placeholder text like "Click to
  add title" or "Bullet 1". Reject these. They are the most common false positive.
- `X` — Not usable for any other reason: no slides at all (interview, vlog, talking head,
  music, b-roll only).

Judge ONLY what the frames show. The video's SUBJECT is irrelevant to its class — but the
frames must show a slide being *presented*, never one being *authored*.

Two required extra fields:
- `LEGIBLE` or `ILLEGIBLE` — is the slide TEXT actually readable in the frames, or is it
  washed out by stage lighting, rendered too small inside a composed layout, out of focus,
  or blocked? An illegible slide cannot be ground-truth labelled, so it measures nothing.
- `BUILD` — write `BUILD` if you can see the same slide gaining elements between adjacent
  frames in one sheet, otherwise `-`.

Report ONE line per video, exactly this pipe-separated format, nothing else per line:

`<id> | <primary class> | <secondary or -> | <LEGIBLE/ILLEGIBLE> | <BUILD or -> | <confidence high/medium/low> | <one short sentence of visual evidence>`

Do not write any other prose. Do not modify any files.

Video ids to classify:
<IDS>

---

## Screening is triage, not verdict

Measured on this project: a cheap model reading these sheets is excellent at bulk
rejection and gets the gross layout right most of the time, but on finalists it was
**wrong 3 times out of 5**. It called editor screencasts presentations, and it called a
speaker's vertical side strip an overlay.

**Every video that enters the set must be verified by a strong model or a human** before
it is recorded. Reading one sheet per finalist is enough.
