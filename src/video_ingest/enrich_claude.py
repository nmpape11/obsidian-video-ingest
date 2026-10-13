"""Stage 3 API side: call Claude with structured output to enrich one note.

Requires the enrich extra (pip install -e ".[enrich]") and ANTHROPIC_API_KEY.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

try:
    import anthropic

    # Setup problems that would fail every note the same way: stop the run instead.
    FATAL_ERRORS: tuple[type[Exception], ...] = (
        anthropic.AuthenticationError,
        anthropic.PermissionDeniedError,
        anthropic.NotFoundError,
    )
except ImportError:  # pragma: no cover - the enrich extra installs it
    anthropic = None
    FATAL_ERRORS = ()

from .enrich import (
    DEFAULT_MODEL,
    SYSTEM_PROMPT,
    EnrichResult,
    Sources,
    build_user_message,
    to_result,
)

# Server-side fallback re-runs a declined request on another model inside the same call.
# "default" routes by refusal category; only these models accept it.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5-1"}


class Enrichment(BaseModel):
    summary: str = Field(description="One or two sentences.")
    key_points: list[str]
    categories: list[str]
    tags: list[str]


class ClaudeEnricher:
    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        effort: str = "low",
        client: Any = None,
    ) -> None:
        if client is None:
            if anthropic is None:
                raise RuntimeError('anthropic not installed; run: pip install -e ".[enrich]"')
            client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
        self.client = client
        self.model = model
        self.effort = effort

    def enrich(
        self, sources: Sources, known_categories: list[str], known_tags: list[str]
    ) -> EnrichResult:
        kwargs: dict[str, Any] = {}
        if self.model in FALLBACK_MODELS:
            kwargs = {"betas": [FALLBACK_BETA], "fallbacks": "default"}
        try:
            response = self.client.beta.messages.parse(
                model=self.model,
                max_tokens=16000,
                # Stable across notes; the per-note sources and vocabulary go in the user turn.
                system=[
                    {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
                ],
                messages=[
                    {
                        "role": "user",
                        "content": build_user_message(sources, known_categories, known_tags),
                    }
                ],
                output_config={"effort": self.effort},
                output_format=Enrichment,
                **kwargs,
            )
        except FATAL_ERRORS:
            raise
        except Exception as exc:  # per-note API/network errors: record and move on
            return EnrichResult(ok=False, error=f"{type(exc).__name__}: {exc}"[:200])

        if response.stop_reason == "refusal":
            return EnrichResult(ok=False, error="refused by model", model=response.model)
        if response.stop_reason == "max_tokens" or response.parsed_output is None:
            return EnrichResult(ok=False, error=f"no parsable output ({response.stop_reason})")
        out = response.parsed_output
        return to_result(
            out.summary, out.key_points, out.categories, out.tags, known_categories, response.model
        )
