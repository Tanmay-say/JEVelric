import pytest

from src.state import (
    Action,
    Answer,
    Case,
    CaseStatus,
    NextBestActions,
    RecommendedAction,
    ApprovalRoute,
    SAR,
    Verdict,
)
from src.validate import validate_answer


def make_answer(summary: str, sar_narrative: str = "", actions=None) -> Answer:
    return Answer(
        case_id="HHG-TEST",
        case=Case(
            status=CaseStatus.open,
            verdict=Verdict.uncertain,
            fraud_probability=0.5,
            pattern="none",
            summary=summary,
        ),
        next_best_actions=NextBestActions(final=actions or []),
        sar=SAR(file=False, reason="not filed", narrative=sar_narrative),
        stop_reason="test",
    )


@pytest.mark.parametrize(
    "summary,narrative",
    [
        ("Recommended action: VERIFY_WITH_CUSTOMER.", ""),
        ("No additional decision text.", "The card should be monitored."),
        ("The bank should decline this transaction.", ""),
    ],
)
def test_empty_final_actions_reject_action_language(summary, narrative):
    problems = validate_answer(make_answer(summary, narrative), set())
    assert any("action-like language" in problem for problem in problems)


def test_empty_final_actions_allow_summary_without_action_language():
    problems = validate_answer(make_answer("The evidence remains inconclusive."), set())
    assert not any("action-like language" in problem for problem in problems)


def test_action_language_allowed_when_policy_action_is_present():
    actions = [
        RecommendedAction(
            action=Action.VERIFY_WITH_CUSTOMER,
            route=ApprovalRoute.auto,
            reason="R1",
        )
    ]
    problems = validate_answer(
        make_answer("Recommended action: VERIFY_WITH_CUSTOMER.", actions=actions), set()
    )
    assert not any("action-like language" in problem for problem in problems)
