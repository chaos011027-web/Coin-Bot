import json
from pathlib import Path

from modules.phase28_feedback_handoff_packet import (
    build_phase28_feedback_handoff_packet,
    write_phase28_feedback_handoff_packet,
)


def test_phase28_feedback_handoff_packet_builds_compact_packet_from_phase27_summary(tmp_path):
    summary = {
        "status": "success",
        "failed_stage": None,
        "error_type": None,
        "error_message": None,
        "phase25_feedback_release_snapshot_path": str((tmp_path / "data" / "phase25_feedback_release_snapshot.json").resolve()),
        "phase26_feedback_release_snapshot_acceptance_report_path": str(
            (tmp_path / "data" / "phase26_feedback_release_snapshot_acceptance_report.json").resolve()
        ),
        "records_count": 2,
        "latest_run_id": "phase22-run-002",
    }

    packet = build_phase28_feedback_handoff_packet(
        phase27_summary=summary,
        phase27_summary_path=str((tmp_path / "data" / "phase27_feedback_release_daily_summary.json").resolve()),
        created_at="2026-04-01T10:00:00Z",
    )

    assert packet["status"] == "success"
    assert packet["failed_stage"] is None
    assert packet["error_type"] is None
    assert packet["error_message"] is None
    assert packet["phase25_feedback_release_snapshot_path"].endswith("phase25_feedback_release_snapshot.json")
    assert packet["phase26_feedback_release_snapshot_acceptance_report_path"].endswith(
        "phase26_feedback_release_snapshot_acceptance_report.json"
    )
    assert packet["phase27_feedback_release_daily_summary_path"].endswith(
        "phase27_feedback_release_daily_summary.json"
    )
    assert packet["records_count"] == 2
    assert packet["latest_run_id"] == "phase22-run-002"
    assert packet["handoff_checklist"]
    assert packet["created_at"] == "2026-04-01T10:00:00Z"


def test_phase28_feedback_handoff_packet_writes_packet_payload(tmp_path):
    packet = {
        "status": "failure",
        "failed_stage": "phase26_release_snapshot_acceptance",
        "error_type": "RuntimeError",
        "error_message": "phase26 acceptance failed",
        "phase25_feedback_release_snapshot_path": str((tmp_path / "data" / "phase25_feedback_release_snapshot.json").resolve()),
        "phase26_feedback_release_snapshot_acceptance_report_path": str(
            (tmp_path / "data" / "phase26_feedback_release_snapshot_acceptance_report.json").resolve()
        ),
        "phase27_feedback_release_daily_summary_path": str(
            (tmp_path / "data" / "phase27_feedback_release_daily_summary.json").resolve()
        ),
        "records_count": None,
        "latest_run_id": None,
        "handoff_checklist": ["review phase25 release snapshot"],
        "created_at": "2026-04-01T10:05:00Z",
    }

    output_path = tmp_path / "data" / "phase28_feedback_handoff_packet.json"
    written_path = write_phase28_feedback_handoff_packet(packet, output_path=str(output_path))

    assert Path(written_path) == output_path.resolve()
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["status"] == "failure"
    assert payload["failed_stage"] == "phase26_release_snapshot_acceptance"
