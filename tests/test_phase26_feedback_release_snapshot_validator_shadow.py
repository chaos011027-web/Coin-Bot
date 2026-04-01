from copy import deepcopy

import pytest

from modules.phase26_feedback_release_snapshot_validator import validate_phase26_feedback_release_snapshot_payload


def _valid_snapshot_payload():
    return {
        "status": "success",
        "failed_stage": None,
        "error_type": None,
        "error_message": None,
        "phase22_feedback_control_history_path": "C:/tmp/data/phase22_feedback_control_history.json",
        "phase22_feedback_control_latest_path": "C:/tmp/data/phase22_feedback_control_latest.json",
        "phase23_feedback_control_history_acceptance_report_path": "C:/tmp/data/phase23_feedback_control_history_acceptance_report.json",
        "phase24_feedback_control_history_daily_summary_path": "C:/tmp/data/phase24_feedback_control_history_daily_summary.json",
        "records_count": 2,
        "latest_run_id": "phase22-run-002",
        "created_at": "2026-04-01T09:00:00Z",
    }


def test_phase26_feedback_release_snapshot_validator_accepts_minimal_valid_snapshot():
    result = validate_phase26_feedback_release_snapshot_payload(snapshot_payload=_valid_snapshot_payload())

    assert result["status"] == "success"
    assert result["records_count"] == 2
    assert result["latest_run_id"] == "phase22-run-002"


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ("not-an-object", "phase25 feedback release snapshot payload must be an object"),
        ({}, "required field missing: status"),
        (
            {**_valid_snapshot_payload(), "phase22_feedback_control_history_path": ""},
            "required field missing: phase22_feedback_control_history_path",
        ),
        (
            {**_valid_snapshot_payload(), "created_at": ""},
            "required field missing: created_at",
        ),
    ],
)
def test_phase26_feedback_release_snapshot_validator_rejects_invalid_snapshot(payload, message):
    with pytest.raises(RuntimeError, match=message):
        validate_phase26_feedback_release_snapshot_payload(snapshot_payload=deepcopy(payload))
