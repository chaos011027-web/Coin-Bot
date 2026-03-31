from copy import deepcopy

import pytest

from modules.phase23_feedback_control_history_validator import validate_phase23_feedback_control_history_payloads


def _valid_history_payload():
    record = {
        "run_id": "phase22-run-001",
        "status": "success",
        "failed_stage": None,
        "error_type": None,
        "error_message": None,
        "phase19_feedback_control_snapshot_path": "C:/tmp/data/phase19_feedback_control_snapshot.json",
        "phase20_feedback_control_snapshot_acceptance_report_path": "C:/tmp/data/phase20_feedback_control_snapshot_acceptance_report.json",
        "phase21_feedback_control_daily_summary_path": "C:/tmp/data/phase21_feedback_control_daily_summary.json",
        "records_count": 2,
        "latest_run_id": "phase16-run-002",
        "created_at": "2026-03-31T13:00:00Z",
    }
    return {
        "records": [record],
        "records_count": 1,
        "latest_run_id": "phase22-run-001",
    }


def _valid_latest_payload():
    return {
        "run_id": "phase22-run-001",
        "status": "success",
        "failed_stage": None,
        "error_type": None,
        "error_message": None,
        "phase19_feedback_control_snapshot_path": "C:/tmp/data/phase19_feedback_control_snapshot.json",
        "phase20_feedback_control_snapshot_acceptance_report_path": "C:/tmp/data/phase20_feedback_control_snapshot_acceptance_report.json",
        "phase21_feedback_control_daily_summary_path": "C:/tmp/data/phase21_feedback_control_daily_summary.json",
        "records_count": 2,
        "latest_run_id": "phase16-run-002",
        "created_at": "2026-03-31T13:00:00Z",
    }


def test_phase23_feedback_control_history_validator_accepts_minimal_valid_history_and_latest_payloads():
    result = validate_phase23_feedback_control_history_payloads(
        history_payload=_valid_history_payload(),
        latest_payload=_valid_latest_payload(),
    )

    assert result["status"] == "success"
    assert result["records_count"] == 1
    assert result["latest_run_id"] == "phase22-run-001"


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda history, latest: history.__setitem__("records", []),
            "feedback control history records empty",
        ),
        (
            lambda history, latest: history.__setitem__("records_count", 99),
            "history records_count mismatch",
        ),
        (
            lambda history, latest: history.__delitem__("latest_run_id"),
            "required field missing: latest_run_id",
        ),
        (
            lambda history, latest: history.__setitem__("latest_run_id", "phase22-run-mismatch"),
            "latest_run_id mismatch",
        ),
        (
            lambda history, latest: latest.__setitem__("run_id", "phase22-run-mismatch"),
            "latest payload mismatch",
        ),
        (
            lambda history, latest: history["records"][0].__delitem__("created_at"),
            "required field missing: created_at",
        ),
    ],
)
def test_phase23_feedback_control_history_validator_rejects_broken_history_or_latest(mutator, message):
    history = deepcopy(_valid_history_payload())
    latest = deepcopy(_valid_latest_payload())
    mutator(history, latest)

    with pytest.raises(RuntimeError, match=message):
        validate_phase23_feedback_control_history_payloads(
            history_payload=history,
            latest_payload=latest,
        )
