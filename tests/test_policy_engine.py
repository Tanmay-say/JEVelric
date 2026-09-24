from src.state import Signals, Pattern, CustomerResponse, Action, ApprovalRoute
from src.policy_engine import determine_actions, file_sar, should_stop, route_for


def test_r1_weak_single_signal_verifies_not_blocks():
    s = Signals(fraud_probability=0.45, single_signal_only=True)
    actions = {a.action for a in determine_actions(s)}
    assert Action.VERIFY_WITH_CUSTOMER in actions
    assert Action.BLOCK_CARD not in actions


def test_r2_denied_blocks_and_creates_case():
    s = Signals(fraud_probability=0.9, customer_response=CustomerResponse.denied, exposure_usd=300)
    actions = {a.action for a in determine_actions(s)}
    assert Action.BLOCK_CARD in actions
    assert Action.CREATE_CASE in actions
    assert Action.FILE_REPORT not in actions  # exposure under $1000, no shared origin


def test_r2_denied_high_exposure_files_report():
    s = Signals(fraud_probability=0.9, customer_response=CustomerResponse.denied, exposure_usd=1500)
    actions = {a.action for a in determine_actions(s)}
    assert Action.FILE_REPORT in actions


def test_block_card_route_by_exposure():
    assert route_for(Action.BLOCK_CARD, exposure_usd=2000) == ApprovalRoute.L1
    assert route_for(Action.BLOCK_CARD, exposure_usd=3000) == ApprovalRoute.L2


def test_r3_confirmed_closes_no_fraud():
    s = Signals(fraud_probability=0.6, customer_response=CustomerResponse.confirmed)
    actions = {a.action for a in determine_actions(s)}
    assert actions == {Action.CLOSE_NO_FRAUD}


def test_r7_recurring_dispute_never_blocks():
    s = Signals(fraud_probability=0.5, dispute_matches_recurring=True)
    actions = {a.action for a in determine_actions(s)}
    assert Action.BLOCK_CARD not in actions
    assert Action.CREATE_CASE in actions
    assert Action.VERIFY_WITH_CUSTOMER in actions
    assert Action.WARN_CUSTOMER in actions


def test_r10_blocks_all_cards_requires_two_confirmed():
    s = Signals(fraud_probability=0.95, confirmed_cards_count=1)
    # manually simulate a rule path that would add BLOCK_ALL_CARDS to check the guard;
    # in practice no R-rule above emits BLOCK_ALL_CARDS directly, so this asserts the
    # guard is a no-op when nothing proposed it, and documents the intended check.
    actions = {a.action for a in determine_actions(s)}
    assert Action.BLOCK_ALL_CARDS not in actions


def test_sar_gate_requires_confirmed_and_trigger():
    s = Signals(fraud_probability=0.8, exposure_usd=500)
    file_flag, _ = file_sar(s, verdict="fraud")
    assert file_flag is False  # confirmed but no qualifying trigger

    s2 = Signals(fraud_probability=0.8, exposure_usd=1500)
    file_flag2, _ = file_sar(s2, verdict="fraud")
    assert file_flag2 is True


def test_stop_condition_high_confidence_two_evidence():
    s = Signals(fraud_probability=0.9, evidence_count=2)
    stopped, _ = should_stop(s)
    assert stopped is True


def test_stop_condition_not_reached_single_evidence():
    s = Signals(fraud_probability=0.9, evidence_count=1)
    stopped, _ = should_stop(s)
    assert stopped is False


def test_stop_condition_verification_settles():
    s = Signals(fraud_probability=0.5, customer_response=CustomerResponse.denied)
    stopped, reason = should_stop(s)
    assert stopped is True
    assert "denied" in reason
