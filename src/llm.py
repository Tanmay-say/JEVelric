"""
Gemini primary, with Groq and OpenRouter fallbacks (configurable).

Never decides verdict, probability, or action — callers use this only for
structured signal JSON and analyst/SAR prose.
"""
from __future__ import annotations

import json
import logging
import re
import time

from .config import (
    GEMINI_MODEL,
    GROQ_MODEL,
    LLM_MAX_TOKENS,
    LLM_TEMPERATURE,
    llm_provider_order,
    OPENROUTER_MODEL,
    get_gemini_client,
    get_groq_client,
    get_openrouter_client,
)

log = logging.getLogger(__name__)

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


class LLMError(Exception):
    pass


def _strip_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = _FENCE.sub("", text).strip()
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return text


def _usage_tokens(usage) -> int:
    if usage is None:
        return 0
    if isinstance(usage, dict):
        return int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0) + int(
            usage.get("output_tokens") or usage.get("completion_tokens") or 0
        )
    prompt = (
        getattr(usage, "prompt_tokens", None)
        or getattr(usage, "input_tokens", None)
        or getattr(usage, "prompt_token_count", None)
        or 0
    )
    completion = (
        getattr(usage, "completion_tokens", None)
        or getattr(usage, "output_tokens", None)
        or getattr(usage, "candidates_token_count", None)
        or 0
    )
    return int(prompt) + int(completion)


def _transient(exc: Exception) -> bool:
    text = str(exc)
    return any(code in text for code in ("429", "503", "UNAVAILABLE", "rate-limited", "high demand", "RESOURCE_EXHAUSTED"))


def _with_retries(fn, attempts: int = 3):
    last: Exception | None = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as exc:
            last = exc
            if not _transient(exc) or i == attempts - 1:
                raise
            time.sleep(2 ** i)
    raise last or LLMError("retry failed")


def _openrouter_complete(system: str, user: str, max_tokens: int) -> tuple[str, int]:
    client = get_openrouter_client()
    if client is None:
        raise LLMError("OPENROUTER_API_KEY is not set")

    def _call():
        return client.chat.completions.create(
            model=OPENROUTER_MODEL,
            temperature=LLM_TEMPERATURE,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            extra_headers={
                "HTTP-Referer": "https://github.com/hhgoa-fraud-agent",
                "X-Title": "Jeveleric Fraud Agent",
            },
        )

    resp = _with_retries(_call)
    choice = resp.choices[0].message.content or ""
    return choice, _usage_tokens(getattr(resp, "usage", None))


def _groq_complete(system: str, user: str, max_tokens: int) -> tuple[str, int]:
    client = get_groq_client()
    if client is None:
        raise LLMError("GROQ_API_KEY and an active GROQ_MODEL are required")

    def _call():
        return client.chat.completions.create(
            model=GROQ_MODEL,
            temperature=LLM_TEMPERATURE,
            max_tokens=max_tokens,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )

    resp = _with_retries(_call)
    return resp.choices[0].message.content or "", _usage_tokens(getattr(resp, "usage", None))


def _gemini_text(resp) -> str:
    text = getattr(resp, "text", None) or ""
    if text.strip():
        return text
    chunks: list[str] = []
    for cand in getattr(resp, "candidates", None) or []:
        content = getattr(cand, "content", None)
        for part in getattr(content, "parts", None) or []:
            if getattr(part, "thought", False):
                continue
            piece = getattr(part, "text", None)
            if piece:
                chunks.append(piece)
    return "".join(chunks)


def _gemini_complete(system: str, user: str, max_tokens: int) -> tuple[str, int]:
    client = get_gemini_client()
    if client is None:
        raise LLMError("GEMINI_API_KEY is not set")
    cap = max(max_tokens, 256)

    def _call():
        kwargs = {
            "model": GEMINI_MODEL,
            "contents": f"{system}\n\n{user}",
            "config": {
                "temperature": LLM_TEMPERATURE,
                "max_output_tokens": cap,
            },
        }
        try:
            kwargs["config"]["thinking_config"] = {"thinking_budget": 0}
            return client.models.generate_content(**kwargs)
        except TypeError:
            kwargs["config"].pop("thinking_config", None)
            return client.models.generate_content(**kwargs)

    resp = _with_retries(_call)
    text = _gemini_text(resp)
    usage = getattr(resp, "usage_metadata", None)
    tokens = 0
    if usage is not None:
        tokens = int(getattr(usage, "prompt_token_count", 0) or 0) + int(
            getattr(usage, "candidates_token_count", 0) or 0
        )
    return text, tokens


def _complete_provider(provider: str, system: str, user: str, max_tokens: int) -> tuple[str, int]:
    if provider == "groq":
        return _groq_complete(system, user, max_tokens)
    if provider == "openrouter":
        return _openrouter_complete(system, user, max_tokens)
    if provider == "gemini":
        return _gemini_complete(system, user, max_tokens)
    raise LLMError(f"Unknown LLM provider: {provider}")


def complete_text(system: str, user: str, max_tokens: int | None = None) -> tuple[str, int]:
    """Return (text, tokens), failing over in the configured provider order."""
    cap = max_tokens if max_tokens is not None else LLM_MAX_TOKENS
    errors: list[str] = []
    for provider in llm_provider_order():
        try:
            text, tokens = _complete_provider(provider, system, user, cap)
            if text.strip():
                return text.strip(), tokens
            errors.append(f"{provider} returned empty text")
        except Exception as exc:
            errors.append(f"{provider}: {exc}")
            log.warning("%s complete_text failed: %s", provider, exc)
    raise LLMError("; ".join(errors) or "no LLM provider configured")


def complete_json(system: str, user: str, max_tokens: int | None = None) -> tuple[dict, int]:
    cap = max_tokens if max_tokens is not None else LLM_MAX_TOKENS
    errors: list[str] = []
    for provider in llm_provider_order():
        try:
            text, tokens = _complete_provider(provider, system, user, cap)
            payload = _strip_fence(text)
            try:
                parsed = json.loads(payload)
            except json.JSONDecodeError:
                start, end = payload.find("{"), payload.rfind("}")
                if start < 0 or end <= start:
                    raise LLMError(f"{provider} did not return JSON: {payload[:200]}")
                parsed = json.loads(payload[start : end + 1])
            if not isinstance(parsed, dict):
                raise LLMError(f"{provider} JSON response was not an object")
            return parsed, tokens
        except Exception as exc:
            errors.append(f"{provider}: {exc}")
            log.warning("%s complete_json failed: %s", provider, exc)
    raise LLMError("; ".join(errors) or "no LLM provider configured")
