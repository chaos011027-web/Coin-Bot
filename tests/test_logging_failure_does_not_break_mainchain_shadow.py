import pytest

import main
from modules.execution_event_logger import log_state_transition
from modules.lifecycle_repository import InMemoryLifecycleRepository
from modules.strategy_state import AnalysisPathKind, StrategyAction, StrategySignalState, lifecycle_context_scope


@pytest.mark.asyncio
async def test_execution_logging_repository_failure_does_not_break_mainchain(monkeypatch):
    monkeypatch.setenv("SHADOW_LIFECYCLE_ENABLED", "1")

    async def fake_arm_position(*args, **kwargs):
        return None

    async def failing_append_execution_event(record):
        raise RuntimeError("db offline")

    monkeypatch.setattr(main.tp_tracker, "arm_position", fake_arm_position)
    monkeypatch.setattr(main, "_runtime_signal_state", lambda ca, token_data=None, record=None: main.SIGNAL_STATE_OBSERVING)
    monkeypatch.setattr(main, "_log_canonical_state", lambda *args, **kwargs: None)
    monkeypatch.setattr(main, "_apply_runtime_metadata", lambda token_data, **kwargs: token_data.update(kwargs) or token_data)
    monkeypatch.setattr(
        main,
        "get_decision_liquidity_context",
        lambda token_data: {
            "formal_enter_ready": True,
            "strict_mode": False,
            "display_source": "CANONICAL",
        },
    )
    monkeypatch.setattr(main.log_execution_event.__globals__["lifecycle_repository"], "append_execution_event", failing_append_execution_event)

    decision, next_state = await main._apply_execution_state_machine(
        "CA_LOG_FAIL",
        {},
        {"verdict": main.ACTION_PROBE, "reason": "logging failure should not break"},
        strategy_id="SMART_TREND",
        strategy_config={},
        current_price=0.25,
        current_mcap=125000.0,
        chat_id=1,
        message_id=2,
    )

    assert decision["verdict"] == main.ACTION_PROBE
    assert next_state == main.SIGNAL_STATE_ARMED


@pytest.mark.asyncio
async def test_strict_transitions_boundary_is_explicit(monkeypatch):
    monkeypatch.setenv("SHADOW_LIFECYCLE_ENABLED", "1")
    monkeypatch.setenv("SHADOW_LIFECYCLE_STRICT_TRANSITIONS", "1")

    repo = InMemoryLifecycleRepository()
    with lifecycle_context_scope(
        path_kind=AnalysisPathKind.TP_TRACKER.value,
        source="tp_tracker.reset_to_observing",
    ):
        with pytest.raises(ValueError, match="Illegal strategy state transition"):
            await log_state_transition(
                "CA_STRICT",
                StrategySignalState.ENTERED.value,
                StrategySignalState.OBSERVING.value,
                action=StrategyAction.EXIT.value,
                repository=repo,
            )
