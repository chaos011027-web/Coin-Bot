import json
from pathlib import Path

import run_phase14_feedback_export as phase14_export
from modules.lifecycle_repository import InMemoryLifecycleRepository
from modules.paper_ledger_repository import InMemoryPaperLedgerRepository
from modules.training_label_builder import InMemoryTrainingLabelRepository
from modules.training_sample_builder import InMemoryTrainingSampleRepository


def _seed_sample_repo(repo: InMemoryTrainingSampleRepository) -> None:
    repo.samples.extend(
        [
            {
                "sample_id": "sample_export_runner_trade_1",
                "analysis_run_id": 14301,
                "ca": "CA_EXPORT_RUNNER_TRADE",
                "trace_link": "CA_EXPORT_RUNNER_TRADE:11:22",
                "final_action": "ENTER",
                "strategy_id": "SMART_TREND",
                "path_kind": "MAIN_STATE_MACHINE",
                "source": "test",
                "legacy_path": False,
                "frozen_features": {},
                "feature_sources": {},
                "metadata": {},
            },
            {
                "sample_id": "sample_export_runner_watch_1",
                "analysis_run_id": 14302,
                "ca": "CA_EXPORT_RUNNER_WATCH",
                "trace_link": "CA_EXPORT_RUNNER_WATCH:33:44",
                "final_action": "WATCH",
                "strategy_id": "SMART_TREND",
                "path_kind": "MAIN_STATE_MACHINE",
                "source": "test",
                "legacy_path": False,
                "frozen_features": {},
                "feature_sources": {},
                "metadata": {},
            },
            {
                "sample_id": "sample_export_runner_legacy_1",
                "analysis_run_id": 14399,
                "ca": "CA_EXPORT_RUNNER_LEGACY",
                "trace_link": "CA_EXPORT_RUNNER_LEGACY:55:66",
                "final_action": "ENTER",
                "strategy_id": "MIXED",
                "path_kind": "LEGACY_DIRECT_ENTER",
                "source": "test",
                "legacy_path": True,
                "frozen_features": {},
                "feature_sources": {},
                "metadata": {},
            },
        ]
    )


def _seed_label_repo(repo: InMemoryTrainingLabelRepository) -> None:
    repo.labels.extend(
        [
            {
                "sample_id": "sample_export_runner_trade_1",
                "analysis_run_id": 14301,
                "ca": "CA_EXPORT_RUNNER_TRADE",
                "label_kind": "trade_closed",
                "label_source": "paper_trade_closes",
                "position_ids": ["pos_export_runner_trade_1"],
                "close_legs": 1,
                "close_reasons": ["CLOSED_TP"],
                "realized_pnl_sol": 0.40,
                "realized_return_pct": 40.0,
                "metadata": {},
            },
            {
                "sample_id": "sample_export_runner_watch_1",
                "analysis_run_id": 14302,
                "ca": "CA_EXPORT_RUNNER_WATCH",
                "label_kind": "no_trade",
                "label_source": "paper_ledger",
                "position_ids": [],
                "close_legs": 0,
                "close_reasons": [],
                "realized_pnl_sol": 0.0,
                "realized_return_pct": 0.0,
                "metadata": {},
            },
            {
                "sample_id": "sample_export_runner_legacy_1",
                "analysis_run_id": 14399,
                "ca": "CA_EXPORT_RUNNER_LEGACY",
                "label_kind": "trade_closed",
                "label_source": "paper_trade_closes",
                "position_ids": ["pos_export_runner_legacy_1"],
                "close_legs": 1,
                "close_reasons": ["CLOSED_TP"],
                "realized_pnl_sol": 0.20,
                "realized_return_pct": 20.0,
                "metadata": {},
            },
        ]
    )


def _seed_lifecycle_repo(repo: InMemoryLifecycleRepository) -> None:
    repo.decision_events.extend(
        [
            {
                "analysis_run_id": 14301,
                "ca": "CA_EXPORT_RUNNER_TRADE",
                "event_type": "FINAL_ACTION",
                "candidate_action": "WATCH",
                "ai_verdict": "ENTER",
                "risk_adjusted_action": "ENTER",
                "final_action": "ENTER",
                "strategy_id": "SMART_TREND",
                "score": 82.0,
                "reason": "score gate passed",
                "risk_flags": [],
                "source": "test",
                "path_kind": "MAIN_STATE_MACHINE",
                "legacy_path": False,
                "metadata": {},
            }
        ]
    )
    repo.execution_events.extend(
        [
            {
                "analysis_run_id": 14301,
                "ca": "CA_EXPORT_RUNNER_TRADE",
                "event_type": "PAPER_OPEN",
                "action": "ENTER",
                "signal_state": "ENTERED",
                "status": "OPEN",
                "source": "test",
                "path_kind": "MAIN_STATE_MACHINE",
                "legacy_path": False,
                "metadata": {
                    "allocated_sol": 0.10,
                    "budget_reason": "armed_new_entry_size",
                    "size_clamp_reason": "no_clamp",
                },
            }
        ]
    )
    repo.strategy_state_transitions.extend(
        [
            {
                "analysis_run_id": 14301,
                "ca": "CA_EXPORT_RUNNER_TRADE",
                "from_state": "OBSERVING",
                "to_state": "ARMED",
                "action": "",
                "source": "test",
                "path_kind": "MAIN_STATE_MACHINE",
                "legacy_path": False,
                "transition_reason": "",
                "metadata": {},
            },
            {
                "analysis_run_id": 14301,
                "ca": "CA_EXPORT_RUNNER_TRADE",
                "from_state": "MANAGING",
                "to_state": "EXITED",
                "action": "",
                "source": "test",
                "path_kind": "MAIN_STATE_MACHINE",
                "legacy_path": False,
                "transition_reason": "",
                "metadata": {},
            },
            {
                "analysis_run_id": 14302,
                "ca": "CA_EXPORT_RUNNER_WATCH",
                "from_state": "OBSERVING",
                "to_state": "REJECTED",
                "action": "",
                "source": "test",
                "path_kind": "MAIN_STATE_MACHINE",
                "legacy_path": False,
                "transition_reason": "reject_blocking_risk_flags",
                "metadata": {},
            },
        ]
    )


def _seed_paper_repo(repo: InMemoryPaperLedgerRepository) -> None:
    repo.trade_closes.extend(
        [
            {
                "trade_close_id": "close_export_runner_trade_1",
                "position_id": "pos_export_runner_trade_1",
                "order_id": "ord_export_runner_trade_1",
                "fill_id": "fill_export_runner_trade_1",
                "analysis_run_id": 14301,
                "ca": "CA_EXPORT_RUNNER_TRADE",
                "strategy": "SMART_TREND",
                "opened_at": 1700000000.0,
                "closed_at": 1700000500.0,
                "close_reason": "CLOSED_TP",
                "partial": False,
                "close_ratio": 1.0,
                "entry_notional_sol": 0.10,
                "exit_notional_sol": 0.14,
                "total_fee_sol": 0.01,
                "realized_pnl_sol": 0.04,
                "realized_return_pct": 40.0,
                "source": "test",
                "path_kind": "MAIN_STATE_MACHINE",
                "legacy_path": False,
                "metadata": {},
            }
        ]
    )


def _install_phase14_sources(monkeypatch) -> None:
    sample_repo = InMemoryTrainingSampleRepository()
    label_repo = InMemoryTrainingLabelRepository()
    lifecycle_repo = InMemoryLifecycleRepository()
    paper_repo = InMemoryPaperLedgerRepository()
    _seed_sample_repo(sample_repo)
    _seed_label_repo(label_repo)
    _seed_lifecycle_repo(lifecycle_repo)
    _seed_paper_repo(paper_repo)

    monkeypatch.setattr(phase14_export, "training_sample_repository", sample_repo)
    monkeypatch.setattr(phase14_export, "training_label_repository", label_repo)
    monkeypatch.setattr(phase14_export, "lifecycle_repository", lifecycle_repo)
    monkeypatch.setattr(phase14_export, "paper_ledger_repository", paper_repo)


def test_phase14_feedback_export_runner_reads_existing_distributed_inputs_without_touching_old_exporters(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _install_phase14_sources(monkeypatch)

    training_replay = tmp_path / "data" / "training_replay_records.json"
    training_dataset = tmp_path / "data" / "training_dataset_bridge.csv"
    replay_dataset = tmp_path / "data" / "replay_dataset_bridge.json"
    training_replay.parent.mkdir(parents=True, exist_ok=True)
    training_replay.write_text("keep-old-training-replay", encoding="utf-8")
    training_dataset.write_text("keep-old-training-dataset", encoding="utf-8")
    replay_dataset.write_text("keep-old-replay-dataset", encoding="utf-8")

    result = phase14_export.run_phase14_feedback_export()

    assert result["status"] == "success"
    assert result["feedback_export_records_path"].endswith("feedback_export_records.json")
    assert result["feedback_manifest_path"].endswith("phase14_feedback_manifest.json")

    records_path = Path(result["feedback_export_records_path"])
    manifest_path = Path(result["feedback_manifest_path"])
    assert records_path.exists()
    assert manifest_path.exists()

    payload = json.loads(records_path.read_text(encoding="utf-8"))
    rows = payload.get("records", []) or []
    assert {row["sample_id"] for row in rows} == {
        "sample_export_runner_trade_1",
        "sample_export_runner_watch_1",
    }
    trade_row = next(row for row in rows if row["sample_id"] == "sample_export_runner_trade_1")
    assert trade_row["sizing_feedback"]["budget_reason"] == "armed_new_entry_size"
    assert trade_row["sizing_feedback"]["effective_allocated_size"] == 0.10

    assert training_replay.read_text(encoding="utf-8") == "keep-old-training-replay"
    assert training_dataset.read_text(encoding="utf-8") == "keep-old-training-dataset"
    assert replay_dataset.read_text(encoding="utf-8") == "keep-old-replay-dataset"


def test_phase14_feedback_export_runner_can_repeat_and_stays_within_data_dir(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _install_phase14_sources(monkeypatch)

    first = phase14_export.run_phase14_feedback_export()
    second = phase14_export.run_phase14_feedback_export()

    assert first["status"] == "success"
    assert second["status"] == "success"
    assert first["feedback_export_records_path"] == second["feedback_export_records_path"]
    assert first["feedback_manifest_path"] == second["feedback_manifest_path"]
    assert str((tmp_path / "data").resolve()) in first["feedback_export_records_path"]
    assert str((tmp_path / "data").resolve()) in first["feedback_manifest_path"]


def test_phase14_feedback_export_runner_fails_loudly_when_required_inputs_are_missing(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(phase14_export, "training_sample_repository", InMemoryTrainingSampleRepository())
    monkeypatch.setattr(phase14_export, "training_label_repository", InMemoryTrainingLabelRepository())
    monkeypatch.setattr(phase14_export, "lifecycle_repository", InMemoryLifecycleRepository())
    monkeypatch.setattr(phase14_export, "paper_ledger_repository", InMemoryPaperLedgerRepository())

    try:
        phase14_export.run_phase14_feedback_export()
        raise AssertionError("expected export runner to fail on missing training samples")
    except RuntimeError as exc:
        assert "training samples missing" in str(exc)
