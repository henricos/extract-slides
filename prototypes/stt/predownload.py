from faster_whisper.utils import download_model
for m in ["small", "medium", "large-v3-turbo"]:
    p = download_model(m, output_dir=None, cache_dir="/home/developer/github/henricos/extract-slides-cache/models/faster-whisper")
    print(m, "->", p, flush=True)
