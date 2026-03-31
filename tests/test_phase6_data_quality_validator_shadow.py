import csv
import json
import re
from pathlib import Path

import pytest

import modules.phase6_data_quality_validator as phase6_validator


def _base_training_replay_records():
    return [
        {
            "sample_id": "sample_phase6_trade_1",
            "analysis_run_id": 6101,
            "ca": "CA_PHASE6_TRADE",
            "final_action": "ENTER",
            "strategy_id": "SMART_TREND",
            "trace_link": "CA_PHASE6_TRADE:11:22",
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
                "position_ids": ["pos_phase6_trade_1"],
                "close_legs": 2,
                "close_reasons": ["TP1", "CLOSED_TP"],
                "realized_pnl_sol": 0.52,
                "realized_return_pct": 52.0,
            },
        },
        {
            "sample_id": "sample_phase6_watch_1",
            "analysis_run_id": 6102,
            "ca": "CA_PHASE6_WATCH",
            "final_action": "WATCH",
            "strategy_id": "SMART_TREND",
            "trace_link": "CA_PHASE6_WATCH:33:44",
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
        {
            "sample_id": "sample_phase6_nofill_1",
            "analysis_run_id": 6103,
            "ca": "CA_PHASE6_NOFILL",
            "final_action": "ENTER",
            "strategy_id": "SMART_TREND",
            "trace_link": "CA_PHASE6_NOFILL:55:66",
            "path_kind": "MAIN_STATE_MACHINE",
            "legacy_path": False,
            "frozen_features": {
                "cap_usd": 93000.0,
                "pair_liquidity_usd": 32000.0,
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


def _write_valid_phase6_artifacts(tmp_path: Path):
    records_path = tmp_path / "data" / "training_replay_records.json"
    training_path = tmp_path / "data" / "training_dataset_bridge.csv"
    replay_path = tmp_path / "data" / "replay_dataset_bridge.json"

    _write_training_replay_records(records_path, _base_training_replay_records())
    _write_training_dataset_csv(
        training_path,
        [
            {
                "sample_id": "sample_phase6_trade_1",
                "analysis_run_id": 6101,
                "ca": "CA_PHASE6_TRADE",
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
        replay_path,
        [
            {
                "sample_id": "sample_phase6_trade_1",
                "analysis_run_id": 6101,
                "ca": "CA_PHASE6_TRADE",
                "symbol": "P6X",
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
    return records_path, training_path, replay_path


def test_phase6_validator_reports_consistent_counts_label_distribution_and_paths(tmp_path):
    records_path, training_path, replay_path = _write_valid_phase6_artifacts(tmp_path)

    report = phase6_validator.build_phase6_data_quality_report(
        training_replay_records_path=str(records_path),
        training_dataset_path=str(training_path),
        replay_dataset_path=str(replay_path),
    )

    assert report["samples_count"] == 3
    assert report["labels_count"] == 3
    assert report["trade_closed_count"] == 1
    assert report["no_trade_count"] == 1
    assert report["no_fill_count"] == 1
    assert report["legacy_records_count"] == 0
    assert report["training_rows_count"] == 1
    assert report["replay_rows_count"] == 1
    assert report["training_sample_ids"] == ["sample_phase6_trade_1"]
    assert report["replay_sample_ids"] == ["sample_phase6_trade_1"]
    assert report["trade_closed_sample_ids"] == ["sample_phase6_trade_1"]
    assert report["training_replay_records_path"] == str(records_path.resolve())
    assert report["training_dataset_path"] == str(training_path.resolve())
    assert report["replay_dataset_path"] == str(replay_path.resolve())


@pytest.mark.parametrize("field_name", ["strategy_id", "market_cap_at_snap", "label"])
def test_phase6_validator_fails_when_training_row_required_field_is_blank(tmp_path, field_name):
    records_path, training_path, replay_path = _write_valid_phase6_artifacts(tmp_path)
    broken_row = {
        "sample_id": "sample_phase6_trade_1",
        "analysis_run_id": 6101,
        "ca": "CA_PHASE6_TRADE",
        "strategy_id": "SMART_TREND",
        "market_cap_at_snap": 100000.0,
        "liquidity_at_snap": 40000.0,
        "smart_money_delta": 5.0,
        "maker_vol_ratio": 1.8,
        "overhang_ratio": 0.15,
        "breakout_vol_ratio": 2.3,
        "label": 1,
    }
    broken_row[field_name] = ""
    _write_training_dataset_csv(training_path, [broken_row])

    with pytest.raises(
        RuntimeError,
        match=re.escape(f"training dataset bridge row missing required fields: {field_name}"),
    ):
        phase6_validator.build_phase6_data_quality_report(
            training_replay_records_path=str(records_path),
            training_dataset_path=str(training_path),
            replay_dataset_path=str(replay_path),
        )


def test_phase6_validator_accepts_zero_numeric_replay_values_as_present_fields(tmp_path):
    records_path, training_path, replay_path = _write_valid_phase6_artifacts(tmp_path)
    _write_replay_dataset_json(
        replay_path,
        [
            {
                "sample_id": "sample_phase6_trade_1",
                "analysis_run_id": 6101,
                "ca": "CA_PHASE6_TRADE",
                "symbol": "P6X",
                "strategy": "SMART_TREND",
                "opened_at": 1700000000.0,
                "closed_at": 1700001000.0,
                "entry_price": 0,
                "exit_price": 0,
                "entry_mcap": 0,
                "exit_mcap": 0,
                "exit_reason": "TP1 | CLOSED_TP",
            }
        ],
    )

    report = phase6_validator.build_phase6_data_quality_report(
        training_replay_records_path=str(records_path),
        training_dataset_path=str(training_path),
        replay_dataset_path=str(replay_path),
    )

    assert report["replay_rows_count"] == 1
    assert report["replay_sample_ids"] == ["sample_phase6_trade_1"]


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda records, training_rows, replay_rows: records.append(
                {
                    "sample_id": "sample_phase6_legacy_1",
                    "analysis_run_id": 6199,
                    "ca": "CA_PHASE6_LEGACY",
                    "final_action": "ENTER",
                    "strategy_id": "MIXED",
                    "trace_link": "CA_PHASE6_LEGACY:77:88",
                    "path_kind": "LEGACY_DIRECT_ENTER",
                    "legacy_path": True,
                    "frozen_features": {"cap_usd": 111000.0},
                    "feature_sources": {},
                    "label": {
                        "label_kind": "trade_closed",
                        "label_source": "paper_trade_closes",
                        "position_ids": ["pos_phase6_legacy_1"],
                        "close_legs": 1,
                        "close_reasons": ["CLOSED_TP"],
                        "realized_pnl_sol": 0.25,
                        "realized_return_pct": 25.0,
                    },
                }
            ),
            "legacy samples must be excluded",
        ),
        (
            lambda records, training_rows, replay_rows: training_rows.append(
                {
                    "sample_id": "sample_phase6_extra_training_1",
                    "analysis_run_id": 6110,
                    "ca": "CA_PHASE6_EXTRA_TRAINING",
                    "strategy_id": "SMART_TREND",
                    "market_cap_at_snap": 100000.0,
                    "liquidity_at_snap": 40000.0,
                    "smart_money_delta": 5.0,
                    "maker_vol_ratio": 1.8,
                    "overhang_ratio": 0.15,
                    "breakout_vol_ratio": 2.3,
                    "label": 1,
                }
            ),
            "training rows exceed trade_closed samples",
        ),
        (
            lambda records, training_rows, replay_rows: replay_rows.append(
                {
                    "sample_id": "sample_phase6_extra_replay_1",
                    "analysis_run_id": 6111,
                    "ca": "CA_PHASE6_EXTRA_REPLAY",
                    "symbol": "P6Y",
                    "strategy": "SMART_TREND",
                    "opened_at": 1700000001.0,
                    "closed_at": 1700000002.0,
                    "entry_price": 1.0,
                    "exit_price": 1.1,
                    "entry_mcap": 100000.0,
                    "exit_mcap": 110000.0,
                    "exit_reason": "CLOSED_TP",
                }
            ),
            "replay rows exceed trade_closed samples",
        ),
    ],
)
def test_phase6_validator_fails_loudly_on_legacy_or_count_inconsistency(tmp_path, mutator, message):
    records = _base_training_replay_records()
    training_rows = [
        {
            "sample_id": "sample_phase6_trade_1",
            "analysis_run_id": 6101,
            "ca": "CA_PHASE6_TRADE",
            "strategy_id": "SMART_TREND",
            "market_cap_at_snap": 100000.0,
            "liquidity_at_snap": 40000.0,
            "smart_money_delta": 5.0,
            "maker_vol_ratio": 1.8,
            "overhang_ratio": 0.15,
            "breakout_vol_ratio": 2.3,
            "label": 1,
        }
    ]
    replay_rows = [
        {
            "sample_id": "sample_phase6_trade_1",
            "analysis_run_id": 6101,
            "ca": "CA_PHASE6_TRADE",
            "symbol": "P6X",
            "strategy": "SMART_TREND",
            "opened_at": 1700000000.0,
            "closed_at": 1700001000.0,
            "entry_price": 1.0,
            "exit_price": 1.52,
            "entry_mcap": 100000.0,
            "exit_mcap": 152000.0,
            "exit_reason": "TP1 | CLOSED_TP",
        }
    ]
    mutator(records, training_rows, replay_rows)

    records_path = tmp_path / "data" / "training_replay_records.json"
    training_path = tmp_path / "data" / "training_dataset_bridge.csv"
    replay_path = tmp_path / "data" / "replay_dataset_bridge.json"
    _write_training_replay_records(records_path, records)
    _write_training_dataset_csv(training_path, training_rows)
    _write_replay_dataset_json(replay_path, replay_rows)

    with pytest.raises(RuntimeError, match=re.escape(message)):
        phase6_validator.build_phase6_data_quality_report(
            training_replay_records_path=str(records_path),
            training_dataset_path=str(training_path),
            replay_dataset_path=str(replay_path),
        )


@pytest.mark.parametrize(
    ("bad_case", "message"),
    [
        ("empty_records", "training replay records empty"),
        ("missing_label", "training replay record missing label payload"),
        ("missing_training_column", "training dataset bridge missing required columns"),
        ("missing_replay_field", "replay dataset bridge row missing required fields"),
        ("orphan_training_sample", "training dataset bridge contains unknown sample_id"),
        ("orphan_replay_sample", "replay dataset bridge contains unknown sample_id"),
        ("bad_replay_structure", "replay dataset bridge payload must be a list or {'records': [...]}"),
    ],
)
def test_phase6_validator_fails_loudly_on_bad_structure_or_incomplete_mapping(tmp_path, bad_case, message):
    records = _base_training_replay_records()
    training_rows = [
        {
            "sample_id": "sample_phase6_trade_1",
            "analysis_run_id": 6101,
            "ca": "CA_PHASE6_TRADE",
            "strategy_id": "SMART_TREND",
            "market_cap_at_snap": 100000.0,
            "liquidity_at_snap": 40000.0,
            "smart_money_delta": 5.0,
            "maker_vol_ratio": 1.8,
            "overhang_ratio": 0.15,
            "breakout_vol_ratio": 2.3,
            "label": 1,
        }
    ]
    replay_rows = [
        {
            "sample_id": "sample_phase6_trade_1",
            "analysis_run_id": 6101,
            "ca": "CA_PHASE6_TRADE",
            "symbol": "P6X",
            "strategy": "SMART_TREND",
            "opened_at": 1700000000.0,
            "closed_at": 1700001000.0,
            "entry_price": 1.0,
            "exit_price": 1.52,
            "entry_mcap": 100000.0,
            "exit_mcap": 152000.0,
            "exit_reason": "TP1 | CLOSED_TP",
        }
    ]

    records_path = tmp_path / "data" / "training_replay_records.json"
    training_path = tmp_path / "data" / "training_dataset_bridge.csv"
    replay_path = tmp_path / "data" / "replay_dataset_bridge.json"

    if bad_case == "empty_records":
        _write_training_replay_records(records_path, [])
    elif bad_case == "missing_label":
        broken = list(records)
        broken[0] = dict(broken[0])
        broken[0].pop("label")
        _write_training_replay_records(records_path, broken)
    else:
        _write_training_replay_records(records_path, records)

    if bad_case == "missing_training_column":
        training_path.parent.mkdir(parents=True, exist_ok=True)
        with training_path.open("w", encoding="utf-8", newline="") as f:
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
                ],
            )
            writer.writeheader()
            writer.writerow({key: training_rows[0][key] for key in writer.fieldnames})
    elif bad_case == "orphan_training_sample":
        broken_training_rows = [dict(training_rows[0], sample_id="sample_phase6_unknown_training_1")]
        _write_training_dataset_csv(training_path, broken_training_rows)
    else:
        _write_training_dataset_csv(training_path, training_rows)

    if bad_case == "bad_replay_structure":
        replay_path.parent.mkdir(parents=True, exist_ok=True)
        replay_path.write_text(json.dumps({"unexpected": []}, ensure_ascii=False), encoding="utf-8")
    elif bad_case == "missing_replay_field":
        broken_replay_rows = [dict(replay_rows[0])]
        broken_replay_rows[0].pop("exit_reason")
        _write_replay_dataset_json(replay_path, broken_replay_rows)
    elif bad_case == "orphan_replay_sample":
        broken_replay_rows = [dict(replay_rows[0], sample_id="sample_phase6_unknown_replay_1")]
        _write_replay_dataset_json(replay_path, broken_replay_rows)
    else:
        _write_replay_dataset_json(replay_path, replay_rows)

    with pytest.raises((RuntimeError, ValueError), match=re.escape(message)):
        phase6_validator.build_phase6_data_quality_report(
            training_replay_records_path=str(records_path),
            training_dataset_path=str(training_path),
            replay_dataset_path=str(replay_path),
        )
