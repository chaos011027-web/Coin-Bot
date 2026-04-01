import json
from pathlib import Path

import pytest

import run_phase26_feedback_release_snapshot_acceptance as phase26_runner


def _write_snapshot(data_dir: Path, *, created_at: str = "2026-04-01T09:00:00Z") -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = data_dir / "phase25_feedback_release_snapshot.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "status": "success",
                "failed_stage": None,
                "error_type": None,
                "error_message": None,
                "phase22_feedback_control_history_path": str((data_dir / "phase22_feedback_control_history.json").resolve()),
                "phase22_feedback_control_latest_path": str((data_dir / "phase22_feedback_control_latest.json").resolve()),
                "phase23_feedback_control_history_acceptance_report_path": str(
                    (data_dir / "phase23_feedback_control_history_acceptance_report.json").resolve()
                ),
                "phase24_feedback_control_history_daily_summary_path": str(
                    (data_dir / "phase24_feedback_control_history_daily_summary.json").resolve()
                ),
                "records_count": 2,
                "latest_run_id": "phase22-run-002",
                "created_at": created_at,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return snapshot_path


def test_phase26_feedback_release_snapshot_acceptance_runner_writes_success_report(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _write_snapshot(tmp_path / "data")

    result = phase26_runner.run_phase26_feedback_release_snapshot_acceptance()

    assert result["status"] == "success"
    assert result["failed_stage"] is None
    assert result["error_type"] is None
    assert result["error_message"] is None
    assert result["phase25_feedback_release_snapshot_path"].endswith("phase25_feedback_release_snapshot.json")
    assert result["records_count"] == 2
    assert result["latest_run_id"] == "phase22-run-002"
    assert result["manual_check_points"]

    report_path = Path(result["report_path"])
    assert report_path.exists()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["status"] == "success"
    assert payload["records_count"] == 2
    assert payload["latest_run_id"] == "phase22-run-002"


def test_phase26_feedback_release_snapshot_acceptance_runner_writes_failure_report_when_snapshot_missing(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    with pytest.raises(FileNotFoundError, match="phase25 feedback release snapshot missing"):
        phase26_runner.run_phase26_feedback_release_snapshot_acceptance()

    report_path = tmp_path / "data" / "phase26_feedback_release_snapshot_acceptance_report.json"
    assert report_path.exists()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["status"] == "failure"
    assert payload["failed_stage"] == "phase25_release_snapshot_load"
    assert payload["error_type"] == "FileNotFoundError"


def test_phase26_feedback_release_snapshot_acceptance_runner_writes_failure_report_when_validator_fails(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    data_dir = tmp_path / "data"
    snapshot_path = _write_snapshot(data_dir, created_at="")
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    payload["created_at"] = ""
    snapshot_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    with pytest.raises(RuntimeError, match="required field missing: created_at"):
        phase26_runner.run_phase26_feedback_release_snapshot_acceptance()

    report_path = data_dir / "phase26_feedback_release_snapshot_acceptance_report.json"
    assert report_path.exists()
    failure = json.loads(report_path.read_text(encoding="utf-8"))
    assert failure["status"] == "failure"
    assert failure["failed_stage"] == "phase26_release_snapshot_validator"
    assert failure["error_type"] == "RuntimeError"
    assert failure["records_count"] is None
    assert failure["latest_run_id"] is None
