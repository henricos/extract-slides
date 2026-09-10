#!/usr/bin/env python3
"""
PROTOTYPE — THROWAWAY. Navigable CLI mock for `extract-slides` (issue #3).

This is the SINGLE PROPOSED SURFACE, settled by grilling over the three
variants in commit 5aa28c2 (task verbs / stage verbs / run workspace). Those
variants are the primary source and stay in this branch's history; this file
is what they converged on.

    extract-slides URL                 # default path: everything, resuming
    extract-slides URL --force         # ignore existing work, recompute

    extract-slides fetch URL           # step 1: acquire + transcribe
    extract-slides transcribe DIR      # redo only the transcript
    extract-slides detect DIR
    extract-slides crop DIR
    extract-slides pair DIR
    extract-slides drop DIR N...
    extract-slides review DIR

Decisions this encodes:
  - Structure is the stage-verb pipeline; the bare root is the A-shaped
    default path so the common case costs no extra word.
  - Only step 1 takes a URL. Every later stage takes a directory.
  - Resumes by default and says out loud what it reused. --force recomputes.
  - A stage command CHAINS FORWARD into the stages that depend on it, so a
    redone detect cannot leave a stale manifest behind.
  - Transcript-only is out of scope: yt-dlp already does that.

Nothing here does real work. No video is downloaded, no model is loaded.
Per ADR 0001: typer with rich_markup_mode=None; rich for progress only.
"""

from __future__ import annotations

import base64
import json
import shutil
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

PROG = "extract-slides"
STAGES = ["acquire", "transcribe", "detect", "crop", "pair"]

# Which stages go stale when a stage is redone, in pipeline order.
# crop changes pixels only; detect changes the slide set, so the manifest and
# the crops both have to follow it.
DOWNSTREAM = {
    "acquire": ["transcribe", "detect", "crop", "pair"],
    "transcribe": ["pair"],
    "detect": ["crop", "pair"],
    "crop": [],
    "pair": [],
}

err = Console(stderr=True, highlight=False, soft_wrap=True)
outc = Console(highlight=False, soft_wrap=True)

PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


class Layout(str, Enum):
    flat = "flat"
    paired = "paired"
    staged = "staged"


class Case(str, Enum):
    captioned = "captioned"
    no_caption = "no-caption"
    ptbr = "ptbr"
    suspects = "suspects"
    fail = "fail"


class Report(str, Enum):
    text = "text"
    json = "json"


@dataclass
class Sim:
    layout: Layout = Layout.flat
    case: Case = Case.captioned
    report: Report = Report.text
    slow: bool = False
    force: bool = False
    review: bool = False
    lang: Optional[str] = None
    roi: Optional[str] = None
    reused: list[str] = field(default_factory=list)


SIM = Sim()

VIDEO = {
    Case.captioned: dict(vid="X2vr81CJ934", title="Designing Data-Intensive Pipelines",
                         dur="41:12", res="1920x1080", lang="en", slides=34, suspects=1),
    Case.no_caption: dict(vid="3sB4Iv_tM7U", title="Internal Tech Talk — Q3 Architecture Review",
                          dur="28:40", res="1280x720", lang="en", slides=22, suspects=0),
    Case.ptbr: dict(vid="C38xlWnkezQ", title="Arquitetura de dados na prática",
                    dur="18:55", res="1920x1080", lang="pt-BR", slides=19, suspects=2),
    Case.suspects: dict(vid="7JbOagrwysE", title="Kubernetes na Vida Real (63 min)",
                        dur="63:07", res="1920x1080", lang="pt-BR", slides=58, suspects=11),
    Case.fail: dict(vid="dQw4w9WgXcQ", title="—", dur="?", res="?", lang="?",
                    slides=0, suspects=0),
}


def human() -> Console:
    """Narration console. Under --report json, stdout is reserved for the JSON."""
    return err if SIM.report is Report.json else outc


def pace(seconds: float) -> None:
    if SIM.slow:
        time.sleep(seconds)



# ---- stage-block narration -------------------------------------------------
# An EXECUTED stage is an indented block with a blank line above it. A REUSED
# stage is a single line. That way a finished re-run stays compact instead of
# printing five blocks that did no work, and a stage that really ran is
# impossible to miss. No boxes here: the running log is a log. The final
# report gets a box, because a report is a discrete block of result.

IND = " " * 7


def head(idx: int, name: str) -> None:
    human().print(f"\n[bold cyan]{idx}/{len(STAGES)}[/bold cyan]  [bold]{name}[/bold]")


def skipped(idx: int, name: str, gist: str) -> None:
    human().print(f"[dim]{idx}/{len(STAGES)}[/dim]  {name:<11}"
                  f"[blue]reused[/blue]   [dim]{gist}[/dim]")


def field(label: str, value: str) -> None:
    human().print(f"{IND}[dim]{label:<10}[/dim] {value}")


def flag(msg: str, hint: str | None = None) -> None:
    human().print(f"{IND}[bold yellow]![/bold yellow] {msg}")
    if hint:
        human().print(f"{IND}  [dim]{hint}[/dim]")


def done(msg: str) -> None:
    human().print(f"{IND}[green]✓[/green] [dim]{msg}[/dim]")


def fail(msg: str, hint: str | None = None) -> None:
    err.print(f"\n[bold red]✗[/bold red] {msg}")
    if hint:
        err.print(f"  [dim]{hint}[/dim]")



def slug(v: dict) -> str:
    keep = "".join(c if c.isalnum() else "-" for c in v["title"].lower())
    while "--" in keep:
        keep = keep.replace("--", "-")
    return f"{keep.strip('-')[:40]}-{v['vid']}"


# ----------------------------------------------------------------------------
# State lives INSIDE the output directory, per video. Not a global run index —
# that was variant C's abstraction, and it was ruled out. The directory is the
# state, so a directory you can see is a state you can see.
# ----------------------------------------------------------------------------

STATE_FILE = ".extract-slides.json"


def read_state(root: Path) -> dict:
    p = root / STATE_FILE
    if not p.exists():
        return dict(done=[], case=None, layout=None)
    return json.loads(p.read_text())


def write_state(root: Path, st: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / STATE_FILE).write_text(json.dumps(st, indent=2) + "\n")


def mark(root: Path, st: dict, stage: str) -> None:
    if stage not in st["done"]:
        st["done"].append(stage)
    st["case"] = SIM.case.value
    st["layout"] = SIM.layout.value
    write_state(root, st)


def invalidate(root: Path, st: dict, stages: list[str]) -> None:
    st["done"] = [s for s in st["done"] if s not in stages]
    write_state(root, st)


def resolve_dir(target: str, output: Path) -> Path:
    """A stage command's DIR argument, or an output dir derived from a URL."""
    p = Path(target)
    if (p / STATE_FILE).exists():
        return p
    return output / slug(VIDEO[SIM.case])


# ----------------------------------------------------------------------------
# Simulated stages. Each one honours the resume contract: skip when already
# done, say so out loud, and never skip silently.
# ----------------------------------------------------------------------------

def do_acquire(root: Path, st: dict, url: str) -> dict:
    v = VIDEO[SIM.case]
    if "acquire" in st["done"] and not SIM.force:
        skipped(1, "acquire", f"{v['title']} · {v['dur']} · {v['res']}")
        return v
    head(1, "acquire")
    field("source", url)
    pace(0.6)
    if SIM.case is Case.fail:
        flag("yt-dlp could not extract the video (HTTP 429 from YouTube)")
        fail("Acquire failed. Nothing was written.", "Rate limited. Retry later.")
        if SIM.report is Report.json:
            print(json.dumps(dict(status="error", error="rate_limited",
                                  message="yt-dlp could not extract the video (HTTP 429)",
                                  retryable=True), indent=2))
        raise typer.Exit(code=2)
    field("title", v["title"])
    field("duration", f"{v['dur']}   resolution {v['res']}")
    if SIM.case is Case.no_caption:
        field("captions", "none (checked automatic_captions and subtitles)")
    else:
        field("captions", f"automatic ASR, {v['lang']}-orig (word timings: yes)")
    field("video", "format 22 (720p) · 214 MB")
    done("acquired in 38s")
    mark(root, st, "acquire")
    return v


def do_transcribe(root: Path, st: dict, v: dict) -> dict:
    caption = SIM.case is not Case.no_caption
    if "transcribe" in st["done"] and not SIM.force:
        skipped(2, "transcribe",
                f"{'YouTube caption' if caption else 'local STT'} · "
                f"{'word' if caption else 'segment'}-level timings")
        return dict(source="caption" if caption else "stt",
                    timings="word" if caption else "segment", lang=v["lang"],
                    words=11204 if caption else 10871,
                    model=None if caption else "faster-whisper medium int8")

    head(2, "transcribe")
    if caption:
        field("source", f"YouTube ASR caption, {v['lang']}-orig, json3")
        pace(0.8)
        field("fetched", "1 track · 1,842 events · 11,204 words")
        field("timings", "word-level")
        done("transcribed in 4s")
        tr = dict(source="caption", timings="word", lang=v["lang"], words=11204,
                  model=None)
    else:
        flag("No YouTube caption for this video — falling back to local STT",
             "yt-dlp exits 0 when no caption exists, so this was decided from "
             "the metadata, not the exit code")
        field("source", "local STT")
        field("model", "faster-whisper medium int8 · 2 threads · CPU only")
        field("note", "this stage is slow by design on the target host")
        total = 24
        if sys.stdout.isatty() and SIM.report is Report.text:
            from rich.progress import (BarColumn, Progress, TextColumn,
                                       TimeElapsedColumn, TimeRemainingColumn)
            with Progress(TextColumn(IND + "transcribing"), BarColumn(bar_width=28),
                          TextColumn("{task.percentage:>3.0f}%"),
                          TextColumn("[dim]{task.fields[at]}[/dim]"),
                          TimeElapsedColumn(), TimeRemainingColumn(),
                          console=human()) as prog:
                t = prog.add_task("stt", total=total, at="00:00")
                for i in range(total):
                    pace(0.12)
                    prog.update(t, advance=1,
                                at=f"{(i + 1) * 105 // 60:02d}:{(i + 1) * 105 % 60:02d}")
        else:
            for i in range(0, total, 6):
                pace(0.12)
                human().print(f"{IND}[dim]transcribing[/dim] {i * 100 // total:>3d}% "
                              f"[dim](audio {i * 105 // 60:02d}:{i * 105 % 60:02d})[/dim]")
        field("timings", "segment-level")
        done("transcribed in 41m 08s")
        tr = dict(source="stt", timings="segment", lang=v["lang"], words=10871,
                  model="faster-whisper medium int8")
    mark(root, st, "transcribe")
    return tr


def do_detect(root: Path, st: dict, v: dict) -> dict:
    kept = v["slides"] + v["suspects"]
    res = dict(candidates=kept + 7, kept=kept, suspects=v["suspects"])
    if "detect" in st["done"] and not SIM.force:
        gist = f"{kept} distinct slides"
        if v["suspects"]:
            gist += f" · {v['suspects']} flagged"
        skipped(3, "detect", gist)
        return res
    head(3, "detect")
    pace(0.9)
    field("scanned", f"{v['dur']} at 2 fps · {kept + 7} candidate transitions")
    field("gate", "deterministic (metric family TBD — issue #11)")
    field("kept", f"{kept} distinct slides after dedupe")
    if v["suspects"]:
        n = v["suspects"]
        flag(f"{n} slide{'' if n == 1 else 's'} flagged as "
             f"{'a possible duplicate' if n == 1 else 'possible duplicates'}",
             "progressive builds — inspect with review, remove with drop")
    done("detected in 2m 51s")
    mark(root, st, "detect")
    return res


def do_crop(root: Path, st: dict, v: dict) -> dict:
    if "crop" in st["done"] and not SIM.force:
        skipped(4, "crop", "manual ROI" if SIM.roi else "auto · 1 full-frame fallback")
        return dict(method="manual-roi" if SIM.roi else "auto", roi=SIM.roi,
                    fallbacks=0 if SIM.roi else 1)
    head(4, "crop")
    pace(0.6)
    if SIM.roi:
        field("method", f"manual ROI from --roi {SIM.roi}")
        done("cropped in 6s")
        mark(root, st, "crop")
        return dict(method="manual-roi", roi=SIM.roi, fallbacks=0)
    field("method", "automatic")
    field("segments", "2 layout-stable · region computed once per segment")
    flag("1 segment fell back to the full frame (no confident slide region)",
         "fallback chain: candidate union → letterbox strip → full frame")
    done("cropped in 11s")
    mark(root, st, "crop")
    return dict(method="auto", roi=None, fallbacks=1)


def do_pair(root: Path, st: dict, v: dict, tr: dict) -> None:
    if "pair" in st["done"] and not SIM.force:
        skipped(5, "pair", "manifest already written")
        return
    head(5, "pair")
    pace(0.4)
    field("timings", f"{tr['timings']}-level")
    if tr["timings"] == "segment":
        flag("Segment-level timings only — slide boundaries are approximate")
    done("paired in 1s")
    mark(root, st, "pair")


# ----------------------------------------------------------------------------
# Output layout — materialised for real so the tree can be inspected
# ----------------------------------------------------------------------------

def write_tree(root: Path, v: dict, tr: dict, det: dict, crop: dict) -> None:
    st = read_state(root)
    for child in root.iterdir():
        if child.name != STATE_FILE:
            shutil.rmtree(child) if child.is_dir() else child.unlink()
    n = det["kept"]

    def png(p: Path) -> None:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(PNG_1X1)

    def txt(p: Path, body: str) -> None:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")

    slides = [dict(n=i, at=f"{i * 47 // 60:02d}:{i * 47 % 60:02d}",
                   suspect=i > n - det["suspects"]) for i in range(1, n + 1)]
    manifest = dict(
        schema="PROTOTYPE — the real schema is locked in issue #14",
        video=dict(id=v["vid"], title=v["title"], url=f"https://youtu.be/{v['vid']}",
                   duration=v["dur"], resolution=v["res"]),
        transcript=tr, detection=det, crop=crop, slides=slides,
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
            png(root / f"{s['n']:03d}" / "slide.png")
            txt(root / f"{s['n']:03d}" / "speech.md",
                f"# Slide {s['n']:03d} — from {s['at']}\n\n(prototype stub)\n")
    else:
        txt(root / "manifest.json", json.dumps(manifest, indent=2) + "\n")
        txt(root / "01-transcript" / "transcript.md", "# Transcript\n\n(stub)\n")
        txt(root / "01-transcript" / f"captions.{v['lang']}.json3", "{}\n")
        for s in slides[:3]:
            png(root / "02-frames" / f"{s['n'] * 1417:06d}.png")
        for s in slides:
            png(root / "03-slides" / f"{s['n']:03d}.png")
        txt(root / "logs" / "run.log", "(prototype stub)\n")
    write_state(root, st)


def print_tree(root: Path, per_dir: int = 4) -> None:
    c = human()
    c.print(f"\n[bold]{root.name}/[/bold]")

    def walk(d: Path, depth: int) -> None:
        pad = "  " * (depth + 1)
        kids = sorted((k for k in d.iterdir() if k.name != STATE_FILE),
                      key=lambda p: (p.is_file(), p.name))
        dirs = [k for k in kids if k.is_dir()]
        files = [k for k in kids if k.is_file()]
        for k in dirs[:per_dir]:
            c.print(f"{pad}{k.name}/")
            walk(k, depth + 1)
        if len(dirs) > per_dir:
            c.print(f"{pad}[dim]… {len(dirs) - per_dir} more directories, same shape[/dim]")
        for k in files[:per_dir]:
            c.print(f"{pad}{k.name}")
        if len(files) > per_dir:
            c.print(f"{pad}[dim]… {len(files) - per_dir} more files[/dim]")

    walk(root, 0)


def final_report(root: Path, v: dict, tr: dict, det: dict, crop: dict) -> None:
    if SIM.report is Report.json:
        print(json.dumps(dict(
            status="ok", output=str(root),
            video=dict(id=v["vid"], title=v["title"]),
            transcript_source=tr["source"], transcript_timings=tr["timings"],
            stt_model=tr["model"], slides=det["kept"], suspects=det["suspects"],
            crop_method=crop["method"], crop_fallbacks=crop["fallbacks"],
            elapsed="4m 12s",
        ), indent=2))
        return

    # The final report IS a box. This is the one place a border earns its keep:
    # a discrete block of result, read at a glance, distinct from the log above
    # it. ADR 0001's "never as a bordered panel" is scoped to --help output.
    from rich.panel import Panel
    from rich.table import Table

    ns = det["suspects"]
    dup = (f" · [yellow]{ns} flagged as "
           f"{'a possible duplicate' if ns == 1 else 'possible duplicates'}[/yellow]"
           ) if ns else ""
    fb = (f" · [yellow]{crop['fallbacks']} full-frame fallback"
          f"{'' if crop['fallbacks'] == 1 else 's'}[/yellow]") if crop["fallbacks"] else ""

    t = Table.grid(padding=(0, 2))
    t.add_column(style="dim", justify="left", min_width=10)
    t.add_column(overflow="fold")
    t.add_row("transcript", f"{tr['source'].upper()}"
                            f"{' · ' + tr['model'] if tr['model'] else ''}"
                            f" · {tr['timings']}-level timings")
    t.add_row("slides", f"{det['kept']}{dup}")
    t.add_row("crop", f"{crop['method']}{fb}")
    t.add_row("elapsed", "4m 12s")
    t.add_row("output", str(root))
    outc.print("")
    outc.print(Panel(t, title="[bold]Done[/bold]", title_align="left",
                     border_style="dim", padding=(1, 2), expand=False))

    if ns:
        flagged = " ".join(str(det["kept"] - i) for i in reversed(range(ns)))
        outc.print("\nNext:")
        outc.print(f"  {PROG} review {root}")
        outc.print(f"  {PROG} drop {root} {flagged}")
        outc.print("")
    outc.print("[dim]MOCK: the tree below is here so the --layout choice can be "
               "judged. A real run would print the path, not 35 filenames.[/dim]")
    print_tree(root)


# ----------------------------------------------------------------------------
# The pipeline runner. Always walks every stage in order; the invalidated ones
# recompute and the rest report themselves as reused.
# ----------------------------------------------------------------------------

def pipeline(root: Path, url: str, redo: Optional[str] = None,
             upto: Optional[str] = None) -> None:
    st = read_state(root)
    if redo:
        chain = [s for s in STAGES if s == redo or s in DOWNSTREAM[redo]]
        if len(chain) > 1:
            human().print(f"[dim]{redo} invalidates {', '.join(chain[1:])} — "
                          f"re-running {'those' if len(chain) > 2 else 'that'} "
                          f"too[/dim]")
        invalidate(root, st, chain)
        st = read_state(root)

    limit = STAGES.index(upto) if upto else len(STAGES) - 1
    v = do_acquire(root, st, url)
    tr = det = crop = None
    if limit >= 1:
        tr = do_transcribe(root, st, v)
    if limit >= 2:
        det = do_detect(root, st, v)
    if limit >= 3:
        crop = do_crop(root, st, v)
    if limit >= 4:
        do_pair(root, st, v, tr)

    if upto:
        human().print(f"\n[bold]Step 1 complete.[/bold]  "
                      f"[dim]continue with:[/dim]  {PROG} {root}")
        return
    write_tree(root, v, tr, det, crop)
    final_report(root, v, tr, det, crop)


def do_drop(root: Path, numbers: list[int]) -> None:
    mf = root / "manifest.json"
    if not mf.exists():
        fail(f"No manifest at {mf}",
             "Point drop at an output directory from a previous run.")
        raise typer.Exit(code=2)
    data = json.loads(mf.read_text())
    keep = [s for s in data["slides"] if s["n"] not in numbers]
    outc.print("\n[bold]drop[/bold]")
    field("slides", f"{', '.join(str(n) for n in sorted(numbers))}")
    field("count", f"{len(data['slides'])} → {len(keep)}")
    renumbered = 0
    for i, sl in enumerate(keep, start=1):
        if sl["n"] != i:
            renumbered += 1
        sl["n"] = i
    field("renumbered", f"{renumbered} slide(s) shifted down")
    data["slides"] = keep
    mf.write_text(json.dumps(data, indent=2) + "\n")
    done("files deleted, survivors renumbered, manifest rewritten")
    flag("A slide number is NOT a stable identity across a drop",
         "whether the manifest also keeps a stable id is issue #14")


# ----------------------------------------------------------------------------
# The CLI. The bare root is the default path, so `extract-slides URL` works
# with no verb; a first token that is not a known subcommand falls through to
# the hidden default command. Ambiguity is limited to a bare token that
# collides with a subcommand name — write `./crop` for a local file named crop.
# ----------------------------------------------------------------------------

DEFAULT_CMD = "_default"


class RootGroup(typer.core.TyperGroup):
    def parse_args(self, ctx, args: list[str]) -> list[str]:
        if args and args[0] not in self.commands and not args[0].startswith("-"):
            args = [DEFAULT_CMD, *args]
        return super().parse_args(ctx, args)

    def list_commands(self, ctx) -> list[str]:
        return [c for c in super().list_commands(ctx) if c != DEFAULT_CMD]

    def format_usage(self, ctx, formatter) -> None:
        formatter.write_usage(ctx.command_path, "[OPTIONS] URL | DIR")
        formatter.write_usage(ctx.command_path, "COMMAND [ARGS]...", prefix="       ")


app = typer.Typer(
    cls=RootGroup, rich_markup_mode=None, add_completion=False,
    no_args_is_help=True,
    help="Reconstruct a presentation from a talk video: the speech transcript "
         "plus one cropped screenshot per distinct slide.\n\n"
         "Given a URL, runs the whole pipeline and resumes whatever a previous "
         "run already finished. The stage commands below redo one step of it "
         "without repeating the expensive ones.",
    epilog="THROWAWAY MOCK for issue #3 — nothing is really downloaded. "
           "Stages: acquire, transcribe, detect, crop, pair.",
)

OUT = typer.Option(Path("./out"), "--out", "-o", help="Directory to write results into.")
FORCE = typer.Option(False, "--force", help="Ignore work a previous run finished and recompute from scratch.")
LANG = typer.Option(None, "--lang", help="Spoken language hint, e.g. en, pt-BR. Autodetected when omitted.")
ROI = typer.Option(None, "--roi", help="Manual slide region as four normalised floats X,Y,W,H. Skips automatic cropping.")
REVIEW = typer.Option(False, "--review", help="Pause for manual confirmation of flagged slides instead of running unattended.")
REPORT = typer.Option(Report.text, "--report", help="Final report format. Use json for unattended/agent runs.")
LAYOUT = typer.Option(Layout.flat, "--layout", help="MOCK ONLY. Output layout to materialise: flat, paired, staged.")
CASE = typer.Option(Case.captioned, "--case", help="MOCK ONLY. Which simulated video to pretend to process.")
SLOW = typer.Option(False, "--slow", help="MOCK ONLY. Pace the simulation so progress output is watchable.")


def setup(layout: Layout, case: Case, report: Report, slow: bool, force: bool,
          lang: Optional[str] = None, roi: Optional[str] = None,
          review: bool = False) -> None:
    SIM.layout, SIM.case, SIM.report = layout, case, report
    SIM.slow, SIM.force = slow, force
    SIM.lang, SIM.roi, SIM.review = lang, roi, review


@app.command(DEFAULT_CMD, hidden=True)
def _default(
    target: str = typer.Argument(..., metavar="URL | DIR",
                                 help="A video URL, a local video file, or an output directory to continue."),
    output: Path = OUT, force: bool = FORCE, lang: Optional[str] = LANG,
    roi: Optional[str] = ROI, review: bool = REVIEW, report: Report = REPORT,
    layout: Layout = LAYOUT, case: Case = CASE, slow: bool = SLOW,
) -> None:
    """Run the whole pipeline, resuming what a previous run already finished."""
    setup(layout, case, report, slow, force, lang, roi, review)
    root = resolve_dir(target, output)
    pipeline(root, target)


@app.command()
def fetch(
    url: str = typer.Argument(..., help="A video URL or a local video file."),
    output: Path = OUT, force: bool = FORCE, lang: Optional[str] = LANG,
    report: Report = REPORT, layout: Layout = LAYOUT, case: Case = CASE,
    slow: bool = SLOW,
) -> None:
    """Step 1 only: download the video and produce the transcript."""
    setup(layout, case, report, slow, force, lang)
    root = resolve_dir(url, output)
    pipeline(root, url, upto="transcribe")


def _stage_cmd(stage: str, summary: str):
    def cmd(
        directory: Path = typer.Argument(..., metavar="DIR",
                                         help="Output directory from a previous run."),
        force: bool = FORCE, roi: Optional[str] = ROI, report: Report = REPORT,
        layout: Layout = LAYOUT, case: Case = CASE, slow: bool = SLOW,
    ) -> None:
        st = read_state(directory)
        if not st["done"]:
            fail(f"{directory} is not an extract-slides output directory.",
                 f"Run  {PROG} <URL>  first, or point at the right directory.")
            raise typer.Exit(code=2)
        setup(Layout(st["layout"] or layout.value), Case(st["case"] or case.value),
              report, slow, force, roi=roi)
        pipeline(directory, f"https://youtu.be/{VIDEO[SIM.case]['vid']}", redo=stage)
    cmd.__doc__ = summary
    cmd.__name__ = stage
    return cmd


app.command("transcribe")(_stage_cmd(
    "transcribe", "Redo the transcript without downloading the video again."))
app.command("detect")(_stage_cmd(
    "detect", "Redo slide-change detection. Re-runs crop and pair after it."))
app.command("crop")(_stage_cmd(
    "crop", "Redo the slide-region crop only."))
app.command("pair")(_stage_cmd(
    "pair", "Redo the speech-to-slide pairing and rewrite the manifest."))


@app.command()
def drop(
    directory: Path = typer.Argument(..., metavar="DIR", help="Output directory from a previous run."),
    slides: list[int] = typer.Argument(..., help="Slide numbers to delete."),
) -> None:
    """Delete duplicate slides, renumber the rest, and rewrite the manifest."""
    st = read_state(directory)
    setup(Layout(st["layout"] or "flat"), Case(st["case"] or "captioned"),
          Report.text, False, False)
    do_drop(directory, slides)


@app.command()
def review(
    directory: Path = typer.Argument(..., metavar="DIR", help="Output directory from a previous run."),
) -> None:
    """Walk the slides flagged as possible duplicates, one at a time."""
    st = read_state(directory)
    setup(Layout(st["layout"] or "flat"), Case(st["case"] or "captioned"),
          Report.text, False, False)
    mf = directory / "manifest.json"
    if not mf.exists():
        fail(f"No manifest at {mf}")
        raise typer.Exit(code=2)
    flagged = [s for s in json.loads(mf.read_text())["slides"] if s["suspect"]]
    if not flagged:
        outc.print("[green]✓[/green] Nothing flagged. Every slide looks distinct.")
        return
    outc.print(f"[bold]{len(flagged)} slide(s) flagged as possible duplicates[/bold]\n")
    for s in flagged:
        outc.print(f"  {s['n']:03d}  at {s['at']}  {directory}/slides/{s['n']:03d}.png")
    outc.print("\n[dim]MOCK: the real command would prompt keep/drop per slide, or open "
               "a contact sheet. Which of those it is remains fog on the map.[/dim]")


if __name__ == "__main__":
    app(prog_name=PROG)
