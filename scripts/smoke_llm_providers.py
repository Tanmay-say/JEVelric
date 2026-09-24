"""Compare configured LLM providers on tiny, identical structured/prose tasks."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import llm_provider_order
from src.llm import _complete_provider, _strip_fence

TASKS = [
    ("json", "Return only JSON with keys fraud_signal (boolean) and confidence (number 0 to 1). Evidence: three online authorizations under $5 followed by a $240 purchase in one hour."),
    ("prose", "In one short sentence, summarize this synthetic evidence without making a final fraud decision: three small online authorizations preceded a $240 purchase within one hour."),
]


def run() -> None:
    results = []
    selected = sys.argv[1:]
    providers = [p for p in llm_provider_order() if not selected or p in selected]
    for provider in providers:
        used_tokens = 0
        elapsed = 0.0
        passed = 0
        errors = []
        for name, prompt in TASKS:
            start = time.perf_counter()
            try:
                text, tokens = _complete_provider(
                    provider,
                    "Be concise. Do not add facts not present in the evidence.",
                    prompt,
                    96,
                )
                if not text.strip():
                    raise ValueError("empty response")
                if name == "json":
                    payload = json.loads(_strip_fence(text))
                    if not isinstance(payload, dict) or not {"fraud_signal", "confidence"} <= payload.keys():
                        raise ValueError("JSON response missed required keys")
                    confidence = float(payload["confidence"])
                    if not 0 <= confidence <= 1:
                        raise ValueError("confidence outside [0, 1]")
                passed += 1
                used_tokens += tokens
            except Exception as exc:
                status = getattr(exc, "status_code", None)
                errors.append(f"{name}: {type(exc).__name__}" + (f" HTTP {status}" if status else ""))
            elapsed += time.perf_counter() - start
        results.append((passed, used_tokens, elapsed, provider, errors))
    for passed, tokens, elapsed, provider, errors in sorted(results, reverse=True):
        print(f"{provider}: {passed}/2 valid, reported_tokens={tokens}, latency_s={elapsed:.2f}, errors={errors}")
    winners = [r for r in results if r[0] == 2]
    if winners:
        recommended = min(winners, key=lambda r: (r[1], r[2]))
        print(f"RECOMMENDED_LOW_TOKEN: {recommended[3]}")
    else:
        print("RECOMMENDED_LOW_TOKEN: none (no provider passed both checks)")


if __name__ == "__main__":
    run()
