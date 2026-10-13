"""Stage 3: turn a note's caption, transcript and on-screen text into a summary,
key points, categories and tags with the Claude API (text only, no images).

This module is the stdlib-only side: prompt, request text and output cleanup.
The API call lives in enrich_claude.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol

DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_CATEGORY = "Other"
TAG_RE = re.compile(r"[^a-z0-9]+")
# Reach-hashtags that say nothing about the content.
GENERIC_TAGS = {
    "fyp",
    "fy",
    "foryou",
    "foryoupage",
    "fypage",
    "viral",
    "viralvideo",
    "trending",
    "explore",
    "explorepage",
    "reels",
    "reel",
    "instagram",
    "tiktok",
    "tiktokmademebuyit",
    "xyzbca",
    "capcut",
    "foryourpage",
    "fypシ",
}

SYSTEM_PROMPT = """\
You turn a saved short-form video (TikTok or Instagram) into an entry in the user's \
personal Obsidian knowledge base. Notes are found later by searching for things like \
"high-protein chicken recipes" or "that video about morning routines", so the entry must \
say plainly what the video contains.

You get up to three sources, each possibly empty:
- caption: the creator's post text, often with hashtags.
- transcript: speech recognized by Whisper; may contain mishearings.
- on_screen_text: text read by OCR from video frames or slideshow images, one line per \
item, in order of appearance. It is noisy: words run together ("250mllowfatmilk"), \
appliance and brand labels slip in (NINJA, cusimax), and wrapped sentences are split \
across lines.

Fractions are the most common OCR damage: "3/4" or "¾" often comes through as "34", \
"¼" as "V4", and "½" is frequently dropped entirely ("tsp pepper"). Correct a quantity \
only when the context makes the true value clear, for example "34 cup ice" in a single \
smoothie is 3/4 cup. When you can't tell, keep the value as read, or list the item \
without a quantity if one was clearly lost. Never invent ingredients, amounts, steps \
or claims that none of the sources support. Where sources disagree, prefer the value \
two of them agree on.

Return:
- summary: one or two plain sentences: what the video is and what makes it worth keeping.
- key_points: the content someone would come back for, as short standalone items \
without bullets or markdown. For a recipe: servings and macros if given, then each \
ingredient with its quantity, then the steps condensed (keep temperatures and times). \
For exercise: exercises, sets and reps, form cues. For advice: the concrete takeaways. \
Rejoin text that OCR split across lines; skip labels, watermarks and hashtags.
- categories: from allowed_categories only, written exactly as listed; they are the \
fixed folders the user filters by. Usually one; two only when the video clearly \
belongs to both. Use Other only when none of the rest fit.
- tags: three to eight hashtag-style topic tags, lowercase and hyphenated, without the #. \
The video's own hashtags are a good source when they describe the content \
(#mealprep becomes meal-prep); skip reach hashtags like fyp, foryou, viral or trending. \
Add specific ingredients, goals and methods the video is about (high-protein, \
air-fryer). Use a known tag's spelling when it means the same thing.

If the sources carry almost nothing (only hashtags, say), keep the summary short, say \
what little is known, and return few or no key points rather than guessing."""


@dataclass
class Sources:
    title: str
    platform: str = ""
    author: str = ""
    caption: str = ""
    transcript: str = ""
    on_screen_text: str = ""

    def is_empty(self) -> bool:
        return not (self.caption or self.transcript or self.on_screen_text)


@dataclass
class EnrichResult:
    ok: bool
    summary: str = ""
    key_points: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    model: str = ""  # model that actually answered (differs if a fallback ran)
    error: str = ""


class Enricher(Protocol):
    def enrich(
        self, sources: Sources, categories: list[str], known_tags: list[str]
    ) -> EnrichResult: ...


def build_user_message(sources: Sources, categories: list[str], known_tags: list[str]) -> str:
    def section(name: str, body: str) -> str:
        return f"<{name}>\n{body.strip() or '(none)'}\n</{name}>"

    meta = f"title: {sources.title}\nplatform: {sources.platform}\nauthor: {sources.author}"
    return "\n\n".join(
        [
            section("video", meta),
            section("caption", sources.caption),
            section("transcript", sources.transcript),
            section("on_screen_text", sources.on_screen_text),
            section("allowed_categories", ", ".join(categories)),
            section("known_tags", ", ".join(known_tags)),
        ]
    )


def clean_tag(tag: str) -> str:
    """Hashtag-style tag: lowercase, hyphenated, no '#'. "" for generic reach hashtags."""
    tag = TAG_RE.sub("-", tag.lower().lstrip("#")).strip("-")
    return "" if tag.replace("-", "") in GENERIC_TAGS else tag


def clean_category(name: str, allowed: list[str]) -> str | None:
    """The allowed category's exact spelling, or None if the name isn't one of them."""
    name = name.strip().removeprefix("[[").removesuffix("]]").strip()
    return next((a for a in allowed if a.lower() == name.lower()), None)


def dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    return [x for x in items if x and not (x.lower() in seen or seen.add(x.lower()))]


def to_result(
    summary: str,
    key_points: list[str],
    categories: list[str],
    tags: list[str],
    allowed: list[str],
    model: str,
) -> EnrichResult:
    """Normalize model output: whitespace, stray bullets, tag format, category spelling.

    Categories outside the allowed list are dropped (the schema already prevents them);
    a note always gets at least one, falling back to Other when it's allowed.
    """
    cats = dedupe([c for c in (clean_category(c, allowed) for c in categories) if c])[:2]
    if not cats and FALLBACK_CATEGORY in allowed:
        cats = [FALLBACK_CATEGORY]
    return EnrichResult(
        ok=True,
        summary=" ".join(summary.split()),
        key_points=[kp.strip().lstrip("-•* ").strip() for kp in key_points if kp.strip()],
        categories=cats,
        tags=dedupe([clean_tag(t) for t in tags]),
        model=model,
    )
