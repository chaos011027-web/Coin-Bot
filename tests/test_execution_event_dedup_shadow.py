from modules import tp_tracker as tp_tracker_module


async def _return_true(*args, **kwargs):
    return True


import pytest


@pytest.mark.asyncio
async def test_ensure_observing_does_not_repeat_same_execution_event(tmp_path, monkeypatch):
    tracker = tp_tracker_module.TPTracker(path=str(tmp_path / "tp_tracker.json"))
    transitions = []
    executions = []

    async def fake_log_state_transition(*args, **kwargs):
        transitions.append((args, kwargs))
        return True

    async def fake_log_execution_event(*args, **kwargs):
        executions.append((args, kwargs))
        return True

    monkeypatch.setattr(tp_tracker_module, "log_state_transition", fake_log_state_transition)
    monkeypatch.setattr(tp_tracker_module, "log_execution_event", fake_log_execution_event)

    await tracker.ensure_observing("CA_DEDUP", 1.0, anchor_price=1.0, reply_chat_id=1, reply_msg_id=2)
    await tracker.ensure_observing("CA_DEDUP", 1.0, anchor_price=1.0, reply_chat_id=1, reply_msg_id=2)

    assert len(transitions) == 1
    assert len(executions) == 1


@pytest.mark.asyncio
async def test_partial_tp_real_event_is_not_mis_deduped(tmp_path, monkeypatch):
    tracker = tp_tracker_module.TPTracker(path=str(tmp_path / "tp_tracker.json"))
    transitions = []
    executions = []

    async def fake_log_state_transition(*args, **kwargs):
        transitions.append((args, kwargs))
        return True

    async def fake_log_execution_event(*args, **kwargs):
        executions.append((args, kwargs))
        return True

    monkeypatch.setattr(tp_tracker_module, "log_state_transition", fake_log_state_transition)
    monkeypatch.setattr(tp_tracker_module, "log_execution_event", fake_log_execution_event)

    tracker._loaded = True
    tracker.data["CA_TP"] = {
        "ca": "CA_TP",
        "status": "ACTIVE",
        "signal_state": "ENTERED",
        "entry": 1.0,
        "entry_price": 1.0,
        "current_price": 1.0,
        "peak_price": 1.0,
        "peak_multiplier": 1.0,
        "peak_change_pct": 0.0,
        "rel_change_pct": 0.0,
        "sl_price": 0.9,
        "sl_pct": 0.1,
        "tp_targets": [1.2, 1.5],
        "tp_hit_index": -1,
        "sl_moved_to_entry": False,
    }

    event = await tracker.update("CA_TP", 1.21, curr_mcap=125000.0)

    assert event["event"] == "止盈1"
    assert len(transitions) == 0
    assert len(executions) == 1
    assert executions[0][0][1] == tp_tracker_module.ExecutionEventType.TP_TRACKER_TP.value
