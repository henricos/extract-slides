# Prototype: does `prune` fit one request over OpenRouter?

Throwaway spike for [#23](https://github.com/henricos/extract-slides/issues/23).

[ADR 0008](../../docs/adr/0008-the-deletion-pass-two-ways-to-name-the-surplus.md) designed
`prune` as a **single vision request** over the whole talk, justified against limits measured
on Anthropic's API directly. [#15](https://github.com/henricos/extract-slides/issues/15)
moved the call to **OpenRouter**, which documents no image-count or request-size limit of
its own and states they "vary per provider and per model". This spike sends real requests
down the shipping route to find out whether the single request survives the move.

## What it does

`probe.py` sends N slide thumbnails as **one** vision request through the `openrouter` SDK
(the shipping client, ADR 0010) and reports acceptance, the error text on refusal, latency
and token usage. Images come from the crop spike's output, resized on the fly, so resolution
is a flag: a refusal can be re-run smaller, which is what separates an image-**count** ceiling
from a **bytes**/**tokens** one.

```
uv run --with openrouter --with pillow --python 3.12 \
  python probe.py --n 216 --max-tokens 65536 --reasoning-effort low --timeout-ms 900000
```

Reads the key from `SLIDE_API_OPENROUTER_API_KEY`.

## Payload

The 216 final slides of the six sweep fixtures, in fixture order, at 680 px on the long edge
and JPEG quality 85 — 6.23 MB, about 8.30 MB base64. That is ADR 0008's measured volume for
one 45-minute talk (4.7 images per minute), and its 6.6 MB estimate lands in the right place.

## Results, `google/gemini-3.8-flash`

| images | latency | prompt tokens | per image | reasoning tokens | cost | finish |
|--------|---------|---------------|-----------|------------------|------|--------|
| 3      | 18.4 s  | 3 364         | 1 121     | 1 918            | —    | stop   |
| 25     | 59.0 s  | 27 564        | 1 102     | 8 274            | $0.052 | stop |
| 50     | 88.8 s  | 55 064        | 1 101     | 13 085           | $0.091 | stop |
| 100    | 112.1 s | 110 064       | 1 101     | 15 359 (capped)  | $0.143 | **length** |
| **216**| **172.1 s** | **237 334** | **1 099** | 26 318         | **$0.278** | **stop** |

The first four rows ran with `max_tokens=16000`; the last with `max_tokens=65536` (the
model's ceiling) and `reasoning_effort=low`.

## What was learned

**There is no image-count ceiling on this route.** No request was refused for image count.
The `too many images and documents: 27 + 0 > 20` report that motivated the ticket is a
*validation* error returned in seconds; 216 images passed that stage and were processed.
The single request survives the move to OpenRouter.

**The binding constraint is the output budget, not the input.** Reasoning tokens grow with
the image count, and at `n=100` they took 15 359 of the 16 000 allowed, leaving 637 for the
answer. The reply degenerated from the requested index list into per-image prose and was cut
with `finish_reason: length`. That row is not a route limit; it is the spike under-budgeting
its own request. Raising the budget to the model's 65 536 fixed it at more than twice the
image count.

**`reasoning: {"enabled": false}` is silently ignored** by this model. Rows 2-4 were sent
with it and reasoned anyway. Use `reasoning_effort`.

**ADR 0008's per-image token number does not transfer.** The ADR computed 350 visual tokens
per image at 680 px from Anthropic's `⌈w/28⌉ × ⌈h/28⌉`. Gemini charges **1 099**, three times
as much, stable across every run. The cost per talk still lands near the ADR's $0.37 —
$0.278 — because the price per token is 6.7× lower, but the arithmetic behind it is
Anthropic's and should not be quoted for this route.

**Latency is sublinear in image count.** 25 → 50 doubled the input and raised latency 1.5×.
216 images cost 172 s, well inside what a `prune` run can spend.

**One earlier run is recorded as inconclusive.** 216 images with reasoning on and
`max_tokens=16000` did not return, raising `ReadTimeout` after 3 648 s. No refusal, no error
text from the route. The httpx client the SDK builds carries `Timeout(5.0)` and an empty
`retry_config`, so the origin of that cut was not pinned down. The successful 216-image run
makes it a property of that request, not of the route.

## Scope

Everything here was measured on `google/gemini-3.8-flash`, at the operator's instruction.
ADR 0008 and #15 ship `anthropic/claude-opus-5`, which was **not** tested.
