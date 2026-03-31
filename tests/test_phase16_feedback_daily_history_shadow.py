import json
from pathlib import Path

from modules.phase16_feedback_daily_history import (
    append_phase16_feedback_daily_history,
    build_phase16_feedback_daily_history_record,
    write_phase16_feedback_daily_latest,
)


def test_phase16_feedback_daily_history_record_builds_minimal_audit_shape_without_revalidating_phase15_payloads(tmp_path):
    summary = {
        "status": "success",
        "failed_stage": None,
        "error_type": None,
        "error_message": None,
        "feedback_export_records_path": str((tmp_path / "data" / "feedback_export_records.json").resolve()),
        "feedback_manifest_path": str((tmp_path / "data" / "phase14_feedback_manifest.json").resolve()),
        "phase14_feedback_acceptance_report_path": str(
            (tmp_path / "data" / "phase14_feedback_acceptance_report.json").resolve()
        ),
        "manual_check_points": ["review phase15 summary"],
        "records_count": 2,
    }

    record = build_phase16_feedback_daily_history_record(
        phase15_summary=summary,
        phase15_summary_path=str((tmp_path / "data" / "phase15_feedback_daily_summary.json").resolve()),
        run_id="phase16-run-001",
        created_at="2026-03-31T12:00:00Z",
    )

    assert record["run_id"] == "phase16-run-001"
    assert record["status"] == "success"
    assert record["failed_stage"] is None
    assert record["error_type"] is None
    assert record["error_message"] is None
    assert record["feedback_export_records_path"].endswith("feedback_export_records.json")
    assert record["feedback_manifest_path"].endswith("phase14_feedback_manifest.json")
    assert record["phase14_feedback_acceptance_report_path"].endswith("phase14_feedback_acceptance_report.json")
    assert record["phase15_feedback_daily_summary_path"].endswith("phase15_feedback_daily_summary.json")
    assert record["records_count"] == 2
    assert record["created_at"] == "2026-03-31T12:00:00Z"


def test_phase16_feedback_daily_history_appends_without_overwriting_and_latest_tracks_most_recent(tmp_path):
    history_path = tmp_path / "data" / "phase16_feedback_daily_history.json"
    latest_path = tmp_path / "data" / "phase16_feedback_daily_latest.json"

    first = build_phase16_feedback_daily_history_record(
        phase15_summary={
            "status": "success",
            "failed_stage": None,
            "error_type": None,
            "error_message": None,
            "feedback_export_records_path": str((tmp_path / "data" / "feedback_export_records.json").resolve()),
            "feedback_manifest_path": str((tmp_path / "data" / "phase14_feedback_manifest.json").resolve()),
            "phase14_feedback_acceptance_report_path": str(
                (tmp_path / "data" / "phase14_feedback_acceptance_report.json").resolve()
            ),
            "records_count": 2,
        },
        phase15_summary_path=str((tmp_path / "data" / "phase15_feedback_daily_summary.json").resolve()),
        run_id="phase16-run-001",
        created_at="2026-03-31T12:00:00Z",
    )
    second = build_phase16_feedback_daily_history_record(
        phase15_summary={
            "status": "failure",
            "failed_stage": "phase14_acceptance",
            "error_type": "RuntimeError",
            "error_message": "phase14 acceptance failed",
            "feedback_export_records_path": str((tmp_path / "data" / "feedback_export_records.json").resolve()),
            "feedback_manifest_path": str((tmp_path / "data" / "phase14_feedback_manifest.json").resolve()),
            "phase14_feedback_acceptance_report_path": str(
                (tmp_path / "data" / "phase14_feedback_acceptance_report.json").resolve()
            ),
            "records_count": None,
        },
        phase15_summary_path=str((tmp_path / "data" / "phase15_feedback_daily_summary.json").resolve()),
        run_id="phase16-run-002",
        created_at="2026-03-31T12:05:00Z",
    )

    first_payload = append_phase16_feedback_daily_history(first, output_path=str(history_path))
    assert first_payload["records_count"] == 1
    assert [row["run_id"] for row in first_payload["records"]] == ["phase16-run-001"]

    second_payload = append_phase16_feedback_daily_history(second, output_path=str(history_path))
    assert second_payload["records_count"] == 2
    assert [row["run_id"] for row in second_payload["records"]] == ["phase16-run-001", "phase16-run-002"]

    written_latest_path = write_phase16_feedback_daily_latest(second, output_path=str(latest_path))
    assert Path(written_latest_path) == latest_path.resolve()

    history_payload = json.loads(history_path.read_text(encoding="utf-8"))
    latest_payload = json.loads(latest_path.read_text(encoding="utf-8"))
    assert history_payload["records_count"] == 2
    assert history_payload["records"][0]["run_id"] == "phase16-run-001"
    assert history_payload["records"][1]["run_id"] == "phase16-run-002"
    assert latest_payload["run_id"] == "phase16-run-002"
    assert "records" not in latest_payload
