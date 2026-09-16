"""PROTOTYPE - throwaway. Answers issue #23: does one prune request fit over OpenRouter?

Sends N slide thumbnails as ONE vision request through the openrouter SDK (the shipping
route, ADR 0010) and reports what came back: acceptance, the error text on refusal, and
token usage. Resolution is a flag so a refusal can be re-run at a smaller size, which is
what separates an image-COUNT ceiling from a BYTES/TOKENS one.
"""
import argparse, base64, glob, io, os, sys, time
from PIL import Image
from openrouter import OpenRouter

SRC = "/home/developer/github/henricos/extract-slides/out/spike-crop"

def source_files():
    out = []
    for d in sorted(glob.glob(f"{SRC}/*/slides")):
        out += sorted(f for f in glob.glob(d + "/*.jpg")
                      if os.path.basename(f)[:-4].isdigit())
    return out

def thumb(path, long_edge, quality=85):
    im = Image.open(path).convert("RGB")
    w, h = im.size
    s = long_edge / max(w, h)
    if s < 1:
        im = im.resize((round(w * s), round(h * s)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality)
    return buf.getvalue()

PROMPT = (
    "These are consecutive screen captures from one recorded talk, in order. "
    "Many are duplicates or near-duplicates of a slide already shown. "
    "Reply with ONLY a comma-separated list of the 1-based indices that should be deleted "
    "because the slide they show is already fully captured by another image in the set. "
    "No prose."
)

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="google/gemini-3.8-flash")
    p.add_argument("--n", type=int, default=216)
    p.add_argument("--long-edge", type=int, default=680)
    p.add_argument("--max-tokens", type=int, default=2000)
    p.add_argument("--timeout-ms", type=int, default=900000)
    p.add_argument("--no-reasoning", action="store_true")
    p.add_argument("--reasoning-effort", default=None)
    a = p.parse_args()

    files = source_files()[: a.n]
    parts = [{"type": "text", "text": PROMPT}]
    total = 0
    for f in files:
        b = thumb(f, a.long_edge)
        total += len(b)
        parts.append({"type": "image_url", "image_url": {
            "url": "data:image/jpeg;base64," + base64.b64encode(b).decode()}})

    b64_mb = total * 4 / 3 / 1e6
    print(f"model={a.model}  images={len(files)}  long_edge={a.long_edge}px  "
          f"jpeg={total/1e6:.2f} MB  base64~{b64_mb:.2f} MB", flush=True)

    client = OpenRouter(api_key=os.environ["SLIDE_API_OPENROUTER_API_KEY"])
    t0 = time.time()
    try:
        kw = {}
        if a.no_reasoning:
            kw["reasoning"] = {"enabled": False}
        if a.reasoning_effort:
            kw["reasoning_effort"] = a.reasoning_effort
        r = client.chat.send(model=a.model, max_tokens=a.max_tokens,
                             timeout_ms=a.timeout_ms,
                             messages=[{"role": "user", "content": parts}], **kw)
    except Exception as e:
        print(f"REFUSED after {time.time()-t0:.1f}s")
        print(f"  {type(e).__name__}: {str(e)[:1500]}")
        sys.exit(1)

    print(f"ACCEPTED in {time.time()-t0:.1f}s")
    u = getattr(r, "usage", None)
    if u:
        print(f"  usage: {u}")
    ch = getattr(r, "choices", None)
    if ch:
        txt = getattr(getattr(ch[0], "message", None), "content", None)
        print(f"  finish_reason: {getattr(ch[0],'finish_reason',None)}")
        print(f"  reply[:600]: {str(txt)[:600]}")

if __name__ == "__main__":
    main()
