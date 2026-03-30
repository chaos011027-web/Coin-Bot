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


async def _seed_open_position(repo, engine, ca):
    with lifecycle_context_scope(
        path_kind=AnalysisPathKind.MAIN_STATE_MACHINE.value,
        source="seed_open_position",
        analysis_run_id=88,
        metadata={
            "trace_link": f"{ca}:77:88",
            "lifecycle_key": f"deep_analysis:{ca}:77:88",
        },
    ):
        order_id = await paper_ledger_service.create_paper_order(
            ca=ca,
            side="BUY",
            intent="open",
            requested_price=1.0,
            strategy_id="SMART_TREND",
            reason="seed_open",
            repository=repo,
        )
        ret = engine.open_position(
            ca=ca,
            symbol="LEDGER",
            strategy="SMART_TREND",
            entry_price=1.0,
            entry_mcap=120000.0,
            opened_at=1700000000.0,
            order_id=order_id,
        )
    await _drain_tasks()
    assert ret["ok"] is True


@pytest.mark.asyncio
async def test_ai_exit_creates_final_close_ledger_chain_without_changing_execution_semantics(monkeypatch, tmp_path):
    repo = InMemoryPaperLedgerRepository()
    engine = PaperPortfolioEngine(state_file=str(tmp_path / "paper_portfolio_state.json"))
    reset_calls = []

    async def fake_reset_to_observing(*args, **kwargs):
        reset_calls.append((args, kwargs))
        return None

    monkeypatch.setattr(paper_ledger_service, "paper_ledger_repository", repo)
    monkeypatch.setattr(main, "paper_portfolio_engine", engine)
    monkeypatch.setattr(main.tp_tracker, "reset_to_observing", fake_reset_to_observing)
    monkeypatch.setattr(main, "_runtime_signal_state", lambda ca, token_data=None, record=None: main.SIGNAL_STATE_ENTERED)
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

    await _seed_open_position(repo, engine, "CA_AI_EXIT")

    with lifecycle_context_scope(
        path_kind=AnalysisPathKind.MAIN_STATE_MACHINE.value,
        source="test_ai_exit",
        analysis_run_id=99,
        metadata={
            "trace_link": "CA_AI_EXIT:9:10",
            "lifecycle_key": "deep_analysis:CA_AI_EXIT:9:10",
        },
    ):
        decision, next_state = await main._apply_execution_state_machine(
            "CA_AI_EXIT",
            {"symbol": "LEDGER", "decision_action": main.ACTION_ENTER, "signal_state": main.SIGNAL_STATE_ENTERED},
            {"verdict": main.ACTION_EXIT, "reason": "close now"},
            strategy_id="SMART_TREND",
            strategy_config={},
            current_price=1.5,
            current_mcap=180000.0,
            chat_id=9,
            message_id=10,
        )

    await _drain_tasks()

    assert decision["verdict"] == main.ACTION_EXIT
    assert next_state == main.SIGNAL_STATE_OBSERVING
    assert len(reset_calls) == 1

    assert len(repo.orders) == 2
    assert repo.orders[-1]["intent"] == "close"
    assert repo.orders[-1]["analysis_run_id"] == 99
    assert repo.orders[-1]["metadata"]["trace_link"] == "CA_AI_EXIT:9:10"

    assert len(repo.fills) == 2
    assert len(repo.positions_ledger) == 2
    assert repo.positions_ledger[-1]["event_type"] == "CLOSED"
    assert len(repo.cash_ledger) == 2
    assert repo.cash_ledger[-1]["event_type"] == "CLOSE_SETTLED"
    assert len(repo.trade_closes) == 1
    assert repo.trade_closes[0]["partial"] is False
    assert repo.trade_closes[0]["close_reason"] == "AI_EXIT"


@pytest.mark.asyncio
async def test_ledger_projection_matches_portfolio_state_and_summary(monkeypatch, tmp_path):
    repo = InMemoryPaperLedgerRepository()
    engine = PaperPortfolioEngine(state_file=str(tmp_path / "paper_portfolio_state.json"))

    monkeypatch.setattr(paper_ledger_service, "paper_ledger_repository", repo)

    await _seed_open_position(repo, engine, "CA_PROJECTION")

    with lifecycle_context_scope(
        path_kind=AnalysisPathKind.PRICE_MONITOR.value,
        source="test_projection",
        metadata={
            "trace_link": "CA_PROJECTION:12:13",
            "lifecycle_key": "price_monitor:CA_PROJECTION:12:13:tp",
        },
    ):
        order_id = await paper_ledger_service.create_paper_order(
            ca="CA_PROJECTION",
            side="SELL",
            intent="reduce",
            requested_price=1.4,
            position_id=engine.open_positions["CA_PROJECTION"]["position_id"],
            strategy_id="SMART_TREND",
            reason="止盈1",
            repository=repo,
        )
        ret = engine.on_tp_event(
            "CA_PROJECTION",
            1.4,
            150000.0,
            "止盈1",
            closed_at=1700000300.0,
            order_id=order_id,
        )

    await _drain_tasks()

    assert ret["ok"] is True

    engine.mark_price("CA_PROJECTION", 1.6, 175000.0)
    projection = paper_ledger_service.build_paper_ledger_projection(
        initial_capital_sol=engine.initial_capital_sol,
        repository=repo,
        mark_prices={"CA_PROJECTION": 1.6},
    )
    summary = engine.summary()

    assert projection["cash_sol"] == pytest.approx(engine.cash_sol)
    assert projection["positions"]["CA_PROJECTION"]["qty_after"] == pytest.approx(
        engine.open_positions["CA_PROJECTION"]["remaining_qty"]
    )
    assert projection["positions"]["CA_PROJECTION"]["realized_pnl_sol_after"] == pytest.approx(
        engine.open_positions["CA_PROJECTION"]["realized_pnl_sol"]
    )
    assert summary["cash_sol"] == pytest.approx(projection["cash_sol"], rel=0, abs=1e-6)
    assert summary["equity_sol"] == pytest.approx(projection["equity_sol"], rel=0, abs=1e-6)

