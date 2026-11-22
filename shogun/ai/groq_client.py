"""Groq Cloud client (OpenAI-compatible REST API) with model discovery.

* Keys are held in :class:`shogun.config.Secret` and only placed in the
  ``Authorization`` header; they never reach logs or exception messages.
* Retries with exponential backoff on 429/5xx/timeouts, honouring
  ``retry-after``.
* JSON mode + Pydantic validation; one corrective retry on invalid output.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from shogun.ai.errors import (
    AIAuthError,
    AINotConfiguredError,
    AIRateLimitError,
    AIResponseError,
    AIUnavailableError,
)
from shogun.config import Secret
from shogun.logging_setup import get_logger, register_secret

log = get_logger("ai.groq")
BASE_URL = "https://api.groq.com/openai/v1"
T = TypeVar("T", bound=BaseModel)

# Strongest-first preference among models known to be offered on Groq. Availability is always
# checked against the live /models list for the user's key; nothing here is assumed to be free
# or permanently available.
PREFERRED_MODELS: tuple[str, ...] = (
    "openai/gpt-oss-120b",
    "moonshotai/kimi-k2-instruct-0905",
    "moonshotai/kimi-k2-instruct",
    "llama-3.3-70b-versatile",
    "qwen/qwen3-32b",
    "meta-llama/llama-4-maverick-17b-128e-instruct",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "openai/gpt-oss-20b",
    "llama-3.1-8b-instant",
)
_NON_CHAT = re.compile(r"whisper|tts|guard|embed|playai|orpheus|compound|prompt-guard|distil", re.I)
_PARAMS = re.compile(r"(\d+(?:\.\d+)?)b\b", re.I)


@dataclass(frozen=True)
class ModelInfo:
    id: str
    owned_by: str | None
    context_window: int | None
    active: bool


def is_chat_model(model_id: str) -> bool:
    return not _NON_CHAT.search(model_id)


def rank_models(models: list[ModelInfo]) -> list[ModelInfo]:
    """Chat-capable active models, strongest first (preference list, then parameter count)."""
    usable = [m for m in models if m.active and is_chat_model(m.id)]
    pref = {mid: i for i, mid in enumerate(PREFERRED_MODELS)}

    def key(m: ModelInfo) -> tuple[int, float, str]:
        size = _PARAMS.findall(m.id)
        params = max((float(s) for s in size), default=0.0)
        return (pref.get(m.id, len(pref)), -params, m.id)

    return sorted(usable, key=key)


def choose_model(models: list[ModelInfo], configured: str | None) -> tuple[str | None, str]:
    """Return (model_id, explanation). Configured model wins if it is available."""
    ranked = rank_models(models)
    ids = {m.id for m in ranked}
    if configured:
        if configured in ids:
            return configured, f"Using configured model {configured}"
        if ranked:
            return ranked[0].id, f"Configured model {configured!r} is not available to this key; using {ranked[0].id}"
        return None, f"Configured model {configured!r} is not available and no chat models were found"
    if ranked:
        return ranked[0].id, f"Auto-selected strongest available model {ranked[0].id}"
    return None, "No chat-capable models are available for this key"


def _extract_json(text: str) -> Any:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


class GroqClient:
    def __init__(
        self, api_key: Secret, *, timeout: float = 60.0, max_retries: int = 3,
        transport: httpx.BaseTransport | None = None, sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not api_key.is_set:
            raise AINotConfiguredError(
                "Groq is not configured. Add GROQ_API_KEY to your environment or local .env file."
            )
        register_secret(api_key.get())
        self._key = api_key
        self._timeout = timeout
        self._max_retries = max_retries
        self._transport = transport
        self._sleep = sleep

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=BASE_URL, timeout=self._timeout, transport=self._transport,
            headers={"Authorization": f"Bearer {self._key.get()}", "Content-Type": "application/json"},
        )

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                with self._client() as client:
                    resp = client.request(method, path, json=payload)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = AIUnavailableError(f"Could not reach Groq ({type(exc).__name__})")
            else:
                if resp.status_code in (401, 403):
                    raise AIAuthError("Groq rejected the API key (401/403). Check GROQ_API_KEY.")
                if resp.status_code == 404:
                    raise AIResponseError("Groq returned 404 — the model may not exist for this key")
                if resp.status_code == 429:
                    last_error = AIRateLimitError("Groq rate limit reached. Try again shortly.")
                    retry_after = resp.headers.get("retry-after")
                    if attempt < self._max_retries:
                        self._sleep(min(30.0, float(retry_after)) if retry_after and retry_after.replace(".", "", 1).isdigit()
                                    else 2.0 ** attempt)
                        continue
                    raise last_error
                if resp.status_code >= 500:
                    last_error = AIUnavailableError(f"Groq service error ({resp.status_code})")
                elif resp.status_code >= 400:
                    detail = ""
                    try:
                        detail = str(resp.json().get("error", {}).get("message", ""))[:200]
                    except (ValueError, AttributeError):
                        pass
                    raise AIResponseError(f"Groq request failed ({resp.status_code}) {detail}".strip())
                else:
                    try:
                        return resp.json()
                    except ValueError as exc:
                        raise AIResponseError("Groq returned a non-JSON response") from exc
            if attempt < self._max_retries:
                self._sleep(2.0 ** attempt)
        assert last_error is not None
        raise last_error

    def list_models(self) -> list[ModelInfo]:
        data = self._request("GET", "/models")
        return [
            ModelInfo(id=m["id"], owned_by=m.get("owned_by"), context_window=m.get("context_window"),
                      active=m.get("active", True) is not False)
            for m in data.get("data", []) if isinstance(m, dict) and m.get("id")
        ]

    def chat_text(self, model: str, messages: list[dict[str, str]], *, temperature: float = 0.2,
                  max_tokens: int = 2000, json_mode: bool = False) -> str:
        payload: dict[str, Any] = {"model": model, "messages": messages, "temperature": temperature,
                                   "max_tokens": max_tokens}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        data = self._request("POST", "/chat/completions", payload)
        try:
            return str(data["choices"][0]["message"]["content"] or "")
        except (KeyError, IndexError, TypeError) as exc:
            raise AIResponseError("Unexpected Groq response shape") from exc

    def chat_json(self, model: str, messages: list[dict[str, str]], schema: type[T], *,
                  temperature: float = 0.2, max_tokens: int = 3000) -> tuple[T, str]:
        """Return (validated object, raw text). Retries once with the validation error fed back."""
        convo = list(messages)
        for attempt in range(2):
            raw = self.chat_text(model, convo, temperature=temperature, max_tokens=max_tokens, json_mode=True)
            try:
                return schema.model_validate(_extract_json(raw)), raw
            except (json.JSONDecodeError, ValidationError) as exc:
                log.warning("Invalid structured output from %s (attempt %d)", model, attempt + 1)
                if attempt == 1:
                    raise AIResponseError("The model returned output that failed validation") from exc
                convo = [*messages, {"role": "assistant", "content": raw[:4000]},
                         {"role": "user", "content": f"That JSON was invalid: {str(exc)[:800]}. "
                                                     "Return ONLY corrected JSON matching the schema."}]
        raise AIResponseError("unreachable")  # pragma: no cover
