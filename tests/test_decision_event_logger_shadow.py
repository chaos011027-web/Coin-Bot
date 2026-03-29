import pytest

from modules.decision_event_logger import log_decision_chain
from modules.lifecycle_repository import InMemoryLifecycleRepository
from modules.strategy_state import AnalysisPathKind, StrategyAction, lifecycle_context_scope
from modules.strategy_state_machine import build_decision_chain


@pytest.mark.asyncio
async def test_final_action_writes_decision_event(monkeypatch):
    monkeypatch.setenv("SHADOW_LIFECYCLE_ENABLED", "1")

    repo = InMemoryLifecycleRepository()
    chain = build_decision_chain(
        candidate_action=StrategyAction.PROBE.value,
        ai_verdict=StrategyAction.ENTER.value,
        risk_adjusted_action=StrategyAction.PROBE.value,
        final_action=StrategyAction.PROBE.value,
        strategy_id="SMART_TREND",
        score=74.2,
        reason="strict liquidity blocked formal enter",
        risk_flags=["STRICT_EXIT_LIQ"],
    )

    with lifecycle_context_scope(
        path_kind=AnalysisPathKind.MAIN_STATE_MACHINE.value,
        source="test_decision_logger",
    ):
        await log_decision_chain("CA_TEST_1", chain, repository=repo)

    assert len(repo.decision_events) == 1
    row = repo.decision_events[0]
    assert row["ca"] == "CA_TEST_1"
    assert row["candidate_action"] == StrategyAction.PROBE.value
    assert row["ai_verdict"] == StrategyAction.ENTER.value
    assert row["risk_adjusted_action"] == StrategyAction.PROBE.value
    assert row["final_action"] == StrategyAction.PROBE.value
    assert row["path_kind"] == AnalysisPathKind.MAIN_STATE_MACHINE.value
    assert row["risk_flags"] == ["STRICT_EXIT_LIQ"]
