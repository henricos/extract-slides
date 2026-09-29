"""Obtains the video, the caption tracks on offer, and the raw captions.

**This is an injected boundary** (#24): network and `yt-dlp` are the outside
world, so the CLI is handed an `Acquirer` and the suite hands it a fake. The
production one drives `yt_dlp` as a library, which is what makes the
downloader the tool's own declared dependency: an import resolves inside the
tool's environment and can never reach the root-owned binary on the PATH that
returns HTTP 403 for every format (ADR 0010).

**Which caption tracks to request is decided here**, because requesting is the
act the rules are about:

- The language is the one the source reports for its audio. There is no
  `--lang` (ADR 0009). With no reported language and no single `-orig` track to
  read one off, there is nothing to choose by, and no caption is requested.
- A human caption in that language is tried first, then the ASR original. The
  human one reads better and is what the operator will read; the ASR one keeps
  word timings. Both are fetched so transcribe can fall back offline.
- A machine-translated track is never requested: 4 of 5 attempts hit HTTP 429
  (`docs/research/youtube-captions.md`). The ASR original is asked for by its
  `-orig` key, the only unambiguous handle on it; the bare language key is a
  translation on any talk not spoken in that language.
"""

from __future__ import annotations

import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from extract_slides.manifest import (
    AUDIO_STEM,
    CAPTION_PREFIX,
    CAPTION_SUFFIX,
    VIDEO_FILENAME,
)

#: `yt-dlp` files a live-chat replay under `subtitles` as if it were a caption.
#: Two of nine sampled talks listed nothing else there.
LIVE_CHAT = "live_chat"

#: The suffix `yt-dlp` gives the ASR original of the spoken language.
ORIGINAL = "-orig"


class DownloaderError(Exception):
    """`yt-dlp` could not do what was asked. The message is its reason."""


@dataclass(frozen=True)
class Source:
    """What the platform says about a video before anything is downloaded."""

    video_id: str
    title: str
    url: str
    #: Seconds, as the platform states it — rounded to the second on YouTube.
    #: The media's own duration replaces it once the file is on disk.
    duration: float
    #: The language the source reports for its audio, where it reports one.
    language: str | None
    #: Keys of the human captions on offer, as `yt-dlp` lists them.
    subtitles: tuple[str, ...] = ()
    #: Keys of the automatic captions: the ASR original and its translations.
    automatic_captions: tuple[str, ...] = ()


@dataclass(frozen=True)
class CaptionTrack:
    key: str
    human: bool

    @property
    def kind(self) -> str:
        return "human" if self.human else "asr"

    @property
    def filename(self) -> str:
        return f"{CAPTION_PREFIX}.{self.kind}.{self.key}{CAPTION_SUFFIX}"


@dataclass(frozen=True)
class Media:
    video: Path
    audio: Path
    #: The media's own duration, which is the authority on time (ADR 0007).
    duration: float


class Acquirer(Protocol):
    def probe(self, url: str) -> Source: ...

    def download_media(self, source: Source, directory: Path) -> Media: ...

    def download_caption(self, source: Source, track: CaptionTrack, destination: Path) -> None: ...


@dataclass(frozen=True)
class Selection:
    """The tracks to request, in the order transcribe tries them."""

    tracks: tuple[CaptionTrack, ...]
    language: str | None
    #: Why nothing was selected. Empty when something was.
    reason: str = ""


def audio_language(source: Source) -> str | None:
    """The language the source reports for its audio.

    Read from the top-level language first. Where that is absent, a single
    `-orig` track names it too — `yt-dlp` sets the audio language from that
    very track. Several `-orig` tracks and no stated language is ambiguous,
    and ambiguity chooses nothing.
    """
    if source.language:
        return source.language
    originals = [key for key in source.automatic_captions if key.endswith(ORIGINAL)]
    if len(originals) == 1:
        return originals[0].removesuffix(ORIGINAL)
    return None


def _same_language(key: str, language: str) -> bool:
    key, language = key.lower(), language.lower()
    return key == language or key.startswith(f"{language}-")


def select_captions(source: Source) -> Selection:
    language = audio_language(source)
    if language is None:
        return Selection((), None, "the source reports no audio language to choose a caption by")

    tracks: list[CaptionTrack] = []
    human = sorted(
        (key for key in source.subtitles if key != LIVE_CHAT and _same_language(key, language)),
        # The exact language before any regional variant of it.
        key=lambda key: (key.lower() != language.lower(), key),
    )
    if human:
        tracks.append(CaptionTrack(human[0], human=True))
    original = f"{language}{ORIGINAL}".lower()
    asr = [key for key in source.automatic_captions if key.lower() == original]
    if asr:
        tracks.append(CaptionTrack(asr[0], human=False))

    if not tracks:
        return Selection((), language, f"the source offers no caption in {language}, its audio language")
    return Selection(tuple(tracks), language)


def captions_in(directory: Path) -> list[Path]:
    """The raw captions an earlier acquire left, in the order to try them."""
    found = sorted(directory.glob(f"{CAPTION_PREFIX}.*{CAPTION_SUFFIX}"))
    return sorted(found, key=lambda path: not path.name.startswith(f"{CAPTION_PREFIX}.human."))


# --- the production acquirer ------------------------------------------------


class _Quiet:
    """`yt-dlp`'s logger, silenced. Its words would land in the operator's log
    unformatted; its errors come back as exceptions and are reported by us."""

    def debug(self, message: str) -> None:
        pass

    info = warning = debug

    def error(self, message: str) -> None:
        pass


#: The best video up to 1080p, as an MP4 and preferring H.264: every fixture
#: the spikes decoded was H.264 in MP4, which is what the OpenCV wheel was
#: measured reading (ADR 0010). A progressive file is the fallback for sources
#: that serve no separate video stream.
VIDEO_FORMAT = "bv*[ext=mp4]/b[ext=mp4]/bv*/b"
VIDEO_SORT = ["res:1080", "vcodec:h264"]

#: YouTube's format 140, which the PyAV wheel inside `faster-whisper` decodes
#: in about a second (ADR 0010).
AUDIO_FORMAT = "ba[ext=m4a]/ba/b"


class YtDlpAcquirer:
    """The acquirer the tool ships: `yt_dlp`, imported, never shelled out to."""

    def _run(self, url: str, *, download: bool, **params: Any) -> dict[str, Any]:
        import yt_dlp

        options: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "logger": _Quiet(),
            "noplaylist": True,
            # Does not stop ASR translations from being listed, but spares
            # building the translated-manual list, which the source notes is slow.
            "extractor_args": {"youtube": {"skip": ["translated_subs"]}},
            **params,
        }
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=download)
        except yt_dlp.utils.DownloadError as error:
            raise DownloaderError(_reason(error)) from error
        if not info:
            raise DownloaderError(f"it returned nothing for {url}")
        if info.get("_type") == "playlist":
            raise DownloaderError(f"{url} is a playlist, not one video")
        return info

    def probe(self, url: str) -> Source:
        info = self._run(url, download=False, skip_download=True)
        return Source(
            video_id=str(info["id"]),
            title=str(info.get("title") or info["id"]),
            url=str(info.get("webpage_url") or url),
            duration=float(info.get("duration") or 0.0),
            language=info.get("language") or None,
            subtitles=tuple(info.get("subtitles") or {}),
            automatic_captions=tuple(info.get("automatic_captions") or {}),
        )

    def download_media(self, source: Source, directory: Path) -> Media:
        video = directory / VIDEO_FILENAME
        self._run(
            source.url,
            download=True,
            format=VIDEO_FORMAT,
            format_sort=VIDEO_SORT,
            outtmpl={"default": str(video)},
            overwrites=True,
        )
        audio = self._download_audio(source, directory)
        return Media(video=video, audio=audio, duration=_media_duration(video) or source.duration)

    def _download_audio(self, source: Source, directory: Path) -> Path:
        """The audio, fetched aside and moved in under a name that cannot collide.

        A fallback format can arrive as `.mp4` — audio in an MP4 container, or a
        progressive file — and written as `source.%(ext)s` it would land on the
        video downloaded a moment before. An MP4 audio stream is what `.m4a`
        names, so both are kept as `source.m4a`.
        """
        with tempfile.TemporaryDirectory() as scratch:
            info = self._run(
                source.url,
                download=True,
                format=AUDIO_FORMAT,
                outtmpl={"default": str(Path(scratch) / "audio.%(ext)s")},
            )
            fetched = Path(_downloaded(info) or next(Path(scratch).glob("audio.*")))
            suffix = ".m4a" if fetched.suffix in (".m4a", ".mp4") else fetched.suffix
            audio = directory / f"{AUDIO_STEM}{suffix}"
            shutil.move(fetched, audio)
        return audio

    def download_caption(self, source: Source, track: CaptionTrack, destination: Path) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            self._run(
                source.url,
                download=True,
                skip_download=True,
                writesubtitles=track.human,
                writeautomaticsub=not track.human,
                # Entries are full-match regular expressions, not literals.
                subtitleslangs=[re.escape(track.key)],
                # The default resolves to vtt, which triples the text.
                subtitlesformat="json3",
                outtmpl={"default": str(Path(scratch) / "caption")},
            )
            written = Path(scratch) / f"caption.{track.key}.json3"
            if not written.exists():
                raise DownloaderError(f"it wrote no {track.key} caption, although one was listed")
            shutil.move(written, destination)


def _reason(error: Exception) -> str:
    return re.sub(r"^ERROR:\s*", "", str(error)).strip()


def _downloaded(info: dict[str, Any]) -> str | None:
    downloads = info.get("requested_downloads") or []
    return downloads[0].get("filepath") if downloads else None


def _media_duration(video: Path) -> float | None:
    """The container's duration, read from its header without decoding."""
    import cv2

    capture = cv2.VideoCapture(str(video))
    try:
        frames = capture.get(cv2.CAP_PROP_FRAME_COUNT)
        fps = capture.get(cv2.CAP_PROP_FPS)
    finally:
        capture.release()
    if frames > 0 and fps > 0:
        return frames / fps
    return None


# --- the stage ---------------------------------------------------------------


@dataclass(frozen=True)
class Acquired:
    duration: float
    gist: str


def acquire(acquirer: Acquirer, source: Source, directory: Path, log: Any) -> Acquired:
    """Stage 1: the media, then every caption worth trying, into `directory`.

    Captions from an earlier acquire are removed first. They are named by
    track, and a track the source no longer offers would otherwise be
    tried by transcribe as though this run had fetched it.
    """
    media = acquirer.download_media(source, directory)
    log.field("video", media.video.name)
    for stale in captions_in(directory):
        stale.unlink()

    selection = select_captions(source)
    for track in selection.tracks:
        acquirer.download_caption(source, track, directory / track.filename)
    if selection.tracks:
        log.field("captions", ", ".join(track.key for track in selection.tracks))
    else:
        log.note(f"No caption: {selection.reason}.")

    captions = len(selection.tracks)
    gist = f"{media.video.name}, {captions} caption{'' if captions == 1 else 's'}"
    log.done(gist)
    return Acquired(duration=media.duration, gist=gist)
