"""
Jev (TypeSafe) client — plan.md §3's question catalog, fanned out in one
call against the current GraphRAG context. Never returns an action —
only the typed judgments the policy engine consumes via `Signals`.

If the Jev SDK/API is unreachable or errors, raise JevUnavailable so the
orchestrator falls back to llm_fallback.assess() behind the identical
`Signals` interface. Keep this file as the ONLY place that imports the
Jev SDK, so swapping/removing it later touches one file.
"""
from __future__ import annotations

from .state import Pattern, Signals

# TODO: from jev import Client  (fill in once the TypeSafe SDK/API is pinned down)


class JevUnavailable(Exception):
    pass


QUESTIONS = [
    # id, type, prompt — see plan.md §3 for what each feeds
    ("pattern_card_testing", "score", "Does the transaction sequence match card testing (3+ small online auths in <1h, then a larger purchase)?"),
    ("pattern_cnp", "score", "Does this match card-not-present fraud: amounts/products inconsistent with the cardholder's history?"),
    ("pattern_cnp_new_device", "score", "Same as card-not-present fraud, and the identity record marks the device as New for this account?"),
    ("pattern_out_of_region", "score", "Card-present purchases in a billing region the cardholder has no history in, while normal activity continues at home?"),
    ("pattern_account_takeover", "score", "Mixed-channel activity with device/match-flag anomalies suggesting stolen credentials rather than a stolen number?"),
    ("pattern_undocumented_signal", "noul", "Does the activity show coordinated or repeated abuse that fits none of the five known patterns?"),
    ("fraud_probability", "score", "Given all retrieved evidence, how likely is the flagged activity fraud?"),
    ("evidence_sufficiency", "score", "Is currently available evidence enough to defensibly stop investigating?"),
    ("shared_origin", "noul", "Do two or more cards share this device profile, billing region, or recipient email in this time window?"),
    ("recurring_match", "noul", "Does the disputed charge match the customer's own recurring pattern (same merchant, same amount, monthly)?"),
    ("single_signal_only", "noul", "Does this case rest on exactly one signal (e.g. the risk score alone, with no corroborating evidence)?"),
]

_PATTERN_SCORE_KEYS = {
    "pattern_card_testing": Pattern.card_testing,
    "pattern_cnp": Pattern.card_not_present_fraud,
    "pattern_cnp_new_device": Pattern.card_not_present_new_device,
    "pattern_out_of_region": Pattern.out_of_region_use,
    "pattern_account_takeover": Pattern.account_takeover,
}


def assess(context: str, prior: Signals) -> tuple[Signals, int]:
    """
    Fans out QUESTIONS against `context` in one Jev call.
    Returns (Signals, tokens_used). Raises JevUnavailable on any client error.
    """
    raise JevUnavailable("Jev client not yet wired — implement against the TypeSafe SDK, "
                          "then remove this raise so the orchestrator stops falling back.")

    # -- Reference shape of what this should do once the SDK is wired: -----
    # answers = jev_client_sdk.evaluate(questions=QUESTIONS, context=context)
    # pattern_scores = {v: answers[k] for k, v in _PATTERN_SCORE_KEYS.items()}
    # dominant_pattern, top_score = max(pattern_scores.items(), key=lambda kv: kv[1])
    # if top_score < 0.35 and answers["pattern_undocumented_signal"]:
    #     dominant_pattern = Pattern.undocumented
    # elif top_score < 0.35:
    #     dominant_pattern = Pattern.none
    #
    # signals = prior.model_copy(update=dict(
    #     fraud_probability=answers["fraud_probability"],
    #     pattern=dominant_pattern,
    #     evidence_sufficiency=answers["evidence_sufficiency"],
    #     shared_device_flag=answers["shared_origin"],  # refine per-flag if Jev is split further
    #     dispute_matches_recurring=answers["recurring_match"],
    #     undocumented_coordinated=answers["pattern_undocumented_signal"],
    #     single_signal_only=answers["single_signal_only"],
    # ))
    # return signals, answers.token_usage
