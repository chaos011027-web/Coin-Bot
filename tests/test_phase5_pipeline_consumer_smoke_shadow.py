import json
from pathlib import Path

import pytest

import run_phase5_data_pipeline as phase5


def _write_training_dataset_bridge(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "sample_id,analysis_run_id,ca,strategy_id,market_cap_at_snap,liquidity_at_snap,smart_money_delta,maker_vol_ratio,overhang_ratio,breakout_vol_ratio,label\n"
        "sample_consumer_1,5301,CA_CONSUMER,SMART_TREND,100000,40000,5.0,1.8,0.15,2.3,1\n",
        encoding="utf-8",
    )
    return path


def _write_replay_dataset_bridge(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "sample_id": "sample_consumer_1",
                        "analysis_run_id": 5301,
                        "ca": "CA_CONSUMER",
                        "symbol": "CNR",
                        "strategy": "SMART_TREND",
                        "opened_at": 1700000000.0,
                        "closed_at": 1700001000.0,
                        "entry_price": 1.0,
                        "exit_price": 1.5,
                        "entry_mcap": 100000.0,
                        "exit_mcap": 150000.0,
                        "exit_reason": "CLOSED_TP",
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def test_phase5_consumer_smoke_prefers_new_phase5_outputs(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    training_path = _write_training_dataset_bridge(tmp_path / "data" / "training_dataset_bridge.csv")
    replay_path = _write_replay_dataset_bridge(tmp_path / "data" / "replay_dataset_bridge.json")

    legacy_training = tmp_path / "data" / "ml_training_dataset.csv"
    legacy_training.write_text("market_cap_at_snap,label\n1,1\n", encoding="utf-8")
    legacy_replay = tmp_path / "data" / "strategy_backtest_records.json"
    legacy_replay.write_text(json.dumps({"records": []}, ensure_ascii=False), encoding="utf-8")

    smoke = phase5.run_phase5_consumer_smoke_check(
        training_dataset_path=str(training_path),
        replay_dataset_path=str(replay_path),
    )

    assert smoke["train_model_dataset_path"] == str(training_path.resolve())
    assert smoke["optuna_tune_model_dataset_path"] == str(training_path.resolve())
    assert smoke["optuna_tune_strategy_records_path"] == str(replay_path.resolve())


def test_phase5_consumer_smoke_fails_when_expected_outputs_are_missing_or_mismatched(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    training_path = _write_training_dataset_bridge(tmp_path / "data" / "training_dataset_bridge.csv")
    replay_path = _write_replay_dataset_bridge(tmp_path / "data" / "replay_dataset_bridge.json")

    with pytest.raises((RuntimeError, FileNotFoundError, ValueError)):
        phase5.run_phase5_consumer_smoke_check(
            training_dataset_path=str(training_path),
            replay_dataset_path=str(tmp_path / "data" / "missing_replay_dataset_bridge.json"),
        )

    with pytest.raises((RuntimeError, FileNotFoundError, ValueError)):
        phase5.run_phase5_consumer_smoke_check(
            training_dataset_path=str(tmp_path / "data" / "other_training_dataset_bridge.csv"),
            replay_dataset_path=str(replay_path),
        )
