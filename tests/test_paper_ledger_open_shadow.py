import asyncio

import pytest

import main
import modules.paper_ledger_service as paper_ledger_service
from modules.paper_ledger_repository import InMemoryPaperLedgerRepository
from modules.paper_portfolio_engine import PaperPortfolioEngine
from modules.strategy_state import AnalysisPathKind, lifecycle_context_scope


async def _drain_tasks():
    await asyncio.sleep(0)
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_main_enter_creates_order_fill_position_and_cash_ledger(monkeypatch, tmp_path):
    repo = InMemoryPaperLedgerRepository()
    engine = PaperPortfolioEngine(state_file=str(tmp_path / "paper_portfolio_state.json"))
    tracker_calls = []

    async def fake_init_position(*args, **kwargs):
        tracker_calls.append((args, kwargs))
        return None

    monkeypatch.setattr(paper_ledger_service, "paper_ledger_repository", repo)
    monkeypatch.setattr(main, "paper_portfolio_engine", engine)
    monkeypatch.setattr(main.tp_tracker, "init_position", fake_init_position)
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

    token_data = {"symbol": "OPEN"}
    with lifecycle_context_scope(
        path_kind=AnalysisPathKind.MAIN_STATE_MACHINE.value,
        source="test_main_enter",
        analysis_run_id=42,
        metadata={
            "trace_link": "CA_ENTER:1:2",
            "lifecycle_key": "deep_analysis:CA_ENTER:1:2",
        },
    ):
        decision, next_state = await main._apply_execution_state_machine(
            "CA_ENTER",
            token_data,
            {"verdict": main.ACTION_ENTER, "reason": "open now"},
            strategy_id="SMART_TREND",
            strategy_config={},
            current_price=0.25,
            current_mcap=125000.0,
            chat_id=1,
            message_id=2,
        )

    await _drain_tasks()

    assert decision["verdict"] == main.ACTION_ENTER
    assert next_state == main.SIGNAL_STATE_ENTERED
    assert len(tracker_calls) == 1

    assert len(repo.orders) == 1
    assert repo.orders[0]["ca"] == "CA_ENTER"
    assert repo.orders[0]["intent"] == "open"
    assert repo.orders[0]["side"] == "BUY"
    assert repo.orders[0]["analysis_run_id"] == 42
    assert repo.orders[0]["metadata"]["trace_link"] == "CA_ENTER:1:2"

    assert len(repo.fills) == 1
    assert repo.fills[0]["order_id"] == repo.orders[0]["order_id"]
    assert repo.fills[0]["position_id"] == repo.orders[0]["position_id"]

    assert len(repo.positions_ledger) == 1
    assert repo.positions_ledger[0]["event_type"] == "OPENED"
    assert repo.positions_ledger[0]["qty_after"] > 0

    assert len(repo.cash_ledger) == 1
    assert repo.cash_ledger[0]["event_type"] == "OPEN_SETTLED"
    assert repo.cash_ledger[0]["delta_sol"] < 0
    assert repo.cash_ledger[0]["balance_after_sol"] == pytest.approx(engine.cash_sol)

    assert repo.trade_closes == []
    assert engine.open_positions["CA_ENTER"]["position_id"] == repo.orders[0]["position_id"]
    assert engine.open_positions["CA_ENTER"]["ledger_excluded"] is False
