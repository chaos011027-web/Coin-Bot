import json
from pathlib import Path

import pytest

import run_phase14_feedback_acceptance as phase14_acceptance
import run_phase14_feedback_export as phase14_export
from modules.lifecycle_repository import InMemoryLifecycleRepository
from modules.paper_ledger_repository import InMemoryPaperLedgerRepository
from modules.training_label_builder import InMemoryTrainingLabelRepository
from modules.training_sample_builder import InMemoryTrainingSampleRepository


def _install_phase14_sources(monkeypatch) -> None:
    sample_repo = InMemoryTrainingSampleRepository()
    label_repo = InMemoryTrainingLabelRepository()
    lifecycle_repo = InMemoryLifecycleRepository()
    paper_repo = InMemoryPaperLedgerRepository()

    sample_repo.samples.append(
        {
            "sample_id": "sample_acceptance_trade_1",
            "analysis_run_id": 14401,
            "ca": "CA_ACCEPTANCE_TRADE",
            "trace_link": "CA_ACCEPTANCE_TRADE:11:22",
            "final_action": "ENTER",
            "strategy_id": "SMART_TREND",
            "path_kind": "MAIN_STATE_MACHINE",
            "source": "test",
            "legacy_path": False,
            "frozen_features": {},
            "feature_sources": {},
            "metadata": {},
        }
    )
    label_repo.labels.append(
        {
            "sample_id": "sample_acceptance_trade_1",
            "analysis_run_id": 14401,
            "ca": "CA_ACCEPTANCE_TRADE",
            "label_kind": "trade_closed",
            "label_source": "paper_trade_closes",
            "position_ids": ["pos_acceptance_trade_1"],
            "close_legs": 1,
            "close_reasons": ["CLOSED_TP"],
            "realized_pnl_sol": 0.35,
            "realized_return_pct": 35.0,
            "metadata": {},
        }
    )
    lifecycle_repo.execution_events.append(
        {
            "analysis_run_id": 14401,
            "ca": "CA_ACCEPTANCE_TRADE",
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
    )
    lifecycle_repo.strategy_state_transitions.append(
        {
            "analysis_run_id": 14401,
            "ca": "CA_ACCEPTANCE_TRADE",
            "from_state": "MANAGING",
            "to_state": "EXITED",
            "action": "",
            "source": "test",
            "path_kind": "MAIN_STATE_MACHINE",
            "legacy_path": False,
            "transition_reason": "",
            "metadata": {},
        }
    )
    paper_repo.trade_closes.append(
        {
            "trade_close_id": "close_acceptance_trade_1",
            "position_id": "pos_acceptance_trade_1",
            "order_id": "ord_acceptance_trade_1",
            "fill_id": "fill_acceptance_trade_1",
            "analysis_run_id": 14401,
            "ca": "CA_ACCEPTANCE_TRADE",
            "strategy": "SMART_TREND",
            "opened_at": 1700000000.0,
            "closed_at": 1700000500.0,
            "close_reason": "CLOSED_TP",
            "partial": False,
            "close_ratio": 1.0,
            "entry_notional_sol": 0.10,
            "exit_notional_sol": 0.135,
            "total_fee_sol": 0.01,
            "realized_pnl_sol": 0.035,
            "realized_return_pct": 35.0,
            "source": "test",
            "path_kind": "MAIN_STATE_MACHINE",
            "legacy_path": False,
            "metadata": {},
        }
    )

    monkeypatch.setattr(phase14_export, "training_sample_repository", sample_repo)
    monkeypatch.setattr(phase14_export, "training_label_repository", label_repo)
    monkeypatch.setattr(phase14_export, "lifecycle_repository", lifecycle_repo)
    monkeypatch.setattr(phase14_export, "paper_ledger_repository", paper_repo)


def test_phase14_feedback_acceptance_runner_writes_success_report_by_default(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _install_phase14_sources(monkeypatch)

    result = phase14_acceptance.run_phase14_feedback_acceptance()

    assert result["status"] == "success"
    assert result["failed_stage"] is None
    assert result["error_type"] is None
    assert result["error_message"] is None
    assert result["feedback_export_records_path"].endswith("feedback_export_records.json")
    assert result["feedback_manifest_path"].endswith("phase14_feedback_manifest.json")
    assert result["report_path"].endswith("phase14_feedback_acceptance_report.json")
    assert result["manual_check_points"]

    report_path = Path(result["report_path"])
    assert report_path.exists()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["status"] == "success"
    assert payload["failed_stage"] is None
    assert payload["error_type"] is None
    assert payload["error_message"] is None
    assert payload["manual_check_points"]
    assert payload["records_count"] == 1


def test_phase14_feedback_acceptance_runner_writes_failure_report_when_export_fails(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(phase14_export, "training_sample_repository", InMemoryTrainingSampleRepository())
    monkeypatch.setattr(phase14_export, "training_label_repository", InMemoryTrainingLabelRepository())
    monkeypatch.setattr(phase14_export, "lifecycle_repository", InMemoryLifecycleRepository())
    monkeypatch.setattr(phase14_export, "paper_ledger_repository", InMemoryPaperLedgerRepository())

    with pytest.raises(RuntimeError, match="training samples missing"):
        phase14_acceptance.run_phase14_feedback_acceptance()

    report_path = tmp_path / "data" / "phase14_feedback_acceptance_report.json"
    assert report_path.exists()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["status"] == "failure"
    assert payload["failed_stage"] == "phase14_export"
    assert payload["error_type"] == "RuntimeError"
    assert payload["feedback_export_records_path"].endswith("feedback_export_records.json")
    assert payload["feedback_manifest_path"].endswith("phase14_feedback_manifest.json")
    assert payload["manual_check_points"]


def test_phase14_feedback_acceptance_runner_writes_failure_report_when_validator_fails(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _install_phase14_sources(monkeypatch)
    phase14_export.run_phase14_feedback_export()

    records_path = tmp_path / "data" / "feedback_export_records.json"
    payload = json.loads(records_path.read_text(encoding="utf-8"))
    payload["records"][0]["feedback_class"] = "trade_closed"
    records_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    with pytest.raises(RuntimeError, match="unsupported feedback_class"):
        phase14_acceptance.run_phase14_feedback_acceptance(skip_export=True)

    report_path = tmp_path / "data" / "phase14_feedback_acceptance_report.json"
    assert report_path.exists()
    failure = json.loads(report_path.read_text(encoding="utf-8"))
    assert failure["status"] == "failure"
    assert failure["failed_stage"] == "phase14_validator"
    assert failure["error_type"] == "RuntimeError"
    assert failure["feedback_export_records_path"].endswith("feedback_export_records.json")
    assert failure["feedback_manifest_path"].endswith("phase14_feedback_manifest.json")
    assert failure["manual_check_points"]
