import json
from pathlib import Path

import pytest

import run_phase8_daily_acceptance as phase8_runner


def test_phase8_runner_chains_phase5_and_phase7_and_writes_summary(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    calls = []

    def fake_phase5(**kwargs):
        calls.append(("phase5", dict(kwargs)))
        return {
            "labels_count": 3,
            "training_replay_records_path": str((tmp_path / "data" / "training_replay_records.json").resolve()),
            "training_dataset_path": str((tmp_path / "data" / "training_dataset_bridge.csv").resolve()),
            "replay_dataset_path": str((tmp_path / "data" / "replay_dataset_bridge.json").resolve()),
            "manifest_path": str((tmp_path / "data" / "phase5_pipeline_manifest.json").resolve()),
            "manifest": {
                "samples_count": 3,
                "trade_closed_count": 1,
                "training_rows_count": 1,
                "replay_rows_count": 1,
            },
            "consumer_smoke": {},
        }

    def fake_phase7(**kwargs):
        calls.append(("phase7", dict(kwargs)))
        return {
            "report_path": str((tmp_path / "data" / "phase7_data_quality_report.json").resolve()),
            "report": {
                "samples_count": 3,
                "trade_closed_count": 1,
                "training_rows_count": 1,
                "replay_rows_count": 1,
            },
        }

    monkeypatch.setattr(phase8_runner, "run_phase5_data_pipeline", fake_phase5)
    monkeypatch.setattr(phase8_runner, "run_phase7_data_quality_check", fake_phase7)

    result = phase8_runner.run_phase8_daily_acceptance()

    assert [name for name, _ in calls] == ["phase5", "phase7"]
    assert calls[1][1]["training_replay_records_path"].endswith("training_replay_records.json")
    assert calls[1][1]["training_dataset_path"].endswith("training_dataset_bridge.csv")
    assert calls[1][1]["replay_dataset_path"].endswith("replay_dataset_bridge.json")

    summary_path = tmp_path / "data" / "phase8_daily_acceptance_summary.json"
    assert Path(result["summary_path"]) == summary_path.resolve()
    assert summary_path.exists()
    assert result["summary"]["status"] == "success"
    assert result["summary"]["phase5_manifest_path"].endswith("phase5_pipeline_manifest.json")
    assert result["summary"]["phase7_report_path"].endswith("phase7_data_quality_report.json")
    assert result["summary"]["training_replay_records_path"].endswith("training_replay_records.json")
    assert result["summary"]["training_dataset_path"].endswith("training_dataset_bridge.csv")
    assert result["summary"]["replay_dataset_path"].endswith("replay_dataset_bridge.json")
    assert result["summary"]["samples_count"] == 3
    assert result["summary"]["trade_closed_count"] == 1
    assert result["summary"]["training_rows_count"] == 1
    assert result["summary"]["replay_rows_count"] == 1

    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload["status"] == "success"
    assert payload["samples_count"] == 3
    assert payload["trade_closed_count"] == 1


def test_phase8_runner_stops_immediately_when_phase5_fails(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    calls = []

    def fake_phase5(**kwargs):
        calls.append("phase5")
        raise RuntimeError("phase5 failed")

    def fake_phase7(**kwargs):
        calls.append("phase7")
        return {}

    monkeypatch.setattr(phase8_runner, "run_phase5_data_pipeline", fake_phase5)
    monkeypatch.setattr(phase8_runner, "run_phase7_data_quality_check", fake_phase7)

    with pytest.raises(RuntimeError, match="phase5 failed"):
        phase8_runner.run_phase8_daily_acceptance()

    assert calls == ["phase5"]
    summary_path = tmp_path / "data" / "phase8_daily_acceptance_summary.json"
    assert summary_path.exists()
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["failed_stage"] == "phase5"
    assert payload["error_type"] == "RuntimeError"
    assert payload["error_message"] == "phase5 failed"
    assert payload["training_replay_records_path"].endswith("training_replay_records.json")
    assert payload["training_dataset_path"].endswith("training_dataset_bridge.csv")
    assert payload["replay_dataset_path"].endswith("replay_dataset_bridge.json")
    assert payload["phase5_manifest_path"].endswith("phase5_pipeline_manifest.json")
    assert payload["manual_check_points"]
    assert any("training_replay_records" in item for item in payload["manual_check_points"])
    assert any("training_dataset_bridge" in item for item in payload["manual_check_points"])
    assert any("replay_dataset_bridge" in item for item in payload["manual_check_points"])
    assert any("phase5 manifest" in item for item in payload["manual_check_points"])


def test_phase8_runner_does_not_swallow_phase7_failures(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    calls = []

    def fake_phase5(**kwargs):
        calls.append("phase5")
        return {
            "labels_count": 3,
            "training_replay_records_path": str((tmp_path / "data" / "training_replay_records.json").resolve()),
            "training_dataset_path": str((tmp_path / "data" / "training_dataset_bridge.csv").resolve()),
            "replay_dataset_path": str((tmp_path / "data" / "replay_dataset_bridge.json").resolve()),
            "manifest_path": str((tmp_path / "data" / "phase5_pipeline_manifest.json").resolve()),
            "manifest": {
                "samples_count": 3,
                "trade_closed_count": 1,
                "training_rows_count": 1,
                "replay_rows_count": 1,
            },
            "consumer_smoke": {},
        }

    def fake_phase7(**kwargs):
        calls.append("phase7")
        raise RuntimeError("phase7 failed")

    monkeypatch.setattr(phase8_runner, "run_phase5_data_pipeline", fake_phase5)
    monkeypatch.setattr(phase8_runner, "run_phase7_data_quality_check", fake_phase7)

    with pytest.raises(RuntimeError, match="phase7 failed"):
        phase8_runner.run_phase8_daily_acceptance()

    assert calls == ["phase5", "phase7"]
    summary_path = tmp_path / "data" / "phase8_daily_acceptance_summary.json"
    assert summary_path.exists()
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["failed_stage"] == "phase7"
    assert payload["error_type"] == "RuntimeError"
    assert payload["error_message"] == "phase7 failed"
    assert payload["phase5_manifest_path"].endswith("phase5_pipeline_manifest.json")
    assert payload["training_replay_records_path"].endswith("training_replay_records.json")
    assert payload["training_dataset_path"].endswith("training_dataset_bridge.csv")
    assert payload["replay_dataset_path"].endswith("replay_dataset_bridge.json")
    assert payload["phase7_report_path"].endswith("phase7_data_quality_report.json")
    assert payload["manual_check_points"]
    assert any("phase7 report" in item for item in payload["manual_check_points"])
    assert any("Phase 5 outputs" in item for item in payload["manual_check_points"])
    assert any("validator inputs" in item for item in payload["manual_check_points"])


def test_phase8_runner_writes_summary_to_custom_output_path(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    def fake_phase5(**kwargs):
        return {
            "labels_count": 3,
            "training_replay_records_path": str((tmp_path / "data" / "training_replay_records.json").resolve()),
            "training_dataset_path": str((tmp_path / "data" / "training_dataset_bridge.csv").resolve()),
            "replay_dataset_path": str((tmp_path / "data" / "replay_dataset_bridge.json").resolve()),
            "manifest_path": str((tmp_path / "data" / "phase5_pipeline_manifest.json").resolve()),
            "manifest": {
                "samples_count": 3,
                "trade_closed_count": 1,
                "training_rows_count": 1,
                "replay_rows_count": 1,
            },
            "consumer_smoke": {},
        }

    def fake_phase7(**kwargs):
        return {
            "report_path": str((tmp_path / "data" / "phase7_data_quality_report.json").resolve()),
            "report": {
                "samples_count": 3,
                "trade_closed_count": 1,
                "training_rows_count": 1,
                "replay_rows_count": 1,
            },
        }

    monkeypatch.setattr(phase8_runner, "run_phase5_data_pipeline", fake_phase5)
    monkeypatch.setattr(phase8_runner, "run_phase7_data_quality_check", fake_phase7)

    output_path = tmp_path / "reports" / "phase8_summary.json"
    result = phase8_runner.run_phase8_daily_acceptance(summary_output_path=str(output_path))

    assert Path(result["summary_path"]) == output_path.resolve()
    assert output_path.exists()
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["status"] == "success"
    assert payload["samples_count"] == 3
    assert payload["trade_closed_count"] == 1
    assert payload["training_replay_records_path"] == str((tmp_path / "data" / "training_replay_records.json").resolve())
