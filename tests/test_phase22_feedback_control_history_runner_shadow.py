import json
from pathlib import Path

import pytest

import run_phase22_feedback_control_history as phase22_runner


def test_phase22_feedback_control_history_runner_calls_phase21_and_writes_history_and_latest(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    calls = []

    def fake_phase21(*, data_dir="data"):
        calls.append({"data_dir": data_dir})
        summary_path = tmp_path / "data" / "phase21_feedback_control_daily_summary.json"
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary = {
            "status": "success",
            "failed_stage": None,
            "error_type": None,
            "error_message": None,
            "phase19_feedback_control_snapshot_path": str((tmp_path / "data" / "phase19_feedback_control_snapshot.json").resolve()),
            "phase20_feedback_control_snapshot_acceptance_report_path": str(
                (tmp_path / "data" / "phase20_feedback_control_snapshot_acceptance_report.json").resolve()
            ),
            "manual_check_points": ["review phase21 summary"],
            "records_count": 2,
            "latest_run_id": "phase16-run-002",
        }
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "summary_path": str(summary_path.resolve()),
            "summary": summary,
        }

    monkeypatch.setattr(phase22_runner, "run_phase21_feedback_control_daily", fake_phase21)

    first = phase22_runner.run_phase22_feedback_control_history()
    second = phase22_runner.run_phase22_feedback_control_history()

    assert len(calls) == 2
    assert str((tmp_path / "data").resolve()) in calls[0]["data_dir"]
    assert str((tmp_path / "data").resolve()) in calls[1]["data_dir"]

    history_path = tmp_path / "data" / "phase22_feedback_control_history.json"
    latest_path = tmp_path / "data" / "phase22_feedback_control_latest.json"
    assert Path(first["history_path"]) == history_path.resolve()
    assert Path(first["latest_path"]) == latest_path.resolve()
    assert history_path.exists()
    assert latest_path.exists()

    history_payload = json.loads(history_path.read_text(encoding="utf-8"))
    latest_payload = json.loads(latest_path.read_text(encoding="utf-8"))
    assert history_payload["records_count"] == 2
    assert len(history_payload["records"]) == 2
    assert latest_payload["run_id"] == history_payload["records"][-1]["run_id"]
    assert latest_payload["phase19_feedback_control_snapshot_path"].endswith("phase19_feedback_control_snapshot.json")
    assert latest_payload["phase20_feedback_control_snapshot_acceptance_report_path"].endswith(
        "phase20_feedback_control_snapshot_acceptance_report.json"
    )
    assert latest_payload["phase21_feedback_control_daily_summary_path"].endswith(
        "phase21_feedback_control_daily_summary.json"
    )


def test_phase22_feedback_control_history_runner_writes_failure_history_and_latest_before_reraising(
    monkeypatch,
    tmp_path,
):
    monkeypatch.chdir(tmp_path)

    def fake_phase21(*, data_dir="data"):
        summary_path = tmp_path / "data" / "phase21_feedback_control_daily_summary.json"
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary = {
            "status": "failure",
            "failed_stage": "phase20_snapshot_acceptance",
            "error_type": "RuntimeError",
            "error_message": "phase20 acceptance failed",
            "phase19_feedback_control_snapshot_path": str((tmp_path / "data" / "phase19_feedback_control_snapshot.json").resolve()),
            "phase20_feedback_control_snapshot_acceptance_report_path": str(
                (tmp_path / "data" / "phase20_feedback_control_snapshot_acceptance_report.json").resolve()
            ),
            "manual_check_points": ["review failure"],
            "records_count": None,
            "latest_run_id": None,
        }
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        raise RuntimeError("phase21 control daily failed")

    monkeypatch.setattr(phase22_runner, "run_phase21_feedback_control_daily", fake_phase21)

    with pytest.raises(RuntimeError, match="phase21 control daily failed"):
        phase22_runner.run_phase22_feedback_control_history()

    history_path = tmp_path / "data" / "phase22_feedback_control_history.json"
    latest_path = tmp_path / "data" / "phase22_feedback_control_latest.json"
    assert history_path.exists()
    assert latest_path.exists()

    history_payload = json.loads(history_path.read_text(encoding="utf-8"))
    latest_payload = json.loads(latest_path.read_text(encoding="utf-8"))
    assert history_payload["records_count"] == 1
    assert history_payload["records"][0]["status"] == "failure"
    assert history_payload["records"][0]["failed_stage"] == "phase20_snapshot_acceptance"
    assert latest_payload["status"] == "failure"
