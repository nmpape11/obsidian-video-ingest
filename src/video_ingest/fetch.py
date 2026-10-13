"""Stage 2: fetch caption, metadata and transcript for a video.

Subtitles are used when the platform has them; otherwise the audio is downloaded to a
temp dir, transcribed locally with faster-whisper, and deleted.
yt-dlp and faster-whisper are optional deps (pip install -e ".[fetch]"), imported lazily.
"""

from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Protocol

from .inbox import fetchable_url

# TikTok's audio-only format "audio" is the background sound/music, not the speaker,
# so take audio from the muxed video there. Instagram serves a separate DASH audio track.
AUDIO_FORMAT = "bestaudio[format_id!=audio]/worst[acodec!=none][vcodec!=none]/best"
SUB_LANG_PREFERENCE = ("en", "en-US", "en-GB", "eng-US", "eng")
VTT_TIMING_RE = re.compile(r"^\d{2}:\d{2}[:.\d]* --> ")
VTT_TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class FetchResult:
    ok: bool
    caption: str = ""
    transcript: str = ""
    transcript_source: str = "none"  # subtitles | whisper | none
    author: str = ""
    duration: int | None = None
    uploaded: date | None = None
    error: str = ""


class Fetcher(Protocol):
    def fetch(self, url: str) -> FetchResult: ...


def vtt_to_text(vtt: str) -> str:
    """Plain text from WebVTT, dropping headers, timings, tags and rolling-caption repeats."""
    lines: list[str] = []
    for raw in vtt.splitlines():
        line = raw.strip()
        if (
            not line
            or line == "WEBVTT"
            or line.startswith(("NOTE", "STYLE", "Kind:", "Language:"))
            or VTT_TIMING_RE.match(line)
            or line.isdigit()
        ):
            continue
        line = VTT_TAG_RE.sub("", line).strip()
        if line and (not lines or lines[-1] != line):
            lines.append(line)
    return " ".join(lines)


def clean_caption(text: str) -> str:
    """TikTok flattens caption newlines into runs of spaces; turn them back into lines."""
    text = re.sub(r"[ \t]{2,}", "\n", text.strip())
    return "\n".join(line.strip() for line in text.splitlines())


def short_error(exc: BaseException) -> str:
    msg = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
    msg = re.sub(r"\x1b\[[0-9;]*m", "", msg).removeprefix("ERROR: ")
    return msg[:200]


def pick_subtitles(info: dict) -> dict | None:
    """Best subtitle track: manual before automatic, English first, vtt preferred."""
    for key in ("subtitles", "automatic_captions"):
        tracks = info.get(key) or {}
        langs = [lang for lang in SUB_LANG_PREFERENCE if lang in tracks] or list(tracks)
        for lang in langs:
            formats = tracks[lang]
            for fmt in sorted(formats, key=lambda f: f.get("ext") != "vtt"):
                if fmt.get("ext") == "vtt" and fmt.get("url"):
                    return fmt
    return None


def has_speech_track(info: dict) -> bool:
    """False for TikTok photo slideshows, whose only format is the background music."""
    return any(f.get("format_id") != "audio" for f in info.get("formats") or [])


class _SilentLogger:
    """yt-dlp prints ERROR lines even with quiet=True; errors reach us as exceptions."""

    def debug(self, msg: str) -> None: ...
    def info(self, msg: str) -> None: ...
    def warning(self, msg: str) -> None: ...
    def error(self, msg: str) -> None: ...


def ytdlp_options(
    cookies_file: str | None = None,
    cookies_from_browser: str | None = None,
    impersonate: bool = True,
) -> dict:
    """Base YoutubeDL options shared by every stage that talks to the platforms."""
    opts: dict = {"quiet": True, "no_warnings": True, "noprogress": True, "logger": _SilentLogger()}
    if cookies_file:
        opts["cookiefile"] = str(Path(cookies_file).expanduser())
    if cookies_from_browser:
        opts["cookiesfrombrowser"] = (cookies_from_browser,)
    if impersonate:
        # TikTok answers plain requests with a bot challenge.
        from yt_dlp.networking.impersonate import ImpersonateTarget

        opts["impersonate"] = ImpersonateTarget("chrome")
    return opts


class YtDlpFetcher:
    def __init__(
        self,
        *,
        whisper_model: str = "base",
        language: str | None = None,
        cookies_file: str | None = None,
        cookies_from_browser: str | None = None,
        impersonate: bool = True,
    ) -> None:
        try:
            import yt_dlp  # noqa: F401
        except ImportError as exc:
            raise RuntimeError('yt-dlp not installed; run: pip install -e ".[fetch]"') from exc
        self.whisper_model = whisper_model
        self.language = language or None
        self.opts = ytdlp_options(cookies_file, cookies_from_browser, impersonate)
        self._model = None

    def fetch(self, url: str) -> FetchResult:
        import yt_dlp

        try:
            with tempfile.TemporaryDirectory(prefix="video-fetch-") as tmp:
                opts = {
                    **self.opts,
                    "format": AUDIO_FORMAT,
                    "outtmpl": str(Path(tmp) / "%(id)s.%(ext)s"),
                }
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(fetchable_url(url), download=False)
                    result = self._metadata(info)

                    sub = pick_subtitles(info)
                    if sub:
                        vtt = ydl.urlopen(sub["url"]).read().decode("utf-8", "replace")
                        result.transcript = vtt_to_text(vtt)
                        result.transcript_source = "subtitles"
                    if not result.transcript and has_speech_track(info):
                        ydl.process_ie_result(info, download=True)
                        audio = next((p for p in Path(tmp).iterdir() if p.is_file()), None)
                        if audio is None:
                            raise RuntimeError("download produced no file")
                        result.transcript = self._transcribe(audio)
                        result.transcript_source = "whisper" if result.transcript else "none"
                return result
        except Exception as exc:  # one bad video must never stop the batch
            return FetchResult(ok=False, error=short_error(exc))

    @staticmethod
    def _metadata(info: dict) -> FetchResult:
        uploaded = None
        if info.get("upload_date"):
            uploaded = datetime.strptime(info["upload_date"], "%Y%m%d").date()
        duration = info.get("duration")
        return FetchResult(
            ok=True,
            caption=clean_caption(info.get("description") or ""),
            author=info.get("uploader") or info.get("channel") or "",
            duration=round(duration) if duration else None,
            uploaded=uploaded,
        )

    def _transcribe(self, audio: Path) -> str:
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise RuntimeError(
                    'faster-whisper not installed; run: pip install -e ".[fetch]"'
                ) from exc
            self._model = WhisperModel(self.whisper_model, device="cpu", compute_type="int8")
        # vad_filter skips music-only stretches, where Whisper tends to hallucinate text.
        segments, _ = self._model.transcribe(str(audio), language=self.language, vad_filter=True)
        return " ".join(seg.text.strip() for seg in segments).strip()
