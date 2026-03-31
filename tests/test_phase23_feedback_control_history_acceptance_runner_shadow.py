import json
from pathlib import Path

import pytest

import run_phase23_feedback_control_history_acceptance as phase23_runner


def _write_valid_phase22_payloads(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "run_id": "phase22-run-001",
        "status": "success",
        "failed_stage": None,
        "error_type": None,
        "error_message": None,
        "phase19_feedback_control_snapshot_path": str((data_dir / "phase19_feedback_control_snapshot.json").resolve()),
        "phase20_feedback_control_snapshot_acceptance_report_path": str(
            (data_dir / "phase20_feedback_control_snapshot_acceptance_report.json").resolve()
        ),
        "phase21_feedback_control_daily_summary_path": str((data_dir / "phase21_feedback_control_daily_summary.json").resolve()),
        "records_count": 2,
        "latest_run_id": "phase16-run-002",
        "created_at": "2026-03-31T13:00:00Z",
    }
    history_payload = {
        "records": [record],
        "records_count": 1,
        "latest_run_id": "phase22-run-001",
    }
    latest_payload = dict(record)
    (data_dir / "phase22_feedback_control_history.json").write_text(
        json.dumps(history_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (data_dir / "phase22_feedback_control_latest.json").write_text(
        json.dumps(latest_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def test_phase23_feedback_control_history_acceptance_runner_writes_success_report(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _write_valid_phase22_payloads(tmp_path / "data")

    result = phase23_runner.run_phase23_feedback_control_history_acceptance()

    assert result["status"] == "success"
    assert result["failed_stage"] is None
    assert result["error_type"] is None
    assert result["error_message"] is None
    assert result["phase22_feedback_control_history_path"].endswith("phase22_feedback_control_history.json")
    assert result["phase22_feedback_control_latest_path"].endswith("phase22_feedback_control_latest.json")
    assert result["records_count"] == 1
    assert result["latest_run_id"] == "phase22-run-001"
    assert result["manual_check_points"]

    report_path = Path(result["report_path"])
    assert report_path.exists()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["status"] == "success"
    assert payload["records_count"] == 1
    assert payload["latest_run_id"] == "phase22-run-001"


def test_phase23_feedback_control_history_acceptance_runner_writes_failure_report_when_history_missing(
    monkeypatch,
    tmp_path,
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)

    with pytest.raises(FileNotFoundError, match="phase22 feedback control history missing"):
        phase23_runner.run_phase23_feedback_control_history_acceptance()

    report_path = tmp_path / "data" / "phase23_feedback_control_history_acceptance_report.json"
    assert report_path.exists()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["status"] == "failure"
    assert payload["failed_stage"] == "phase22_control_history_load"


def test_phase23_feedback_control_history_acceptance_runner_writes_failure_report_when_latest_missing(
    monkeypatch,
    tmp_path,
):
    monkeypatch.chdir(tmp_path)
    data_dir = tmp_path / "data"
    _write_valid_phase22_payloads(data_dir)
    (data_dir / "phase22_feedback_control_latest.json").unlink()

    with pytest.raises(FileNotFoundError, match="phase22 feedback control latest missing"):
        phase23_runner.run_phase23_feedback_control_history_acceptance()

    report_path = data_dir / "phase23_feedback_control_history_acceptance_report.json"
    assert report_path.exists()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["status"] == "failure"
    assert payload["failed_stage"] == "phase22_control_latest_load"


def test_phase23_feedback_control_history_acceptance_runner_writes_failure_report_when_validator_fails(
    monkeypatch,
    tmp_path,
):
    monkeypatch.chdir(tmp_path)
    data_dir = tmp_path / "data"
    _write_valid_phase22_payloads(data_dir)
    broken_history = json.loads((data_dir / "phase22_feedback_control_history.json").read_text(encoding="utf-8"))
    broken_history["latest_run_id"] = "phase22-run-mismatch"
    (data_dir / "phase22_feedback_control_history.json").write_text(
        json.dumps(broken_history, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="latest_run_id mismatch"):
        phase23_runner.run_phase23_feedback_control_history_acceptance()

    report_path = data_dir / "phase23_feedback_control_history_acceptance_report.json"
    assert report_path.exists()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["status"] == "failure"
    assert payload["failed_stage"] == "phase23_control_history_validator"
