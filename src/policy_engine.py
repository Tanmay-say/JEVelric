"""
Deterministic policy engine — README "Fraud Policy" v1.0, rules R1-R10.

Pure functions only. No LLM, no Jev, no network calls. This module is the
audit trail: every action this returns carries a `reason` string that cites
the exact rule that produced it, and every value it reads comes from
`Signals` (populated upstream by graph retrieval + Jev/fallback).

Test this in isolation (tests/test_policy_engine.py) against synthetic
Signals before wiring it into the orchestrator.
"""
from __future__ import annotations

from .state import Action, ApprovalRoute, RecommendedAction, Signals, Pattern


# --------------------------------------------------------------------------
# Approval routing (README §2) — applied to whatever the rules below emit.
# --------------------------------------------------------------------------

_AUTO_ACTIONS = {
    Action.ALLOW_TRANSACTION, Action.MONITOR_CARD, Action.MONITOR_CONNECTED_CARDS,
    Action.WARN_CUSTOMER, Action.VERIFY_WITH_CUSTOMER, Action.STEP_UP_AUTH,
    Action.GENERATE_REPORT, Action.CREATE_CASE, Action.ESCALATE_TO_ANALYST,
    Action.CLOSE_NO_FRAUD,
}


def route_for(action: Action, exposure_usd: float) -> ApprovalRoute:
    if action in _AUTO_ACTIONS:
        return ApprovalRoute.auto
    if action == Action.DECLINE_TRANSACTION:
        return ApprovalRoute.L1
    if action == Action.BLOCK_CARD:
        return ApprovalRoute.L1 if exposure_usd <= 2500 else ApprovalRoute.L2
    if action == Action.BLOCK_ALL_CARDS:
        return ApprovalRoute.L2
    if action == Action.FILE_REPORT:
        return ApprovalRoute.L2
    raise ValueError(f"No route defined for action {action}")


def _rec(action: Action, reason: str, exposure_usd: float) -> RecommendedAction:
    return RecommendedAction(action=action, route=route_for(action, exposure_usd), reason=reason)


# --------------------------------------------------------------------------
# R1-R10, each returning [] if it doesn't fire.
# --------------------------------------------------------------------------

def _r1(s: Signals) -> list[RecommendedAction]:
    # R1 is a "before you know more" rule: once a customer/analyst response
    # has come back (R2/R3/R4 territory), it no longer applies — otherwise
    # it fires alongside those rules and proposes contradictory actions.
    if s.customer_response.value != "none_requested":
        return []
    if s.single_signal_only and s.fraud_probability < 0.70:
        # STEP_UP_AUTH preferred when the trigger implies an active session;
        # VERIFY_WITH_CUSTOMER otherwise. Caller may override via context.
        return [_rec(Action.VERIFY_WITH_CUSTOMER, "R1: single weak signal, probability below 0.70", s.exposure_usd)]
    return []


def _r2(s: Signals) -> list[RecommendedAction]:
    if s.customer_response.value == "denied":
        out = [
            _rec(Action.BLOCK_CARD, "R2: customer denied the transaction", s.exposure_usd),
            _rec(Action.CREATE_CASE, "R2: customer denied the transaction", s.exposure_usd),
        ]
        if s.exposure_usd > 1000 or s.shared_device_flag or s.shared_region_flag or s.shared_email_flag:
            out.append(_rec(Action.FILE_REPORT,
                             "R2: exposure exceeds $1,000 or activity connects to a shared origin",
                             s.exposure_usd))
        return out
    return []


def _r3(s: Signals) -> list[RecommendedAction]:
    if s.customer_response.value == "confirmed":
        return [_rec(Action.CLOSE_NO_FRAUD, "R3: customer confirmed the transaction", s.exposure_usd)]
    return []


def _r4(s: Signals) -> list[RecommendedAction]:
    if s.customer_response.value == "no_reply":
        out = [
            _rec(Action.MONITOR_CARD, "R4: no reply within 24 hours", s.exposure_usd),
            _rec(Action.DECLINE_TRANSACTION, "R4: no reply within 24 hours, pending authorization", s.exposure_usd),
        ]
        if s.exposure_usd > 500:
            out.append(_rec(Action.ESCALATE_TO_ANALYST, "R4: no reply and exposure exceeds $500", s.exposure_usd))
        return out
    return []


def _r5(s: Signals) -> list[RecommendedAction]:
    if s.pattern == Pattern.card_testing:
        out = [
            _rec(Action.DECLINE_TRANSACTION, "R5: card testing sequence observed", s.exposure_usd),
            _rec(Action.STEP_UP_AUTH, "R5: card testing sequence observed", s.exposure_usd),
        ]
        # Caller sets a cleared_over_100 flag into context if applicable; kept
        # simple here — extend Signals with `cleared_purchase_over_100: bool`
        # if you need this sub-branch distinguished from the base R5 case.
        return out
    return []


def _r6(s: Signals) -> list[RecommendedAction]:
    if s.shared_device_flag or s.shared_region_flag or s.shared_email_flag:
        shared = []
        if s.shared_device_flag:
            shared.append("device profile")
        if s.shared_region_flag:
            shared.append("billing region")
        if s.shared_email_flag:
            shared.append("recipient email")
        reason = f"R6: shared {', '.join(shared)} across cards"
        return [
            _rec(Action.CREATE_CASE, reason, s.exposure_usd),
            _rec(Action.FILE_REPORT, reason, s.exposure_usd),
            _rec(Action.MONITOR_CONNECTED_CARDS, reason, s.exposure_usd),
        ]
    return []


def _r7(s: Signals) -> list[RecommendedAction]:
    if s.dispute_matches_recurring:
        return [
            _rec(Action.CREATE_CASE, "R7: dispute matches customer's own recurring pattern", s.exposure_usd),
            _rec(Action.VERIFY_WITH_CUSTOMER, "R7: dispute matches customer's own recurring pattern", s.exposure_usd),
            _rec(Action.WARN_CUSTOMER, "R7: dispute matches customer's own recurring pattern", s.exposure_usd),
        ]
    return []


def _r8(s: Signals, verdict_uncertain: bool) -> list[RecommendedAction]:
    if verdict_uncertain and s.exposure_usd > 500:
        return [_rec(Action.ESCALATE_TO_ANALYST, "R8: uncertain verdict with exposure over $500", s.exposure_usd)]
    return []


def _r9(s: Signals) -> list[RecommendedAction]:
    if s.pattern == Pattern.undocumented and s.undocumented_coordinated:
        reason = "R9: undocumented pattern showing coordinated/repeated abuse"
        return [
            _rec(Action.CREATE_CASE, reason, s.exposure_usd),
            _rec(Action.FILE_REPORT, reason, s.exposure_usd),
            _rec(Action.ESCALATE_TO_ANALYST, reason, s.exposure_usd),
        ]
    return []


def _r10_guard(actions: list[RecommendedAction], s: Signals) -> list[RecommendedAction]:
    """R10: never BLOCK_ALL_CARDS unless >=2 confirmed-fraud cards, or credentials confirmed compromised."""
    if s.confirmed_cards_count < 2:
        actions = [a for a in actions if a.action != Action.BLOCK_ALL_CARDS]
    return actions


# --------------------------------------------------------------------------
# Public entrypoint
# --------------------------------------------------------------------------

_ACTION_ORDER = [
    Action.DECLINE_TRANSACTION, Action.BLOCK_CARD, Action.BLOCK_ALL_CARDS,
    Action.ALLOW_TRANSACTION, Action.STEP_UP_AUTH, Action.VERIFY_WITH_CUSTOMER,
    Action.MONITOR_CARD, Action.MONITOR_CONNECTED_CARDS, Action.WARN_CUSTOMER,
    Action.CREATE_CASE, Action.FILE_REPORT, Action.ESCALATE_TO_ANALYST,
    Action.GENERATE_REPORT, Action.CLOSE_NO_FRAUD,
]


def determine_actions(signals: Signals, verdict_uncertain: bool = False) -> list[RecommendedAction]:
    """
    Runs all applicable rules, unions the results, dedupes by action name
    (first reason wins), and orders by what happens first.
    """
    r3 = _r3(signals)
    if r3:
        return r3

    fired: list[RecommendedAction] = []
    for rule_fn in (_r1, _r2, _r4, _r5, _r6, _r7):
        fired.extend(rule_fn(signals))
    fired.extend(_r8(signals, verdict_uncertain))
    fired.extend(_r9(signals))
    fired = _r10_guard(fired, signals)

    seen: dict[Action, RecommendedAction] = {}
    for rec in fired:
        seen.setdefault(rec.action, rec)

    return sorted(seen.values(), key=lambda r: _ACTION_ORDER.index(r.action)
                  if r.action in _ACTION_ORDER else len(_ACTION_ORDER))


def file_sar(signals: Signals, verdict: str) -> tuple[bool, str]:
    """README §3a SAR gate. Returns (file: bool, reason: str)."""
    confirmed_or_strong = verdict == "fraud" or signals.fraud_probability >= 0.70
    trigger = (
        signals.exposure_usd > 1000
        or signals.shared_device_flag or signals.shared_region_flag or signals.shared_email_flag
        or signals.pattern == Pattern.undocumented
    )
    if confirmed_or_strong and trigger:
        reasons = []
        if signals.exposure_usd > 1000:
            reasons.append("exposure exceeds $1,000")
        if signals.shared_device_flag or signals.shared_region_flag or signals.shared_email_flag:
            reasons.append("activity connects to a shared origin")
        if signals.pattern == Pattern.undocumented:
            reasons.append("pattern is undocumented/coordinated (R9)")
        return True, "3a: fraud confirmed/strongly suspected and " + "; ".join(reasons)
    return False, "3a: not filed — either not confirmed/strongly suspected, or no qualifying trigger present"


def should_stop(signals: Signals) -> tuple[bool, str]:
    """README §6 stopping condition."""
    if (signals.fraud_probability >= 0.85 or signals.fraud_probability <= 0.15) and signals.evidence_count >= 2:
        return True, "Fraud probability at or beyond the 0.85/0.15 threshold, supported by 2+ independent pieces of evidence."
    if signals.customer_response.value in ("denied", "confirmed"):
        return True, f"Verification response ({signals.customer_response.value}) settled the question."
    if signals.evidence_sufficiency >= 0.85:
        return True, "Further evidence is unlikely to change the decision (evidence_sufficiency >= 0.85)."
    return False, ""
