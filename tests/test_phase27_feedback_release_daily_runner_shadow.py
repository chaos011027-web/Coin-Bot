import json
from pathlib import Path

import pytest

import run_phase27_feedback_release_daily as phase27_runner


def test_phase27_feedback_release_daily_runner_chains_phase25_then_phase26_and_writes_summary(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    calls = []

    def fake_phase25(*, data_dir="data"):
        calls.append(("phase25", {"data_dir": data_dir}))
        return {
            "snapshot_path": str((tmp_path / "data" / "phase25_feedback_release_snapshot.json").resolve()),
            "snapshot": {
                "records_count": 2,
                "latest_run_id": "phase22-run-002",
            },
        }

    def fake_phase26(*, data_dir="data"):
        calls.append(("phase26", {"data_dir": data_dir}))
        return {
            "status": "success",
            "failed_stage": None,
            "error_type": None,
            "error_message": None,
            "phase25_feedback_release_snapshot_path": str((tmp_path / "data" / "phase25_feedback_release_snapshot.json").resolve()),
            "records_count": 2,
            "latest_run_id": "phase22-run-002",
            "manual_check_points": ["review phase26 report"],
            "report_path": str((tmp_path / "data" / "phase26_feedback_release_snapshot_acceptance_report.json").resolve()),
        }

    monkeypatch.setattr(phase27_runner, "run_phase25_feedback_release_snapshot", fake_phase25)
    monkeypatch.setattr(phase27_runner, "run_phase26_feedback_release_snapshot_acceptance", fake_phase26)

    result = phase27_runner.run_phase27_feedback_release_daily()

    assert [name for name, _ in calls] == ["phase25", "phase26"]
    assert str((tmp_path / "data").resolve()) in calls[0][1]["data_dir"]
    assert str((tmp_path / "data").resolve()) in calls[1][1]["data_dir"]

    summary_path = tmp_path / "data" / "phase27_feedback_release_daily_summary.json"
    assert Path(result["summary_path"]) == summary_path.resolve()
    assert summary_path.exists()

    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload["status"] == "success"
    assert payload["failed_stage"] is None
    assert payload["error_type"] is None
    assert payload["error_message"] is None
    assert payload["phase25_feedback_release_snapshot_path"].endswith("phase25_feedback_release_snapshot.json")
    assert payload["phase26_feedback_release_snapshot_acceptance_report_path"].endswith(
        "phase26_feedback_release_snapshot_acceptance_report.json"
    )
    assert payload["records_count"] == 2
    assert payload["latest_run_id"] == "phase22-run-002"
    assert payload["manual_check_points"]


def test_phase27_feedback_release_daily_runner_writes_failure_summary_when_phase25_fails(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    def fake_phase25(*, data_dir="data"):
        raise RuntimeError("phase25 release snapshot failed")

    def fake_phase26(*, data_dir="data"):
        raise AssertionError("phase26 should not run after phase25 failure")

    monkeypatch.setattr(phase27_runner, "run_phase25_feedback_release_snapshot", fake_phase25)
    monkeypatch.setattr(phase27_runner, "run_phase26_feedback_release_snapshot_acceptance", fake_phase26)

    with pytest.raises(RuntimeError, match="phase25 release snapshot failed"):
        phase27_runner.run_phase27_feedback_release_daily()

    summary_path = tmp_path / "data" / "phase27_feedback_release_daily_summary.json"
    assert summary_path.exists()
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload["status"] == "failure"
    assert payload["failed_stage"] == "phase25_release_snapshot"
    assert payload["error_type"] == "RuntimeError"
    assert payload["error_message"] == "phase25 release snapshot failed"


def test_phase27_feedback_release_daily_runner_writes_failure_summary_when_phase26_fails(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    def fake_phase25(*, data_dir="data"):
        return {
            "snapshot_path": str((tmp_path / "data" / "phase25_feedback_release_snapshot.json").resolve()),
            "snapshot": {
                "records_count": 2,
                "latest_run_id": "phase22-run-002",
            },
        }

    def fake_phase26(*, data_dir="data"):
        raise RuntimeError("phase26 acceptance failed")

    monkeypatch.setattr(phase27_runner, "run_phase25_feedback_release_snapshot", fake_phase25)
    monkeypatch.setattr(phase27_runner, "run_phase26_feedback_release_snapshot_acceptance", fake_phase26)

    with pytest.raises(RuntimeError, match="phase26 acceptance failed"):
        phase27_runner.run_phase27_feedback_release_daily()

    summary_path = tmp_path / "data" / "phase27_feedback_release_daily_summary.json"
    assert summary_path.exists()
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload["status"] == "failure"
    assert payload["failed_stage"] == "phase26_release_snapshot_acceptance"
    assert payload["error_type"] == "RuntimeError"
    assert payload["error_message"] == "phase26 acceptance failed"
    assert payload["phase25_feedback_release_snapshot_path"].endswith("phase25_feedback_release_snapshot.json")
