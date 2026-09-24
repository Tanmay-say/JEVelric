"""Run the complete case pack on TigerGraph with Groq then free OpenRouter fallback."""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import config, llm

config.GRAPH_BACKEND = "tigergraph"
config.LLM_PROVIDER = "groq"
config.GEMINI_API_KEY = ""
# Pin a current OpenRouter free model for predictable text/JSON responses.
config.OPENROUTER_MODEL = "google/gemma-4-26b-a4b-it:free"
llm.OPENROUTER_MODEL = config.OPENROUTER_MODEL
llm.llm_provider_order = lambda: ["groq", "openrouter"]

from src import main as app

if llm.llm_provider_order() != ["groq", "openrouter"] or not config.GROQ_API_KEY:
    raise RuntimeError("Groq/OpenRouter run is not correctly configured")
if not config.OPENROUTER_API_KEY or not config.OPENROUTER_MODEL.endswith(":free"):
    raise RuntimeError("A configured OpenRouter :free model is required as Groq fallback")

# Hand a Groq 429 straight to OpenRouter instead of waiting through Groq's
# long Retry-After interval. Other Groq errors are also surfaced to the normal
# provider-order fallback; no Gemini provider is enabled in this runner.
def _groq_once(system: str, user: str, max_tokens: int) -> tuple[str, int]:
    client = config.get_groq_client()
    if client is None:
        raise llm.LLMError("GROQ_API_KEY and an active GROQ_MODEL are required")
    response = client.with_options(max_retries=0).chat.completions.create(
        model=config.GROQ_MODEL,
        temperature=config.LLM_TEMPERATURE,
        max_tokens=max_tokens,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    )
    return response.choices[0].message.content or "", llm._usage_tokens(getattr(response, "usage", None))


llm._groq_complete = _groq_once

_run_case = app.run_case


def _paced_run_case(row, graph):
    # Leave a short gap between cases to stay clear of provider request bursts.
    time.sleep(5)
    _run_case(row, graph)


app.run_case = _paced_run_case

if __name__ == "__main__":
    app.main()
