"""Stage 2b media side: get slide images or video frames and run RapidOCR on them.

Requires the ocr extra (pip install -e ".[ocr]"); heavy imports are lazy.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Protocol

from .fetch import has_speech_track, short_error, ytdlp_options
from .inbox import fetchable_url
from .ocr import OcrResult, consolidate

# A muxed h264 file up to 1024px tall (TikTok's 576x1024) is big enough for overlay text
# and fast to decode. Not a "res:" sort: that ranks vertical 720x1280 as 720p, and
# TikTok's h265 720p variants 403'd in testing. The fallback covers Instagram's DASH.
VIDEO_FORMAT = "b[vcodec^=h264][height<=1024]/bv*[height<=1280]/b"
VIDEO_FORMAT_SORT = ["+size"]
UNIVERSAL_DATA_RE = re.compile(
    r'<script[^>]+id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', re.S
)


class Reader(Protocol):
    def read(
        self, url: str, transcript: str = "", handles: set[str] | None = None
    ) -> OcrResult: ...


def tiktok_slide_urls(html: str) -> list[str]:
    """Image URLs of a TikTok photo slideshow, from the page's embedded JSON.

    yt-dlp exposes only the background music for slideshows, but the page data has every
    slide. Returns [] when the page isn't a slideshow or the layout has changed.
    """
    m = UNIVERSAL_DATA_RE.search(html)
    if not m:
        return []
    try:
        item = json.loads(m.group(1))["__DEFAULT_SCOPE__"]["webapp.video-detail"]["itemInfo"][
            "itemStruct"
        ]
        images = item["imagePost"]["images"]
        return [img["imageURL"]["urlList"][0] for img in images]
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        return []


def sample_frames(path: Path, fps: float) -> Iterator:
    """Yield RGB frames (numpy arrays) at roughly `fps` frames per second of video."""
    import av

    step = 1.0 / fps
    next_t = 0.0
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        stream.thread_type = "AUTO"
        for frame in container.decode(stream):
            if frame.time is None or frame.time + 1e-6 < next_t:
                continue
            yield frame.to_ndarray(format="rgb24")
            while next_t <= frame.time + 1e-6:
                next_t += step


class OcrEngine:
    def __init__(self, threads: int, min_score: float) -> None:
        try:
            from rapidocr import RapidOCR
        except ImportError as exc:
            raise RuntimeError('rapidocr not installed; run: pip install -e ".[ocr]"') from exc
        self.min_score = min_score
        self._ocr = RapidOCR(
            params={
                "Global.log_level": "error",
                # The default (all cores) oversubscribes and is slower than ~6 threads.
                "EngineConfig.onnxruntime.intra_op_num_threads": threads,
                # Frames are ~576x1024; the default upscales them for detection, which is
                # the slow step, without reading overlay text any better.
                "Det.limit_type": "max",
                "Det.limit_side_len": 960,
            }
        )

    def read(self, image) -> list[str]:
        # Overlay text is upright, so skip the orientation classifier (~30% faster).
        r = self._ocr(image, use_cls=False)
        return [t for t, s in zip(r.txts or (), r.scores or (), strict=True) if s >= self.min_score]


class YtDlpOcr:
    def __init__(
        self,
        *,
        fps: float = 1.0,
        threads: int | None = None,
        min_score: float = 0.8,
        cookies_file: str | None = None,
        cookies_from_browser: str | None = None,
    ) -> None:
        try:
            import yt_dlp  # noqa: F401
        except ImportError as exc:
            raise RuntimeError('yt-dlp not installed; run: pip install -e ".[ocr]"') from exc
        self.fps = fps
        self.engine = OcrEngine(threads or min(6, os.cpu_count() or 1), min_score)
        self.opts = ytdlp_options(cookies_file, cookies_from_browser)

    def read(self, url: str, transcript: str = "", handles: set[str] | None = None) -> OcrResult:
        import yt_dlp

        try:
            with tempfile.TemporaryDirectory(prefix="video-ocr-") as tmp:
                opts = {
                    **self.opts,
                    "format": VIDEO_FORMAT,
                    "format_sort": VIDEO_FORMAT_SORT,
                    "outtmpl": str(Path(tmp) / "%(id)s.%(ext)s"),
                }
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(fetchable_url(url), download=False)
                    if has_speech_track(info):
                        ydl.process_ie_result(info, download=True)
                        video = next((p for p in Path(tmp).iterdir() if p.is_file()), None)
                        if video is None:
                            raise RuntimeError("download produced no file")
                        images = [self.engine.read(f) for f in sample_frames(video, self.fps)]
                        source = "frames"
                    else:
                        html = ydl.urlopen(info["webpage_url"]).read().decode("utf-8", "replace")
                        urls = tiktok_slide_urls(html)
                        images = [self.engine.read(ydl.urlopen(u).read()) for u in urls]
                        source = "slides"
            lines = consolidate(images, transcript, handles)
            return OcrResult(
                ok=True, lines=lines, source=source if lines else "none", images=len(images)
            )
        except Exception as exc:  # one bad video must never stop the batch
            return OcrResult(ok=False, error=short_error(exc))
