"""
LLM-only (or heuristic) stand-in for jev_client.assess() — identical Signals
return shape. OpenRouter Qwen first, Gemini 2.5 Flash if that fails, graph
heuristics if no keys / both providers fail.
"""
from __future__ import annotations

import logging

from .config import llm_configured
from .jev_client import QUESTIONS, _PATTERN_SCORE_KEYS
from .llm import LLMError, complete_json
from .state import Pattern, Signals

log = logging.getLogger(__name__)

_SYSTEM = """You are a fraud-signal extractor. You do not decide actions.
Given the investigation context, answer the listed questions and return ONLY
a JSON object mapping each question id to its answer (score questions: a
float 0-1; noul/boolean questions: true/false). No prose, no markdown fences.
Do not invent transaction IDs, card IDs, or amounts that are not in CONTEXT."""


def _prompt(context: str) -> str:
    qs = "\n".join(f"- {qid} ({qtype}): {text}" for qid, qtype, text in QUESTIONS)
    return f"CONTEXT:\n{context}\n\nQUESTIONS:\n{qs}\n\nReturn the JSON object now."


def _pattern_from_answers(answers: dict) -> Pattern:
    pattern_scores = {}
    for key, pattern in _PATTERN_SCORE_KEYS.items():
        try:
            pattern_scores[pattern] = float(answers.get(key) or 0)
        except (TypeError, ValueError):
            pattern_scores[pattern] = 0.0
    dominant_pattern, top_score = max(pattern_scores.items(), key=lambda kv: kv[1])
    if top_score < 0.35:
        if answers.get("pattern_undocumented_signal"):
            return Pattern.undocumented
        return Pattern.none
    return dominant_pattern


def _from_hints(prior: Signals) -> Signals:
    return prior.model_copy()


def assess(context: str, prior: Signals) -> tuple[Signals, int]:
    if not llm_configured():
        return _from_hints(prior), 0

    try:
        answers, tokens = complete_json(_SYSTEM, _prompt(context), max_tokens=1000)
    except (LLMError, Exception) as exc:
        log.warning("Signal LLM failed, using graph heuristics: %s", exc)
        return _from_hints(prior), 0

    try:
        pattern = _pattern_from_answers(answers)
        fraud_p = float(answers.get("fraud_probability", prior.fraud_probability))
        sufficiency = float(answers.get("evidence_sufficiency", prior.evidence_sufficiency))
    except (TypeError, ValueError, KeyError):
        return _from_hints(prior), 0

    shared_origin = bool(answers.get("shared_origin", False))
    signals = prior.model_copy(update=dict(
        fraud_probability=max(0.0, min(1.0, fraud_p)),
        pattern=pattern,
        evidence_sufficiency=max(0.0, min(1.0, sufficiency)),
        shared_device_flag=prior.shared_device_flag or shared_origin,
        shared_region_flag=prior.shared_region_flag,
        shared_email_flag=prior.shared_email_flag,
        dispute_matches_recurring=bool(answers.get("recurring_match", prior.dispute_matches_recurring)),
        undocumented_coordinated=bool(answers.get("pattern_undocumented_signal", False)),
        single_signal_only=bool(answers.get("single_signal_only", prior.single_signal_only)),
    ))
    return signals, tokens
