# Candidate search calibration

Learned while assembling the reference set for issue #4. These are the rules that
turn a noisy search into usable fixtures. Encode them in the search queries AND in
the classification prompt.

## Subject matter must be accessible

Restrict to subjects where people normally present slides AND where a non-specialist
can tell whether the output is wrong: **technology, education, health, culture and
customs, business**. Avoid highly specialised research vocabulary.

The reason is not taste. The set is ground-truth labelled by a human (issue #10) and
its transcript is judged for quality. If the subject is obscure, the labeller cannot
see when something is wrong, so the validation loses its weight, and the transcript's
error profile stops being representative.

Rejected on this rule: `2AWv_nIfp-U` (Gaussian Point Splatting, SIGGRAPH) — visually
an excellent embedded-video fixture, but the vocabulary is unreadable to a
non-specialist.

## Reject: editor screencasts

The single most common false positive. A screencast of PowerPoint, Google Slides or
Keynote in **edit view** looks like slides to a cheap classifier but is not a
presentation: the frames carry the ribbon, the thumbnail rail, tool panels, and
placeholder text like "Click to add title" or "Bullet 1".

Caught three of these: `3TLjFhv9IRk`, `cDdLZO7ET_I`, `74YwR4EFdYk`. Queries about
animation and transitions pull them in bulk, because tutorial channels dominate those
terms.

The subject of a video is irrelevant to its class — but the frames have to show a
*presented* slide, not a slide being *authored*.

## Reject: illegible slides

The second most common reason to drop a candidate, and cheap classifiers do not
volunteer it. Make `LEGIBLE / ILLEGIBLE` a required field. Typical causes: a projector
screen blown out by stage lighting (`Z-PA3Pohp7Q`, `CRQSrIWX81k`), slide rendered too
small inside a composed layout (`l8xiNOCIdLY`, `VTxJbUPhRJw`).

An illegible slide cannot be ground-truth labelled, so it measures nothing.

## Reject: meta-content about presenting

Queries containing "presentation", "slides" or "how to" return advice videos about
giving talks, not talks. Search for the *venue* instead: conference names, "lightning
talk", "meetup", "webinar", "lecture".

## Query patterns that worked

- `lightning talk <topic>` — reliably short (3-6 min) and slide-heavy, which serves
  the duration budget at the same time.
- `<conference name> talk <topic>` — conference-produced recordings, so camera cutting
  and composed layouts.
- `webinar <topic>` / `online meetup <topic>` — the webcam-overlay and inset layouts.
- `lecture <subject>` — progressive builds, which are commoner in teaching decks than
  in modern conference decks.

## Cheap-model screening is triage, not verdict

A Haiku subagent reading storyboard sheets is excellent at bulk rejection and gets the
gross layout right most of the time. On finalists it was wrong 3 times out of 5:
it called editor screencasts presentations, and it called a speaker's side strip an
overlay. **Every video that enters the set must be verified by a strong model or a
human** before it is recorded.

## Reject: tutorials, whatever the subject

Any query containing **"how to", "record", "create"** or **"presentation"** returns
tutorial channels in bulk, and the subject of the query barely shifts the result. A
search for `webinar public health slides presentation` returned eight PowerPoint
tutorials and nothing else. Search for the **venue**, never for the activity.

## C2a is not reachable by search

The webcam-overlaid-on-the-slide layout (Zoom/Meet/Teams) is an artefact of the
recording tool. Nobody writes it in a title or a description, so searching for it
returns tutorials about *producing* that layout. Two dedicated rounds returned
sixteen tutorials and zero fixtures.

Get C2a from a **known source** instead: a channel you already know records that way,
or a video already in hand. In this project it came from the operator's own corpus.

## Short duration fights accessible subject

They pull in opposite directions. `lightning talk` reliably yields 3-6 minutes but
skews hard to conference software topics. Health, education and culture content that
people present with slides is normally a 25-60 minute lecture or webinar. Budget for
one long fixture per accessible-subject class rather than trying to find a short one.

## Where the subject rule actually binds

Accessible vocabulary matters where **a human judges content**: ground-truth labelling
of which slides are distinct (issue #10) and judging transcript quality. It matters
much less for a pure false-positive count — "did the detector emit forty slides for
one slide with a video playing?" needs no understanding of the content. So an obscure
but severe fixture can still earn its place in a class whose test is mechanical.
