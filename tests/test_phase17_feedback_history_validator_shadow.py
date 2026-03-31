from copy import deepcopy

import pytest

from modules.phase17_feedback_history_validator import validate_phase17_feedback_history_payloads


def _valid_history_payload():
    record = {
        "run_id": "phase16-run-001",
        "status": "success",
        "failed_stage": None,
        "error_type": None,
        "error_message": None,
        "feedback_export_records_path": "C:/tmp/data/feedback_export_records.json",
        "feedback_manifest_path": "C:/tmp/data/phase14_feedback_manifest.json",
        "phase14_feedback_acceptance_report_path": "C:/tmp/data/phase14_feedback_acceptance_report.json",
        "phase15_feedback_daily_summary_path": "C:/tmp/data/phase15_feedback_daily_summary.json",
        "records_count": 2,
        "created_at": "2026-03-31T12:00:00Z",
    }
    return {
        "records": [record],
        "records_count": 1,
        "latest_run_id": "phase16-run-001",
    }


def _valid_latest_payload():
    return {
        "run_id": "phase16-run-001",
        "status": "success",
        "failed_stage": None,
        "error_type": None,
        "error_message": None,
        "feedback_export_records_path": "C:/tmp/data/feedback_export_records.json",
        "feedback_manifest_path": "C:/tmp/data/phase14_feedback_manifest.json",
        "phase14_feedback_acceptance_report_path": "C:/tmp/data/phase14_feedback_acceptance_report.json",
        "phase15_feedback_daily_summary_path": "C:/tmp/data/phase15_feedback_daily_summary.json",
        "records_count": 2,
        "created_at": "2026-03-31T12:00:00Z",
    }


def test_phase17_feedback_history_validator_accepts_minimal_valid_history_and_latest_payloads():
    result = validate_phase17_feedback_history_payloads(
        history_payload=_valid_history_payload(),
        latest_payload=_valid_latest_payload(),
    )

    assert result["status"] == "success"
    assert result["records_count"] == 1
    assert result["latest_run_id"] == "phase16-run-001"


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda history, latest: history.__setitem__("records", []),
            "feedback history records empty",
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
            lambda history, latest: history.__setitem__("latest_run_id", "phase16-run-mismatch"),
            "latest_run_id mismatch",
        ),
        (
            lambda history, latest: latest.__setitem__("run_id", "phase16-run-mismatch"),
            "latest payload mismatch",
        ),
        (
            lambda history, latest: history["records"][0].__delitem__("created_at"),
            "required field missing: created_at",
        ),
        (
            lambda history, latest: latest.__setitem__("records", []),
            "latest payload must not contain records",
        ),
    ],
)
def test_phase17_feedback_history_validator_rejects_broken_history_or_latest(mutator, message):
    history = deepcopy(_valid_history_payload())
    latest = deepcopy(_valid_latest_payload())
    mutator(history, latest)

    with pytest.raises(RuntimeError, match=message):
        validate_phase17_feedback_history_payloads(
            history_payload=history,
            latest_payload=latest,
        )
