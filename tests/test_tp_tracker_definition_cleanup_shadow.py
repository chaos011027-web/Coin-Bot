import inspect

import pytest

from modules.tp_tracker import TPTracker


def test_tp_tracker_removes_legacy_shadowed_dead_code():
    source = inspect.getsource(TPTracker)

    assert "_legacy_shadowed_init_position" not in source
    assert "_legacy_shadowed_get_baseline_metrics" not in source
    assert source.count("def _make_placeholder(") == 1
    assert source.count("def _apply_observation(") == 1
    assert source.count("async def init_position(") == 1
    assert source.count("async def get_baseline_metrics(") == 1


@pytest.mark.asyncio
async def test_tp_tracker_cleanup_keeps_current_runtime_behavior(tmp_path):
    tracker = TPTracker(path=str(tmp_path / "tp_tracker.json"))
    tracker._loaded = True
    tracker.data["CA_TRACKER"] = tracker._make_placeholder("CA_TRACKER", 1.25)

    baseline = await tracker.get_baseline_metrics("CA_TRACKER", current_price=1.25)

    assert tracker.data["CA_TRACKER"]["signal_state"] == "OBSERVING"
    assert tracker.data["CA_TRACKER"]["anchor_price"] == 1.25
    assert baseline["entry_price"] == 0.0
    assert baseline["current_price"] == 1.25
