"""Stage 2b: read on-screen text from slideshow images and sampled video frames.

This module holds the pure text side: turning noisy per-frame OCR lines into one clean,
ordered list. Media download and the OCR engine live in ocr_media.py.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher

# Lines this similar (on normalized text) are treated as the same line read twice,
# e.g. "Oncé oil is hot; fry" vs "Once oil is hot, fry".
SAME_LINE_RATIO = 0.85
# Only drop a line for already being in the transcript if it's long enough that the
# match is meaningful ("Salt" is in plenty of transcripts and still worth listing).
MIN_TRANSCRIPT_MATCH = 12
WATERMARK = "tiktok"


@dataclass
class OcrResult:
    ok: bool
    lines: list[str] = field(default_factory=list)
    source: str = "none"  # slides | frames | none
    images: int = 0  # slides or frames read
    error: str = ""


def norm(text: str) -> str:
    """Lowercase letters and digits only: the comparison key for OCR lines."""
    return "".join(ch for ch in text.lower() if ch.isalnum())


def similar(a: str, b: str) -> bool:
    m = SequenceMatcher(None, a, b, autojunk=False)
    return m.real_quick_ratio() >= SAME_LINE_RATIO and m.ratio() >= SAME_LINE_RATIO


def same_line(a: str, b: str) -> bool:
    """Same text read twice. Digits must match exactly: "1 Tbsp" and "2 Tbsp" are
    different lines, and quantities are the part of a recipe worth keeping."""
    return re.sub(r"\D", "", a) == re.sub(r"\D", "", b) and similar(a, b)


def is_noise(text: str, handles: set[str]) -> bool:
    """Watermark, @handles and fragments too short to carry information."""
    n = norm(text)
    if len(n) < 3 or text.lstrip().startswith("@"):
        return True
    if n == WATERMARK or (len(n) <= len(WATERMARK) + 2 and similar(n, WATERMARK)):
        return True
    return any(similar(n, h) for h in handles)


def consolidate(
    images: list[list[str]],
    transcript: str = "",
    handles: set[str] | None = None,
) -> list[str]:
    """Merge per-image OCR lines (already confidence-filtered) into unique lines,
    in order of first appearance.

    Each line is represented by the spelling read most often across images, which
    irons out single-frame OCR jitter. Lines already spoken in the transcript
    (burned-in subtitles) are dropped.
    """
    handles = {norm(h) for h in handles or set() if norm(h)}
    # Handles seen on screen ("@creator") also show up without the @ in other frames.
    handles |= {norm(line) for img in images for line in img if line.lstrip().startswith("@")}
    handles.discard("")

    keys: list[str] = []
    spellings: list[Counter[str]] = []
    for image in images:
        for line in image:
            text = re.sub(r"\s+", " ", line).strip()
            if is_noise(text, handles):
                continue
            n = norm(text)
            idx = next((i for i, k in enumerate(keys) if same_line(n, k)), None)
            if idx is None:
                keys.append(n)
                spellings.append(Counter())
                idx = len(keys) - 1
            spellings[idx][text] += 1

    spoken = norm(transcript)
    out = []
    for counter in spellings:
        best = counter.most_common(1)[0][0]  # ties keep the first-seen spelling
        n = norm(best)
        if spoken and len(n) >= MIN_TRANSCRIPT_MATCH and n in spoken:
            continue
        out.append(best)
    return out
