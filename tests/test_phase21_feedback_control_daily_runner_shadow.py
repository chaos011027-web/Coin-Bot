import json
from pathlib import Path

import pytest

import run_phase21_feedback_control_daily as phase21_runner


def test_phase21_feedback_control_daily_runner_chains_phase19_then_phase20_and_writes_summary(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    calls = []

    def fake_phase19(*, data_dir="data"):
        calls.append(("phase19", {"data_dir": data_dir}))
        return {
            "snapshot_path": str((tmp_path / "data" / "phase19_feedback_control_snapshot.json").resolve()),
            "snapshot": {
                "records_count": 2,
                "latest_run_id": "phase16-run-002",
            },
        }

    def fake_phase20(*, data_dir="data"):
        calls.append(("phase20", {"data_dir": data_dir}))
        return {
            "status": "success",
            "failed_stage": None,
            "error_type": None,
            "error_message": None,
            "phase19_feedback_control_snapshot_path": str((tmp_path / "data" / "phase19_feedback_control_snapshot.json").resolve()),
            "records_count": 2,
            "latest_run_id": "phase16-run-002",
            "manual_check_points": ["review phase20 report"],
            "report_path": str((tmp_path / "data" / "phase20_feedback_control_snapshot_acceptance_report.json").resolve()),
        }

    monkeypatch.setattr(phase21_runner, "run_phase19_feedback_control_snapshot", fake_phase19)
    monkeypatch.setattr(phase21_runner, "run_phase20_feedback_control_snapshot_acceptance", fake_phase20)

    result = phase21_runner.run_phase21_feedback_control_daily()

    assert [name for name, _ in calls] == ["phase19", "phase20"]
    assert str((tmp_path / "data").resolve()) in calls[0][1]["data_dir"]
    assert str((tmp_path / "data").resolve()) in calls[1][1]["data_dir"]

    summary_path = tmp_path / "data" / "phase21_feedback_control_daily_summary.json"
    assert Path(result["summary_path"]) == summary_path.resolve()
    assert summary_path.exists()

    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload["status"] == "success"
    assert payload["failed_stage"] is None
    assert payload["error_type"] is None
    assert payload["error_message"] is None
    assert payload["phase19_feedback_control_snapshot_path"].endswith("phase19_feedback_control_snapshot.json")
    assert payload["phase20_feedback_control_snapshot_acceptance_report_path"].endswith(
        "phase20_feedback_control_snapshot_acceptance_report.json"
    )
    assert payload["records_count"] == 2
    assert payload["latest_run_id"] == "phase16-run-002"
    assert payload["manual_check_points"]


def test_phase21_feedback_control_daily_runner_writes_failure_summary_when_phase19_fails(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    def fake_phase19(*, data_dir="data"):
        raise RuntimeError("phase19 snapshot failed")

    def fake_phase20(*, data_dir="data"):
        raise AssertionError("phase20 should not run after phase19 failure")

    monkeypatch.setattr(phase21_runner, "run_phase19_feedback_control_snapshot", fake_phase19)
    monkeypatch.setattr(phase21_runner, "run_phase20_feedback_control_snapshot_acceptance", fake_phase20)

    with pytest.raises(RuntimeError, match="phase19 snapshot failed"):
        phase21_runner.run_phase21_feedback_control_daily()

    summary_path = tmp_path / "data" / "phase21_feedback_control_daily_summary.json"
    assert summary_path.exists()
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload["status"] == "failure"
    assert payload["failed_stage"] == "phase19_snapshot"
    assert payload["error_type"] == "RuntimeError"
    assert payload["error_message"] == "phase19 snapshot failed"


def test_phase21_feedback_control_daily_runner_writes_failure_summary_when_phase20_fails(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    def fake_phase19(*, data_dir="data"):
        return {
            "snapshot_path": str((tmp_path / "data" / "phase19_feedback_control_snapshot.json").resolve()),
            "snapshot": {
                "records_count": 2,
                "latest_run_id": "phase16-run-002",
            },
        }

    def fake_phase20(*, data_dir="data"):
        raise RuntimeError("phase20 acceptance failed")

    monkeypatch.setattr(phase21_runner, "run_phase19_feedback_control_snapshot", fake_phase19)
    monkeypatch.setattr(phase21_runner, "run_phase20_feedback_control_snapshot_acceptance", fake_phase20)

    with pytest.raises(RuntimeError, match="phase20 acceptance failed"):
        phase21_runner.run_phase21_feedback_control_daily()

    summary_path = tmp_path / "data" / "phase21_feedback_control_daily_summary.json"
    assert summary_path.exists()
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload["status"] == "failure"
    assert payload["failed_stage"] == "phase20_snapshot_acceptance"
    assert payload["error_type"] == "RuntimeError"
    assert payload["error_message"] == "phase20 acceptance failed"
    assert payload["phase19_feedback_control_snapshot_path"].endswith("phase19_feedback_control_snapshot.json")
