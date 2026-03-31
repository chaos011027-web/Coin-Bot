import csv
import json
from pathlib import Path

import pytest

import run_phase7_data_quality_check as phase7_runner


def _base_training_replay_records():
    return [
        {
            "sample_id": "sample_phase7_trade_1",
            "analysis_run_id": 7101,
            "ca": "CA_PHASE7_TRADE",
            "final_action": "ENTER",
            "strategy_id": "SMART_TREND",
            "trace_link": "CA_PHASE7_TRADE:11:22",
            "path_kind": "MAIN_STATE_MACHINE",
            "legacy_path": False,
            "frozen_features": {
                "cap_usd": 100000.0,
                "pair_liquidity_usd": 40000.0,
                "smart_money_delta": 5.0,
                "maker_vol_ratio": 1.8,
                "overhang_ratio": 0.15,
                "breakout_vol_ratio": 2.3,
            },
            "feature_sources": {},
            "label": {
                "label_kind": "trade_closed",
                "label_source": "paper_trade_closes",
                "position_ids": ["pos_phase7_trade_1"],
                "close_legs": 2,
                "close_reasons": ["TP1", "CLOSED_TP"],
                "realized_pnl_sol": 0.52,
                "realized_return_pct": 52.0,
            },
        },
        {
            "sample_id": "sample_phase7_watch_1",
            "analysis_run_id": 7102,
            "ca": "CA_PHASE7_WATCH",
            "final_action": "WATCH",
            "strategy_id": "SMART_TREND",
            "trace_link": "CA_PHASE7_WATCH:33:44",
            "path_kind": "MAIN_STATE_MACHINE",
            "legacy_path": False,
            "frozen_features": {
                "cap_usd": 91000.0,
                "pair_liquidity_usd": 31000.0,
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
    ]


def _write_training_replay_records(path: Path, records) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_training_dataset_csv(path: Path, rows) -> None:
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
        for row in rows:
            writer.writerow(row)


def _write_replay_dataset_json(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"records": rows, "records_count": len(rows)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_default_artifacts(root: Path) -> None:
    data_dir = root / "data"
    _write_training_replay_records(
        data_dir / "training_replay_records.json",
        _base_training_replay_records(),
    )
    _write_training_dataset_csv(
        data_dir / "training_dataset_bridge.csv",
        [
            {
                "sample_id": "sample_phase7_trade_1",
                "analysis_run_id": 7101,
                "ca": "CA_PHASE7_TRADE",
                "strategy_id": "SMART_TREND",
                "market_cap_at_snap": 100000.0,
                "liquidity_at_snap": 40000.0,
                "smart_money_delta": 5.0,
                "maker_vol_ratio": 1.8,
                "overhang_ratio": 0.15,
                "breakout_vol_ratio": 2.3,
                "label": 1,
            }
        ],
    )
    _write_replay_dataset_json(
        data_dir / "replay_dataset_bridge.json",
        [
            {
                "sample_id": "sample_phase7_trade_1",
                "analysis_run_id": 7101,
                "ca": "CA_PHASE7_TRADE",
                "symbol": "P7X",
                "strategy": "SMART_TREND",
                "opened_at": 1700000000.0,
                "closed_at": 1700001000.0,
                "entry_price": 1.0,
                "exit_price": 1.52,
                "entry_mcap": 100000.0,
                "exit_mcap": 152000.0,
                "exit_reason": "TP1 | CLOSED_TP",
            }
        ],
    )


def test_phase7_runner_uses_default_paths_and_writes_report(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _write_default_artifacts(tmp_path)

    result = phase7_runner.run_phase7_data_quality_check()

    report_path = tmp_path / "data" / "phase7_data_quality_report.json"
    assert Path(result["report_path"]) == report_path.resolve()
    assert report_path.exists()
    assert result["report"]["samples_count"] == 2
    assert result["report"]["trade_closed_count"] == 1
    assert result["report"]["no_trade_count"] == 1
    assert result["report"]["training_rows_count"] == 1
    assert result["report"]["replay_rows_count"] == 1

    written = json.loads(report_path.read_text(encoding="utf-8"))
    assert written["samples_count"] == 2
    assert written["trade_closed_count"] == 1
    assert written["training_dataset_path"] == str((tmp_path / "data" / "training_dataset_bridge.csv").resolve())


@pytest.mark.parametrize(
    ("missing_name", "message"),
    [
        ("training_replay_records.json", "training replay records missing"),
        ("training_dataset_bridge.csv", "training dataset bridge missing"),
        ("replay_dataset_bridge.json", "replay dataset bridge missing"),
    ],
)
def test_phase7_runner_fails_loudly_when_required_artifact_is_missing(monkeypatch, tmp_path, missing_name, message):
    monkeypatch.chdir(tmp_path)
    _write_default_artifacts(tmp_path)
    (tmp_path / "data" / missing_name).unlink()

    with pytest.raises(FileNotFoundError, match=message):
        phase7_runner.run_phase7_data_quality_check()


def test_phase7_runner_does_not_swallow_validator_failures(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _write_default_artifacts(tmp_path)
    _write_training_dataset_csv(
        tmp_path / "data" / "training_dataset_bridge.csv",
        [
            {
                "sample_id": "sample_phase7_trade_1",
                "analysis_run_id": 7101,
                "ca": "CA_PHASE7_TRADE",
                "strategy_id": "SMART_TREND",
                "market_cap_at_snap": 100000.0,
                "liquidity_at_snap": 40000.0,
                "smart_money_delta": 5.0,
                "maker_vol_ratio": 1.8,
                "overhang_ratio": 0.15,
                "breakout_vol_ratio": 2.3,
                "label": 1,
            },
            {
                "sample_id": "sample_phase7_extra_training_1",
                "analysis_run_id": 7199,
                "ca": "CA_PHASE7_EXTRA",
                "strategy_id": "SMART_TREND",
                "market_cap_at_snap": 100000.0,
                "liquidity_at_snap": 40000.0,
                "smart_money_delta": 5.0,
                "maker_vol_ratio": 1.8,
                "overhang_ratio": 0.15,
                "breakout_vol_ratio": 2.3,
                "label": 1,
            },
        ],
    )

    with pytest.raises(RuntimeError, match="training rows exceed trade_closed samples"):
        phase7_runner.run_phase7_data_quality_check()


def test_phase7_runner_writes_report_to_custom_output_path(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _write_default_artifacts(tmp_path)
    output_path = tmp_path / "reports" / "phase7_acceptance.json"

    result = phase7_runner.run_phase7_data_quality_check(output_path=str(output_path))

    assert Path(result["report_path"]) == output_path.resolve()
    assert output_path.exists()
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["samples_count"] == 2
    assert payload["trade_closed_count"] == 1
    assert payload["replay_dataset_path"] == str((tmp_path / "data" / "replay_dataset_bridge.json").resolve())
