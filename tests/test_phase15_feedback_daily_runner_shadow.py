import json
from pathlib import Path

import pytest

import run_phase15_feedback_daily as phase15_runner


def test_phase15_feedback_daily_runner_chains_phase14_export_then_acceptance_with_skip_export(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    calls = []

    def fake_export(*, data_dir="data"):
        calls.append(("phase14_export", {"data_dir": data_dir}))
        return {
            "status": "success",
            "feedback_export_records_path": str((tmp_path / "data" / "feedback_export_records.json").resolve()),
            "feedback_manifest_path": str((tmp_path / "data" / "phase14_feedback_manifest.json").resolve()),
        }

    def fake_acceptance(*, data_dir="data", skip_export=False):
        calls.append(("phase14_acceptance", {"data_dir": data_dir, "skip_export": skip_export}))
        return {
            "status": "success",
            "failed_stage": None,
            "error_type": None,
            "error_message": None,
            "feedback_export_records_path": str((tmp_path / "data" / "feedback_export_records.json").resolve()),
            "feedback_manifest_path": str((tmp_path / "data" / "phase14_feedback_manifest.json").resolve()),
            "manual_check_points": ["review acceptance report"],
            "records_count": 2,
            "report_path": str((tmp_path / "data" / "phase14_feedback_acceptance_report.json").resolve()),
        }

    monkeypatch.setattr(phase15_runner, "run_phase14_feedback_export", fake_export)
    monkeypatch.setattr(phase15_runner, "run_phase14_feedback_acceptance", fake_acceptance)

    result = phase15_runner.run_phase15_feedback_daily()

    assert [name for name, _ in calls] == ["phase14_export", "phase14_acceptance"]
    assert str((tmp_path / "data").resolve()) in calls[0][1]["data_dir"]
    assert str((tmp_path / "data").resolve()) in calls[1][1]["data_dir"]
    assert calls[1][1]["skip_export"] is True

    summary_path = tmp_path / "data" / "phase15_feedback_daily_summary.json"
    assert Path(result["summary_path"]) == summary_path.resolve()
    assert summary_path.exists()

    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload["status"] == "success"
    assert payload["failed_stage"] is None
    assert payload["error_type"] is None
    assert payload["error_message"] is None
    assert payload["feedback_export_records_path"].endswith("feedback_export_records.json")
    assert payload["feedback_manifest_path"].endswith("phase14_feedback_manifest.json")
    assert payload["phase14_feedback_acceptance_report_path"].endswith("phase14_feedback_acceptance_report.json")
    assert payload["manual_check_points"]
    assert payload["records_count"] == 2


def test_phase15_feedback_daily_runner_writes_failure_summary_when_phase14_export_fails(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    def fake_export(*, data_dir="data"):
        raise RuntimeError("phase14 export failed")

    def fake_acceptance(*, data_dir="data", skip_export=False):
        raise AssertionError("acceptance should not run after export failure")

    monkeypatch.setattr(phase15_runner, "run_phase14_feedback_export", fake_export)
    monkeypatch.setattr(phase15_runner, "run_phase14_feedback_acceptance", fake_acceptance)

    with pytest.raises(RuntimeError, match="phase14 export failed"):
        phase15_runner.run_phase15_feedback_daily()

    summary_path = tmp_path / "data" / "phase15_feedback_daily_summary.json"
    assert summary_path.exists()
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload["status"] == "failure"
    assert payload["failed_stage"] == "phase14_export"
    assert payload["error_type"] == "RuntimeError"
    assert payload["error_message"] == "phase14 export failed"
    assert payload["phase14_feedback_acceptance_report_path"].endswith("phase14_feedback_acceptance_report.json")


def test_phase15_feedback_daily_runner_writes_failure_summary_when_phase14_acceptance_fails(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    def fake_export(*, data_dir="data"):
        return {
            "status": "success",
            "feedback_export_records_path": str((tmp_path / "data" / "feedback_export_records.json").resolve()),
            "feedback_manifest_path": str((tmp_path / "data" / "phase14_feedback_manifest.json").resolve()),
        }

    def fake_acceptance(*, data_dir="data", skip_export=False):
        assert skip_export is True
        raise RuntimeError("phase14 acceptance failed")

    monkeypatch.setattr(phase15_runner, "run_phase14_feedback_export", fake_export)
    monkeypatch.setattr(phase15_runner, "run_phase14_feedback_acceptance", fake_acceptance)

    with pytest.raises(RuntimeError, match="phase14 acceptance failed"):
        phase15_runner.run_phase15_feedback_daily()

    summary_path = tmp_path / "data" / "phase15_feedback_daily_summary.json"
    assert summary_path.exists()
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload["status"] == "failure"
    assert payload["failed_stage"] == "phase14_acceptance"
    assert payload["error_type"] == "RuntimeError"
    assert payload["error_message"] == "phase14 acceptance failed"
    assert payload["feedback_export_records_path"].endswith("feedback_export_records.json")
    assert payload["feedback_manifest_path"].endswith("phase14_feedback_manifest.json")
