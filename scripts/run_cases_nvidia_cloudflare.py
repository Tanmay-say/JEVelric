"""Run the case pack on TigerGraph with NVIDIA NIM then Cloudflare Workers AI.

Required .env variables:
  NVIDIA_API_KEY
  CF_API_TOKEN
  CF_ACCOUNT_ID

Optional model overrides:
  NVIDIA_MODEL (default: openai/gpt-oss-20b)
  CLOUDFLARE_WORKERS_AI_MODEL (default: @cf/openai/gpt-oss-20b)

Run all cases with:
  .venv/Scripts/python.exe scripts/run_cases_nvidia_cloudflare.py
Run one case with:
  .venv/Scripts/python.exe scripts/run_cases_nvidia_cloudflare.py --case HHG-017

This is intentionally a separate runner; it does not change the existing
Gemini/Groq runner or the application's normal provider configuration.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from openai import OpenAI

from src import config, llm

config.GRAPH_BACKEND = "tigergraph"

NVIDIA_NIM_API_KEY = os.getenv("NVIDIA_API_KEY", "").strip()
NVIDIA_NIM_MODEL = os.getenv("NVIDIA_MODEL", "openai/gpt-oss-20b").strip()
CLOUDFLARE_API_TOKEN = os.getenv("CF_API_TOKEN", "").strip()
CLOUDFLARE_ACCOUNT_ID = os.getenv("CF_ACCOUNT_ID", "").strip()
CLOUDFLARE_WORKERS_AI_MODEL = os.getenv(
    "CLOUDFLARE_WORKERS_AI_MODEL", "@cf/openai/gpt-oss-20b"
).strip()

missing = [
    name
    for name, value in (
        ("NVIDIA_API_KEY", NVIDIA_NIM_API_KEY),
        ("CF_API_TOKEN", CLOUDFLARE_API_TOKEN),
        ("CF_ACCOUNT_ID", CLOUDFLARE_ACCOUNT_ID),
    )
    if not value
]
if missing:
    raise RuntimeError("Missing required .env settings: " + ", ".join(missing))

nim_client = OpenAI(
    api_key=NVIDIA_NIM_API_KEY,
    base_url="https://integrate.api.nvidia.com/v1",
    timeout=90.0,
)
workers_ai_client = OpenAI(
    api_key=CLOUDFLARE_API_TOKEN,
    base_url=(
        "https://api.cloudflare.com/client/v4/accounts/"
        f"{CLOUDFLARE_ACCOUNT_ID}/ai/v1"
    ),
    timeout=90.0,
)


def _chat_completion(client: OpenAI, model: str, system: str, user: str, max_tokens: int):
    request = dict(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens=max_tokens,
        temperature=config.LLM_TEMPERATURE,
    )
    if client is nim_client:
        # GLM-5.3 defaults to maximum reasoning and keeps it in the response
        # unless explicitly cleared. Low effort leaves room for the answer.
        request["reasoning_effort"] = "low"
        request["extra_body"] = {"chat_template_kwargs": {"clear_thinking": True}}
    response = client.chat.completions.create(**request)
    text = response.choices[0].message.content or ""
    if not text.strip():
        raise llm.LLMError(f"{model} returned an empty response")
    return text, llm._usage_tokens(getattr(response, "usage", None))


def _complete_provider(provider: str, system: str, user: str, max_tokens: int):
    if provider == "nvidia_nim":
        return _chat_completion(nim_client, NVIDIA_NIM_MODEL, system, user, max_tokens)
    if provider == "cloudflare_workers_ai":
        return _chat_completion(
            workers_ai_client,
            CLOUDFLARE_WORKERS_AI_MODEL,
            system,
            user,
            max_tokens,
        )
    raise llm.LLMError(f"Unknown provider in NVIDIA/Cloudflare runner: {provider}")


# src.llm's existing complete_text/complete_json methods implement ordered
# fallback and JSON parsing. Limit this runner's provider chain to these two.
llm.llm_provider_order = lambda: ["nvidia_nim", "cloudflare_workers_ai"]
llm._complete_provider = _complete_provider

from src import main as app


if __name__ == "__main__":
    app.main()
