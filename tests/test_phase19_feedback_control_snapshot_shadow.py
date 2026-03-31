import json
from pathlib import Path

from modules.phase19_feedback_control_snapshot import (
    build_phase19_feedback_control_snapshot,
    write_phase19_feedback_control_snapshot,
)


def test_phase19_feedback_control_snapshot_builds_compact_snapshot_from_phase18_summary(tmp_path):
    summary = {
        "status": "success",
        "failed_stage": None,
        "error_type": None,
        "error_message": None,
        "phase16_feedback_daily_history_path": str((tmp_path / "data" / "phase16_feedback_daily_history.json").resolve()),
        "phase16_feedback_daily_latest_path": str((tmp_path / "data" / "phase16_feedback_daily_latest.json").resolve()),
        "phase17_feedback_history_acceptance_report_path": str(
            (tmp_path / "data" / "phase17_feedback_history_acceptance_report.json").resolve()
        ),
        "records_count": 2,
        "latest_run_id": "phase16-run-002",
    }

    snapshot = build_phase19_feedback_control_snapshot(
        phase18_summary=summary,
        phase18_summary_path=str((tmp_path / "data" / "phase18_feedback_history_daily_summary.json").resolve()),
        created_at="2026-03-31T12:30:00Z",
    )

    assert snapshot["status"] == "success"
    assert snapshot["failed_stage"] is None
    assert snapshot["error_type"] is None
    assert snapshot["error_message"] is None
    assert snapshot["phase16_feedback_daily_history_path"].endswith("phase16_feedback_daily_history.json")
    assert snapshot["phase16_feedback_daily_latest_path"].endswith("phase16_feedback_daily_latest.json")
    assert snapshot["phase17_feedback_history_acceptance_report_path"].endswith(
        "phase17_feedback_history_acceptance_report.json"
    )
    assert snapshot["phase18_feedback_history_daily_summary_path"].endswith(
        "phase18_feedback_history_daily_summary.json"
    )
    assert snapshot["records_count"] == 2
    assert snapshot["latest_run_id"] == "phase16-run-002"
    assert snapshot["created_at"] == "2026-03-31T12:30:00Z"


def test_phase19_feedback_control_snapshot_writes_snapshot_payload(tmp_path):
    snapshot = {
        "status": "failure",
        "failed_stage": "phase17_history_acceptance",
        "error_type": "RuntimeError",
        "error_message": "phase17 acceptance failed",
        "phase16_feedback_daily_history_path": str((tmp_path / "data" / "phase16_feedback_daily_history.json").resolve()),
        "phase16_feedback_daily_latest_path": str((tmp_path / "data" / "phase16_feedback_daily_latest.json").resolve()),
        "phase17_feedback_history_acceptance_report_path": str(
            (tmp_path / "data" / "phase17_feedback_history_acceptance_report.json").resolve()
        ),
        "phase18_feedback_history_daily_summary_path": str(
            (tmp_path / "data" / "phase18_feedback_history_daily_summary.json").resolve()
        ),
        "records_count": None,
        "latest_run_id": None,
        "created_at": "2026-03-31T12:35:00Z",
    }

    output_path = tmp_path / "data" / "phase19_feedback_control_snapshot.json"
    written_path = write_phase19_feedback_control_snapshot(snapshot, output_path=str(output_path))

    assert Path(written_path) == output_path.resolve()
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["status"] == "failure"
    assert payload["failed_stage"] == "phase17_history_acceptance"
