import json
from pathlib import Path

from modules.phase15_feedback_daily_summary import (
    build_phase15_feedback_daily_failure_summary,
    build_phase15_feedback_daily_success_summary,
    write_phase15_feedback_daily_summary,
)


def test_phase15_feedback_daily_summary_builds_success_payload_without_revalidating_manifest(tmp_path):
    export_result = {
        "status": "success",
        "feedback_export_records_path": str((tmp_path / "data" / "feedback_export_records.json").resolve()),
        "feedback_manifest_path": str((tmp_path / "data" / "phase14_feedback_manifest.json").resolve()),
    }
    acceptance_result = {
        "status": "success",
        "failed_stage": None,
        "error_type": None,
        "error_message": None,
        "feedback_export_records_path": export_result["feedback_export_records_path"],
        "feedback_manifest_path": export_result["feedback_manifest_path"],
        "manual_check_points": ["review acceptance report"],
        "records_count": 2,
        "report_path": str((tmp_path / "data" / "phase14_feedback_acceptance_report.json").resolve()),
    }

    summary = build_phase15_feedback_daily_success_summary(
        phase14_export_result=export_result,
        phase14_acceptance_result=acceptance_result,
    )

    assert summary["status"] == "success"
    assert summary["failed_stage"] is None
    assert summary["error_type"] is None
    assert summary["error_message"] is None
    assert summary["feedback_export_records_path"].endswith("feedback_export_records.json")
    assert summary["feedback_manifest_path"].endswith("phase14_feedback_manifest.json")
    assert summary["phase14_feedback_acceptance_report_path"].endswith("phase14_feedback_acceptance_report.json")
    assert summary["manual_check_points"]
    assert summary["records_count"] == 2


def test_phase15_feedback_daily_summary_builds_failure_payload_and_writes_file(tmp_path):
    data_dir = tmp_path / "data"
    summary = build_phase15_feedback_daily_failure_summary(
        failed_stage="phase14_acceptance",
        error=RuntimeError("phase14 acceptance failed"),
        data_dir=str(data_dir),
    )

    assert summary["status"] == "failure"
    assert summary["failed_stage"] == "phase14_acceptance"
    assert summary["error_type"] == "RuntimeError"
    assert summary["error_message"] == "phase14 acceptance failed"
    assert summary["feedback_export_records_path"].endswith("feedback_export_records.json")
    assert summary["feedback_manifest_path"].endswith("phase14_feedback_manifest.json")
    assert summary["phase14_feedback_acceptance_report_path"].endswith("phase14_feedback_acceptance_report.json")
    assert summary["manual_check_points"]
    assert summary["records_count"] is None

    output_path = data_dir / "phase15_feedback_daily_summary.json"
    written_path = write_phase15_feedback_daily_summary(summary, output_path=str(output_path))

    assert Path(written_path) == output_path.resolve()
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["status"] == "failure"
    assert payload["failed_stage"] == "phase14_acceptance"
