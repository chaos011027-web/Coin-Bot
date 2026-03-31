import builtins
import json
from pathlib import Path

import pytest

import run_phase5_data_pipeline as phase5
from modules.paper_ledger_repository import InMemoryPaperLedgerRepository
from modules.training_label_builder import InMemoryTrainingLabelRepository
from modules.training_sample_builder import InMemoryTrainingSampleRepository


def _seed_phase5_sample_repo(sample_repo: InMemoryTrainingSampleRepository) -> None:
    sample_repo.samples.extend(
        [
            {
                "sample_id": "sample_phase5_trade_1",
                "analysis_run_id": 5101,
                "ca": "CA_PHASE5_TRADE",
                "final_action": "ENTER",
                "strategy_id": "SMART_TREND",
                "trace_link": "CA_PHASE5_TRADE:11:22",
                "path_kind": "MAIN_STATE_MACHINE",
                "source": "test",
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
                "metadata": {},
            },
            {
                "sample_id": "sample_phase5_watch_1",
                "analysis_run_id": 5102,
                "ca": "CA_PHASE5_WATCH",
                "final_action": "WATCH",
                "strategy_id": "SMART_TREND",
                "trace_link": "CA_PHASE5_WATCH:33:44",
                "path_kind": "MAIN_STATE_MACHINE",
                "source": "test",
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
                "metadata": {},
            },
            {
                "sample_id": "sample_phase5_nofill_1",
                "analysis_run_id": 5103,
                "ca": "CA_PHASE5_NOFILL",
                "final_action": "ENTER",
                "strategy_id": "SMART_TREND",
                "trace_link": "CA_PHASE5_NOFILL:55:66",
                "path_kind": "MAIN_STATE_MACHINE",
                "source": "test",
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
                "metadata": {},
            },
            {
                "sample_id": "sample_phase5_legacy_1",
                "analysis_run_id": 5104,
                "ca": "CA_PHASE5_LEGACY",
                "final_action": "ENTER",
                "strategy_id": "MIXED",
                "trace_link": "CA_PHASE5_LEGACY:77:88",
                "path_kind": "LEGACY_DIRECT_ENTER",
                "source": "test",
                "legacy_path": True,
                "frozen_features": {
                    "cap_usd": 111000.0,
                    "pair_liquidity_usd": 41000.0,
                    "smart_money_delta": 3.0,
                    "maker_vol_ratio": 1.7,
                    "overhang_ratio": 0.13,
                    "breakout_vol_ratio": 2.0,
                },
                "feature_sources": {},
                "metadata": {},
            },
        ]
    )


def _seed_phase5_paper_ledger_truth(repo: InMemoryPaperLedgerRepository) -> None:
    repo.orders.append(
        {
            "order_id": "ord_phase5_open_1",
            "analysis_run_id": 5101,
            "ca": "CA_PHASE5_TRADE",
            "position_id": "pos_phase5_trade_1",
            "intent": "open",
            "side": "BUY",
            "requested_price": 1.0,
            "strategy_id": "SMART_TREND",
            "legacy_path": False,
            "metadata": {"symbol": "P5X"},
        }
    )
    repo.fills.extend(
        [
            {
                "fill_id": "fill_phase5_open_1",
                "order_id": "ord_phase5_open_1",
                "analysis_run_id": 5101,
                "ca": "CA_PHASE5_TRADE",
                "position_id": "pos_phase5_trade_1",
                "side": "BUY",
                "fill_qty": 1.0,
                "fill_price": 1.0,
                "legacy_path": False,
                "metadata": {"symbol": "P5X"},
            },
            {
                "fill_id": "fill_phase5_reduce_1",
                "order_id": "ord_phase5_reduce_1",
                "analysis_run_id": 5101,
                "ca": "CA_PHASE5_TRADE",
                "position_id": "pos_phase5_trade_1",
                "side": "SELL",
                "fill_qty": 0.4,
                "fill_price": 1.4,
                "legacy_path": False,
                "metadata": {"symbol": "P5X"},
            },
            {
                "fill_id": "fill_phase5_close_1",
                "order_id": "ord_phase5_close_1",
                "analysis_run_id": 5101,
                "ca": "CA_PHASE5_TRADE",
                "position_id": "pos_phase5_trade_1",
                "side": "SELL",
                "fill_qty": 0.6,
                "fill_price": 1.8,
                "legacy_path": False,
                "metadata": {"symbol": "P5X"},
            },
        ]
    )
    repo.trade_closes.extend(
        [
            {
                "trade_close_id": "close_phase5_1",
                "position_id": "pos_phase5_trade_1",
                "order_id": "ord_phase5_reduce_1",
                "fill_id": "fill_phase5_reduce_1",
                "analysis_run_id": 5101,
                "ca": "CA_PHASE5_TRADE",
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
                "legacy_path": False,
            },
            {
                "trade_close_id": "close_phase5_2",
                "position_id": "pos_phase5_trade_1",
                "order_id": "ord_phase5_close_1",
                "fill_id": "fill_phase5_close_1",
                "analysis_run_id": 5101,
                "ca": "CA_PHASE5_TRADE",
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
                "legacy_path": False,
            },
        ]
    )


def test_phase5_pipeline_runner_builds_outputs_manifest_and_consumer_smoke_without_legacy_or_old_fallback(monkeypatch, tmp_path):
    sample_repo = InMemoryTrainingSampleRepository()
    label_repo = InMemoryTrainingLabelRepository()
    paper_repo = InMemoryPaperLedgerRepository()
    _seed_phase5_sample_repo(sample_repo)
    _seed_phase5_paper_ledger_truth(paper_repo)

    monkeypatch.chdir(tmp_path)

    forbidden_fragments = (
        "paper_portfolio_state.json",
        "tp_tracker.json",
        "strategy_performance.json",
        "ml_training_dataset.csv",
        "strategy_backtest_records.json",
    )
    real_open = builtins.open
    real_path_open = Path.open
    real_path_read_text = Path.read_text

    def _assert_not_legacy_fallback(target):
        path_text = str(target)
        for fragment in forbidden_fragments:
            if fragment in path_text:
                raise AssertionError(f"unexpected fallback path: {path_text}")

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

    result = phase5.run_phase5_data_pipeline(
        sample_repository=sample_repo,
        label_repository=label_repo,
        paper_ledger_repository=paper_repo,
        training_replay_output_path=str(tmp_path / "data" / "training_replay_records.json"),
        training_dataset_output_path=str(tmp_path / "data" / "training_dataset_bridge.csv"),
        replay_dataset_output_path=str(tmp_path / "data" / "replay_dataset_bridge.json"),
        manifest_output_path=str(tmp_path / "data" / "phase5_pipeline_manifest.json"),
    )

    manifest = dict(result["manifest"])
    assert Path(result["training_replay_records_path"]).exists()
    assert Path(result["training_dataset_path"]).exists()
    assert Path(result["replay_dataset_path"]).exists()
    assert Path(result["manifest_path"]).exists()

    assert manifest["samples_count"] == 3
    assert manifest["labels_count"] == 3
    assert manifest["trade_closed_count"] == 1
    assert manifest["no_trade_count"] == 1
    assert manifest["no_fill_count"] == 1
    assert manifest["training_rows_count"] == 1
    assert manifest["replay_rows_count"] == 1
    assert manifest["training_replay_records_count"] == 3

    smoke = dict(result["consumer_smoke"])
    assert smoke["train_model_dataset_path"].endswith("training_dataset_bridge.csv")
    assert smoke["optuna_tune_model_dataset_path"].endswith("training_dataset_bridge.csv")
    assert smoke["optuna_tune_strategy_records_path"].endswith("replay_dataset_bridge.json")


def test_phase5_pipeline_runner_stops_immediately_when_one_step_fails(monkeypatch, tmp_path):
    calls = []

    def fake_build_training_labels(**kwargs):
        calls.append("labels")
        return [{"sample_id": "sample_1", "label_kind": "trade_closed"}]

    def fake_export_training_replay_records(**kwargs):
        calls.append("training_replay")
        target = Path(kwargs["output_path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("[]", encoding="utf-8")
        return target

    def fake_export_training_dataset_bridge(**kwargs):
        calls.append("training_bridge")
        raise RuntimeError("training bridge failed")

    def fake_export_replay_dataset_bridge(**kwargs):
        calls.append("replay_bridge")
        return Path(kwargs["output_path"])

    def fake_build_manifest(**kwargs):
        calls.append("manifest")
        return {}

    def fake_smoke(**kwargs):
        calls.append("smoke")
        return {}

    monkeypatch.setattr(phase5, "build_training_labels", fake_build_training_labels)
    monkeypatch.setattr(phase5, "export_training_replay_records", fake_export_training_replay_records)
    monkeypatch.setattr(phase5, "export_training_dataset_bridge", fake_export_training_dataset_bridge)
    monkeypatch.setattr(phase5, "export_replay_dataset_bridge", fake_export_replay_dataset_bridge)
    monkeypatch.setattr(phase5, "build_phase5_pipeline_manifest", fake_build_manifest)
    monkeypatch.setattr(phase5, "run_phase5_consumer_smoke_check", fake_smoke)

    with pytest.raises(RuntimeError, match="training bridge failed"):
        phase5.run_phase5_data_pipeline(
            training_replay_output_path=str(tmp_path / "data" / "training_replay_records.json"),
            training_dataset_output_path=str(tmp_path / "data" / "training_dataset_bridge.csv"),
            replay_dataset_output_path=str(tmp_path / "data" / "replay_dataset_bridge.json"),
            manifest_output_path=str(tmp_path / "data" / "phase5_pipeline_manifest.json"),
        )

    assert calls == ["labels", "training_replay", "training_bridge"]
