"""
Environment/config. Loads from .env (see .env.example).

LLM: configurable Groq / OpenRouter / Gemini provider chain.
Graph: CSV for development, TigerGraph MCP for submission runs.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]

DATA_DIR = Path(os.getenv("DATA_DIR", str(ROOT / "data")))
ANSWERS_DIR = Path(os.getenv("ANSWERS_DIR", str(ROOT / "cases")))

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "qwen/qwen3.8-27b:free")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b").strip()
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq").strip().lower()

TG_HOST = os.getenv("TG_HOST", "")
TG_SECRET = os.getenv("TG_SECRET", "")
TG_GRAPH_NAME = os.getenv("TG_GRAPHNAME") or "HHGOA"
GRAPH_BACKEND = os.getenv("GRAPH_BACKEND", "csv").strip().lower()
GRAPHRAG_MODE = os.getenv("GRAPHRAG_MODE", "static").strip().lower()
if GRAPHRAG_MODE not in {"static", "grip"}:
    raise ValueError("GRAPHRAG_MODE must be 'static' or 'grip'")
CF_API_TOKEN = os.getenv("CF_API_TOKEN", "")
CF_ACCOUNT_ID = os.getenv("CF_ACCOUNT_ID", "")

JEV_API_KEY = os.getenv("JEV_API_KEY", "")
JEV_BASE_URL = os.getenv("JEV_BASE_URL", "")
JEV_ENABLED = os.getenv("JEV_ENABLED", "false").lower() in ("1", "true", "yes")

CARD_WINDOW_HOURS = int(os.getenv("CAL_CARD_WINDOW_HOURS", "48"))
CUSTOMER_HISTORY_DAYS = int(os.getenv("CAL_CUSTOMER_HISTORY_DAYS", "120"))
SHARED_ORIGIN_WINDOW_DAYS = int(os.getenv("CAL_SHARED_ORIGIN_WINDOW_DAYS", "30"))
SIMILAR_CASES_TOP_K = int(os.getenv("CAL_SIMILAR_CASES_TOP_K", "5"))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "2000"))
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.0"))


def llm_configured() -> bool:
    return bool(OPENROUTER_API_KEY or GEMINI_API_KEY or (GROQ_API_KEY and GROQ_MODEL))


def llm_provider_order() -> list[str]:
    configured = {"gemini": bool(GEMINI_API_KEY), "groq": bool(GROQ_API_KEY and GROQ_MODEL), "openrouter": bool(OPENROUTER_API_KEY)}
    if LLM_PROVIDER != "auto":
        if LLM_PROVIDER not in configured:
            raise ValueError("LLM_PROVIDER must be auto, groq, openrouter, or gemini")
        if LLM_PROVIDER == "groq":
            return ["groq"] + (["openrouter"] if configured["openrouter"] else [])
        return [LLM_PROVIDER] + [p for p, enabled in configured.items() if enabled and p != LLM_PROVIDER]
    return [p for p, enabled in configured.items() if enabled]


def tigergraph_configured() -> bool:
    host = (TG_HOST or "").strip()
    return bool(host and TG_SECRET.strip() and "<your-workspace>" not in host)


@lru_cache
def get_openrouter_client():
    if not OPENROUTER_API_KEY:
        return None
    from openai import OpenAI

    return OpenAI(
        api_key=OPENROUTER_API_KEY,
        base_url=OPENROUTER_BASE_URL,
        timeout=60.0,
    )


@lru_cache
def get_gemini_client():
    if not GEMINI_API_KEY:
        return None
    from google import genai

    return genai.Client(api_key=GEMINI_API_KEY)


@lru_cache
def get_groq_client():
    if not GROQ_API_KEY or not GROQ_MODEL:
        return None
    from openai import OpenAI

    return OpenAI(
        api_key=GROQ_API_KEY,
        base_url="https://api.groq.com/openai/v1",
        timeout=45.0,
    )


@lru_cache
def get_mcp_client():
    if not tigergraph_configured():
        raise RuntimeError(
            "TigerGraph backend selected, but TG_HOST and TG_SECRET "
            "must be configured."
        )
    from .mcp_client import TigerGraphMCPClient

    return TigerGraphMCPClient(TG_HOST, TG_SECRET, TG_GRAPH_NAME)


@lru_cache
def get_grip_client():
    from .grip_client import GripMCPClient

    return GripMCPClient()


@lru_cache
def get_jev_client():
    raise NotImplementedError("Jev SDK is not wired; the orchestrator uses llm_fallback.assess().")
