import json
from pathlib import Path

import pytest

import run_phase25_feedback_release_snapshot as phase25_runner


def _write_phase24_summary(data_dir: Path) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    summary_path = data_dir / "phase24_feedback_control_history_daily_summary.json"
    summary_path.write_text(
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
                "records_count": 2,
                "latest_run_id": "phase22-run-002",
                "manual_check_points": ["review phase24 summary"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return summary_path


def test_phase25_feedback_release_snapshot_runner_reads_phase24_summary_and_writes_snapshot(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    summary_path = _write_phase24_summary(tmp_path / "data")

    result = phase25_runner.run_phase25_feedback_release_snapshot()

    snapshot_path = tmp_path / "data" / "phase25_feedback_release_snapshot.json"
    assert Path(result["phase24_feedback_control_history_daily_summary_path"]) == summary_path.resolve()
    assert Path(result["snapshot_path"]) == snapshot_path.resolve()
    assert snapshot_path.exists()

    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert payload["status"] == "success"
    assert payload["failed_stage"] is None
    assert payload["error_type"] is None
    assert payload["error_message"] is None
    assert payload["phase22_feedback_control_history_path"].endswith("phase22_feedback_control_history.json")
    assert payload["phase22_feedback_control_latest_path"].endswith("phase22_feedback_control_latest.json")
    assert payload["phase23_feedback_control_history_acceptance_report_path"].endswith(
        "phase23_feedback_control_history_acceptance_report.json"
    )
    assert payload["phase24_feedback_control_history_daily_summary_path"].endswith(
        "phase24_feedback_control_history_daily_summary.json"
    )
    assert payload["records_count"] == 2
    assert payload["latest_run_id"] == "phase22-run-002"
    assert payload["created_at"]


def test_phase25_feedback_release_snapshot_runner_fails_when_phase24_summary_missing(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    with pytest.raises(FileNotFoundError, match="phase24 feedback control history daily summary missing"):
        phase25_runner.run_phase25_feedback_release_snapshot()
