"""Claude API access for report analysis: client creation, one guarded call, usage accounting."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

import anthropic

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Server-side refusal fallback (beta): if the model declines, the API reruns the request on a fallback model.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
PROMPT_VERSION = "2026-11-11.1"


class AIUnavailable(Exception):
    """The analysis cannot run (no key, API error). The message is shown in the report."""


@dataclass
class Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    web_searches: int = 0
    request_ids: list[str] = field(default_factory=list)

    def add(self, message) -> None:
        self.calls += 1
        u = getattr(message, "usage", None)
        if u is not None:
            self.input_tokens += getattr(u, "input_tokens", 0) or 0
            self.output_tokens += getattr(u, "output_tokens", 0) or 0
            self.cache_read_tokens += getattr(u, "cache_read_input_tokens", 0) or 0
            self.cache_write_tokens += getattr(u, "cache_creation_input_tokens", 0) or 0
            server = getattr(u, "server_tool_use", None)
            self.web_searches += getattr(server, "web_search_requests", 0) or 0 if server is not None else 0
        request_id = getattr(message, "_request_id", None)
        if request_id:
            self.request_ids.append(request_id)

    def as_dict(self) -> dict:
        return {"calls": self.calls, "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
                "cache_read_tokens": self.cache_read_tokens, "cache_write_tokens": self.cache_write_tokens,
                "web_searches": self.web_searches, "request_ids": self.request_ids[-20:]}


def make_client() -> anthropic.Anthropic:
    """Client from ANTHROPIC_API_KEY in .env (settings) or the environment. Raises AIUnavailable without a key."""
    settings = get_settings()
    key = settings.anthropic_api_key.get_secret_value() or os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise AIUnavailable("No Anthropic API key is configured. Add ANTHROPIC_API_KEY to the backend .env file.")
    return anthropic.Anthropic(api_key=key, timeout=180.0, max_retries=2)


def create(client, usage: Usage, **params):
    """One Messages API call with refusal fallback; maps SDK errors to AIUnavailable."""
    settings = get_settings()
    params.setdefault("model", settings.ai_model)
    try:
        message = client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **params)
    except anthropic.AuthenticationError as exc:
        raise AIUnavailable("The Anthropic API key was rejected.") from exc
    except anthropic.PermissionDeniedError as exc:
        raise AIUnavailable(f"The Anthropic API refused access: {exc.message}") from exc
    except anthropic.NotFoundError as exc:
        raise AIUnavailable(f"Model or endpoint not found ({params.get('model')}).") from exc
    except anthropic.RateLimitError as exc:
        raise AIUnavailable("The Anthropic API rate limit was reached; try again later.") from exc
    except anthropic.BadRequestError:
        raise  # caller decides (e.g. retry without web search)
    except anthropic.APIStatusError as exc:
        raise AIUnavailable(f"The Anthropic API returned an error ({exc.status_code}).") from exc
    except anthropic.APIConnectionError as exc:
        raise AIUnavailable("Could not reach the Anthropic API.") from exc
    usage.add(message)
    return message


def refusal_text(message) -> str | None:
    """A readable reason when the model (and its fallback) declined."""
    if getattr(message, "stop_reason", None) != "refusal":
        return None
    details = getattr(message, "stop_details", None)
    category = getattr(details, "category", None) if details else None
    return "The model declined to analyse this item" + (f" ({category})." if category else ".")
