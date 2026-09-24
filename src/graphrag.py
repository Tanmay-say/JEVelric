"""
GraphRAG context assembly + prose synthesis (summary, pattern_description, SAR).
Verdict / probability / actions are never chosen here.
"""
from __future__ import annotations

from pathlib import Path

from .config import ROOT, llm_configured
from .llm import LLMError, complete_text
from .state import (
    Action,
    Case,
    CaseStatus,
    CustomerResponse,
    EvidenceItem,
    EvidenceSource,
    InvestigationState,
    Pattern,
    SAR,
    Verdict,
)

_POLICY = ROOT / "policy" / "fraud_policy.md"
_PATTERNS = ROOT / "policy" / "fraud_patterns.md"


def _read_capped(path: Path, n: int = 4000) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")[:n]


def assemble_context(graph_evidence: dict, round_: int) -> str:
    sections = [
        f"ROUND: {round_}",
        "KNOWN FRAUD PATTERNS:\n" + _read_capped(_PATTERNS),
        "POLICY EXCERPT:\n" + _read_capped(_POLICY, 2500),
        "GRAPH EVIDENCE (entity IDs must be copied verbatim, never invented):",
    ]
    cw = graph_evidence.get("card_window") or {}
    sections.append(
        "CARD WINDOW:\n"
        f"  txn_ids={cw.get('affected_txn_ids')}\n"
        f"  dates={cw.get('activity_dates')}\n"
        f"  exposure_usd={cw.get('exposure_usd')}\n"
        f"  txns={cw.get('txns')}"
    )
    dn = graph_evidence.get("device_neighbors") or {}
    sections.append(f"DEVICE NEIGHBORS: cards={dn.get('card_ids')} profiles={dn.get('device_profiles')}")
    rc = graph_evidence.get("region_cluster") or {}
    sections.append(f"REGION CLUSTER: region={rc.get('region')} cards={rc.get('card_ids')}")
    ec = graph_evidence.get("email_cluster") or {}
    sections.append(f"EMAIL CLUSTER: email={ec.get('email')} cards={ec.get('card_ids')}")
    hist = graph_evidence.get("customer_history") or {}
    sections.append(
        "CUSTOMER HISTORY:\n"
        f"  n={hist.get('n')} mean_amt={hist.get('mean_amt')} "
        f"regions={hist.get('regions')} products={hist.get('products')} "
        f"channels={hist.get('channels')} cards={hist.get('card_ids')}"
    )
    matches = (graph_evidence.get("closed_case_similarity") or {}).get("matches") or []
    if matches:
        lines = []
        for m in matches:
            lines.append(
                f"  {m.get('case_id')} pattern={m.get('pattern')} "
                f"outcome={m.get('outcome')} notes={m.get('notes')}"
            )
        sections.append("SIMILAR CLOSED CASES:\n" + "\n".join(lines))
    hints = graph_evidence.get("_hints") or {}
    if hints:
        sections.append(f"GRAPH HEURISTIC HINTS: {hints}")
    return "\n\n".join(sections)


def build_case(state: InvestigationState) -> Case:
    s = state.signals
    verdict = _verdict(state)
    status = _status(state, verdict)

    summary, extra_tokens = _llm_summary(state, verdict)
    state.tokens += extra_tokens
    pattern_description = ""
    if s.pattern == Pattern.undocumented:
        pattern_description, tok = _llm_pattern_description(state)
        state.tokens += tok

    ev = state.graph_evidence
    cw = ev.get("card_window") or {}
    if verdict == Verdict.legitimate:
        affected: list[str] = []
        exposure = 0.0
    else:
        affected = [str(x) for x in (cw.get("affected_txn_ids") or [])]
        exposure = round(float(s.exposure_usd or cw.get("exposure_usd") or 0), 2)

    device_cards = list((ev.get("device_neighbors") or {}).get("card_ids") or [])
    email_cards = list((ev.get("email_cluster") or {}).get("card_ids") or [])
    region_cards = list((ev.get("region_cluster") or {}).get("card_ids") or [])
    connected_cards = []
    for src in (device_cards, email_cards[:5], region_cards[:5]):
        for c in src:
            if c and c != state.card_id and c not in connected_cards:
                connected_cards.append(c)
    connected_cards = connected_cards[:12]

    connected_devices = list((ev.get("device_neighbors") or {}).get("device_profiles") or [])
    similar_cases = [
        str(c["case_id"])
        for c in (ev.get("closed_case_similarity") or {}).get("matches") or []
        if c.get("case_id")
    ]

    return Case(
        status=status,
        verdict=verdict,
        fraud_probability=round(s.fraud_probability, 4),
        pattern=s.pattern,
        pattern_description=pattern_description,
        affected_txn_ids=affected,
        first_suspicious_txn_id=(affected[0] if affected else ""),
        connected_card_ids=sorted(set(connected_cards)),
        connected_device_profiles=connected_devices,
        exposure_usd=exposure,
        evidence=_build_evidence_list(state, affected),
        similar_prior_cases=similar_cases,
        summary=summary,
    )


def build_sar(state: InvestigationState, file_flag: bool, reason: str) -> SAR:
    if not file_flag:
        return SAR(file=False, reason=reason)
    narrative, tok = _llm_sar_narrative(state)
    state.tokens += tok
    ev = state.graph_evidence
    dates = list((ev.get("card_window") or {}).get("activity_dates") or [])
    dates = [d for d in dates if d]
    subjects = sorted({state.customer_id, state.card_id})
    return SAR(
        file=True,
        reason=reason,
        narrative=narrative,
        subjects=subjects,
        total_amount_usd=round(state.signals.exposure_usd, 2),
        activity_dates=dates[:2] if dates else [],
    )


def _build_evidence_list(state: InvestigationState, affected: list[str]) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    cw = state.graph_evidence.get("card_window") or {}
    if cw.get("affected_txn_ids"):
        items.append(EvidenceItem(
            claim=cw.get("claim_text") or "Transaction pattern observed on this card in the review window.",
            source=EvidenceSource.graph,
            ref=f"query:card_window(card_id={state.card_id})",
            entity_ids=list(affected or cw.get("affected_txn_ids") or []),
        ))
    dn = state.graph_evidence.get("device_neighbors") or {}
    if dn.get("card_ids"):
        items.append(EvidenceItem(
            claim="Device profile shared with other cards in the review window.",
            source=EvidenceSource.graph,
            ref=f"query:device_neighbors(txn_id={state.flagged_txn_id})",
            entity_ids=list(dn.get("card_ids") or [])[:12],
        ))
    matches = (state.graph_evidence.get("closed_case_similarity") or {}).get("matches") or []
    if matches:
        ids = [str(m["case_id"]) for m in matches if m.get("case_id")]
        items.append(EvidenceItem(
            claim="Similar closed investigations were retrieved from case history.",
            source=EvidenceSource.graph,
            ref="query:closed_case_similarity",
            entity_ids=ids,
        ))
    for i, req in enumerate(state.evidence_requests, start=1):
        items.append(EvidenceItem(
            claim=req.assumed_response,
            source=EvidenceSource.customer,
            ref=f"evidence_request:{i}",
            entity_ids=[],
        ))
    return items


def _verdict(state: InvestigationState) -> Verdict:
    if state.signals.customer_response == CustomerResponse.confirmed:
        return Verdict.legitimate
    if Action.CLOSE_NO_FRAUD in {a.action for a in state.next_best_actions.final}:
        return Verdict.legitimate
    if state.signals.fraud_probability >= 0.70:
        return Verdict.fraud
    if state.signals.fraud_probability <= 0.15:
        return Verdict.legitimate
    return Verdict.uncertain


def _status(state: InvestigationState, verdict: Verdict) -> CaseStatus:
    actions = {a.action for a in state.next_best_actions.final}
    if Action.ESCALATE_TO_ANALYST in actions and verdict != Verdict.legitimate:
        return CaseStatus.escalated
    if verdict == Verdict.fraud:
        return CaseStatus.closed_fraud
    if verdict == Verdict.legitimate:
        return CaseStatus.closed_legitimate
    return CaseStatus.open


def _fallback_summary(state: InvestigationState, verdict: Verdict) -> str:
    s = state.signals
    actions = ", ".join(a.action.value for a in state.next_best_actions.final) or "none"
    return (
        f"Case {state.case_id} on card {state.card_id} (customer {state.customer_id}) "
        f"was triggered by {state.trigger_type.value}: {state.trigger_text} "
        f"Flagged transaction {state.flagged_txn_id}. "
        f"Graph evidence supports pattern {s.pattern.value} with fraud probability "
        f"{s.fraud_probability:.2f} and exposure ${s.exposure_usd:.2f}. "
        f"Working verdict is {verdict.value}. Recommended actions: {actions}."
    )


def _llm_summary(state: InvestigationState, verdict: Verdict) -> tuple[str, int]:
    instruction = (
        "Write a 2-6 sentence analyst-readable summary of this fraud investigation. "
        "State the verdict, the pattern (if any), the key evidence, and the recommended action. "
        "Use only IDs and amounts present in CONTEXT. No preamble."
        f" The decided verdict is {verdict.value}; do not contradict it."
    )
    if not llm_configured():
        return _fallback_summary(state, verdict), 0
    try:
        text, tokens = complete_text(
            "You write case documentation from the given evidence only. Never invent IDs, amounts, or dates.",
            f"{instruction}\n\nCONTEXT:\n{state.graphrag_context}",
            max_tokens=600,
        )
        return text, tokens
    except LLMError:
        return _fallback_summary(state, verdict), 0


def _llm_pattern_description(state: InvestigationState) -> tuple[str, int]:
    instruction = (
        "In 2-3 sentences, describe the undocumented fraud pattern found: what it is, "
        "who it affects, and how it was found. Do not force it into a known category. "
        "Use only facts in CONTEXT."
    )
    if not llm_configured():
        return (
            "Activity on this account shows coordinated or repeated abuse that does not "
            "fit card testing, CNP, new-device CNP, out-of-region use, or account takeover.",
            0,
        )
    try:
        text, tokens = complete_text(
            "You write case documentation from evidence only. Never invent IDs.",
            f"{instruction}\n\nCONTEXT:\n{state.graphrag_context}",
            max_tokens=400,
        )
        return text or "Coordinated activity that does not match the five documented patterns.", tokens
    except LLMError:
        return (
            "Activity on this account shows coordinated or repeated abuse that does not "
            "fit card testing, CNP, new-device CNP, out-of-region use, or account takeover.",
            0,
        )


def _llm_sar_narrative(state: InvestigationState) -> tuple[str, int]:
    instruction = (
        "Write the Suspicious Activity Report narrative: 6-12 sentences covering who, what, "
        "when, where, how, and why the activity is suspicious. It must stand on its own. "
        "Use only IDs, dates, and amounts in CONTEXT."
    )
    if not llm_configured():
        s = state.signals
        cw = state.graph_evidence.get("card_window") or {}
        return (
            f"This SAR concerns customer {state.customer_id} and card {state.card_id}. "
            f"Transaction {state.flagged_txn_id} was reviewed after the following trigger: "
            f"{state.trigger_text} "
            f"During the review window the card showed transactions {cw.get('affected_txn_ids')} "
            f"with exposure ${s.exposure_usd:.2f}. "
            f"The activity is classified as {s.pattern.value} with fraud probability "
            f"{s.fraud_probability:.2f}. Shared-origin flags: device={s.shared_device_flag}, "
            f"region={s.shared_region_flag}, email={s.shared_email_flag}. "
            f"Recommended next actions are "
            f"{', '.join(a.action.value for a in state.next_best_actions.final)}. "
            f"This narrative is based solely on graph-retrieved records in the investigation dataset.",
            0,
        )
    try:
        text, tokens = complete_text(
            "You write FinCEN-style SAR narratives from evidence only. Never invent IDs.",
            f"{instruction}\n\nCONTEXT:\n{state.graphrag_context}",
            max_tokens=900,
        )
        return text, tokens
    except LLMError:
        s = state.signals
        cw = state.graph_evidence.get("card_window") or {}
        return (
            f"This SAR concerns customer {state.customer_id} and card {state.card_id}. "
            f"Transaction {state.flagged_txn_id} was reviewed after the following trigger: "
            f"{state.trigger_text} "
            f"During the review window the card showed transactions {cw.get('affected_txn_ids')} "
            f"with exposure ${s.exposure_usd:.2f}. "
            f"The activity is classified as {s.pattern.value} with fraud probability "
            f"{s.fraud_probability:.2f}. Shared-origin flags: device={s.shared_device_flag}, "
            f"region={s.shared_region_flag}, email={s.shared_email_flag}. "
            f"Recommended next actions are "
            f"{', '.join(a.action.value for a in state.next_best_actions.final)}. "
            f"This narrative is based solely on graph-retrieved records in the investigation dataset.",
            0,
        )
