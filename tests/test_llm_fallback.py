from src import llm_fallback
from src.state import Pattern, Signals


def test_llm_cannot_override_graph_derived_r1_single_signal_flag(monkeypatch):
    monkeypatch.setattr(llm_fallback, "llm_configured", lambda: True)
    monkeypatch.setattr(
        llm_fallback,
        "complete_json",
        lambda *args, **kwargs: (
            {
                "fraud_probability": 0.68,
                "evidence_sufficiency": 0.55,
                "single_signal_only": False,
            },
            12,
        ),
    )
    prior = Signals(
        fraud_probability=0.68,
        pattern=Pattern.card_not_present_new_device,
        single_signal_only=True,
    )

    signals, _ = llm_fallback.assess("context", prior)

    assert signals.single_signal_only is True
