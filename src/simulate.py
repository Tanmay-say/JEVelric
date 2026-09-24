"""
EVIDENCE_REQUEST + SIMULATE_RESPONSE nodes (plan.md §4).

README §5: "Customer and analyst replies are not provided... Simulate them
in your own system and state the assumption you made." The simulation rule
must be simple, deterministic, and stated once here — not re-derived per
case by an LLM — so every run is reproducible and the assumption is
defensible when read back from evidence_requests[].assumed_response.
"""
from __future__ import annotations

from .state import (
    CustomerResponse, EvidenceRequest, EvidenceRequestType, InvestigationState, TriggerType,
)

# Tune this threshold against the hand-run case (plan.md §7 step 3).
_STRONG_EVIDENCE_THRESHOLD = 0.65
_WEAK_EVIDENCE_THRESHOLD = 0.40


def build_request(state: InvestigationState) -> EvidenceRequest:
    if state.trigger_type == TriggerType.analyst_request:
        req_type = EvidenceRequestType.analyst_info
        assumption = "Analyst confirms the related activity flagged in the trigger is part of the same episode."
    elif state.signals.fraud_probability >= _STRONG_EVIDENCE_THRESHOLD:
        # Evidence already points strongly one way — ask the customer directly.
        req_type = EvidenceRequestType.customer_validation
        assumption = "Customer states they did not make these purchases and still has the card."
    else:
        # Weak/ambiguous — step-up auth is less intrusive and still resolves an active-session question.
        req_type = EvidenceRequestType.step_up_auth
        assumption = "Step-up authentication fails, consistent with the account being compromised."

    return EvidenceRequest(
        type=req_type,
        asked_after_step=state.round,
        assumed_response=assumption,
    )


def simulate_response(state: InvestigationState) -> CustomerResponse:
    """
    Deterministic rule (state it once, apply uniformly — README §5):
    - Strong existing evidence (>= _STRONG_EVIDENCE_THRESHOLD)      -> denied
    - Evidence points toward the customer's own known pattern       -> confirmed
      (i.e. dispute_matches_recurring already true from round 0)
    - Otherwise (genuinely ambiguous, evidence in the weak band)    -> no_reply
    """
    s = state.signals
    if s.dispute_matches_recurring:
        return CustomerResponse.confirmed
    if s.fraud_probability >= _STRONG_EVIDENCE_THRESHOLD:
        return CustomerResponse.denied
    if s.fraud_probability <= _WEAK_EVIDENCE_THRESHOLD:
        return CustomerResponse.no_reply
    # mid-band: treat as denied if the evidence already carries a shared-origin
    # signal (device/region/email), else no_reply
    return CustomerResponse.denied if (s.shared_device_flag or s.shared_region_flag or s.shared_email_flag) \
        else CustomerResponse.no_reply
