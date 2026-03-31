from __future__ import annotations

from typing import Any, Dict, List


REQUIRED_HISTORY_TOP_LEVEL_FIELDS = [
    "records",
    "records_count",
    "latest_run_id",
]
REQUIRED_HISTORY_RECORD_FIELDS = [
    "run_id",
    "status",
    "failed_stage",
    "error_type",
    "error_message",
    "phase19_feedback_control_snapshot_path",
    "phase20_feedback_control_snapshot_acceptance_report_path",
    "phase21_feedback_control_daily_summary_path",
    "records_count",
    "latest_run_id",
    "created_at",
]


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_row(row: Any) -> Dict[str, Any]:
    if isinstance(row, dict):
        return dict(row)
    try:
        return dict(row)
    except Exception:
        pass
    if hasattr(row, "keys"):
        return {key: row[key] for key in row.keys()}
    raise TypeError(f"unsupported phase23 history row type: {type(row)!r}")


def _require_field(record: Dict[str, Any], field_name: str) -> None:
    if field_name not in record:
        raise RuntimeError(f"required field missing: {field_name}")


def _require_non_empty_text(record: Dict[str, Any], field_name: str) -> str:
    _require_field(record, field_name)
    text = _safe_text(record.get(field_name))
    if not text:
        raise RuntimeError(f"required field missing: {field_name}")
    return text


def _validate_history_record(record: Dict[str, Any]) -> Dict[str, Any]:
    normalized = _normalize_row(record)
    for field_name in REQUIRED_HISTORY_RECORD_FIELDS:
        _require_field(normalized, field_name)

    for field_name in [
        "run_id",
        "status",
        "phase19_feedback_control_snapshot_path",
        "phase20_feedback_control_snapshot_acceptance_report_path",
        "phase21_feedback_control_daily_summary_path",
        "created_at",
    ]:
        _require_non_empty_text(normalized, field_name)

    return normalized


def validate_phase23_feedback_control_history_payloads(*, history_payload: dict, latest_payload: dict) -> dict:
    history = _normalize_row(history_payload or {})
    latest = _normalize_row(latest_payload or {})

    for field_name in REQUIRED_HISTORY_TOP_LEVEL_FIELDS:
        _require_field(history, field_name)

    records = history.get("records")
    if not isinstance(records, list):
        raise RuntimeError("history records must be a list")
    if not records:
        raise RuntimeError("feedback control history records empty")

    if int(history.get("records_count") or 0) != len(records):
        raise RuntimeError("history records_count mismatch")

    latest_run_id = _require_non_empty_text(history, "latest_run_id")
    normalized_records: List[Dict[str, Any]] = [_validate_history_record(record) for record in records]
    last_record = normalized_records[-1]
    if latest_run_id != _safe_text(last_record.get("run_id")):
        raise RuntimeError("latest_run_id mismatch")

    normalized_latest = _validate_history_record(latest)
    if normalized_latest != last_record:
        raise RuntimeError("latest payload mismatch")

    return {
        "status": "success",
        "records_count": len(normalized_records),
        "latest_run_id": latest_run_id,
    }
