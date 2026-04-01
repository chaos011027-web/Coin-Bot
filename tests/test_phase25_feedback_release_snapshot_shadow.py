import json
from pathlib import Path

from modules.phase25_feedback_release_snapshot import (
    build_phase25_feedback_release_snapshot,
    write_phase25_feedback_release_snapshot,
)


def test_phase25_feedback_release_snapshot_builds_compact_snapshot_from_phase24_summary(tmp_path):
    summary = {
        "status": "success",
        "failed_stage": None,
        "error_type": None,
        "error_message": None,
        "phase22_feedback_control_history_path": str((tmp_path / "data" / "phase22_feedback_control_history.json").resolve()),
        "phase22_feedback_control_latest_path": str((tmp_path / "data" / "phase22_feedback_control_latest.json").resolve()),
        "phase23_feedback_control_history_acceptance_report_path": str(
            (tmp_path / "data" / "phase23_feedback_control_history_acceptance_report.json").resolve()
        ),
        "records_count": 2,
        "latest_run_id": "phase22-run-002",
    }

    snapshot = build_phase25_feedback_release_snapshot(
        phase24_summary=summary,
        phase24_summary_path=str((tmp_path / "data" / "phase24_feedback_control_history_daily_summary.json").resolve()),
        created_at="2026-04-01T09:00:00Z",
    )

    assert snapshot["status"] == "success"
    assert snapshot["failed_stage"] is None
    assert snapshot["error_type"] is None
    assert snapshot["error_message"] is None
    assert snapshot["phase22_feedback_control_history_path"].endswith("phase22_feedback_control_history.json")
    assert snapshot["phase22_feedback_control_latest_path"].endswith("phase22_feedback_control_latest.json")
    assert snapshot["phase23_feedback_control_history_acceptance_report_path"].endswith(
        "phase23_feedback_control_history_acceptance_report.json"
    )
    assert snapshot["phase24_feedback_control_history_daily_summary_path"].endswith(
        "phase24_feedback_control_history_daily_summary.json"
    )
    assert snapshot["records_count"] == 2
    assert snapshot["latest_run_id"] == "phase22-run-002"
    assert snapshot["created_at"] == "2026-04-01T09:00:00Z"


def test_phase25_feedback_release_snapshot_writes_snapshot_payload(tmp_path):
    snapshot = {
        "status": "failure",
        "failed_stage": "phase23_control_history_acceptance",
        "error_type": "RuntimeError",
        "error_message": "phase23 acceptance failed",
        "phase22_feedback_control_history_path": str((tmp_path / "data" / "phase22_feedback_control_history.json").resolve()),
        "phase22_feedback_control_latest_path": str((tmp_path / "data" / "phase22_feedback_control_latest.json").resolve()),
        "phase23_feedback_control_history_acceptance_report_path": str(
            (tmp_path / "data" / "phase23_feedback_control_history_acceptance_report.json").resolve()
        ),
        "phase24_feedback_control_history_daily_summary_path": str(
            (tmp_path / "data" / "phase24_feedback_control_history_daily_summary.json").resolve()
        ),
        "records_count": 1,
        "latest_run_id": "phase22-run-001",
        "created_at": "2026-04-01T09:05:00Z",
    }

    output_path = tmp_path / "data" / "phase25_feedback_release_snapshot.json"
    written_path = write_phase25_feedback_release_snapshot(snapshot, output_path=str(output_path))

    assert Path(written_path) == output_path.resolve()
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["status"] == "failure"
    assert payload["failed_stage"] == "phase23_control_history_acceptance"
