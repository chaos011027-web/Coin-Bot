import json
from pathlib import Path

import pytest

import run_phase16_feedback_daily_history as phase16_runner


def test_phase16_feedback_daily_history_runner_calls_phase15_and_writes_history_and_latest(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    calls = []

    def fake_phase15(*, data_dir="data"):
        calls.append({"data_dir": data_dir})
        summary_path = tmp_path / "data" / "phase15_feedback_daily_summary.json"
        summary_path.parent.mkdir(parents=True, exist_ok=True)
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
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "summary_path": str(summary_path.resolve()),
            "summary": summary,
        }

    monkeypatch.setattr(phase16_runner, "run_phase15_feedback_daily", fake_phase15)

    first = phase16_runner.run_phase16_feedback_daily_history()
    second = phase16_runner.run_phase16_feedback_daily_history()

    assert len(calls) == 2
    assert str((tmp_path / "data").resolve()) in calls[0]["data_dir"]
    assert str((tmp_path / "data").resolve()) in calls[1]["data_dir"]

    history_path = tmp_path / "data" / "phase16_feedback_daily_history.json"
    latest_path = tmp_path / "data" / "phase16_feedback_daily_latest.json"
    assert Path(first["history_path"]) == history_path.resolve()
    assert Path(first["latest_path"]) == latest_path.resolve()
    assert history_path.exists()
    assert latest_path.exists()

    history_payload = json.loads(history_path.read_text(encoding="utf-8"))
    latest_payload = json.loads(latest_path.read_text(encoding="utf-8"))
    assert history_payload["records_count"] == 2
    assert len(history_payload["records"]) == 2
    assert history_payload["records"][0]["status"] == "success"
    assert history_payload["records"][1]["status"] == "success"
    assert latest_payload["run_id"] == history_payload["records"][-1]["run_id"]
    assert latest_payload["feedback_export_records_path"].endswith("feedback_export_records.json")
    assert latest_payload["feedback_manifest_path"].endswith("phase14_feedback_manifest.json")
    assert latest_payload["phase14_feedback_acceptance_report_path"].endswith("phase14_feedback_acceptance_report.json")
    assert latest_payload["phase15_feedback_daily_summary_path"].endswith("phase15_feedback_daily_summary.json")
    assert latest_payload["records_count"] == 2
    assert latest_payload["created_at"]


def test_phase16_feedback_daily_history_runner_writes_failure_history_and_latest_before_reraising(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    def fake_phase15(*, data_dir="data"):
        summary_path = tmp_path / "data" / "phase15_feedback_daily_summary.json"
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary = {
            "status": "failure",
            "failed_stage": "phase14_acceptance",
            "error_type": "RuntimeError",
            "error_message": "phase14 acceptance failed",
            "feedback_export_records_path": str((tmp_path / "data" / "feedback_export_records.json").resolve()),
            "feedback_manifest_path": str((tmp_path / "data" / "phase14_feedback_manifest.json").resolve()),
            "phase14_feedback_acceptance_report_path": str(
                (tmp_path / "data" / "phase14_feedback_acceptance_report.json").resolve()
            ),
            "manual_check_points": ["review failure"],
            "records_count": None,
        }
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        raise RuntimeError("phase15 daily failed")

    monkeypatch.setattr(phase16_runner, "run_phase15_feedback_daily", fake_phase15)

    with pytest.raises(RuntimeError, match="phase15 daily failed"):
        phase16_runner.run_phase16_feedback_daily_history()

    history_path = tmp_path / "data" / "phase16_feedback_daily_history.json"
    latest_path = tmp_path / "data" / "phase16_feedback_daily_latest.json"
    assert history_path.exists()
    assert latest_path.exists()

    history_payload = json.loads(history_path.read_text(encoding="utf-8"))
    latest_payload = json.loads(latest_path.read_text(encoding="utf-8"))
    assert history_payload["records_count"] == 1
    assert history_payload["records"][0]["status"] == "failure"
    assert history_payload["records"][0]["failed_stage"] == "phase14_acceptance"
    assert history_payload["records"][0]["error_type"] == "RuntimeError"
    assert history_payload["records"][0]["phase15_feedback_daily_summary_path"].endswith(
        "phase15_feedback_daily_summary.json"
    )
    assert latest_payload["status"] == "failure"
    assert latest_payload["failed_stage"] == "phase14_acceptance"
