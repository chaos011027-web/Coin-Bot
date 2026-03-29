import pytest

from modules.strategy_state import StrategyAction, StrategySignalState
from modules.strategy_state_machine import (
    assert_transition_allowed,
    build_decision_chain,
    derive_candidate_action,
)


def test_new_signal_to_observing_allowed():
    assert_transition_allowed(
        StrategySignalState.NEW_SIGNAL.value,
        StrategySignalState.OBSERVING.value,
    )


@pytest.mark.parametrize(
    "to_state",
    [
        StrategySignalState.WATCH.value,
        StrategySignalState.ARMED.value,
        StrategySignalState.REJECTED.value,
    ],
)
def test_observing_to_watch_armed_rejected_allowed(to_state):
    assert_transition_allowed(StrategySignalState.OBSERVING.value, to_state)


def test_illegal_transition_raises_clear_error():
    with pytest.raises(ValueError, match="Illegal strategy state transition"):
        assert_transition_allowed(
            StrategySignalState.INVALIDATED.value,
            StrategySignalState.ENTERED.value,
        )


def test_strategy_candidate_ai_risk_and_final_action_are_normalized():
    chain = build_decision_chain(
        candidate_action="probe",
        ai_verdict="ENTER",
        risk_adjusted_action="PROBE",
        final_action="PROBE",
        strategy_id="MIXED",
        score=72.5,
        reason="risk gate downgraded enter",
    )

    assert chain.candidate_action == StrategyAction.PROBE.value
    assert chain.ai_verdict == StrategyAction.ENTER.value
    assert chain.risk_adjusted_action == StrategyAction.PROBE.value
    assert chain.final_action == StrategyAction.PROBE.value


def test_candidate_action_can_be_derived_from_score_and_state():
    assert derive_candidate_action(82.0, StrategySignalState.OBSERVING.value) == StrategyAction.ENTER.value
    assert derive_candidate_action(67.0, StrategySignalState.OBSERVING.value) == StrategyAction.PROBE.value
    assert derive_candidate_action(34.0, StrategySignalState.ENTERED.value) == StrategyAction.EXIT.value
