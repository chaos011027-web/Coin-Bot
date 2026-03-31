import json
from pathlib import Path

import pytest

import run_phase17_feedback_history_acceptance as phase17_runner


def _write_valid_phase16_payloads(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "run_id": "phase16-run-001",
        "status": "success",
        "failed_stage": None,
        "error_type": None,
        "error_message": None,
        "feedback_export_records_path": str((data_dir / "feedback_export_records.json").resolve()),
        "feedback_manifest_path": str((data_dir / "phase14_feedback_manifest.json").resolve()),
        "phase14_feedback_acceptance_report_path": str((data_dir / "phase14_feedback_acceptance_report.json").resolve()),
        "phase15_feedback_daily_summary_path": str((data_dir / "phase15_feedback_daily_summary.json").resolve()),
        "records_count": 2,
        "created_at": "2026-03-31T12:00:00Z",
    }
    history_payload = {
        "records": [record],
        "records_count": 1,
        "latest_run_id": "phase16-run-001",
    }
    latest_payload = dict(record)
    (data_dir / "phase16_feedback_daily_history.json").write_text(
        json.dumps(history_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (data_dir / "phase16_feedback_daily_latest.json").write_text(
        json.dumps(latest_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def test_phase17_feedback_history_acceptance_runner_writes_success_report_by_default(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _write_valid_phase16_payloads(tmp_path / "data")

    result = phase17_runner.run_phase17_feedback_history_acceptance()

    assert result["status"] == "success"
    assert result["failed_stage"] is None
    assert result["error_type"] is None
    assert result["error_message"] is None
    assert result["phase16_feedback_daily_history_path"].endswith("phase16_feedback_daily_history.json")
    assert result["phase16_feedback_daily_latest_path"].endswith("phase16_feedback_daily_latest.json")
    assert result["records_count"] == 1
    assert result["latest_run_id"] == "phase16-run-001"
    assert result["manual_check_points"]
    assert result["report_path"].endswith("phase17_feedback_history_acceptance_report.json")

    report_path = Path(result["report_path"])
    assert report_path.exists()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["status"] == "success"
    assert payload["records_count"] == 1
    assert payload["latest_run_id"] == "phase16-run-001"


def test_phase17_feedback_history_acceptance_runner_writes_failure_report_when_history_missing(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)

    with pytest.raises(FileNotFoundError, match="phase16 feedback history missing"):
        phase17_runner.run_phase17_feedback_history_acceptance()

    report_path = tmp_path / "data" / "phase17_feedback_history_acceptance_report.json"
    assert report_path.exists()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["status"] == "failure"
    assert payload["failed_stage"] == "phase16_history_load"
    assert payload["error_type"] == "FileNotFoundError"
    assert payload["phase16_feedback_daily_history_path"].endswith("phase16_feedback_daily_history.json")
    assert payload["phase16_feedback_daily_latest_path"].endswith("phase16_feedback_daily_latest.json")


def test_phase17_feedback_history_acceptance_runner_writes_failure_report_when_latest_missing(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    data_dir = tmp_path / "data"
    _write_valid_phase16_payloads(data_dir)
    (data_dir / "phase16_feedback_daily_latest.json").unlink()

    with pytest.raises(FileNotFoundError, match="phase16 feedback latest missing"):
        phase17_runner.run_phase17_feedback_history_acceptance()

    report_path = data_dir / "phase17_feedback_history_acceptance_report.json"
    assert report_path.exists()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["status"] == "failure"
    assert payload["failed_stage"] == "phase16_latest_load"
    assert payload["error_type"] == "FileNotFoundError"


def test_phase17_feedback_history_acceptance_runner_writes_failure_report_when_validator_fails(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    data_dir = tmp_path / "data"
    _write_valid_phase16_payloads(data_dir)
    broken_history = json.loads((data_dir / "phase16_feedback_daily_history.json").read_text(encoding="utf-8"))
    broken_history["latest_run_id"] = "phase16-run-mismatch"
    (data_dir / "phase16_feedback_daily_history.json").write_text(
        json.dumps(broken_history, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="latest_run_id mismatch"):
        phase17_runner.run_phase17_feedback_history_acceptance()

    report_path = data_dir / "phase17_feedback_history_acceptance_report.json"
    assert report_path.exists()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["status"] == "failure"
    assert payload["failed_stage"] == "phase17_history_validator"
    assert payload["error_type"] == "RuntimeError"
    assert payload["records_count"] is None
    assert payload["latest_run_id"] is None
