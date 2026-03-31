import json
from pathlib import Path

from modules.phase21_feedback_control_daily_summary import (
    build_phase21_feedback_control_daily_failure_summary,
    build_phase21_feedback_control_daily_success_summary,
    write_phase21_feedback_control_daily_summary,
)


def test_phase21_feedback_control_daily_summary_builds_success_payload_without_revalidating_phase19_or_phase20(tmp_path):
    phase19_result = {
        "snapshot_path": str((tmp_path / "data" / "phase19_feedback_control_snapshot.json").resolve()),
        "snapshot": {
            "records_count": 2,
            "latest_run_id": "phase16-run-002",
        },
    }
    phase20_result = {
        "status": "success",
        "failed_stage": None,
        "error_type": None,
        "error_message": None,
        "phase19_feedback_control_snapshot_path": phase19_result["snapshot_path"],
        "records_count": 2,
        "latest_run_id": "phase16-run-002",
        "manual_check_points": ["review phase20 report"],
        "report_path": str((tmp_path / "data" / "phase20_feedback_control_snapshot_acceptance_report.json").resolve()),
    }

    summary = build_phase21_feedback_control_daily_success_summary(
        phase19_result=phase19_result,
        phase20_result=phase20_result,
    )

    assert summary["status"] == "success"
    assert summary["failed_stage"] is None
    assert summary["error_type"] is None
    assert summary["error_message"] is None
    assert summary["phase19_feedback_control_snapshot_path"].endswith("phase19_feedback_control_snapshot.json")
    assert summary["phase20_feedback_control_snapshot_acceptance_report_path"].endswith(
        "phase20_feedback_control_snapshot_acceptance_report.json"
    )
    assert summary["records_count"] == 2
    assert summary["latest_run_id"] == "phase16-run-002"
    assert summary["manual_check_points"]


def test_phase21_feedback_control_daily_summary_builds_failure_payload_and_writes_file(tmp_path):
    data_dir = tmp_path / "data"
    summary = build_phase21_feedback_control_daily_failure_summary(
        failed_stage="phase20_snapshot_acceptance",
        error=RuntimeError("phase20 acceptance failed"),
        data_dir=str(data_dir),
        phase19_result={
            "snapshot_path": str((data_dir / "phase19_feedback_control_snapshot.json").resolve()),
        },
    )

    assert summary["status"] == "failure"
    assert summary["failed_stage"] == "phase20_snapshot_acceptance"
    assert summary["error_type"] == "RuntimeError"
    assert summary["error_message"] == "phase20 acceptance failed"
    assert summary["phase19_feedback_control_snapshot_path"].endswith("phase19_feedback_control_snapshot.json")
    assert summary["phase20_feedback_control_snapshot_acceptance_report_path"].endswith(
        "phase20_feedback_control_snapshot_acceptance_report.json"
    )
    assert summary["records_count"] is None
    assert summary["latest_run_id"] is None
    assert summary["manual_check_points"]

    output_path = data_dir / "phase21_feedback_control_daily_summary.json"
    written_path = write_phase21_feedback_control_daily_summary(summary, output_path=str(output_path))

    assert Path(written_path) == output_path.resolve()
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["status"] == "failure"
    assert payload["failed_stage"] == "phase20_snapshot_acceptance"
