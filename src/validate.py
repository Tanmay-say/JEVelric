"""
ANSWER_VALIDATE (plan.md §4). Runs after CASE_ASSEMBLY, before ANSWER_EMIT.

Two kinds of checks:
1. Structural — the Pydantic model in state.py already enforces field
   names/types/enums; this module re-raises with clearer messages.
2. Cross-field / dataset checks that Pydantic can't express alone:
   - every ID mentioned anywhere exists in the graph ("made-up IDs score zero")
   - sar.file agrees with FILE_REPORT presence in next_best_actions.final
   - final == initial (by value) when evidence_requests is empty
   - sar defaults are correctly zeroed when file is false
   - pattern_description is non-empty iff pattern == undocumented
"""
from __future__ import annotations

import re

from .state import Answer, Action


class ValidationError(Exception):
    pass


_ACTION_LIKE_TEXT = re.compile(
    r"\b(?:BLOCK(?:_CARD|_ALL_CARDS)?|DECLINE_TRANSACTION|ESCALATE_TO_ANALYST|"
    r"MONITOR(?:_CARD|_CONNECTED_CARDS)?|VERIFY_WITH_CUSTOMER|STEP_UP_AUTH|"
    r"WARN_CUSTOMER|CREATE_CASE|FILE_REPORT|ALLOW_TRANSACTION|CLOSE_NO_FRAUD|"
    r"block(?:s|ed|ing)?|declin(?:e|ed|ing)|escalat(?:e|ed|ion|ing)|"
    r"monitor(?:s|ed|ing)?|verif(?:y|ies|ied|ication)|step[ -]+up(?: authentication)?|"
    r"warn(?:s|ed|ing)?|create(?:s|d)?\s+(?:a\s+)?case|"
    r"file(?:s|d|ing)?\s+(?:a\s+)?(?:sar|report)|"
    r"allow(?:s|ed|ing)?(?:\s+transaction)?|close[ -]+no[ -]+fraud|"
    r"close(?:s|d|ing)?\s+(?:the\s+)?case)\b",
    re.IGNORECASE,
)


def validate_answer(answer: Answer, known_ids: set[str]) -> list[str]:
    """Returns a list of problems (empty = valid). Never raises on content issues."""
    problems: list[str] = []

    # -- ID existence -------------------------------------------------
    referenced_ids = set(answer.case.affected_txn_ids) \
        | set(answer.case.connected_card_ids) \
        | set(answer.case.similar_prior_cases) \
        | ({answer.case.first_suspicious_txn_id} if answer.case.first_suspicious_txn_id else set())
    unknown = referenced_ids - known_ids
    if unknown:
        problems.append(f"IDs not found in dataset: {sorted(unknown)}")

    # Free-text synthesis may describe actions, but only policy output is
    # authoritative. An empty structured list must not be paired with prose
    # that recommends blocking, verification, escalation, or other actions.
    if not answer.next_best_actions.final:
        narrative_text = f"{answer.case.summary}\n{answer.sar.narrative}"
        if _ACTION_LIKE_TEXT.search(narrative_text):
            problems.append(
                "case.summary or sar.narrative references action-like language "
                "but next_best_actions.final is empty"
            )

    # -- SAR consistency -----------------------------------------------
    final_has_file_report = any(a.action == Action.FILE_REPORT for a in answer.next_best_actions.final)
    if answer.sar.file != final_has_file_report:
        problems.append(
            f"sar.file={answer.sar.file} but FILE_REPORT in next_best_actions.final={final_has_file_report}"
        )
    if not answer.sar.file:
        if answer.sar.narrative or answer.sar.subjects or answer.sar.total_amount_usd or answer.sar.activity_dates:
            problems.append("sar.file is false but narrative/subjects/total_amount_usd/activity_dates are non-empty")
    else:
        if not answer.sar.narrative:
            problems.append("sar.file is true but narrative is empty")

    # -- initial/final equality when no evidence was requested ---------
    if not answer.evidence_requests:
        if [a.model_dump() for a in answer.next_best_actions.initial] != \
           [a.model_dump() for a in answer.next_best_actions.final]:
            problems.append("no evidence_requests logged, but next_best_actions.final != .initial")

    # -- legitimate verdict constraints ---------------------------------
    if answer.case.verdict == "legitimate":
        if answer.case.affected_txn_ids or answer.case.exposure_usd != 0 or answer.sar.file:
            problems.append("verdict is legitimate but affected_txn_ids/exposure_usd/sar.file are not empty/zero")

    # -- undocumented pattern requires a description ---------------------
    if answer.case.pattern == "undocumented" and not answer.case.pattern_description.strip():
        problems.append("pattern is undocumented but pattern_description is empty")
    if answer.case.pattern != "undocumented" and answer.case.pattern_description.strip():
        problems.append("pattern_description should be '' when pattern != undocumented")

    return problems
