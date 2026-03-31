import json
from pathlib import Path

import pytest

import run_phase24_feedback_control_history_daily as phase24_runner


def test_phase24_feedback_control_history_daily_runner_chains_phase22_then_phase23_and_writes_summary(
    monkeypatch,
    tmp_path,
):
    monkeypatch.chdir(tmp_path)
    calls = []

    def fake_phase22(*, data_dir="data"):
        calls.append(("phase22", {"data_dir": data_dir}))
        return {
            "history_path": str((tmp_path / "data" / "phase22_feedback_control_history.json").resolve()),
            "latest_path": str((tmp_path / "data" / "phase22_feedback_control_latest.json").resolve()),
            "history": {
                "records_count": 2,
                "latest_run_id": "phase22-run-002",
            },
        }

    def fake_phase23(*, data_dir="data"):
        calls.append(("phase23", {"data_dir": data_dir}))
        return {
            "status": "success",
            "failed_stage": None,
            "error_type": None,
            "error_message": None,
            "phase22_feedback_control_history_path": str(
                (tmp_path / "data" / "phase22_feedback_control_history.json").resolve()
            ),
            "phase22_feedback_control_latest_path": str((tmp_path / "data" / "phase22_feedback_control_latest.json").resolve()),
            "records_count": 2,
            "latest_run_id": "phase22-run-002",
            "manual_check_points": ["review phase23 report"],
            "report_path": str((tmp_path / "data" / "phase23_feedback_control_history_acceptance_report.json").resolve()),
        }

    monkeypatch.setattr(phase24_runner, "run_phase22_feedback_control_history", fake_phase22)
    monkeypatch.setattr(phase24_runner, "run_phase23_feedback_control_history_acceptance", fake_phase23)

    result = phase24_runner.run_phase24_feedback_control_history_daily()

    assert [name for name, _ in calls] == ["phase22", "phase23"]
    assert str((tmp_path / "data").resolve()) in calls[0][1]["data_dir"]
    assert str((tmp_path / "data").resolve()) in calls[1][1]["data_dir"]

    summary_path = tmp_path / "data" / "phase24_feedback_control_history_daily_summary.json"
    assert Path(result["summary_path"]) == summary_path.resolve()
    assert summary_path.exists()

    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload["status"] == "success"
    assert payload["failed_stage"] is None
    assert payload["error_type"] is None
    assert payload["error_message"] is None
    assert payload["phase22_feedback_control_history_path"].endswith("phase22_feedback_control_history.json")
    assert payload["phase22_feedback_control_latest_path"].endswith("phase22_feedback_control_latest.json")
    assert payload["phase23_feedback_control_history_acceptance_report_path"].endswith(
        "phase23_feedback_control_history_acceptance_report.json"
    )
    assert payload["records_count"] == 2
    assert payload["latest_run_id"] == "phase22-run-002"
    assert payload["manual_check_points"]


def test_phase24_feedback_control_history_daily_runner_writes_failure_summary_when_phase22_fails(
    monkeypatch,
    tmp_path,
):
    monkeypatch.chdir(tmp_path)

    def fake_phase22(*, data_dir="data"):
        raise RuntimeError("phase22 control history failed")

    def fake_phase23(*, data_dir="data"):
        raise AssertionError("phase23 should not run after phase22 failure")

    monkeypatch.setattr(phase24_runner, "run_phase22_feedback_control_history", fake_phase22)
    monkeypatch.setattr(phase24_runner, "run_phase23_feedback_control_history_acceptance", fake_phase23)

    with pytest.raises(RuntimeError, match="phase22 control history failed"):
        phase24_runner.run_phase24_feedback_control_history_daily()

    summary_path = tmp_path / "data" / "phase24_feedback_control_history_daily_summary.json"
    assert summary_path.exists()
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload["status"] == "failure"
    assert payload["failed_stage"] == "phase22_control_history"
    assert payload["error_type"] == "RuntimeError"


def test_phase24_feedback_control_history_daily_runner_writes_failure_summary_when_phase23_fails(
    monkeypatch,
    tmp_path,
):
    monkeypatch.chdir(tmp_path)

    def fake_phase22(*, data_dir="data"):
        return {
            "history_path": str((tmp_path / "data" / "phase22_feedback_control_history.json").resolve()),
            "latest_path": str((tmp_path / "data" / "phase22_feedback_control_latest.json").resolve()),
            "history": {
                "records_count": 2,
                "latest_run_id": "phase22-run-002",
            },
        }

    def fake_phase23(*, data_dir="data"):
        raise RuntimeError("phase23 acceptance failed")

    monkeypatch.setattr(phase24_runner, "run_phase22_feedback_control_history", fake_phase22)
    monkeypatch.setattr(phase24_runner, "run_phase23_feedback_control_history_acceptance", fake_phase23)

    with pytest.raises(RuntimeError, match="phase23 acceptance failed"):
        phase24_runner.run_phase24_feedback_control_history_daily()

    summary_path = tmp_path / "data" / "phase24_feedback_control_history_daily_summary.json"
    assert summary_path.exists()
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload["status"] == "failure"
    assert payload["failed_stage"] == "phase23_control_history_acceptance"
    assert payload["error_type"] == "RuntimeError"
    assert payload["phase22_feedback_control_history_path"].endswith("phase22_feedback_control_history.json")
