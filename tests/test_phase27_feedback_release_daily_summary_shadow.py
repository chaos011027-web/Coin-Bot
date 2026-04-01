import json
from pathlib import Path

from modules.phase27_feedback_release_daily_summary import (
    build_phase27_feedback_release_daily_failure_summary,
    build_phase27_feedback_release_daily_success_summary,
    write_phase27_feedback_release_daily_summary,
)


def test_phase27_feedback_release_daily_summary_builds_success_payload_without_revalidating_phase25_or_phase26(tmp_path):
    phase25_result = {
        "snapshot_path": str((tmp_path / "data" / "phase25_feedback_release_snapshot.json").resolve()),
        "snapshot": {
            "records_count": 2,
            "latest_run_id": "phase22-run-002",
        },
    }
    phase26_result = {
        "status": "success",
        "failed_stage": None,
        "error_type": None,
        "error_message": None,
        "phase25_feedback_release_snapshot_path": phase25_result["snapshot_path"],
        "records_count": 2,
        "latest_run_id": "phase22-run-002",
        "manual_check_points": ["review phase26 report"],
        "report_path": str((tmp_path / "data" / "phase26_feedback_release_snapshot_acceptance_report.json").resolve()),
    }

    summary = build_phase27_feedback_release_daily_success_summary(
        phase25_result=phase25_result,
        phase26_result=phase26_result,
    )

    assert summary["status"] == "success"
    assert summary["failed_stage"] is None
    assert summary["error_type"] is None
    assert summary["error_message"] is None
    assert summary["phase25_feedback_release_snapshot_path"].endswith("phase25_feedback_release_snapshot.json")
    assert summary["phase26_feedback_release_snapshot_acceptance_report_path"].endswith(
        "phase26_feedback_release_snapshot_acceptance_report.json"
    )
    assert summary["records_count"] == 2
    assert summary["latest_run_id"] == "phase22-run-002"
    assert summary["manual_check_points"]


def test_phase27_feedback_release_daily_summary_builds_failure_payload_and_writes_file(tmp_path):
    data_dir = tmp_path / "data"
    summary = build_phase27_feedback_release_daily_failure_summary(
        failed_stage="phase26_release_snapshot_acceptance",
        error=RuntimeError("phase26 acceptance failed"),
        data_dir=str(data_dir),
        phase25_result={
            "snapshot_path": str((data_dir / "phase25_feedback_release_snapshot.json").resolve()),
        },
    )

    assert summary["status"] == "failure"
    assert summary["failed_stage"] == "phase26_release_snapshot_acceptance"
    assert summary["error_type"] == "RuntimeError"
    assert summary["error_message"] == "phase26 acceptance failed"
    assert summary["phase25_feedback_release_snapshot_path"].endswith("phase25_feedback_release_snapshot.json")
    assert summary["phase26_feedback_release_snapshot_acceptance_report_path"].endswith(
        "phase26_feedback_release_snapshot_acceptance_report.json"
    )
    assert summary["records_count"] is None
    assert summary["latest_run_id"] is None
    assert summary["manual_check_points"]

    output_path = data_dir / "phase27_feedback_release_daily_summary.json"
    written_path = write_phase27_feedback_release_daily_summary(summary, output_path=str(output_path))

    assert Path(written_path) == output_path.resolve()
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["status"] == "failure"
    assert payload["failed_stage"] == "phase26_release_snapshot_acceptance"
