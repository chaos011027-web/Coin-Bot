import asyncio

import pytest

import main


class _DummyFetcher:
    async def get_price_only(self, ca):
        return 1.25, 150000.0


@pytest.mark.asyncio
async def test_price_monitor_tp_keeps_order_then_settlement_then_notification(monkeypatch):
    events = []
    sleep_calls = {"count": 0}

    class FakePaperPortfolioEngine:
        def __init__(self):
            self.open_positions = {
                "CA_TP_ORDER": {
                    "remaining_qty": 10.0,
                    "ledger_excluded": False,
                    "strategy": "SMART_TREND",
                    "position_id": "pos_tp_1",
                    "symbol": "TPX",
                }
            }

        def mark_price(self, ca, current_price, current_mcap=0.0):
            return None

        def on_tp_event(self, ca, exit_price, exit_mcap, event_type, order_id=None):
            events.append(("portfolio_tp", order_id, event_type))
            return {"ok": True, "net_pnl_sol": 0.42, "cash_sol": 10.42}

    async def fake_sleep(_seconds):
        sleep_calls["count"] += 1
        if sleep_calls["count"] >= 2:
            raise asyncio.CancelledError()

    async def fake_observe_price(*args, **kwargs):
        return None

    async def fake_update(*args, **kwargs):
        return {"event": "止盈1", "pnl": 18.5}

    async def fake_create_paper_order(**kwargs):
        events.append(("create_order", kwargs.get("intent"), kwargs.get("reason")))
        return "ord_tp_1"

    async def fake_send_thread_reply(chat_id, message_id, text):
        events.append(("send_reply", chat_id, message_id))

    async def fake_refresh_token_panel(*args, **kwargs):
        events.append(("refresh_panel",))

    monkeypatch.setattr(main, "paper_portfolio_engine", FakePaperPortfolioEngine())
    monkeypatch.setattr(main, "fetcher", _DummyFetcher())
    monkeypatch.setattr(main.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(main.tp_tracker, "observe_price", fake_observe_price)
    monkeypatch.setattr(main.tp_tracker, "update", fake_update)
    monkeypatch.setattr(main, "create_paper_order", fake_create_paper_order)
    monkeypatch.setattr(main, "send_thread_reply", fake_send_thread_reply)
    monkeypatch.setattr(main, "refresh_token_panel", fake_refresh_token_panel)
    monkeypatch.setattr(
        main.tp_tracker,
        "data",
        {
            "CA_TP_ORDER": {
                "status": "ACTIVE",
                "reply_chat_id": 11,
                "reply_msg_id": 22,
                "strategy_id": "SMART_TREND",
            }
        },
    )

    await main.price_monitor_loop()

    assert events == [
        ("create_order", "reduce", "止盈1"),
        ("portfolio_tp", "ord_tp_1", "止盈1"),
        ("send_reply", 11, 22),
    ]


@pytest.mark.asyncio
async def test_price_monitor_final_close_keeps_stats_then_order_then_settlement_then_notification(monkeypatch):
    events = []
    sleep_calls = {"count": 0}

    class FakePaperPortfolioEngine:
        def __init__(self):
            self.open_positions = {
                "CA_CLOSE_ORDER": {
                    "remaining_qty": 8.0,
                    "ledger_excluded": False,
                    "strategy": "SMART_TREND",
                    "position_id": "pos_close_1",
                    "symbol": "CLOSEX",
                }
            }

        def mark_price(self, ca, current_price, current_mcap=0.0):
            return None

        def on_final_close(self, ca, exit_price, exit_mcap, reason="FINAL_CLOSE", order_id=None):
            events.append(("portfolio_close", order_id, reason))
            return {"ok": True, "net_pnl_sol": 1.23, "cash_sol": 11.23}

    async def fake_sleep(_seconds):
        sleep_calls["count"] += 1
        if sleep_calls["count"] >= 2:
            raise asyncio.CancelledError()

    async def fake_observe_price(*args, **kwargs):
        return None

    async def fake_update(*args, **kwargs):
        return {"event": "CLOSED_TP", "pnl_percentage": 44.0}

    async def fake_create_paper_order(**kwargs):
        events.append(("create_order", kwargs.get("intent"), kwargs.get("reason")))
        return "ord_close_1"

    async def fake_send_thread_reply(chat_id, message_id, text):
        events.append(("send_reply", chat_id, message_id))

    def fake_record(**kwargs):
        events.append(("stats_record", kwargs.get("result_type")))

    monkeypatch.setattr(main, "paper_portfolio_engine", FakePaperPortfolioEngine())
    monkeypatch.setattr(main, "fetcher", _DummyFetcher())
    monkeypatch.setattr(main.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(main.tp_tracker, "observe_price", fake_observe_price)
    monkeypatch.setattr(main.tp_tracker, "update", fake_update)
    monkeypatch.setattr(main, "create_paper_order", fake_create_paper_order)
    monkeypatch.setattr(main, "send_thread_reply", fake_send_thread_reply)
    monkeypatch.setattr(main.stats_engine, "record", fake_record)
    monkeypatch.setattr(
        main.tp_tracker,
        "data",
        {
            "CA_CLOSE_ORDER": {
                "status": "ACTIVE",
                "reply_chat_id": 33,
                "reply_msg_id": 44,
                "strategy_id": "SMART_TREND",
            }
        },
    )

    await main.price_monitor_loop()

    assert events == [
        ("stats_record", "CLOSED_TP"),
        ("create_order", "close", "CLOSED_TP"),
        ("portfolio_close", "ord_close_1", "CLOSED_TP"),
        ("send_reply", 33, 44),
    ]
