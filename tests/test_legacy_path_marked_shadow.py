import pytest

import main
from modules.strategy_state import AnalysisPathKind


@pytest.mark.asyncio
async def test_legacy_direct_enter_path_is_explicitly_marked(monkeypatch):
    monkeypatch.setenv("SHADOW_LIFECYCLE_ENABLED", "1")
    captured = {}

    async def fake_start_analysis_run(ca, *, source, path_kind, chat_id, message_id, metadata=None, legacy_path=False):
        captured["ca"] = ca
        captured["source"] = source
        captured["path_kind"] = path_kind
        captured["chat_id"] = chat_id
        captured["message_id"] = message_id
        captured["legacy_path"] = legacy_path
        raise RuntimeError("stop-after-legacy-mark")

    monkeypatch.setattr(main, "start_analysis_run", fake_start_analysis_run)

    await main._legacy_run_deep_analysis_direct_enter(
        "CA_LEGACY_1",
        {},
        message_id=321,
        chat_id=654,
        use_insightx=False,
    )

    assert captured["ca"] == "CA_LEGACY_1"
    assert captured["source"] == "_legacy_run_deep_analysis_direct_enter"
    assert captured["path_kind"] == AnalysisPathKind.LEGACY_DIRECT_ENTER.value
    assert captured["legacy_path"] is True
