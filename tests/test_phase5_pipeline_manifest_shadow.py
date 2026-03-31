import csv
import json
from pathlib import Path

import pytest

import modules.phase5_pipeline_manifest as manifest_mod


def _write_training_replay_records(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            [
                {
                    "sample_id": "sample_manifest_trade_1",
                    "analysis_run_id": 5201,
                    "ca": "CA_MANIFEST_TRADE",
                    "final_action": "ENTER",
                    "strategy_id": "SMART_TREND",
                    "trace_link": "CA_MANIFEST_TRADE:11:22",
                    "path_kind": "MAIN_STATE_MACHINE",
                    "frozen_features": {"cap_usd": 100000.0},
                    "feature_sources": {},
                    "label": {
                        "label_kind": "trade_closed",
                        "label_source": "paper_trade_closes",
                        "position_ids": ["pos_manifest_trade_1"],
                        "close_legs": 2,
                        "close_reasons": ["TP1", "CLOSED_TP"],
                        "realized_pnl_sol": 0.52,
                        "realized_return_pct": 52.0,
                    },
                },
                {
                    "sample_id": "sample_manifest_watch_1",
                    "analysis_run_id": 5202,
                    "ca": "CA_MANIFEST_WATCH",
                    "final_action": "WATCH",
                    "strategy_id": "SMART_TREND",
                    "trace_link": "CA_MANIFEST_WATCH:33:44",
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
                    "sample_id": "sample_manifest_nofill_1",
                    "analysis_run_id": 5203,
                    "ca": "CA_MANIFEST_NOFILL",
                    "final_action": "ENTER",
                    "strategy_id": "SMART_TREND",
                    "trace_link": "CA_MANIFEST_NOFILL:55:66",
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
                    "sample_id": "sample_manifest_legacy_1",
                    "analysis_run_id": 5204,
                    "ca": "CA_MANIFEST_LEGACY",
                    "final_action": "ENTER",
                    "strategy_id": "MIXED",
                    "trace_link": "CA_MANIFEST_LEGACY:77:88",
                    "path_kind": "LEGACY_DIRECT_ENTER",
                    "frozen_features": {"cap_usd": 111000.0},
                    "feature_sources": {},
                    "label": {
                        "label_kind": "trade_closed",
                        "label_source": "paper_trade_closes",
                        "position_ids": ["pos_manifest_legacy_1"],
                        "close_legs": 1,
                        "close_reasons": ["CLOSED_TP"],
                        "realized_pnl_sol": 0.25,
                        "realized_return_pct": 25.0,
                    },
                },
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _write_training_dataset_csv(path: Path, rows_count: int = 1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
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
            ],
        )
        writer.writeheader()
        for idx in range(rows_count):
            writer.writerow(
                {
                    "sample_id": f"sample_manifest_trade_{idx + 1}",
                    "analysis_run_id": 5201 + idx,
                    "ca": f"CA_MANIFEST_TRADE_{idx + 1}",
                    "strategy_id": "SMART_TREND",
                    "market_cap_at_snap": 100000.0,
                    "liquidity_at_snap": 40000.0,
                    "smart_money_delta": 5.0,
                    "maker_vol_ratio": 1.8,
                    "overhang_ratio": 0.15,
                    "breakout_vol_ratio": 2.3,
                    "label": 1,
                }
            )


def _write_replay_dataset_json(path: Path, rows_count: int = 1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for idx in range(rows_count):
        rows.append(
            {
                "sample_id": f"sample_manifest_trade_{idx + 1}",
                "analysis_run_id": 5201 + idx,
                "ca": f"CA_MANIFEST_TRADE_{idx + 1}",
                "symbol": "MFX",
                "strategy": "SMART_TREND",
                "opened_at": 1700000000.0,
                "closed_at": 1700001000.0,
                "entry_price": 1.0,
                "exit_price": 1.52,
                "entry_mcap": 100000.0,
                "exit_mcap": 152000.0,
                "exit_reason": "TP1 | CLOSED_TP",
            }
        )
    path.write_text(
        json.dumps({"records": rows, "records_count": len(rows)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def test_phase5_pipeline_manifest_counts_paths_and_legacy_exclusion(tmp_path):
    records_path = tmp_path / "data" / "training_replay_records.json"
    training_path = tmp_path / "data" / "training_dataset_bridge.csv"
    replay_path = tmp_path / "data" / "replay_dataset_bridge.json"
    _write_training_replay_records(records_path)
    _write_training_dataset_csv(training_path, rows_count=1)
    _write_replay_dataset_json(replay_path, rows_count=1)

    manifest = manifest_mod.build_phase5_pipeline_manifest(
        training_replay_records_path=str(records_path),
        training_dataset_path=str(training_path),
        replay_dataset_path=str(replay_path),
    )

    assert manifest["samples_count"] == 3
    assert manifest["labels_count"] == 3
    assert manifest["trade_closed_count"] == 1
    assert manifest["no_trade_count"] == 1
    assert manifest["no_fill_count"] == 1
    assert manifest["training_rows_count"] == 1
    assert manifest["replay_rows_count"] == 1
    assert manifest["training_replay_records_count"] == 3
    assert manifest["training_replay_records_path"] == str(records_path.resolve())
    assert manifest["training_dataset_path"] == str(training_path.resolve())
    assert manifest["replay_dataset_path"] == str(replay_path.resolve())


def test_phase5_pipeline_manifest_fails_on_inconsistent_trade_closed_counts(tmp_path):
    records_path = tmp_path / "data" / "training_replay_records.json"
    training_path = tmp_path / "data" / "training_dataset_bridge.csv"
    replay_path = tmp_path / "data" / "replay_dataset_bridge.json"
    _write_training_replay_records(records_path)
    _write_training_dataset_csv(training_path, rows_count=2)
    _write_replay_dataset_json(replay_path, rows_count=1)

    with pytest.raises(RuntimeError, match="training rows exceed trade_closed samples"):
        manifest_mod.build_phase5_pipeline_manifest(
            training_replay_records_path=str(records_path),
            training_dataset_path=str(training_path),
            replay_dataset_path=str(replay_path),
        )


@pytest.mark.parametrize(
    "bad_case",
    ["missing_records", "bad_records_structure", "bad_replay_structure"],
)
def test_phase5_pipeline_manifest_fails_loudly_on_missing_or_bad_inputs(tmp_path, bad_case):
    records_path = tmp_path / "data" / "training_replay_records.json"
    training_path = tmp_path / "data" / "training_dataset_bridge.csv"
    replay_path = tmp_path / "data" / "replay_dataset_bridge.json"

    if bad_case != "missing_records":
        _write_training_replay_records(records_path)
        _write_training_dataset_csv(training_path, rows_count=1)
        _write_replay_dataset_json(replay_path, rows_count=1)

    if bad_case == "bad_records_structure":
        records_path.write_text(json.dumps({"unexpected": []}, ensure_ascii=False), encoding="utf-8")
    if bad_case == "bad_replay_structure":
        replay_path.write_text(json.dumps({"unexpected": []}, ensure_ascii=False), encoding="utf-8")

    with pytest.raises((RuntimeError, FileNotFoundError, ValueError)):
        manifest_mod.build_phase5_pipeline_manifest(
            training_replay_records_path=str(records_path),
            training_dataset_path=str(training_path),
            replay_dataset_path=str(replay_path),
        )
