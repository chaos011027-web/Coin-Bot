import pytest

from modules.strategy_state import (
    PRIMARY_STRATEGY_STATE_VALUES,
    StrategyAction,
    StrategySignalState,
    is_primary_strategy_state,
)
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


def test_phase11_primary_strategy_states_are_frozen_to_main_backbone():
    assert PRIMARY_STRATEGY_STATE_VALUES == {
        StrategySignalState.NEW_SIGNAL.value,
        StrategySignalState.OBSERVING.value,
        StrategySignalState.ARMED.value,
        StrategySignalState.ENTERED.value,
        StrategySignalState.MANAGING.value,
        StrategySignalState.EXITED.value,
        StrategySignalState.REJECTED.value,
    }
    assert is_primary_strategy_state(StrategySignalState.NEW_SIGNAL.value) is True
    assert is_primary_strategy_state(StrategySignalState.WATCH.value) is False
    assert is_primary_strategy_state(StrategySignalState.PROBE.value) is False


@pytest.mark.parametrize(
    ("from_state", "to_state"),
    [
        (StrategySignalState.NEW_SIGNAL.value, StrategySignalState.OBSERVING.value),
        (StrategySignalState.NEW_SIGNAL.value, StrategySignalState.REJECTED.value),
        (StrategySignalState.OBSERVING.value, StrategySignalState.ARMED.value),
        (StrategySignalState.OBSERVING.value, StrategySignalState.REJECTED.value),
        (StrategySignalState.ARMED.value, StrategySignalState.ENTERED.value),
        (StrategySignalState.ARMED.value, StrategySignalState.REJECTED.value),
        (StrategySignalState.ENTERED.value, StrategySignalState.MANAGING.value),
        (StrategySignalState.MANAGING.value, StrategySignalState.EXITED.value),
    ],
)
def test_phase11_primary_backbone_transitions_are_allowed(from_state, to_state):
    assert_transition_allowed(from_state, to_state)


@pytest.mark.parametrize(
    ("from_state", "to_state"),
    [
        (StrategySignalState.OBSERVING.value, StrategySignalState.WATCH.value),
        (StrategySignalState.OBSERVING.value, StrategySignalState.ENTER_PENDING.value),
        (StrategySignalState.ENTERED.value, StrategySignalState.REJECTED.value),
        (StrategySignalState.MANAGING.value, StrategySignalState.REJECTED.value),
        (StrategySignalState.ENTERED.value, StrategySignalState.EXITED.value),
    ],
)
def test_phase11_primary_backbone_rejects_extension_or_invalid_terminal_jumps(from_state, to_state):
    with pytest.raises(ValueError, match="Illegal strategy state transition"):
        assert_transition_allowed(from_state, to_state)


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
    assert derive_candidate_action(34.0, StrategySignalState.ENTERED.value) == StrategyAction.EXIT.value
