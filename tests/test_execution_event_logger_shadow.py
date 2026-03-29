import pytest

import main
from modules.execution_event_logger import log_execution_event, log_state_transition
from modules.lifecycle_repository import InMemoryLifecycleRepository
from modules.strategy_state import (
    AnalysisPathKind,
    ExecutionEventType,
    StrategyAction,
    StrategySignalState,
    lifecycle_context_scope,
)


@pytest.mark.asyncio
async def test_transition_and_execution_event_are_logged(monkeypatch):
    monkeypatch.setenv("SHADOW_LIFECYCLE_ENABLED", "1")

    repo = InMemoryLifecycleRepository()
    with lifecycle_context_scope(
        path_kind=AnalysisPathKind.FAST_SIGNAL_INIT.value,
        source="test_execution_logger",
    ):
        await log_state_transition(
            "CA_TEST_2",
            StrategySignalState.NEW_SIGNAL.value,
            StrategySignalState.OBSERVING.value,
            action=StrategyAction.WATCH.value,
            source="process_new_signal",
            repository=repo,
        )
        await log_execution_event(
            "CA_TEST_2",
            ExecutionEventType.EXECUTION_TRANSITION.value,
            action=StrategyAction.WATCH.value,
            signal_state=StrategySignalState.OBSERVING.value,
            source="_apply_execution_state_machine",
            repository=repo,
            metadata={"stage": "fast_init"},
        )

    assert len(repo.strategy_state_transitions) == 1
    assert repo.strategy_state_transitions[0]["from_state"] == StrategySignalState.NEW_SIGNAL.value
    assert repo.strategy_state_transitions[0]["to_state"] == StrategySignalState.OBSERVING.value

    assert len(repo.execution_events) == 1
    assert repo.execution_events[0]["event_type"] == ExecutionEventType.EXECUTION_TRANSITION.value
    assert repo.execution_events[0]["signal_state"] == StrategySignalState.OBSERVING.value


@pytest.mark.asyncio
async def test_execution_event_preserves_shadow_action_enum(monkeypatch):
    monkeypatch.setenv("SHADOW_LIFECYCLE_ENABLED", "1")

    repo = InMemoryLifecycleRepository()
    with lifecycle_context_scope(
        path_kind=AnalysisPathKind.TP_TRACKER.value,
        source="test_execution_logger",
    ):
        await log_execution_event(
            "CA_TEST_2B",
            ExecutionEventType.TP_TRACKER_TP.value,
            action=StrategyAction.REDUCE.value,
            signal_state=StrategySignalState.MANAGING.value,
            source="tp_tracker.update",
            repository=repo,
        )

    assert len(repo.execution_events) == 1
    assert repo.execution_events[0]["action"] == StrategyAction.REDUCE.value
    assert repo.execution_events[0]["signal_state"] == StrategySignalState.MANAGING.value


@pytest.mark.asyncio
async def test_main_execution_state_machine_unchanged_when_flags_off(monkeypatch):
    monkeypatch.delenv("SHADOW_LIFECYCLE_ENABLED", raising=False)

    async def fake_arm_position(*args, **kwargs):
        return None

    async def fake_init_position(*args, **kwargs):
        raise AssertionError("ENTER path should not be used")

    async def fake_ensure_observing(*args, **kwargs):
        raise AssertionError("WATCH path should not be used")

    monkeypatch.setattr(main.tp_tracker, "arm_position", fake_arm_position)
    monkeypatch.setattr(main.tp_tracker, "init_position", fake_init_position)
    monkeypatch.setattr(main.tp_tracker, "ensure_observing", fake_ensure_observing)
    monkeypatch.setattr(main, "_runtime_signal_state", lambda ca, token_data=None, record=None: main.SIGNAL_STATE_OBSERVING)
    monkeypatch.setattr(main, "_log_canonical_state", lambda *args, **kwargs: None)
    monkeypatch.setattr(main, "_apply_runtime_metadata", lambda token_data, **kwargs: token_data.update(kwargs) or token_data)
    monkeypatch.setattr(
        main,
        "get_decision_liquidity_context",
        lambda token_data: {
            "formal_enter_ready": True,
            "strict_mode": True,
            "display_source": "EXIT_CANONICAL",
        },
    )

    decision, next_state = await main._apply_execution_state_machine(
        "CA_TEST_3",
        {},
        {"verdict": main.ACTION_PROBE, "reason": "shadow flags disabled"},
        strategy_id="SMART_TREND",
        strategy_config={},
        current_price=0.25,
        current_mcap=125000.0,
        chat_id=1,
        message_id=2,
    )

    assert decision["verdict"] == main.ACTION_PROBE
    assert next_state == main.SIGNAL_STATE_ARMED
