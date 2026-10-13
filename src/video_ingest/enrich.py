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
TAG_RE = re.compile(r"[^a-z0-9]+")

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
- categories: one or two broad areas. Reuse a known category exactly as written \
whenever one fits; only create a new one (Title Case, one or two words) if none does.
- tags: three to eight specific themes that cut across categories (ingredients, goals, \
methods, e.g. high-protein, meal-prep, air-fryer). Lowercase, hyphenated. Reuse known \
tags when they fit.

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
        self, sources: Sources, known_categories: list[str], known_tags: list[str]
    ) -> EnrichResult: ...


def build_user_message(sources: Sources, known_categories: list[str], known_tags: list[str]) -> str:
    def section(name: str, body: str) -> str:
        return f"<{name}>\n{body.strip() or '(none)'}\n</{name}>"

    meta = f"title: {sources.title}\nplatform: {sources.platform}\nauthor: {sources.author}"
    return "\n\n".join(
        [
            section("video", meta),
            section("caption", sources.caption),
            section("transcript", sources.transcript),
            section("on_screen_text", sources.on_screen_text),
            section("known_categories", ", ".join(known_categories)),
            section("known_tags", ", ".join(known_tags)),
        ]
    )


def clean_tag(tag: str) -> str:
    return TAG_RE.sub("-", tag.lower().lstrip("#")).strip("-")


def clean_category(name: str, known: list[str]) -> str:
    """Strip [[...]] wrappers and snap to a known category's exact spelling."""
    name = name.strip().removeprefix("[[").removesuffix("]]").strip()
    known_match = next((k for k in known if k.lower() == name.lower()), None)
    if known_match:
        return known_match
    # New categories become note links, so "cooking" and "Cooking" must not both appear.
    return name.title() if name.islower() else name


def dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    return [x for x in items if x and not (x.lower() in seen or seen.add(x.lower()))]


def to_result(
    summary: str,
    key_points: list[str],
    categories: list[str],
    tags: list[str],
    known_categories: list[str],
    model: str,
) -> EnrichResult:
    """Normalize model output: whitespace, stray bullets, tag format, category spelling."""
    return EnrichResult(
        ok=True,
        summary=" ".join(summary.split()),
        key_points=[kp.strip().lstrip("-•* ").strip() for kp in key_points if kp.strip()],
        categories=dedupe([clean_category(c, known_categories) for c in categories]),
        tags=dedupe([clean_tag(t) for t in tags]),
        model=model,
    )
