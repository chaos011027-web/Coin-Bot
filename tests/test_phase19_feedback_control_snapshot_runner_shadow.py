import json
from pathlib import Path

import pytest

import run_phase19_feedback_control_snapshot as phase19_runner


def _write_phase18_summary(data_dir: Path) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    summary_path = data_dir / "phase18_feedback_history_daily_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "status": "success",
                "failed_stage": None,
                "error_type": None,
                "error_message": None,
                "phase16_feedback_daily_history_path": str((data_dir / "phase16_feedback_daily_history.json").resolve()),
                "phase16_feedback_daily_latest_path": str((data_dir / "phase16_feedback_daily_latest.json").resolve()),
                "phase17_feedback_history_acceptance_report_path": str(
                    (data_dir / "phase17_feedback_history_acceptance_report.json").resolve()
                ),
                "records_count": 2,
                "latest_run_id": "phase16-run-002",
                "manual_check_points": ["review phase18 summary"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return summary_path


def test_phase19_feedback_control_snapshot_runner_reads_phase18_summary_and_writes_snapshot(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    summary_path = _write_phase18_summary(tmp_path / "data")

    result = phase19_runner.run_phase19_feedback_control_snapshot()

    snapshot_path = tmp_path / "data" / "phase19_feedback_control_snapshot.json"
    assert Path(result["phase18_feedback_history_daily_summary_path"]) == summary_path.resolve()
    assert Path(result["snapshot_path"]) == snapshot_path.resolve()
    assert snapshot_path.exists()

    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert payload["status"] == "success"
    assert payload["failed_stage"] is None
    assert payload["error_type"] is None
    assert payload["error_message"] is None
    assert payload["phase16_feedback_daily_history_path"].endswith("phase16_feedback_daily_history.json")
    assert payload["phase16_feedback_daily_latest_path"].endswith("phase16_feedback_daily_latest.json")
    assert payload["phase17_feedback_history_acceptance_report_path"].endswith(
        "phase17_feedback_history_acceptance_report.json"
    )
    assert payload["phase18_feedback_history_daily_summary_path"].endswith(
        "phase18_feedback_history_daily_summary.json"
    )
    assert payload["records_count"] == 2
    assert payload["latest_run_id"] == "phase16-run-002"
    assert payload["created_at"]


def test_phase19_feedback_control_snapshot_runner_fails_when_phase18_summary_missing(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    with pytest.raises(FileNotFoundError, match="phase18 feedback history daily summary missing"):
        phase19_runner.run_phase19_feedback_control_snapshot()
