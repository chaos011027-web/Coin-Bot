import builtins
import json
from pathlib import Path

import pytest

import export_replay_dataset_bridge as replay_bridge
from modules.paper_ledger_repository import InMemoryPaperLedgerRepository


def _build_phase4_replay_records():
    return [
        {
            "sample_id": "sample_replay_trade_1",
            "analysis_run_id": 4201,
            "ca": "CA_REPLAY",
            "final_action": "ENTER",
            "strategy_id": "SMART_TREND",
            "trace_link": "CA_REPLAY:11:22",
            "path_kind": "MAIN_STATE_MACHINE",
            "frozen_features": {
                "cap_usd": 100000.0,
                "pair_liquidity_usd": 40000.0,
            },
            "feature_sources": {
                "cap_usd": "stable_snapshot",
                "pair_liquidity_usd": "stable_snapshot",
            },
            "label": {
                "label_kind": "trade_closed",
                "label_source": "paper_trade_closes",
                "position_ids": ["pos_replay_1"],
                "close_legs": 2,
                "close_reasons": ["TP1", "CLOSED_TP"],
                "realized_pnl_sol": 0.52,
                "realized_return_pct": 52.0,
            },
        },
        {
            "sample_id": "sample_replay_no_trade_1",
            "analysis_run_id": 4202,
            "ca": "CA_REPLAY_NO_TRADE",
            "final_action": "WATCH",
            "strategy_id": "SMART_TREND",
            "trace_link": "CA_REPLAY_NO_TRADE:33:44",
            "path_kind": "MAIN_STATE_MACHINE",
            "frozen_features": {"cap_usd": 87000.0},
            "feature_sources": {},
            "label": {
                "label_kind": "no_trade",
                "label_source": "paper_ledger",
                "position_ids": [],
                "close_legs": 0,
                "close_reasons": [],
                "realized_pnl_sol": 0.0,
                "realized_return_pct": 0.0,
            },
        },
        {
            "sample_id": "sample_replay_no_fill_1",
            "analysis_run_id": 4203,
            "ca": "CA_REPLAY_NO_FILL",
            "final_action": "ENTER",
            "strategy_id": "SMART_TREND",
            "trace_link": "CA_REPLAY_NO_FILL:55:66",
            "path_kind": "MAIN_STATE_MACHINE",
            "frozen_features": {"cap_usd": 91000.0},
            "feature_sources": {},
            "label": {
                "label_kind": "no_fill",
                "label_source": "paper_ledger",
                "position_ids": [],
                "close_legs": 0,
                "close_reasons": [],
                "realized_pnl_sol": 0.0,
                "realized_return_pct": 0.0,
            },
        },
        {
            "sample_id": "sample_replay_legacy_1",
            "analysis_run_id": 4204,
            "ca": "CA_REPLAY_LEGACY",
            "final_action": "ENTER",
            "strategy_id": "MIXED",
            "trace_link": "CA_REPLAY_LEGACY:77:88",
            "path_kind": "LEGACY_DIRECT_ENTER",
            "frozen_features": {"cap_usd": 103000.0},
            "feature_sources": {},
            "label": {
                "label_kind": "trade_closed",
                "label_source": "paper_trade_closes",
                "position_ids": ["pos_replay_legacy_1"],
                "close_legs": 1,
                "close_reasons": ["CLOSED_TP"],
                "realized_pnl_sol": 0.42,
                "realized_return_pct": 42.0,
            },
        },
    ]


def _seed_paper_ledger_truth(repo):
    repo.orders.append(
        {
            "order_id": "ord_open_replay_1",
            "analysis_run_id": 4201,
            "ca": "CA_REPLAY",
            "position_id": "pos_replay_1",
            "intent": "open",
            "side": "BUY",
            "requested_price": 1.0,
            "strategy_id": "SMART_TREND",
            "metadata": {"symbol": "RPLY"},
        }
    )
    repo.fills.extend(
        [
            {
                "fill_id": "fill_open_replay_1",
                "order_id": "ord_open_replay_1",
                "analysis_run_id": 4201,
                "ca": "CA_REPLAY",
                "position_id": "pos_replay_1",
                "side": "BUY",
                "fill_qty": 1.0,
                "fill_price": 1.0,
                "metadata": {"symbol": "RPLY"},
            },
            {
                "fill_id": "fill_reduce_replay_1",
                "order_id": "ord_reduce_replay_1",
                "analysis_run_id": 4201,
                "ca": "CA_REPLAY",
                "position_id": "pos_replay_1",
                "side": "SELL",
                "fill_qty": 0.4,
                "fill_price": 1.4,
                "metadata": {"symbol": "RPLY"},
            },
            {
                "fill_id": "fill_close_replay_1",
                "order_id": "ord_close_replay_1",
                "analysis_run_id": 4201,
                "ca": "CA_REPLAY",
                "position_id": "pos_replay_1",
                "side": "SELL",
                "fill_qty": 0.6,
                "fill_price": 1.8,
                "metadata": {"symbol": "RPLY"},
            },
        ]
    )
    repo.trade_closes.extend(
        [
            {
                "trade_close_id": "close_replay_1",
                "position_id": "pos_replay_1",
                "order_id": "ord_reduce_replay_1",
                "fill_id": "fill_reduce_replay_1",
                "analysis_run_id": 4201,
                "ca": "CA_REPLAY",
                "strategy": "SMART_TREND",
                "opened_at": 1700000000.0,
                "closed_at": 1700000500.0,
                "close_reason": "TP1",
                "partial": True,
                "close_ratio": 0.4,
                "entry_notional_sol": 0.4,
                "exit_notional_sol": 0.56,
                "total_fee_sol": 0.02,
                "realized_pnl_sol": 0.14,
                "realized_return_pct": 35.0,
            },
            {
                "trade_close_id": "close_replay_2",
                "position_id": "pos_replay_1",
                "order_id": "ord_close_replay_1",
                "fill_id": "fill_close_replay_1",
                "analysis_run_id": 4201,
                "ca": "CA_REPLAY",
                "strategy": "SMART_TREND",
                "opened_at": 1700000000.0,
                "closed_at": 1700001000.0,
                "close_reason": "CLOSED_TP",
                "partial": False,
                "close_ratio": 1.0,
                "entry_notional_sol": 0.6,
                "exit_notional_sol": 1.08,
                "total_fee_sol": 0.03,
                "realized_pnl_sol": 0.38,
                "realized_return_pct": 63.333333,
            },
        ]
    )


def test_replay_bridge_derives_entry_and_exit_mcap_from_frozen_entry_mcap_and_weighted_exit_price():
    paper_repo = InMemoryPaperLedgerRepository()
    _seed_paper_ledger_truth(paper_repo)

    rows = replay_bridge.build_replay_dataset_records(
        _build_phase4_replay_records(),
        paper_ledger_repository=paper_repo,
    )

    expected_entry_price = 1.0
    expected_entry_mcap = 100000.0
    expected_exit_price = ((0.4 * 1.4) + (0.6 * 1.8)) / (0.4 + 0.6)
    expected_exit_mcap = expected_entry_mcap * (expected_exit_price / expected_entry_price)

    assert len(rows) == 1
    row = rows[0]

    assert set(
        [
            "sample_id",
            "analysis_run_id",
            "ca",
            "symbol",
            "strategy",
            "opened_at",
            "closed_at",
            "entry_price",
            "exit_price",
            "entry_mcap",
            "exit_mcap",
            "exit_reason",
        ]
    ).issubset(row.keys())

    assert row["sample_id"] == "sample_replay_trade_1"
    assert row["ca"] == "CA_REPLAY"
    assert row["symbol"] == "RPLY"
    assert row["strategy"] == "SMART_TREND"

    assert row["opened_at"] == pytest.approx(1700000000.0)
    assert row["closed_at"] == pytest.approx(1700001000.0)

    assert row["entry_price"] == pytest.approx(expected_entry_price)
    assert row["entry_mcap"] == pytest.approx(expected_entry_mcap)

    assert row["exit_price"] == pytest.approx(expected_exit_price)
    assert row["exit_mcap"] == pytest.approx(expected_exit_mcap)

    assert row["exit_reason"] == "TP1 | CLOSED_TP"


def test_replay_bridge_export_writes_new_json_without_legacy_state_fallback(monkeypatch, tmp_path):
    paper_repo = InMemoryPaperLedgerRepository()
    _seed_paper_ledger_truth(paper_repo)

    input_path = tmp_path / "data" / "training_replay_records.json"
    output_path = tmp_path / "data" / "replay_dataset_bridge.json"
    input_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.write_text(json.dumps(_build_phase4_replay_records(), ensure_ascii=False, indent=2), encoding="utf-8")

    assert replay_bridge.DEFAULT_OUTPUT.name != "strategy_backtest_records.json"

    forbidden_fragments = (
        "paper_portfolio_state.json",
        "tp_tracker.json",
        "strategy_performance.json",
        "golden_dog_morphology",
        "strategy_backtest_records.json",
    )
    real_open = builtins.open
    real_path_open = Path.open
    real_path_read_text = Path.read_text

    def _assert_not_legacy_fallback(target):
        path_text = str(target)
        for fragment in forbidden_fragments:
            if fragment in path_text:
                raise AssertionError(f"unexpected legacy replay fallback: {path_text}")

    def guarded_open(file, *args, **kwargs):
        _assert_not_legacy_fallback(file)
        return real_open(file, *args, **kwargs)

    def guarded_path_open(self, *args, **kwargs):
        _assert_not_legacy_fallback(self)
        return real_path_open(self, *args, **kwargs)

    def guarded_read_text(self, *args, **kwargs):
        _assert_not_legacy_fallback(self)
        return real_path_read_text(self, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(Path, "open", guarded_path_open)
    monkeypatch.setattr(Path, "read_text", guarded_read_text)

    exported = replay_bridge.export_replay_dataset_bridge(
        input_path=str(input_path),
        output_path=str(output_path),
        paper_ledger_repository=paper_repo,
    )

    assert exported == output_path
    assert output_path.exists()

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        rows = payload.get("records", []) or []
    else:
        rows = payload

    expected_exit_price = ((0.4 * 1.4) + (0.6 * 1.8)) / (0.4 + 0.6)
    expected_exit_mcap = 100000.0 * (expected_exit_price / 1.0)

    assert len(rows) == 1
    assert rows[0]["sample_id"] == "sample_replay_trade_1"
    assert rows[0]["ca"] == "CA_REPLAY"
    assert rows[0]["entry_mcap"] == pytest.approx(100000.0)
    assert rows[0]["exit_price"] == pytest.approx(expected_exit_price)
    assert rows[0]["exit_mcap"] == pytest.approx(expected_exit_mcap)
