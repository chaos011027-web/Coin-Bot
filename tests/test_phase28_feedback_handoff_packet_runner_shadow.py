import json
from pathlib import Path

import pytest

import run_phase28_feedback_handoff_packet as phase28_runner


def _write_phase27_summary(data_dir: Path) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    summary_path = data_dir / "phase27_feedback_release_daily_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "status": "success",
                "failed_stage": None,
                "error_type": None,
                "error_message": None,
                "phase25_feedback_release_snapshot_path": str((data_dir / "phase25_feedback_release_snapshot.json").resolve()),
                "phase26_feedback_release_snapshot_acceptance_report_path": str(
                    (data_dir / "phase26_feedback_release_snapshot_acceptance_report.json").resolve()
                ),
                "records_count": 2,
                "latest_run_id": "phase22-run-002",
                "manual_check_points": ["review phase27 summary"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return summary_path


def test_phase28_feedback_handoff_packet_runner_reads_phase27_summary_and_writes_packet(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    summary_path = _write_phase27_summary(tmp_path / "data")

    result = phase28_runner.run_phase28_feedback_handoff_packet()

    packet_path = tmp_path / "data" / "phase28_feedback_handoff_packet.json"
    assert Path(result["phase27_feedback_release_daily_summary_path"]) == summary_path.resolve()
    assert Path(result["packet_path"]) == packet_path.resolve()
    assert packet_path.exists()

    payload = json.loads(packet_path.read_text(encoding="utf-8"))
    assert payload["status"] == "success"
    assert payload["failed_stage"] is None
    assert payload["error_type"] is None
    assert payload["error_message"] is None
    assert payload["phase25_feedback_release_snapshot_path"].endswith("phase25_feedback_release_snapshot.json")
    assert payload["phase26_feedback_release_snapshot_acceptance_report_path"].endswith(
        "phase26_feedback_release_snapshot_acceptance_report.json"
    )
    assert payload["phase27_feedback_release_daily_summary_path"].endswith(
        "phase27_feedback_release_daily_summary.json"
    )
    assert payload["records_count"] == 2
    assert payload["latest_run_id"] == "phase22-run-002"
    assert payload["handoff_checklist"]
    assert payload["created_at"]


def test_phase28_feedback_handoff_packet_runner_fails_when_phase27_summary_missing(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    with pytest.raises(FileNotFoundError, match="phase27 feedback release daily summary missing"):
        phase28_runner.run_phase28_feedback_handoff_packet()
