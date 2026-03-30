import asyncio

import pytest

import main
import modules.paper_ledger_service as paper_ledger_service
from modules.paper_ledger_repository import InMemoryPaperLedgerRepository
from modules.paper_portfolio_engine import PaperPortfolioEngine
from modules.strategy_state import AnalysisPathKind, lifecycle_context_scope


_REAL_SLEEP = asyncio.sleep


async def _drain_tasks():
    await _REAL_SLEEP(0)
    await _REAL_SLEEP(0)


async def _seed_open_position(repo, engine, ca, *, price=1.0, mcap=100000.0):
    with lifecycle_context_scope(
        path_kind=AnalysisPathKind.MAIN_STATE_MACHINE.value,
        source="seed_open_position",
        analysis_run_id=7,
        metadata={
            "trace_link": f"{ca}:11:22",
            "lifecycle_key": f"deep_analysis:{ca}:11:22",
        },
    ):
        order_id = await paper_ledger_service.create_paper_order(
            ca=ca,
            side="BUY",
            intent="open",
            requested_price=price,
            strategy_id="SMART_TREND",
            reason="seed_open",
            repository=repo,
        )
        ret = engine.open_position(
            ca=ca,
            symbol="TPX",
            strategy="SMART_TREND",
            entry_price=price,
            entry_mcap=mcap,
            opened_at=1700000000.0,
            order_id=order_id,
        )
    await _drain_tasks()
    assert ret["ok"] is True


@pytest.mark.asyncio
async def test_price_monitor_tp_creates_reduce_fill_position_cash_and_partial_close(monkeypatch, tmp_path):
    repo = InMemoryPaperLedgerRepository()
    engine = PaperPortfolioEngine(state_file=str(tmp_path / "paper_portfolio_state.json"))
    messages = []

    class DummyFetcher:
        async def get_price_only(self, ca):
            return 1.25, 150000.0

    sleep_calls = {"count": 0}

    async def fake_sleep(_seconds):
        sleep_calls["count"] += 1
        if sleep_calls["count"] >= 2:
            raise asyncio.CancelledError()

    async def fake_observe_price(*args, **kwargs):
        return None

    async def fake_update(*args, **kwargs):
        return {"event": "止盈1", "pnl": 25.0}

    async def fake_send_thread_reply(chat_id, message_id, text):
        messages.append((chat_id, message_id, text))

    async def fake_refresh_token_panel(*args, **kwargs):
        return None

    monkeypatch.setattr(paper_ledger_service, "paper_ledger_repository", repo)
    monkeypatch.setattr(main, "paper_portfolio_engine", engine)
    monkeypatch.setattr(main, "fetcher", DummyFetcher())
    monkeypatch.setattr(main.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(main.tp_tracker, "observe_price", fake_observe_price)
    monkeypatch.setattr(main.tp_tracker, "update", fake_update)
    monkeypatch.setattr(main, "send_thread_reply", fake_send_thread_reply)
    monkeypatch.setattr(main, "refresh_token_panel", fake_refresh_token_panel)
    monkeypatch.setattr(
        main.tp_tracker,
        "data",
        {
            "CA_TP": {
                "status": "ACTIVE",
                "reply_chat_id": 11,
                "reply_msg_id": 22,
                "strategy_id": "SMART_TREND",
            }
        },
    )

    await _seed_open_position(repo, engine, "CA_TP")
    await main.price_monitor_loop()
    await _drain_tasks()

    assert len(messages) == 1

    assert len(repo.orders) == 2
    assert repo.orders[-1]["intent"] == "reduce"
    assert repo.orders[-1]["side"] == "SELL"
    assert repo.orders[-1]["metadata"]["trace_link"] == "CA_TP:11:22"
    assert repo.orders[-1]["metadata"]["lifecycle_key"] == "price_monitor:CA_TP:11:22:tp"

    assert len(repo.fills) == 2
    assert repo.fills[-1]["order_id"] == repo.orders[-1]["order_id"]

    assert len(repo.positions_ledger) == 2
    assert repo.positions_ledger[-1]["event_type"] == "UPDATED"
    assert repo.positions_ledger[-1]["qty_after"] > 0

    assert len(repo.cash_ledger) == 2
    assert repo.cash_ledger[-1]["event_type"] == "REDUCE_SETTLED"
    assert repo.cash_ledger[-1]["delta_sol"] > 0

    assert len(repo.trade_closes) == 1
    assert repo.trade_closes[0]["partial"] is True
    assert repo.trade_closes[0]["close_reason"] == "止盈1"


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type", ["CLOSED_TP", "CLOSED_SL"])
async def test_price_monitor_final_close_creates_close_fill_position_cash_and_trade_close(
    monkeypatch,
    tmp_path,
    event_type,
):
    repo = InMemoryPaperLedgerRepository()
    engine = PaperPortfolioEngine(state_file=str(tmp_path / "paper_portfolio_state.json"))
    messages = []
    stats_calls = []

    class DummyFetcher:
        async def get_price_only(self, ca):
            return 1.6, 175000.0

    sleep_calls = {"count": 0}

    async def fake_sleep(_seconds):
        sleep_calls["count"] += 1
        if sleep_calls["count"] >= 2:
            raise asyncio.CancelledError()

    async def fake_observe_price(*args, **kwargs):
        return None

    async def fake_update(*args, **kwargs):
        return {"event": event_type, "pnl_percentage": 44.0}

    async def fake_send_thread_reply(chat_id, message_id, text):
        messages.append((chat_id, message_id, text))

    def fake_record(**kwargs):
        stats_calls.append(kwargs)

    monkeypatch.setattr(paper_ledger_service, "paper_ledger_repository", repo)
    monkeypatch.setattr(main, "paper_portfolio_engine", engine)
    monkeypatch.setattr(main, "fetcher", DummyFetcher())
    monkeypatch.setattr(main.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(main.tp_tracker, "observe_price", fake_observe_price)
    monkeypatch.setattr(main.tp_tracker, "update", fake_update)
    monkeypatch.setattr(main, "send_thread_reply", fake_send_thread_reply)
    monkeypatch.setattr(main.stats_engine, "record", fake_record)
    monkeypatch.setattr(
        main.tp_tracker,
        "data",
        {
            "CA_CLOSE": {
                "status": "ACTIVE",
                "reply_chat_id": 33,
                "reply_msg_id": 44,
                "strategy_id": "SMART_TREND",
            }
        },
    )

    await _seed_open_position(repo, engine, "CA_CLOSE", price=1.0, mcap=110000.0)
    await main.price_monitor_loop()
    await _drain_tasks()

    assert len(messages) == 1
    assert len(stats_calls) == 1

    assert len(repo.orders) == 2
    assert repo.orders[-1]["intent"] == "close"
    assert repo.orders[-1]["metadata"]["trace_link"] == "CA_CLOSE:33:44"
    assert repo.orders[-1]["metadata"]["lifecycle_key"] == "price_monitor:CA_CLOSE:33:44:close"

    assert len(repo.fills) == 2
    assert len(repo.positions_ledger) == 2
    assert repo.positions_ledger[-1]["event_type"] == "CLOSED"
    assert repo.positions_ledger[-1]["qty_after"] == pytest.approx(0.0)

    assert len(repo.cash_ledger) == 2
    assert repo.cash_ledger[-1]["event_type"] == "CLOSE_SETTLED"
    assert repo.cash_ledger[-1]["delta_sol"] > 0

    assert len(repo.trade_closes) == 1
    assert repo.trade_closes[0]["partial"] is False
    assert repo.trade_closes[0]["close_reason"] == event_type
