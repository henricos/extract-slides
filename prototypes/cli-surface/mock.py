#!/usr/bin/env -S uv run --quiet --with typer --with rich --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["typer", "rich"]
# ///
"""
PROTOTYPE — THROWAWAY. Navigable CLI mock for `extract-slides` (issue #3).

Answers one question: what is the user-facing surface of the CLI?

Nothing here does real work. No video is downloaded, no model is loaded. Every
stage is simulated so the *ergonomics* can be judged before anything is built:
subcommands, flags and defaults, the output directory as the user sees it, the
messages, and the invocation an agent would use unattended.

Three RADICALLY DIFFERENT command structures are implemented, switchable with
the V env var. Flip between them, then steal the best bits from each:

    V=A  task verbs      — one shot: extract / drop / review
    V=B  stage verbs     — composable: transcript / slides / crop / pair / all
    V=C  run workspace   — stateful, resumable: new / run / status / ls

Output layout is a second, independent axis (--layout flat|paired|staged) and
is really materialised on disk so the tree can be inspected with `tree`.

Per ADR 0001: typer with rich_markup_mode=None (plain indented help, no boxed
panels); rich is used for progress output only.
"""

from __future__ import annotations

import base64
import json
import os
import random
import shutil
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

VARIANT = os.environ.get("V", "A").upper()
PROG = "extract-slides"

err = Console(stderr=True, highlight=False, soft_wrap=True)
out = Console(highlight=False, soft_wrap=True)

# A real 1x1 transparent PNG, so materialised stubs open in an image viewer.
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


# ----------------------------------------------------------------------------
# Mock-only knobs (NOT part of the proposed surface)
# ----------------------------------------------------------------------------

class Layout(str, Enum):
    flat = "flat"
    paired = "paired"
    staged = "staged"


class Case(str, Enum):
    captioned = "captioned"      # happy path: ASR caption exists
    no_caption = "no-caption"    # yt-dlp exits 0 with nothing; STT fallback
    ptbr = "ptbr"                # pt-BR caption, lower confidence
    suspects = "suspects"        # progressive builds -> dedupe suspects
    fail = "fail"                # hard failure mid-run


class Report(str, Enum):
    text = "text"
    json = "json"


@dataclass
class Sim:
    layout: Layout = Layout.flat
    case: Case = Case.captioned
    report: Report = Report.text
    slow: bool = False
    review: bool = False
    transcript_only: bool = False
    slides_only: bool = False
    force_stt: bool = False
    lang: Optional[str] = None
    roi: Optional[str] = None
    events: list[str] = field(default_factory=list)


SIM = Sim()


def pace(seconds: float) -> None:
    if SIM.slow:
        time.sleep(seconds)


def footer() -> None:
    others = [v for v in ("A", "B", "C") if v != VARIANT]
    err.print(
        f"\n[dim]── mock ── variant [bold]{VARIANT}[/bold] "
        f"({VARIANT_NAMES[VARIANT]}) · flip with "
        f"{' or '.join(f'V={o}' for o in others)} · "
        f"layout={SIM.layout.value} case={SIM.case.value} · nothing was really "
        f"downloaded[/dim]"
    )


VARIANT_NAMES = {
    "A": "task verbs, one shot",
    "B": "stage verbs, composable",
    "C": "run workspace, resumable",
}


# ----------------------------------------------------------------------------
# Message vocabulary — the actual thing under review
# ----------------------------------------------------------------------------

def human() -> Console:
    """Narration console. With --report json, stdout is reserved for the JSON."""
    return err if SIM.report is Report.json else out


def step(msg: str) -> None:
    human().print(f"[bold cyan]·[/bold cyan] {msg}")


def ok(msg: str) -> None:
    human().print(f"[bold green]✓[/bold green] {msg}")


def warn(msg: str) -> None:
    human().print(f"[bold yellow]![/bold yellow] {msg}")


def fail(msg: str, hint: str | None = None) -> None:
    err.print(f"[bold red]✗[/bold red] {msg}")
    if hint:
        err.print(f"  [dim]{hint}[/dim]")


def detail(msg: str) -> None:
    human().print(f"  [dim]{msg}[/dim]")


VIDEO = {
    Case.captioned: dict(
        vid="X2vr81CJ934", title="Designing Data-Intensive Pipelines",
        dur="41:12", res="1920x1080", lang="en", slides=34, suspects=1,
    ),
    Case.no_caption: dict(
        vid="3sB4Iv_tM7U", title="Internal Tech Talk — Q3 Architecture Review",
        dur="28:40", res="1280x720", lang="en", slides=22, suspects=0,
    ),
    Case.ptbr: dict(
        vid="C38xlWnkezQ", title="Arquitetura de dados na prática",
        dur="18:55", res="1920x1080", lang="pt-BR", slides=19, suspects=2,
    ),
    Case.suspects: dict(
        vid="7JbOagrwysE", title="Kubernetes na Vida Real (63 min)",
        dur="63:07", res="1920x1080", lang="pt-BR", slides=58, suspects=11,
    ),
    Case.fail: dict(
        vid="dQw4w9WgXcQ", title="—", dur="?", res="?", lang="?",
        slides=0, suspects=0,
    ),
}


def slug(v: dict) -> str:
    base = v["title"].lower()
    keep = "".join(c if c.isalnum() else "-" for c in base)
    while "--" in keep:
        keep = keep.replace("--", "-")
    return f"{keep.strip('-')[:40]}-{v['vid']}"


# ----------------------------------------------------------------------------
# Simulated stages
# ----------------------------------------------------------------------------

def stage_probe(url: str) -> dict:
    v = VIDEO[SIM.case]
    step(f"Probing {url}")
    pace(0.6)
    if SIM.case is Case.fail:
        fail(
            "yt-dlp could not extract the video (HTTP 429 from YouTube)",
            "Rate limited. Retry later, or lower --concurrency.",
        )
        if SIM.report is Report.json:
            print(json.dumps(dict(
                status="error", error="rate_limited",
                message="yt-dlp could not extract the video (HTTP 429)",
                retryable=True,
            ), indent=2))
        footer()
        raise typer.Exit(code=2)
    detail(f"title      {v['title']}")
    detail(f"duration   {v['dur']}   resolution {v['res']}")
    if SIM.case is Case.no_caption:
        # The research finding that most shapes the messages: yt-dlp exits 0
        # when a video has no caption, indistinguishable from success.
        detail("captions   none (checked automatic_captions and subtitles)")
    else:
        detail(f"captions   automatic ASR, {v['lang']}-orig (word timings: yes)")
    ok("Probe complete")
    return v


def stage_transcript(v: dict) -> dict:
    if SIM.force_stt:
        step("Transcript: local STT (forced with --stt)")
        source = "stt"
    elif SIM.case is Case.no_caption:
        warn("No YouTube caption for this video — falling back to local STT")
        detail("yt-dlp exits 0 when no caption exists, so this was decided "
               "from the metadata, not the exit code")
        step("Transcript: local STT")
        source = "stt"
    else:
        step(f"Transcript: YouTube ASR caption ({v['lang']}-orig, json3)")
        source = "caption"

    if source == "caption":
        pace(1.0)
        detail("fetched  1 track · 1,842 events · 11,204 words · timings word-level")
        ok(f"Transcript from YOUTUBE CAPTION ({v['lang']}-orig)")
        return dict(source="caption", timings="word", lang=v["lang"],
                    words=11204, model=None)

    # Long STT pass — the progress rendering under review.
    detail("model    faster-whisper medium int8 · 2 threads · CPU only")
    detail("this stage is slow by design on the target host")
    total = 24
    if sys.stdout.isatty():
        from rich.progress import (BarColumn, Progress, TextColumn,
                                   TimeElapsedColumn, TimeRemainingColumn)
        with Progress(
            TextColumn("  transcribing"), BarColumn(bar_width=30),
            TextColumn("{task.percentage:>3.0f}%"),
            TextColumn("[dim]{task.fields[at]}[/dim]"),
            TimeElapsedColumn(), TimeRemainingColumn(),
            console=human(), transient=False,
        ) as prog:
            t = prog.add_task("stt", total=total, at="00:00")
            for i in range(total):
                pace(0.12)
                prog.update(t, advance=1,
                            at=f"{(i + 1) * 105 // 60:02d}:{(i + 1) * 105 % 60:02d}")
    else:
        # Non-TTY (an agent, or a captured log): plain periodic lines, no
        # cursor tricks. Judge this shape too — it is the unattended default.
        for i in range(0, total, 6):
            pace(0.12)
            human().print(f"  transcribing … {i * 100 // total:>3d}% "
                          f"(audio {i * 105 // 60:02d}:{i * 105 % 60:02d})")
    ok(f"Transcript from LOCAL STT (faster-whisper medium int8, {v['lang']})")
    return dict(source="stt", timings="segment", lang=v["lang"],
                words=10871, model="faster-whisper medium int8")


def stage_video(v: dict) -> None:
    step("Downloading video")
    pace(0.8)
    detail("format 22 (720p) · 214 MB · reusing cached file if present")
    ok("Video ready")


def stage_detect(v: dict) -> dict:
    step("Detecting slide changes")
    pace(1.0)
    raw = v["slides"] + v["suspects"] + 7
    detail(f"scanned  {v['dur']} at 2 fps · {raw} candidate transitions")
    detail("gate     deterministic (metric family TBD — issue #11)")
    ok(f"{v['slides'] + v['suspects']} distinct slides after dedupe")
    if v["suspects"]:
        n = v["suspects"]
        warn(f"{n} slide{'' if n == 1 else 's'} flagged as "
             f"{'a possible duplicate' if n == 1 else 'possible duplicates'} "
             f"(progressive builds)")
        detail(f"review them with:  {PROG} {'review' if VARIANT == 'A' else 'review'} <DIR>")
    return dict(candidates=raw, kept=v["slides"] + v["suspects"],
                suspects=v["suspects"])


def stage_crop(v: dict) -> dict:
    step("Cropping to the slide region")
    pace(0.7)
    if SIM.roi:
        detail(f"manual ROI from --roi {SIM.roi}")
        return dict(method="manual-roi", roi=SIM.roi, fallbacks=0)
    detail("layout-stable segments: 2 · region computed once per segment")
    warn("1 segment fell back to the full frame (no confident slide region)")
    detail("fallback chain: candidate union → letterbox strip → full frame")
    ok("Crop complete")
    return dict(method="auto", roi=None, fallbacks=1)


def stage_pair(v: dict, tr: dict) -> None:
    step("Pairing speech to slides")
    pace(0.5)
    detail(f"transcript timings: {tr['timings']}-level")
    if tr["timings"] == "segment":
        warn("Segment-level timings only — slide boundaries are approximate")
    ok("Pairing complete")


# ----------------------------------------------------------------------------
# Output layout — materialised for real so it can be inspected
# ----------------------------------------------------------------------------

def write_tree(dest: Path, v: dict, tr: dict, det: dict, crop: dict) -> Path:
    root = dest / slug(v)
    if root.exists():
        shutil.rmtree(root)
    n = det["kept"]
    random.seed(v["vid"])

    def png(p: Path) -> None:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(PNG_1X1)

    def txt(p: Path, body: str) -> None:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")

    slides = []
    for i in range(1, n + 1):
        at = i * 47
        slides.append(dict(
            n=i, at=f"{at // 60:02d}:{at % 60:02d}",
            suspect=i > n - det["suspects"],
        ))

    manifest = dict(
        schema="PROTOTYPE — schema is locked separately in issue #14",
        video=dict(id=v["vid"], title=v["title"], url=f"https://youtu.be/{v['vid']}",
                   duration=v["dur"], resolution=v["res"]),
        transcript=tr,
        detection=det,
        crop=crop,
        slides=[dict(n=s["n"], at=s["at"], suspect=s["suspect"]) for s in slides],
    )

    if SIM.layout is Layout.flat:
        txt(root / "manifest.json", json.dumps(manifest, indent=2) + "\n")
        txt(root / "transcript.md", "# Transcript\n\n(prototype stub)\n")
        txt(root / "transcript.json", "{}\n")
        for s in slides:
            png(root / "slides" / f"{s['n']:03d}.png")

    elif SIM.layout is Layout.paired:
        txt(root / "manifest.json", json.dumps(manifest, indent=2) + "\n")
        txt(root / "transcript.md", "# Transcript\n\n(prototype stub)\n")
        for s in slides:
            d = root / f"{s['n']:03d}"
            png(d / "slide.png")
            txt(d / "speech.md",
                f"# Slide {s['n']:03d} — from {s['at']}\n\n(prototype stub)\n")

    else:  # staged
        txt(root / "manifest.json", json.dumps(manifest, indent=2) + "\n")
        txt(root / "01-transcript" / "transcript.md", "# Transcript\n\n(stub)\n")
        txt(root / "01-transcript" / f"captions.{v['lang']}.json3", "{}\n")
        for s in slides[:3]:
            png(root / "02-frames" / f"{s['n'] * 1417:06d}.png")
        for s in slides:
            png(root / "03-slides" / f"{s['n']:03d}.png")
        txt(root / "logs" / "run.log", "(prototype stub)\n")

    return root


def print_tree(root: Path, per_dir: int = 4) -> None:
    """Print the materialised tree, collapsing long runs of siblings."""
    c = human()
    c.print(f"\n[bold]{root.name}/[/bold]")

    def walk(d: Path, depth: int) -> None:
        pad = "  " * (depth + 1)
        kids = sorted(d.iterdir(), key=lambda p: (p.is_file(), p.name))
        files = [k for k in kids if k.is_file()]
        dirs = [k for k in kids if k.is_dir()]
        for k in dirs[:per_dir]:
            c.print(f"{pad}{k.name}/")
            walk(k, depth + 1)
        if len(dirs) > per_dir:
            c.print(f"{pad}[dim]… {len(dirs) - per_dir} more directories, "
                    f"same shape[/dim]")
        for k in files[:per_dir]:
            c.print(f"{pad}{k.name}")
        if len(files) > per_dir:
            c.print(f"{pad}[dim]… {len(files) - per_dir} more files[/dim]")

    walk(root, 0)


# ----------------------------------------------------------------------------
# Final report — what the tool prints when it finishes
# ----------------------------------------------------------------------------

def final_report(root: Path, v: dict, tr: dict, det: dict, crop: dict,
                 elapsed: str = "4m 12s") -> None:
    if SIM.report is Report.json:
        # The shape an agent parses. Human lines all went to stderr above.
        print(json.dumps(dict(
            status="ok",
            output=str(root),
            video=dict(id=v["vid"], title=v["title"]),
            transcript_source=tr["source"],
            transcript_timings=tr["timings"],
            stt_model=tr["model"],
            slides=det["kept"],
            suspects=det["suspects"],
            crop_method=crop["method"],
            crop_fallbacks=crop["fallbacks"],
            elapsed=elapsed,
        ), indent=2))
        return

    out.print("")
    out.print("[bold]Done.[/bold]")
    out.print(f"  transcript   {tr['source'].upper()}"
              f"{' (' + tr['model'] + ')' if tr['model'] else ''}"
              f" · {tr['timings']}-level timings")
    ns = det["suspects"]
    dup = (f" · {ns} flagged as "
           f"{'a possible duplicate' if ns == 1 else 'possible duplicates'}"
           ) if ns else ""
    fb = f" · {crop['fallbacks']} segment(s) fell back to full frame" if crop["fallbacks"] else ""
    out.print(f"  slides       {det['kept']}{dup}")
    out.print(f"  crop         {crop['method']}{fb}")
    out.print(f"  output       {root}")
    out.print(f"  elapsed      {elapsed}")
    if det["suspects"]:
        flagged = " ".join(
            str(det["kept"] - i) for i in reversed(range(det["suspects"]))
        )
        out.print("")
        out.print("Next:")
        if VARIANT == "A":
            out.print(f"  {PROG} review {root}")
            out.print(f"  {PROG} drop {root} {flagged}")
        elif VARIANT == "B":
            out.print(f"  {PROG} review {root}")
            out.print(f"  {PROG} drop {root} {flagged}")
        else:
            out.print(f"  {PROG} status")
            out.print(f"  {PROG} drop {flagged}")
    print_tree(root)


def run_pipeline(url: str, dest: Path) -> Path:
    v = stage_probe(url)
    tr = dict(source="skipped", timings="none", lang=v["lang"], words=0, model=None)
    det = dict(candidates=0, kept=0, suspects=0)
    crop = dict(method="skipped", roi=None, fallbacks=0)

    if not SIM.slides_only:
        tr = stage_transcript(v)
    if not SIM.transcript_only:
        stage_video(v)
        det = stage_detect(v)
        crop = stage_crop(v)
        if not SIM.slides_only:
            stage_pair(v, tr)

    root = write_tree(dest, v, tr, det, crop)
    final_report(root, v, tr, det, crop)
    return root


def do_drop(root: Path, numbers: list[int]) -> None:
    mf = root / "manifest.json"
    if not mf.exists():
        fail(f"No manifest at {mf}",
             "Point drop at an output directory produced by a previous run.")
        footer()
        raise typer.Exit(code=2)
    data = json.loads(mf.read_text())
    keep = [s for s in data["slides"] if s["n"] not in numbers]
    step(f"Dropping {len(numbers)} slide(s): {', '.join(str(n) for n in numbers)}")
    detail(f"{len(data['slides'])} slides → {len(keep)} slides")
    for i, s in enumerate(keep, start=1):
        if s["n"] != i:
            detail(f"renumber {s['n']:03d} → {i:03d}")
        s["n"] = i
    data["slides"] = keep
    mf.write_text(json.dumps(data, indent=2) + "\n")
    ok("Files deleted, remaining slides renumbered, manifest rewritten")
    warn("Renumbering means slide numbers are NOT stable identities across a "
         "drop — decide in issue #14 whether the manifest also keeps a stable id")


# ----------------------------------------------------------------------------
# Shared option declarations
# ----------------------------------------------------------------------------

OUT = typer.Option(Path("./out"), "--out", "-o", help="Directory to write results into.")
LANG = typer.Option(None, "--lang", help="Spoken language hint, e.g. en, pt-BR. Autodetected when omitted.")
STT = typer.Option(False, "--stt", help="Force local speech-to-text even when a YouTube caption exists.")
ROI = typer.Option(None, "--roi", help="Manual slide region as four normalised floats X,Y,W,H. Skips automatic cropping.")
REVIEW = typer.Option(False, "--review", help="Pause for manual confirmation of flagged slides instead of running unattended.")
REPORT = typer.Option(Report.text, "--report", help="Final report format. Use json for unattended/agent runs.")
LAYOUT = typer.Option(Layout.flat, "--layout", help="MOCK ONLY. Output directory layout to materialise: flat, paired, staged.")
CASE = typer.Option(Case.captioned, "--case", help="MOCK ONLY. Which simulated video to pretend to process.")
SLOW = typer.Option(False, "--slow", help="MOCK ONLY. Pace the simulation so progress output is watchable.")


def apply(layout, case, report, slow, **kw) -> None:
    SIM.layout, SIM.case, SIM.report, SIM.slow = layout, case, report, slow
    for k, val in kw.items():
        setattr(SIM, k, val)


# ============================================================================
# VARIANT A — task verbs. One shot. Everything about the run is a flag.
# ============================================================================

app_a = typer.Typer(
    rich_markup_mode=None, add_completion=False, no_args_is_help=True,
    help="Reconstruct a presentation from a talk video: the speech transcript "
         "plus one cropped screenshot per distinct slide.",
    epilog="MOCK (variant A of 3). Flip with V=B or V=C. Nothing is really downloaded.",
)


@app_a.command()
def extract(
    url: str = typer.Argument(..., help="YouTube URL, any yt-dlp URL, or a local video file."),
    output: Path = OUT,
    transcript_only: bool = typer.Option(False, "--transcript-only", help="Only produce the transcript. Skips the video download entirely."),
    slides_only: bool = typer.Option(False, "--slides-only", help="Only produce the slide screenshots. Skips the transcript."),
    stt: bool = STT, lang: Optional[str] = LANG, roi: Optional[str] = ROI,
    review: bool = REVIEW, report: Report = REPORT,
    layout: Layout = LAYOUT, case: Case = CASE, slow: bool = SLOW,
) -> None:
    """Run the whole pipeline on a video. Unattended by default."""
    apply(layout, case, report, slow, transcript_only=transcript_only,
          slides_only=slides_only, force_stt=stt, lang=lang, roi=roi, review=review)
    run_pipeline(url, output)
    footer()


@app_a.command()
def drop(
    directory: Path = typer.Argument(..., help="Output directory from a previous extract."),
    slides: list[int] = typer.Argument(..., help="Slide numbers to delete."),
    layout: Layout = LAYOUT, case: Case = CASE,
) -> None:
    """Delete duplicate slides, renumber the rest, and rewrite the manifest."""
    apply(layout, case, Report.text, False)
    do_drop(directory, slides)
    footer()


@app_a.command()
def review(
    directory: Path = typer.Argument(..., help="Output directory from a previous extract."),
    layout: Layout = LAYOUT, case: Case = CASE,
) -> None:
    """Walk the slides flagged as possible duplicates, one at a time."""
    apply(layout, case, Report.text, False)
    mf = directory / "manifest.json"
    if not mf.exists():
        fail(f"No manifest at {mf}")
        footer()
        raise typer.Exit(code=2)
    data = json.loads(mf.read_text())
    flagged = [s for s in data["slides"] if s["suspect"]]
    if not flagged:
        ok("Nothing flagged. Every slide looks distinct.")
        footer()
        return
    out.print(f"[bold]{len(flagged)} slide(s) flagged as possible duplicates[/bold]\n")
    for s in flagged:
        out.print(f"  {s['n']:03d}  at {s['at']}  {directory}/slides/{s['n']:03d}.png")
    out.print("\n[dim]MOCK: the real command would prompt keep/drop per slide, or "
              "open a contact-sheet. Which of those it should be is deliberately "
              "left to the review-mode fog on the map.[/dim]")
    footer()


# ============================================================================
# VARIANT B — stage verbs. Composable pipeline; each stage re-runnable alone.
# ============================================================================

app_b = typer.Typer(
    rich_markup_mode=None, add_completion=False, no_args_is_help=True,
    help="Reconstruct a presentation from a talk video, one stage at a time. "
         "Use 'all' to chain every stage.",
    epilog="MOCK (variant B of 3). Flip with V=A or V=C. Nothing is really downloaded.",
)


@app_b.command("transcript")
def b_transcript(
    url: str = typer.Argument(..., help="YouTube URL, any yt-dlp URL, or a local video file."),
    output: Path = OUT, stt: bool = STT, lang: Optional[str] = LANG,
    report: Report = REPORT, layout: Layout = LAYOUT, case: Case = CASE, slow: bool = SLOW,
) -> None:
    """Produce only the transcript. Needs no ffmpeg and no video download."""
    apply(layout, case, report, slow, transcript_only=True, force_stt=stt, lang=lang)
    run_pipeline(url, output)
    footer()


@app_b.command("slides")
def b_slides(
    url: str = typer.Argument(..., help="YouTube URL, any yt-dlp URL, or a local video file."),
    output: Path = OUT, roi: Optional[str] = ROI, report: Report = REPORT,
    layout: Layout = LAYOUT, case: Case = CASE, slow: bool = SLOW,
) -> None:
    """Download the video, detect slide changes, and write the screenshots."""
    apply(layout, case, report, slow, slides_only=True, roi=roi)
    run_pipeline(url, output)
    footer()


@app_b.command("crop")
def b_crop(
    directory: Path = typer.Argument(..., help="Output directory holding uncropped slides."),
    roi: Optional[str] = ROI, layout: Layout = LAYOUT, case: Case = CASE, slow: bool = SLOW,
) -> None:
    """Re-crop slides already written, without re-downloading or re-detecting."""
    apply(layout, case, Report.text, slow, roi=roi)
    stage_crop(VIDEO[case])
    ok(f"Rewrote slides in {directory}")
    footer()


@app_b.command("pair")
def b_pair(
    directory: Path = typer.Argument(..., help="Output directory holding a transcript and slides."),
    layout: Layout = LAYOUT, case: Case = CASE,
) -> None:
    """Pair the transcript with the slides and write the manifest."""
    apply(layout, case, Report.text, False)
    stage_pair(VIDEO[case], dict(timings="word"))
    ok(f"Manifest written to {directory}/manifest.json")
    footer()


@app_b.command("all")
def b_all(
    url: str = typer.Argument(..., help="YouTube URL, any yt-dlp URL, or a local video file."),
    output: Path = OUT, stt: bool = STT, lang: Optional[str] = LANG,
    roi: Optional[str] = ROI, review: bool = REVIEW, report: Report = REPORT,
    layout: Layout = LAYOUT, case: Case = CASE, slow: bool = SLOW,
) -> None:
    """Run every stage: transcript, slides, crop, pair."""
    apply(layout, case, report, slow, force_stt=stt, lang=lang, roi=roi, review=review)
    run_pipeline(url, output)
    footer()


app_b.command("drop")(drop)
app_b.command("review")(review)


# ============================================================================
# VARIANT C — run workspace. A run is a first-class, resumable object.
# ============================================================================

app_c = typer.Typer(
    rich_markup_mode=None, add_completion=False, no_args_is_help=True,
    help="Reconstruct presentations from talk videos. Work is organised into "
         "runs: create one, run it, resume it, inspect it.",
    epilog="MOCK (variant C of 3). Flip with V=A or V=B. Nothing is really downloaded.",
)

STAGES = ["probe", "transcript", "video", "detect", "crop", "pair"]


def store(root: Path) -> Path:
    return root / ".extract-slides-runs.json"


def load_runs(root: Path) -> dict:
    p = store(root)
    return json.loads(p.read_text()) if p.exists() else dict(current=None, runs={})


def save_runs(root: Path, data: dict) -> None:
    store(root).parent.mkdir(parents=True, exist_ok=True)
    store(root).write_text(json.dumps(data, indent=2) + "\n")


@app_c.command("new")
def c_new(
    url: str = typer.Argument(..., help="YouTube URL, any yt-dlp URL, or a local video file."),
    output: Path = OUT, lang: Optional[str] = LANG,
    layout: Layout = LAYOUT, case: Case = CASE,
) -> None:
    """Create a run for a video and make it current. Does not process anything."""
    apply(layout, case, Report.text, False, lang=lang)
    v = VIDEO[case]
    runs = load_runs(output)
    rid = slug(v)
    runs["runs"][rid] = dict(url=url, video=v["vid"], title=v["title"],
                             done=[], layout=layout.value, case=case.value)
    runs["current"] = rid
    save_runs(output, runs)
    ok(f"Run created and made current: {rid}")
    detail(f"next:  {PROG} run")
    footer()


@app_c.command("run")
def c_run(
    run_id: Optional[str] = typer.Argument(None, help="Run to process. Defaults to the current run."),
    output: Path = OUT,
    from_stage: Optional[str] = typer.Option(None, "--from", help=f"Restart from this stage, discarding later ones. One of: {', '.join(STAGES)}."),
    stt: bool = STT, roi: Optional[str] = ROI, review: bool = REVIEW,
    report: Report = REPORT, slow: bool = SLOW,
) -> None:
    """Process a run, resuming from wherever it stopped."""
    runs = load_runs(output)
    rid = run_id or runs.get("current")
    if not rid or rid not in runs["runs"]:
        fail("No current run.", f"Create one first:  {PROG} new <URL>")
        footer()
        raise typer.Exit(code=2)
    r = runs["runs"][rid]
    apply(Layout(r["layout"]), Case(r["case"]), report, slow,
          force_stt=stt, roi=roi, review=review)
    if r["done"] and not from_stage:
        detail(f"resuming {rid} — already done: {', '.join(r['done'])}")
    if from_stage:
        detail(f"restarting {rid} from {from_stage}")
    run_pipeline(r["url"], output)
    r["done"] = STAGES
    save_runs(output, runs)
    footer()


@app_c.command("status")
def c_status(
    run_id: Optional[str] = typer.Argument(None, help="Run to inspect. Defaults to the current run."),
    output: Path = OUT, report: Report = REPORT,
) -> None:
    """Show a run's stages, what is done, and what is flagged."""
    runs = load_runs(output)
    rid = run_id or runs.get("current")
    if not rid or rid not in runs["runs"]:
        fail("No current run.", f"Create one first:  {PROG} new <URL>")
        footer()
        raise typer.Exit(code=2)
    r = runs["runs"][rid]
    apply(Layout(r["layout"]), Case(r["case"]), report, False)
    out.print(f"[bold]{rid}[/bold]")
    out.print(f"  url    {r['url']}")
    out.print(f"  title  {r['title']}")
    for s in STAGES:
        mark = "[green]done[/green]" if s in r["done"] else "[dim]pending[/dim]"
        out.print(f"  {s:<11} {mark}")
    footer()


@app_c.command("ls")
def c_ls(output: Path = OUT) -> None:
    """List every run in the output directory."""
    runs = load_runs(output)
    if not runs["runs"]:
        out.print("[dim]No runs yet.[/dim]")
        footer()
        return
    for rid, r in runs["runs"].items():
        cur = "*" if rid == runs.get("current") else " "
        state = "complete" if len(r["done"]) == len(STAGES) else f"{len(r['done'])}/{len(STAGES)}"
        out.print(f" {cur} {rid:<48} {state}")
    out.print("\n[dim]* = current run[/dim]")
    footer()


@app_c.command("drop")
def c_drop(
    slides: list[int] = typer.Argument(..., help="Slide numbers to delete from the current run."),
    output: Path = OUT,
    run_id: Optional[str] = typer.Option(None, "--run", help="Run to act on. Defaults to the current run."),
) -> None:
    """Delete duplicate slides from a run, renumber, and rewrite the manifest."""
    runs = load_runs(output)
    rid = run_id or runs.get("current")
    if not rid or rid not in runs["runs"]:
        fail("No current run.")
        footer()
        raise typer.Exit(code=2)
    apply(Layout(runs["runs"][rid]["layout"]), Case(runs["runs"][rid]["case"]),
          Report.text, False)
    do_drop(output / rid, slides)
    footer()


@app_c.command("review")
def c_review(
    output: Path = OUT,
    run_id: Optional[str] = typer.Option(None, "--run", help="Run to review. Defaults to the current run."),
) -> None:
    """Walk the current run's flagged slides, one at a time."""
    runs = load_runs(output)
    rid = run_id or runs.get("current")
    if not rid or rid not in runs["runs"]:
        fail("No current run.")
        footer()
        raise typer.Exit(code=2)
    review(output / rid, Layout(runs["runs"][rid]["layout"]),
           Case(runs["runs"][rid]["case"]))


# ============================================================================

APPS = {"A": app_a, "B": app_b, "C": app_c}

if __name__ == "__main__":
    if VARIANT not in APPS:
        err.print(f"Unknown variant {VARIANT!r}. Use V=A, V=B or V=C.")
        raise SystemExit(2)
    APPS[VARIANT](prog_name=PROG)
