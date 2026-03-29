import inspect

import pytest

import main


@pytest.mark.asyncio
async def test_apply_execution_state_machine_rewrites_verdict_to_executed_action(monkeypatch):
    captured = {}

    async def fake_arm_position(*args, **kwargs):
        return None

    async def fake_log_execution_event(ca, event_type, **kwargs):
        captured["ca"] = ca
        captured["event_type"] = event_type
        captured["action"] = kwargs.get("action")
        captured["signal_state"] = kwargs.get("signal_state")
        return True

    monkeypatch.setattr(main.tp_tracker, "arm_position", fake_arm_position)
    monkeypatch.setattr(main, "log_execution_event", fake_log_execution_event)
    monkeypatch.setattr(main, "_runtime_signal_state", lambda ca, token_data=None, record=None: main.SIGNAL_STATE_OBSERVING)
    monkeypatch.setattr(main, "_log_canonical_state", lambda *args, **kwargs: None)
    monkeypatch.setattr(main, "_apply_runtime_metadata", lambda token_data, **kwargs: token_data.update(kwargs) or token_data)
    monkeypatch.setattr(main, "canonical_pipeline_settings", lambda: {"strict_enter_block_verdict": main.ACTION_PROBE})
    monkeypatch.setattr(
        main,
        "get_decision_liquidity_context",
        lambda token_data: {
            "formal_enter_ready": False,
            "strict_mode": True,
            "display_source": "CANONICAL",
        },
    )

    decision, next_state = await main._apply_execution_state_machine(
        "CA_SINGLE_ACTION",
        {},
        {"verdict": main.ACTION_ENTER, "reason": "downgrade to probe"},
        strategy_id="SMART_TREND",
        strategy_config={},
        current_price=0.25,
        current_mcap=125000.0,
        chat_id=1,
        message_id=2,
    )

    assert decision["verdict"] == main.ACTION_PROBE
    assert decision["verdict"] == captured["action"]
    assert captured["signal_state"] == main.SIGNAL_STATE_ARMED
    assert next_state == main.SIGNAL_STATE_ARMED


def test_run_deep_analysis_uses_written_back_verdict_as_outer_final_action_mirror():
    source = inspect.getsource(main.run_deep_analysis)

    assert 'decision.get("final_action") or' not in source
    assert 'final_action = _normalize_verdict(' in source
    assert 'decision.get("verdict", ACTION_WATCH)' in source
