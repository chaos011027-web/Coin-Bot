from copy import deepcopy

import pytest

from modules.phase20_feedback_control_snapshot_validator import validate_phase20_feedback_control_snapshot_payload


def _valid_snapshot_payload():
    return {
        "status": "success",
        "failed_stage": None,
        "error_type": None,
        "error_message": None,
        "phase16_feedback_daily_history_path": "C:/tmp/data/phase16_feedback_daily_history.json",
        "phase16_feedback_daily_latest_path": "C:/tmp/data/phase16_feedback_daily_latest.json",
        "phase17_feedback_history_acceptance_report_path": "C:/tmp/data/phase17_feedback_history_acceptance_report.json",
        "phase18_feedback_history_daily_summary_path": "C:/tmp/data/phase18_feedback_history_daily_summary.json",
        "records_count": 2,
        "latest_run_id": "phase16-run-002",
        "created_at": "2026-03-31T12:30:00Z",
    }


def test_phase20_feedback_control_snapshot_validator_accepts_minimal_valid_snapshot():
    result = validate_phase20_feedback_control_snapshot_payload(snapshot_payload=_valid_snapshot_payload())

    assert result["status"] == "success"
    assert result["records_count"] == 2
    assert result["latest_run_id"] == "phase16-run-002"


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ("not-an-object", "phase19 feedback control snapshot payload must be an object"),
        ({}, "required field missing: status"),
        (
            {**_valid_snapshot_payload(), "phase16_feedback_daily_history_path": ""},
            "required field missing: phase16_feedback_daily_history_path",
        ),
        (
            {**_valid_snapshot_payload(), "created_at": ""},
            "required field missing: created_at",
        ),
    ],
)
def test_phase20_feedback_control_snapshot_validator_rejects_invalid_snapshot(payload, message):
    with pytest.raises(RuntimeError, match=message):
        validate_phase20_feedback_control_snapshot_payload(snapshot_payload=deepcopy(payload))
