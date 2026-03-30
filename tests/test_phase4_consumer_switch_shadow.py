from pathlib import Path

import pytest

import train_model
import optuna_tune_model
import optuna_tune_strategy


def _touch(path: Path, content: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "module_ref",
    [train_model, optuna_tune_model],
)
def test_training_consumers_prefer_new_training_bridge_csv_before_legacy_csv(module_ref, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    new_path = _touch(
        tmp_path / "data" / "training_dataset_bridge.csv",
        "sample_id,analysis_run_id,ca,strategy_id,market_cap_at_snap,liquidity_at_snap,smart_money_delta,maker_vol_ratio,overhang_ratio,breakout_vol_ratio,label\n",
    )
    old_path = _touch(
        tmp_path / "data" / "ml_training_dataset.csv",
        "market_cap_at_snap,liquidity_at_snap,smart_money_delta,maker_vol_ratio,overhang_ratio,breakout_vol_ratio,label\n",
    )

    resolved = module_ref.resolve_dataset_path()

    assert resolved == new_path
    assert resolved != old_path
    assert resolved.name == "training_dataset_bridge.csv"


@pytest.mark.parametrize(
    "module_ref",
    [train_model, optuna_tune_model],
)
def test_training_consumers_fall_back_to_legacy_csv_only_when_new_bridge_missing(module_ref, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    old_path = _touch(
        tmp_path / "data" / "ml_training_dataset.csv",
        "market_cap_at_snap,liquidity_at_snap,smart_money_delta,maker_vol_ratio,overhang_ratio,breakout_vol_ratio,label\n",
    )

    resolved = module_ref.resolve_dataset_path()

    assert resolved == old_path
    assert resolved.name == "ml_training_dataset.csv"


def test_optuna_tune_strategy_prefers_new_replay_bridge_json_before_legacy_records(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    new_path = _touch(
        tmp_path / "data" / "replay_dataset_bridge.json",
        '{"records":[{"ca":"CA_R","symbol":"R","strategy":"SMART_TREND","opened_at":1,"closed_at":2,"entry_price":1,"exit_price":1.2,"entry_mcap":100000,"exit_mcap":120000,"exit_reason":"CLOSED_TP"}]}',
    )
    old_path = _touch(
        tmp_path / "data" / "strategy_backtest_records.json",
        '{"records":[{"ca":"CA_OLD","symbol":"O","strategy":"SMART_TREND","opened_at":1,"closed_at":2,"entry_price":1,"exit_price":1.1,"entry_mcap":100000,"exit_mcap":110000,"exit_reason":"OLD"}]}',
    )

    resolved = optuna_tune_strategy.resolve_records_path()

    assert resolved == new_path
    assert resolved != old_path
    assert resolved.name == "replay_dataset_bridge.json"


def test_optuna_tune_strategy_falls_back_to_legacy_records_only_when_new_bridge_missing(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    old_path = _touch(
        tmp_path / "data" / "strategy_backtest_records.json",
        '{"records":[{"ca":"CA_OLD","symbol":"O","strategy":"SMART_TREND","opened_at":1,"closed_at":2,"entry_price":1,"exit_price":1.1,"entry_mcap":100000,"exit_mcap":110000,"exit_reason":"OLD"}]}',
    )

    resolved = optuna_tune_strategy.resolve_records_path()

    assert resolved == old_path
    assert resolved.name == "strategy_backtest_records.json"
