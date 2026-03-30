import asyncio

import pytest

import main
from modules.paper_portfolio_engine import PaperPortfolioEngine


class _DummyFetcher:
    async def get_price_only(self, ca):
        return 1.25, 150000.0


TP_EVENT = "\u6b62\u76c81"


@pytest.mark.asyncio
async def test_partial_take_profit_returns_net_return_pct_for_tp_display(tmp_path):
    engine = PaperPortfolioEngine(state_file=str(tmp_path / "paper_portfolio_state.json"))
    opened = engine.open_position(
        ca="CA_TP_RET",
        symbol="TPRET",
        strategy="SMART_TREND",
        entry_price=1.0,
        entry_mcap=100000.0,
        opened_at=1700000000.0,
    )
    assert opened["ok"] is True

    ret = engine.on_tp_event(
        "CA_TP_RET",
        1.25,
        150000.0,
        TP_EVENT,
        closed_at=1700000300.0,
    )

    assert ret["ok"] is True
    assert "net_return_pct" in ret
    assert isinstance(ret["net_return_pct"], float)


@pytest.mark.asyncio
async def test_price_monitor_tp_message_uses_engine_return_not_event_dict_pnl(monkeypatch):
    events = []
    messages = []
    sleep_calls = {"count": 0}

    class FakePaperPortfolioEngine:
        def __init__(self):
            self.open_positions = {
                "CA_TP_DISPLAY": {
                    "remaining_qty": 10.0,
                    "ledger_excluded": False,
                    "strategy": "SMART_TREND",
                    "position_id": "pos_tp_display_1",
                    "symbol": "TPX",
                }
            }

        def mark_price(self, ca, current_price, current_mcap=0.0):
            return None

        def on_tp_event(self, ca, exit_price, exit_mcap, event_type, order_id=None):
            events.append(("portfolio_tp", order_id, event_type))
            return {
                "ok": True,
                "net_pnl_sol": 0.42,
                "net_return_pct": 12.34,
                "cash_sol": 10.42,
            }

    async def fake_sleep(_seconds):
        sleep_calls["count"] += 1
        if sleep_calls["count"] >= 2:
            raise asyncio.CancelledError()

    async def fake_observe_price(*args, **kwargs):
        return None

    async def fake_update(*args, **kwargs):
        return {"event": TP_EVENT, "pnl": 999.99}

    async def fake_create_paper_order(**kwargs):
        events.append(("create_order", kwargs.get("intent"), kwargs.get("reason")))
        return "ord_tp_display_1"

    async def fake_send_thread_reply(chat_id, message_id, text):
        events.append(("send_reply", chat_id, message_id))
        messages.append(text)

    async def fake_refresh_token_panel(*args, **kwargs):
        return None

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
            "CA_TP_DISPLAY": {
                "status": "ACTIVE",
                "reply_chat_id": 11,
                "reply_msg_id": 22,
                "strategy_id": "SMART_TREND",
            }
        },
    )

    await main.price_monitor_loop()

    assert events == [
        ("create_order", "reduce", TP_EVENT),
        ("portfolio_tp", "ord_tp_display_1", TP_EVENT),
        ("send_reply", 11, 22),
    ]
    assert len(messages) == 1
    assert "+12.34%" in messages[0]
    assert "+999.99%" not in messages[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("event_type", "engine_pnl_pct", "event_pnl_pct", "expected_fragment"),
    [
        ("CLOSED_TP", 44.56, -777.0, "+44.56%"),
        ("CLOSED_SL", -9.87, 321.0, "-9.87%"),
    ],
)
async def test_price_monitor_final_close_message_uses_engine_return_not_event_dict_pnl_percentage(
    monkeypatch,
    event_type,
    engine_pnl_pct,
    event_pnl_pct,
    expected_fragment,
):
    events = []
    messages = []
    sleep_calls = {"count": 0}

    class FakePaperPortfolioEngine:
        def __init__(self):
            self.open_positions = {
                "CA_CLOSE_DISPLAY": {
                    "remaining_qty": 8.0,
                    "ledger_excluded": False,
                    "strategy": "SMART_TREND",
                    "position_id": "pos_close_display_1",
                    "symbol": "CLOSEX",
                }
            }

        def mark_price(self, ca, current_price, current_mcap=0.0):
            return None

        def on_final_close(self, ca, exit_price, exit_mcap, reason="FINAL_CLOSE", order_id=None):
            events.append(("portfolio_close", order_id, reason))
            return {
                "ok": True,
                "net_pnl_sol": 1.23,
                "net_return_pct": engine_pnl_pct,
                "cash_sol": 11.23,
            }

    async def fake_sleep(_seconds):
        sleep_calls["count"] += 1
        if sleep_calls["count"] >= 2:
            raise asyncio.CancelledError()

    async def fake_observe_price(*args, **kwargs):
        return None

    async def fake_update(*args, **kwargs):
        return {"event": event_type, "pnl_percentage": event_pnl_pct}

    async def fake_create_paper_order(**kwargs):
        events.append(("create_order", kwargs.get("intent"), kwargs.get("reason")))
        return "ord_close_display_1"

    async def fake_send_thread_reply(chat_id, message_id, text):
        events.append(("send_reply", chat_id, message_id))
        messages.append(text)

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
            "CA_CLOSE_DISPLAY": {
                "status": "ACTIVE",
                "reply_chat_id": 33,
                "reply_msg_id": 44,
                "strategy_id": "SMART_TREND",
            }
        },
    )

    await main.price_monitor_loop()

    assert events == [
        ("stats_record", event_type),
        ("create_order", "close", event_type),
        ("portfolio_close", "ord_close_display_1", event_type),
        ("send_reply", 33, 44),
    ]
    assert len(messages) == 1
    assert expected_fragment in messages[0]
    assert f"{event_pnl_pct:+.2f}%" not in messages[0]
