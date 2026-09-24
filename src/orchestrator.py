"""
Orchestrator — LangGraph implementation of plan.md §4 (state machine) and
§6 (valid transitions). Node bodies call into graph_client / graphrag /
jev_client (or llm_fallback) / policy_engine / simulate / validate; this
file only wires the control flow, it contains no decision logic itself.

MAX_EVIDENCE_ROUNDS caps the loop per README's own worked example
(one evidence request, then settle) — see plan.md §4 "Loop cap".
"""
from __future__ import annotations

from langgraph.graph import StateGraph, END

from .state import Action, InvestigationState, CustomerResponse, Pattern, RecommendedAction
from . import graph_client, graphrag, jev_client, llm_fallback, policy_engine, simulate, validate
from .policy_engine import route_for

MAX_EVIDENCE_ROUNDS = 2


# --------------------------------------------------------------------------
# Nodes
# --------------------------------------------------------------------------

def _apply_graph_hints(state: InvestigationState) -> None:
    hints = state.graph_evidence.get("_hints") or {}
    if not hints:
        return
    try:
        pattern = Pattern(hints.get("pattern") or "none")
    except ValueError:
        pattern = Pattern.none
    s = state.signals
    s.exposure_usd = float(hints.get("exposure_usd") or s.exposure_usd)
    s.shared_device_flag = bool(hints.get("shared_device_flag"))
    s.shared_region_flag = bool(hints.get("shared_region_flag"))
    s.shared_email_flag = bool(hints.get("shared_email_flag"))
    s.confirmed_cards_count = int(hints.get("confirmed_cards_count") or 0)
    s.evidence_count = max(s.evidence_count, int(hints.get("evidence_count") or 1))
    if s.fraud_probability == 0.0 and s.pattern == Pattern.none:
        s.fraud_probability = float(hints.get("fraud_probability") or 0)
        s.pattern = pattern
        s.single_signal_only = bool(hints.get("single_signal_only", True))
        s.evidence_sufficiency = float(hints.get("evidence_sufficiency") or 0)
        s.undocumented_coordinated = bool(hints.get("undocumented_coordinated"))
        s.dispute_matches_recurring = bool(hints.get("dispute_matches_recurring"))


def node_graph_retrieval(state: InvestigationState) -> InvestigationState:
    state.graph_evidence = graph_client.retrieve_all(
        card_id=state.card_id,
        customer_id=state.customer_id,
        flagged_txn_id=state.flagged_txn_id,
    )
    _apply_graph_hints(state)
    state.tool_calls += graph_client.LAST_CALL_COUNT
    return state


def node_graphrag_context(state: InvestigationState) -> InvestigationState:
    state.graphrag_context = graphrag.assemble_context(state.graph_evidence, round_=state.round)
    return state


def node_jev_assess(state: InvestigationState) -> InvestigationState:
    try:
        signals, tokens = jev_client.assess(state.graphrag_context, prior=state.signals)
    except jev_client.JevUnavailable:
        signals, tokens = llm_fallback.assess(state.graphrag_context, prior=state.signals)
    state.signals = signals
    hints = state.graph_evidence.get("_hints") or {}
    if hints:
        state.signals.exposure_usd = float(hints.get("exposure_usd") or state.signals.exposure_usd)
        state.signals.shared_device_flag = state.signals.shared_device_flag or bool(hints.get("shared_device_flag"))
        state.signals.shared_region_flag = state.signals.shared_region_flag or bool(hints.get("shared_region_flag"))
        state.signals.shared_email_flag = state.signals.shared_email_flag or bool(hints.get("shared_email_flag"))
        state.signals.evidence_count = max(
            state.signals.evidence_count, int(hints.get("evidence_count") or 1)
        )
    state.tokens += tokens
    return state


def node_stop_check(state: InvestigationState) -> InvestigationState:
    stopped, reason = policy_engine.should_stop(state.signals)
    if stopped:
        state.stop_reason = reason
    return state


def node_policy_initial(state: InvestigationState) -> InvestigationState:
    actions = policy_engine.determine_actions(state.signals, verdict_uncertain=_is_uncertain(state))
    state.next_best_actions.initial = actions
    return state


def node_evidence_request(state: InvestigationState) -> InvestigationState:
    req = simulate.build_request(state)  # decides type (customer_validation/step_up_auth/analyst_info)
    state.evidence_requests.append(req)
    return state


def node_simulate_response(state: InvestigationState) -> InvestigationState:
    response: CustomerResponse = simulate.simulate_response(state)
    state.signals.customer_response = response
    state.signals.evidence_count += 1
    state.round += 1
    return state


def node_policy_final(state: InvestigationState) -> InvestigationState:
    actions = policy_engine.determine_actions(state.signals, verdict_uncertain=_is_uncertain(state))
    if state.evidence_requests:
        state.next_best_actions.final = actions
    else:
        if not state.next_best_actions.initial:
            state.next_best_actions.initial = actions
        state.next_best_actions.final = list(state.next_best_actions.initial)
    state.next_best_actions.what_changed = _diff_summary(state)
    if not state.stop_reason:
        state.stop_reason = "Evidence round cap reached; recommendation reflects best available evidence."
    return state


def node_sar_decision(state: InvestigationState) -> InvestigationState:
    verdict = _verdict_str(state)
    if verdict == "legitimate":
        closed = [a for a in state.next_best_actions.final if a.action == Action.CLOSE_NO_FRAUD]
        if closed:
            state.next_best_actions.final = closed
        else:
            state.next_best_actions.final = [
                a for a in state.next_best_actions.final if a.action != Action.FILE_REPORT
            ]
        if not state.evidence_requests:
            state.next_best_actions.initial = list(state.next_best_actions.final)
        state.sar = graphrag.build_sar(state, False, "3a: not filed — verdict is legitimate")
        return state

    file_flag, reason = policy_engine.file_sar(state.signals, verdict)
    has_report = any(a.action == Action.FILE_REPORT for a in state.next_best_actions.final)
    if has_report:
        file_flag = True
        if "not filed" in reason or not reason.startswith("3a:"):
            reason = "3a: FILE_REPORT recommended under policy (R2/R6/R9)"
    elif file_flag:
        state.next_best_actions.final = list(state.next_best_actions.final) + [
            RecommendedAction(
                action=Action.FILE_REPORT,
                route=route_for(Action.FILE_REPORT, state.signals.exposure_usd),
                reason=reason,
            )
        ]
    if not state.evidence_requests:
        state.next_best_actions.initial = list(state.next_best_actions.final)
    state.sar = graphrag.build_sar(state, file_flag, reason)
    return state


def node_case_assembly(state: InvestigationState) -> InvestigationState:
    state.case = graphrag.build_case(state)  # LLM writes summary/pattern_description; rest from graph_evidence/signals
    return state


def node_graph_write(state: InvestigationState) -> InvestigationState:
    if state.case is not None:
        state.case._primary_card_id = state.card_id
    graph_case_id = graph_client.write_case(state.case, state.case_id, state.customer_id)
    state.case.written_to_graph = bool(graph_case_id)
    state.case.graph_case_id = graph_case_id or ""
    state.tool_calls += 1
    return state


def _ids_from_evidence(evidence: dict) -> set[str]:
    ids: set[str] = set()
    cw = evidence.get("card_window") or {}
    ids.update(str(x) for x in (cw.get("affected_txn_ids") or []))
    for key in ("card_window", "device_neighbors", "region_cluster", "email_cluster", "customer_history"):
        for txn in (evidence.get(key) or {}).get("txns") or []:
            ids.update(str(txn[k]) for k in ("txn_id", "card_id", "customer_id", "device_profile") if txn.get(k))
    for key in ("device_neighbors", "region_cluster", "email_cluster", "customer_history"):
        ids.update(str(x) for x in ((evidence.get(key) or {}).get("card_ids") or []))
    for m in ((evidence.get("closed_case_similarity") or {}).get("matches") or []):
        if m.get("case_id"):
            ids.add(str(m["case_id"]))
    return {i for i in ids if i}


def _autofix_answer(state: InvestigationState, known_ids: set[str]) -> None:
    case = state.case
    if case is None:
        return
    case.affected_txn_ids = [i for i in case.affected_txn_ids if i in known_ids]
    if case.first_suspicious_txn_id not in known_ids:
        case.first_suspicious_txn_id = case.affected_txn_ids[0] if case.affected_txn_ids else ""
    case.connected_card_ids = [i for i in case.connected_card_ids if i in known_ids]
    case.similar_prior_cases = [i for i in case.similar_prior_cases if i in known_ids]
    if case.verdict.value == "legitimate":
        case.affected_txn_ids = []
        case.first_suspicious_txn_id = ""
        case.exposure_usd = 0
        if state.sar:
            state.sar.file = False
            state.sar.narrative = ""
            state.sar.subjects = []
            state.sar.total_amount_usd = 0
            state.sar.activity_dates = []
        state.next_best_actions.final = [
            a for a in state.next_best_actions.final if a.action != Action.FILE_REPORT
        ]
        if not state.evidence_requests:
            state.next_best_actions.initial = list(state.next_best_actions.final)
    if state.sar and not state.sar.file:
        state.sar.narrative = ""
        state.sar.subjects = []
        state.sar.total_amount_usd = 0
        state.sar.activity_dates = []
        state.next_best_actions.final = [
            a for a in state.next_best_actions.final if a.action != Action.FILE_REPORT
        ]
        if not state.evidence_requests:
            state.next_best_actions.initial = list(state.next_best_actions.final)
    elif state.sar and state.sar.file:
        if not any(a.action == Action.FILE_REPORT for a in state.next_best_actions.final):
            state.next_best_actions.final = list(state.next_best_actions.final) + [
                RecommendedAction(
                    action=Action.FILE_REPORT,
                    route=route_for(Action.FILE_REPORT, state.signals.exposure_usd),
                    reason=state.sar.reason,
                )
            ]
            if not state.evidence_requests:
                state.next_best_actions.initial = list(state.next_best_actions.final)
        if not state.sar.narrative:
            state.sar.narrative = (
                f"SAR for {state.case_id}: customer {state.customer_id}, card {state.card_id}, "
                f"flagged transaction {state.flagged_txn_id}, exposure ${state.signals.exposure_usd:.2f}."
            )


def node_answer_validate(state: InvestigationState) -> InvestigationState:
    known_ids = graph_client.known_ids_for(state.card_id, state.customer_id) | _ids_from_evidence(state.graph_evidence)
    known_ids.add(state.card_id)
    known_ids.add(state.customer_id)
    known_ids.add(str(state.flagged_txn_id))
    problems = validate.validate_answer(state.to_answer(), known_ids)
    attempts = int(state.graph_evidence.get("_validation_attempts") or 0) + 1
    state.graph_evidence["_validation_attempts"] = attempts
    if problems:
        _autofix_answer(state, known_ids)
        problems = validate.validate_answer(state.to_answer(), known_ids)
    # Never loop forever: emit after autofix even if residual issues remain.
    state.graph_evidence["_validation_problems"] = problems
    return state


def node_answer_emit(state: InvestigationState) -> InvestigationState:
    from .config import ANSWERS_DIR
    ANSWERS_DIR.mkdir(parents=True, exist_ok=True)
    out = ANSWERS_DIR / f"{state.case_id}.json"
    out.write_text(state.to_answer().model_dump_json(indent=2), encoding="utf-8")
    return state


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _is_uncertain(state: InvestigationState) -> bool:
    return 0.15 < state.signals.fraud_probability < 0.85


def _verdict_str(state: InvestigationState) -> str:
    if state.signals.customer_response == CustomerResponse.confirmed:
        return "legitimate"
    if state.signals.fraud_probability >= 0.70:
        return "fraud"
    if state.signals.fraud_probability <= 0.15:
        return "legitimate"
    return "uncertain"


def _diff_summary(state: InvestigationState) -> str:
    if not state.evidence_requests:
        return "nothing"
    before = {a.action for a in state.next_best_actions.initial}
    after = {a.action for a in state.next_best_actions.final}
    if before == after:
        return "nothing"
    added = after - before
    removed = before - after
    parts = []
    if added:
        parts.append(f"added {[a.value for a in added]}")
    if removed:
        parts.append(f"removed {[a.value for a in removed]}")
    return f"{state.signals.customer_response.value.replace('_', ' ')} response " + " and ".join(parts)


# --------------------------------------------------------------------------
# Conditional edges (plan.md §6)
# --------------------------------------------------------------------------

def route_after_stop_check(state: InvestigationState) -> str:
    if state.stop_reason:
        return "policy_final"
    return "policy_initial" if state.round == 0 else "policy_final"


def route_after_policy_initial(state: InvestigationState) -> str:
    needs_evidence = (
        any(a.reason.startswith("R1") for a in state.next_best_actions.initial)
        or state.signals.evidence_sufficiency < 0.6
    )
    if needs_evidence and state.round < MAX_EVIDENCE_ROUNDS:
        return "evidence_request"
    state.next_best_actions.final = state.next_best_actions.initial
    if not state.stop_reason:
        state.stop_reason = "Initial evidence was sufficient to recommend actions without a further request."
    return "sar_decision"


def route_after_jev_reassess(state: InvestigationState) -> str:
    stopped, reason = policy_engine.should_stop(state.signals)
    if stopped:
        state.stop_reason = reason
        return "policy_final"
    if state.round >= MAX_EVIDENCE_ROUNDS:
        return "policy_final"
    return "policy_final"  # round cap is 2; a 3rd fan-out is not spec'd — extend here if desired


def route_after_validate(state: InvestigationState) -> str:
    problems = state.graph_evidence.get("_validation_problems", [])
    attempts = int(state.graph_evidence.get("_validation_attempts") or 0)
    if problems and attempts < 2:
        return "case_assembly"
    if problems:
        raise ValueError("Answer validation failed after repair: " + "; ".join(problems))
    return "answer_emit"


# --------------------------------------------------------------------------
# Graph assembly
# --------------------------------------------------------------------------

def build_graph():
    g = StateGraph(InvestigationState)

    g.add_node("graph_retrieval", node_graph_retrieval)
    g.add_node("graphrag_context", node_graphrag_context)
    g.add_node("jev_assess", node_jev_assess)
    g.add_node("stop_check", node_stop_check)
    g.add_node("policy_initial", node_policy_initial)
    g.add_node("evidence_request", node_evidence_request)
    g.add_node("simulate_response", node_simulate_response)
    g.add_node("policy_final", node_policy_final)
    g.add_node("sar_decision", node_sar_decision)
    g.add_node("case_assembly", node_case_assembly)
    g.add_node("graph_write", node_graph_write)
    g.add_node("answer_validate", node_answer_validate)
    g.add_node("answer_emit", node_answer_emit)

    g.set_entry_point("graph_retrieval")
    g.add_edge("graph_retrieval", "graphrag_context")
    g.add_edge("graphrag_context", "jev_assess")
    g.add_edge("jev_assess", "stop_check")

    g.add_conditional_edges("stop_check", route_after_stop_check, {
        "policy_initial": "policy_initial",
        "policy_final": "policy_final",
    })
    g.add_conditional_edges("policy_initial", route_after_policy_initial, {
        "evidence_request": "evidence_request",
        "sar_decision": "sar_decision",
    })
    g.add_edge("evidence_request", "simulate_response")
    g.add_edge("simulate_response", "graphrag_context")  # loop back, round += 1 already applied

    # after the loop settles (routed via stop_check on round >= 1), policy_final -> sar_decision
    g.add_edge("policy_final", "sar_decision")
    g.add_edge("sar_decision", "case_assembly")
    g.add_edge("case_assembly", "graph_write")
    g.add_edge("graph_write", "answer_validate")
    g.add_conditional_edges("answer_validate", route_after_validate, {
        "case_assembly": "case_assembly",
        "answer_emit": "answer_emit",
    })
    g.add_edge("answer_emit", END)

    return g.compile()
