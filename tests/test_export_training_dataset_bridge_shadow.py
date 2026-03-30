import builtins
import csv
import json
from pathlib import Path

import pytest

import export_training_dataset_bridge as training_bridge


def _build_phase4_training_records():
    return [
        {
            "sample_id": "sample_train_win_1",
            "analysis_run_id": 4101,
            "ca": "CA_TRAIN_WIN",
            "final_action": "ENTER",
            "strategy_id": "SMART_TREND",
            "trace_link": "CA_TRAIN_WIN:11:22",
            "path_kind": "MAIN_STATE_MACHINE",
            "frozen_features": {
                "cap_usd": 125000.0,
                "pair_liquidity_usd": 45000.0,
                "smart_money_delta": 5.0,
                "maker_vol_ratio": 1.8,
                "overhang_ratio": 0.12,
                "breakout_vol_ratio": 2.4,
            },
            "feature_sources": {
                "cap_usd": "stable_snapshot",
                "pair_liquidity_usd": "stable_snapshot",
                "smart_money_delta": "feature_engine",
                "maker_vol_ratio": "feature_engine",
                "overhang_ratio": "feature_engine",
                "breakout_vol_ratio": "feature_engine",
            },
            "label": {
                "label_kind": "trade_closed",
                "label_source": "paper_trade_closes",
                "position_ids": ["pos_train_win_1"],
                "close_legs": 1,
                "close_reasons": ["CLOSED_TP"],
                "realized_pnl_sol": 0.75,
                "realized_return_pct": 75.0,
            },
        },
        {
            "sample_id": "sample_train_loss_1",
            "analysis_run_id": 4102,
            "ca": "CA_TRAIN_LOSS",
            "final_action": "ENTER",
            "strategy_id": "SMART_TREND",
            "trace_link": "CA_TRAIN_LOSS:33:44",
            "path_kind": "MAIN_STATE_MACHINE",
            "frozen_features": {
                "cap_usd": 98000.0,
                "pair_liquidity_usd": 31000.0,
                "smart_money_delta": -1.0,
                "maker_vol_ratio": 0.7,
                "overhang_ratio": 0.45,
                "breakout_vol_ratio": 0.8,
            },
            "feature_sources": {
                "cap_usd": "stable_snapshot",
                "pair_liquidity_usd": "stable_snapshot",
                "smart_money_delta": "feature_engine",
                "maker_vol_ratio": "feature_engine",
                "overhang_ratio": "feature_engine",
                "breakout_vol_ratio": "feature_engine",
            },
            "label": {
                "label_kind": "trade_closed",
                "label_source": "paper_trade_closes",
                "position_ids": ["pos_train_loss_1"],
                "close_legs": 1,
                "close_reasons": ["CLOSED_SL"],
                "realized_pnl_sol": -0.22,
                "realized_return_pct": -22.0,
            },
        },
        {
            "sample_id": "sample_no_trade_1",
            "analysis_run_id": 4103,
            "ca": "CA_NO_TRADE",
            "final_action": "WATCH",
            "strategy_id": "SMART_TREND",
            "trace_link": "CA_NO_TRADE:55:66",
            "path_kind": "MAIN_STATE_MACHINE",
            "frozen_features": {
                "cap_usd": 88000.0,
                "pair_liquidity_usd": 28000.0,
                "smart_money_delta": 0.0,
                "maker_vol_ratio": 1.0,
                "overhang_ratio": 0.20,
                "breakout_vol_ratio": 1.0,
            },
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
            "sample_id": "sample_no_fill_1",
            "analysis_run_id": 4104,
            "ca": "CA_NO_FILL",
            "final_action": "ENTER",
            "strategy_id": "SMART_TREND",
            "trace_link": "CA_NO_FILL:77:88",
            "path_kind": "MAIN_STATE_MACHINE",
            "frozen_features": {
                "cap_usd": 91000.0,
                "pair_liquidity_usd": 30000.0,
                "smart_money_delta": 0.5,
                "maker_vol_ratio": 1.1,
                "overhang_ratio": 0.18,
                "breakout_vol_ratio": 1.1,
            },
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
            "sample_id": "sample_legacy_1",
            "analysis_run_id": 4105,
            "ca": "CA_LEGACY_TRAIN",
            "final_action": "ENTER",
            "strategy_id": "MIXED",
            "trace_link": "CA_LEGACY_TRAIN:99:11",
            "path_kind": "LEGACY_DIRECT_ENTER",
            "frozen_features": {
                "cap_usd": 123000.0,
                "pair_liquidity_usd": 41000.0,
                "smart_money_delta": 4.0,
                "maker_vol_ratio": 1.6,
                "overhang_ratio": 0.14,
                "breakout_vol_ratio": 2.0,
            },
            "feature_sources": {},
            "label": {
                "label_kind": "trade_closed",
                "label_source": "paper_trade_closes",
                "position_ids": ["pos_legacy_1"],
                "close_legs": 1,
                "close_reasons": ["CLOSED_TP"],
                "realized_pnl_sol": 0.33,
                "realized_return_pct": 33.0,
            },
        },
    ]


def test_training_bridge_maps_trade_closed_records_to_flat_training_rows_and_excludes_non_trade_samples():
    rows = training_bridge.build_training_dataset_rows(_build_phase4_training_records())

    assert len(rows) == 2
    by_sample = {row["sample_id"]: row for row in rows}

    assert "sample_train_win_1" in by_sample
    assert "sample_train_loss_1" in by_sample
    assert "sample_no_trade_1" not in by_sample
    assert "sample_no_fill_1" not in by_sample
    assert "sample_legacy_1" not in by_sample

    win_row = by_sample["sample_train_win_1"]
    loss_row = by_sample["sample_train_loss_1"]

    for row in (win_row, loss_row):
        assert set(
            [
                "sample_id",
                "analysis_run_id",
                "ca",
                "strategy_id",
                "market_cap_at_snap",
                "liquidity_at_snap",
                "smart_money_delta",
                "maker_vol_ratio",
                "overhang_ratio",
                "breakout_vol_ratio",
                "label",
            ]
        ).issubset(row.keys())

    assert win_row["market_cap_at_snap"] == pytest.approx(125000.0)
    assert win_row["liquidity_at_snap"] == pytest.approx(45000.0)
    assert win_row["smart_money_delta"] == pytest.approx(5.0)
    assert win_row["maker_vol_ratio"] == pytest.approx(1.8)
    assert win_row["overhang_ratio"] == pytest.approx(0.12)
    assert win_row["breakout_vol_ratio"] == pytest.approx(2.4)
    assert int(win_row["label"]) == 1

    assert loss_row["market_cap_at_snap"] == pytest.approx(98000.0)
    assert loss_row["liquidity_at_snap"] == pytest.approx(31000.0)
    assert int(loss_row["label"]) == 0


def test_training_bridge_export_writes_new_csv_without_legacy_label_fallback(monkeypatch, tmp_path):
    records = _build_phase4_training_records()
    input_path = tmp_path / "data" / "training_replay_records.json"
    output_path = tmp_path / "data" / "training_dataset_bridge.csv"
    input_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")

    assert training_bridge.DEFAULT_OUTPUT.name != "ml_training_dataset.csv"

    forbidden_fragments = (
        "ml_training_dataset.csv",
        "midnight_hunter.py",
        "performance_labels",
    )
    real_open = builtins.open
    real_path_open = Path.open
    real_path_read_text = Path.read_text

    def _assert_not_legacy_fallback(target):
        path_text = str(target)
        for fragment in forbidden_fragments:
            if fragment in path_text:
                raise AssertionError(f"unexpected legacy fallback: {path_text}")

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

    exported = training_bridge.export_training_dataset_bridge(
        input_path=str(input_path),
        output_path=str(output_path),
    )

    assert exported == output_path
    assert output_path.exists()

    with output_path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    assert len(rows) == 2
    assert {row["sample_id"] for row in rows} == {"sample_train_win_1", "sample_train_loss_1"}
