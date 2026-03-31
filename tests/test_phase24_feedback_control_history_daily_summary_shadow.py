import json
from pathlib import Path

from modules.phase24_feedback_control_history_daily_summary import (
    build_phase24_feedback_control_history_daily_failure_summary,
    build_phase24_feedback_control_history_daily_success_summary,
    write_phase24_feedback_control_history_daily_summary,
)


def test_phase24_feedback_control_history_daily_summary_builds_success_payload_without_revalidating_phase22_or_phase23(
    tmp_path,
):
    phase22_result = {
        "history_path": str((tmp_path / "data" / "phase22_feedback_control_history.json").resolve()),
        "latest_path": str((tmp_path / "data" / "phase22_feedback_control_latest.json").resolve()),
        "history": {
            "records_count": 2,
            "latest_run_id": "phase22-run-002",
        },
    }
    phase23_result = {
        "status": "success",
        "failed_stage": None,
        "error_type": None,
        "error_message": None,
        "phase22_feedback_control_history_path": phase22_result["history_path"],
        "phase22_feedback_control_latest_path": phase22_result["latest_path"],
        "records_count": 2,
        "latest_run_id": "phase22-run-002",
        "manual_check_points": ["review phase23 report"],
        "report_path": str((tmp_path / "data" / "phase23_feedback_control_history_acceptance_report.json").resolve()),
    }

    summary = build_phase24_feedback_control_history_daily_success_summary(
        phase22_result=phase22_result,
        phase23_result=phase23_result,
    )

    assert summary["status"] == "success"
    assert summary["failed_stage"] is None
    assert summary["error_type"] is None
    assert summary["error_message"] is None
    assert summary["phase22_feedback_control_history_path"].endswith("phase22_feedback_control_history.json")
    assert summary["phase22_feedback_control_latest_path"].endswith("phase22_feedback_control_latest.json")
    assert summary["phase23_feedback_control_history_acceptance_report_path"].endswith(
        "phase23_feedback_control_history_acceptance_report.json"
    )
    assert summary["records_count"] == 2
    assert summary["latest_run_id"] == "phase22-run-002"
    assert summary["manual_check_points"]


def test_phase24_feedback_control_history_daily_summary_builds_failure_payload_and_writes_file(tmp_path):
    data_dir = tmp_path / "data"
    summary = build_phase24_feedback_control_history_daily_failure_summary(
        failed_stage="phase23_control_history_acceptance",
        error=RuntimeError("phase23 acceptance failed"),
        data_dir=str(data_dir),
        phase22_result={
            "history_path": str((data_dir / "phase22_feedback_control_history.json").resolve()),
            "latest_path": str((data_dir / "phase22_feedback_control_latest.json").resolve()),
            "history": {
                "records_count": 2,
                "latest_run_id": "phase22-run-002",
            },
        },
    )

    assert summary["status"] == "failure"
    assert summary["failed_stage"] == "phase23_control_history_acceptance"
    assert summary["error_type"] == "RuntimeError"
    assert summary["error_message"] == "phase23 acceptance failed"
    assert summary["phase22_feedback_control_history_path"].endswith("phase22_feedback_control_history.json")
    assert summary["phase22_feedback_control_latest_path"].endswith("phase22_feedback_control_latest.json")
    assert summary["phase23_feedback_control_history_acceptance_report_path"].endswith(
        "phase23_feedback_control_history_acceptance_report.json"
    )
    assert summary["records_count"] == 2
    assert summary["latest_run_id"] == "phase22-run-002"
    assert summary["manual_check_points"]

    output_path = data_dir / "phase24_feedback_control_history_daily_summary.json"
    written_path = write_phase24_feedback_control_history_daily_summary(summary, output_path=str(output_path))

    assert Path(written_path) == output_path.resolve()
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["status"] == "failure"
    assert payload["failed_stage"] == "phase23_control_history_acceptance"
