import json
from pathlib import Path

import pytest

import run_phase18_feedback_history_daily as phase18_runner


def test_phase18_feedback_history_daily_runner_chains_phase16_then_phase17_and_writes_summary(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    calls = []

    def fake_phase16(*, data_dir="data"):
        calls.append(("phase16", {"data_dir": data_dir}))
        return {
            "history_path": str((tmp_path / "data" / "phase16_feedback_daily_history.json").resolve()),
            "latest_path": str((tmp_path / "data" / "phase16_feedback_daily_latest.json").resolve()),
            "history": {
                "records_count": 2,
                "latest_run_id": "phase16-run-002",
            },
        }

    def fake_phase17(*, data_dir="data"):
        calls.append(("phase17", {"data_dir": data_dir}))
        return {
            "status": "success",
            "failed_stage": None,
            "error_type": None,
            "error_message": None,
            "phase16_feedback_daily_history_path": str((tmp_path / "data" / "phase16_feedback_daily_history.json").resolve()),
            "phase16_feedback_daily_latest_path": str((tmp_path / "data" / "phase16_feedback_daily_latest.json").resolve()),
            "records_count": 2,
            "latest_run_id": "phase16-run-002",
            "manual_check_points": ["review phase17 report"],
            "report_path": str((tmp_path / "data" / "phase17_feedback_history_acceptance_report.json").resolve()),
        }

    monkeypatch.setattr(phase18_runner, "run_phase16_feedback_daily_history", fake_phase16)
    monkeypatch.setattr(phase18_runner, "run_phase17_feedback_history_acceptance", fake_phase17)

    result = phase18_runner.run_phase18_feedback_history_daily()

    assert [name for name, _ in calls] == ["phase16", "phase17"]
    assert str((tmp_path / "data").resolve()) in calls[0][1]["data_dir"]
    assert str((tmp_path / "data").resolve()) in calls[1][1]["data_dir"]

    summary_path = tmp_path / "data" / "phase18_feedback_history_daily_summary.json"
    assert Path(result["summary_path"]) == summary_path.resolve()
    assert summary_path.exists()

    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload["status"] == "success"
    assert payload["failed_stage"] is None
    assert payload["error_type"] is None
    assert payload["error_message"] is None
    assert payload["phase16_feedback_daily_history_path"].endswith("phase16_feedback_daily_history.json")
    assert payload["phase16_feedback_daily_latest_path"].endswith("phase16_feedback_daily_latest.json")
    assert payload["phase17_feedback_history_acceptance_report_path"].endswith("phase17_feedback_history_acceptance_report.json")
    assert payload["records_count"] == 2
    assert payload["latest_run_id"] == "phase16-run-002"
    assert payload["manual_check_points"]


def test_phase18_feedback_history_daily_runner_writes_failure_summary_when_phase16_fails(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    def fake_phase16(*, data_dir="data"):
        raise RuntimeError("phase16 history failed")

    def fake_phase17(*, data_dir="data"):
        raise AssertionError("phase17 should not run after phase16 failure")

    monkeypatch.setattr(phase18_runner, "run_phase16_feedback_daily_history", fake_phase16)
    monkeypatch.setattr(phase18_runner, "run_phase17_feedback_history_acceptance", fake_phase17)

    with pytest.raises(RuntimeError, match="phase16 history failed"):
        phase18_runner.run_phase18_feedback_history_daily()

    summary_path = tmp_path / "data" / "phase18_feedback_history_daily_summary.json"
    assert summary_path.exists()
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload["status"] == "failure"
    assert payload["failed_stage"] == "phase16_history_daily"
    assert payload["error_type"] == "RuntimeError"
    assert payload["error_message"] == "phase16 history failed"
    assert payload["phase16_feedback_daily_history_path"].endswith("phase16_feedback_daily_history.json")
    assert payload["phase16_feedback_daily_latest_path"].endswith("phase16_feedback_daily_latest.json")
    assert payload["phase17_feedback_history_acceptance_report_path"].endswith("phase17_feedback_history_acceptance_report.json")


def test_phase18_feedback_history_daily_runner_writes_failure_summary_when_phase17_fails(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    def fake_phase16(*, data_dir="data"):
        return {
            "history_path": str((tmp_path / "data" / "phase16_feedback_daily_history.json").resolve()),
            "latest_path": str((tmp_path / "data" / "phase16_feedback_daily_latest.json").resolve()),
            "history": {
                "records_count": 2,
                "latest_run_id": "phase16-run-002",
            },
        }

    def fake_phase17(*, data_dir="data"):
        raise RuntimeError("phase17 acceptance failed")

    monkeypatch.setattr(phase18_runner, "run_phase16_feedback_daily_history", fake_phase16)
    monkeypatch.setattr(phase18_runner, "run_phase17_feedback_history_acceptance", fake_phase17)

    with pytest.raises(RuntimeError, match="phase17 acceptance failed"):
        phase18_runner.run_phase18_feedback_history_daily()

    summary_path = tmp_path / "data" / "phase18_feedback_history_daily_summary.json"
    assert summary_path.exists()
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload["status"] == "failure"
    assert payload["failed_stage"] == "phase17_history_acceptance"
    assert payload["error_type"] == "RuntimeError"
    assert payload["error_message"] == "phase17 acceptance failed"
    assert payload["phase16_feedback_daily_history_path"].endswith("phase16_feedback_daily_history.json")
    assert payload["phase16_feedback_daily_latest_path"].endswith("phase16_feedback_daily_latest.json")
    assert payload["phase17_feedback_history_acceptance_report_path"].endswith("phase17_feedback_history_acceptance_report.json")
