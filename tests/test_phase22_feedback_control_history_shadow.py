import json
from pathlib import Path

from modules.phase22_feedback_control_history import (
    append_phase22_feedback_control_history,
    build_phase22_feedback_control_history_record,
    write_phase22_feedback_control_latest,
)


def test_phase22_feedback_control_history_record_builds_minimal_audit_shape_without_revalidating_phase21_summary(
    tmp_path,
):
    summary = {
        "status": "success",
        "failed_stage": None,
        "error_type": None,
        "error_message": None,
        "phase19_feedback_control_snapshot_path": str((tmp_path / "data" / "phase19_feedback_control_snapshot.json").resolve()),
        "phase20_feedback_control_snapshot_acceptance_report_path": str(
            (tmp_path / "data" / "phase20_feedback_control_snapshot_acceptance_report.json").resolve()
        ),
        "records_count": 2,
        "latest_run_id": "phase16-run-002",
    }

    record = build_phase22_feedback_control_history_record(
        phase21_summary=summary,
        phase21_summary_path=str((tmp_path / "data" / "phase21_feedback_control_daily_summary.json").resolve()),
        run_id="phase22-run-001",
        created_at="2026-03-31T13:00:00Z",
    )

    assert record["run_id"] == "phase22-run-001"
    assert record["status"] == "success"
    assert record["failed_stage"] is None
    assert record["error_type"] is None
    assert record["error_message"] is None
    assert record["phase19_feedback_control_snapshot_path"].endswith("phase19_feedback_control_snapshot.json")
    assert record["phase20_feedback_control_snapshot_acceptance_report_path"].endswith(
        "phase20_feedback_control_snapshot_acceptance_report.json"
    )
    assert record["phase21_feedback_control_daily_summary_path"].endswith(
        "phase21_feedback_control_daily_summary.json"
    )
    assert record["records_count"] == 2
    assert record["latest_run_id"] == "phase16-run-002"
    assert record["created_at"] == "2026-03-31T13:00:00Z"


def test_phase22_feedback_control_history_appends_without_overwriting_and_latest_tracks_most_recent(tmp_path):
    history_path = tmp_path / "data" / "phase22_feedback_control_history.json"
    latest_path = tmp_path / "data" / "phase22_feedback_control_latest.json"

    first = build_phase22_feedback_control_history_record(
        phase21_summary={
            "status": "success",
            "failed_stage": None,
            "error_type": None,
            "error_message": None,
            "phase19_feedback_control_snapshot_path": str(
                (tmp_path / "data" / "phase19_feedback_control_snapshot.json").resolve()
            ),
            "phase20_feedback_control_snapshot_acceptance_report_path": str(
                (tmp_path / "data" / "phase20_feedback_control_snapshot_acceptance_report.json").resolve()
            ),
            "records_count": 2,
            "latest_run_id": "phase16-run-002",
        },
        phase21_summary_path=str((tmp_path / "data" / "phase21_feedback_control_daily_summary.json").resolve()),
        run_id="phase22-run-001",
        created_at="2026-03-31T13:00:00Z",
    )
    second = build_phase22_feedback_control_history_record(
        phase21_summary={
            "status": "failure",
            "failed_stage": "phase20_snapshot_acceptance",
            "error_type": "RuntimeError",
            "error_message": "phase20 acceptance failed",
            "phase19_feedback_control_snapshot_path": str(
                (tmp_path / "data" / "phase19_feedback_control_snapshot.json").resolve()
            ),
            "phase20_feedback_control_snapshot_acceptance_report_path": str(
                (tmp_path / "data" / "phase20_feedback_control_snapshot_acceptance_report.json").resolve()
            ),
            "records_count": None,
            "latest_run_id": None,
        },
        phase21_summary_path=str((tmp_path / "data" / "phase21_feedback_control_daily_summary.json").resolve()),
        run_id="phase22-run-002",
        created_at="2026-03-31T13:05:00Z",
    )

    first_payload = append_phase22_feedback_control_history(first, output_path=str(history_path))
    assert first_payload["records_count"] == 1
    assert [row["run_id"] for row in first_payload["records"]] == ["phase22-run-001"]

    second_payload = append_phase22_feedback_control_history(second, output_path=str(history_path))
    assert second_payload["records_count"] == 2
    assert [row["run_id"] for row in second_payload["records"]] == ["phase22-run-001", "phase22-run-002"]

    written_latest_path = write_phase22_feedback_control_latest(second, output_path=str(latest_path))
    assert Path(written_latest_path) == latest_path.resolve()

    history_payload = json.loads(history_path.read_text(encoding="utf-8"))
    latest_payload = json.loads(latest_path.read_text(encoding="utf-8"))
    assert history_payload["records_count"] == 2
    assert history_payload["records"][1]["run_id"] == "phase22-run-002"
    assert latest_payload["run_id"] == "phase22-run-002"
    assert "records" not in latest_payload
