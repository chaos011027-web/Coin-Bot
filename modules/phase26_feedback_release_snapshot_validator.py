from __future__ import annotations

from typing import Any, Dict


REQUIRED_SNAPSHOT_FIELDS = [
    "status",
    "failed_stage",
    "error_type",
    "error_message",
    "phase22_feedback_control_history_path",
    "phase22_feedback_control_latest_path",
    "phase23_feedback_control_history_acceptance_report_path",
    "phase24_feedback_control_history_daily_summary_path",
    "records_count",
    "latest_run_id",
    "created_at",
]
REQUIRED_PATH_FIELDS = [
    "phase22_feedback_control_history_path",
    "phase22_feedback_control_latest_path",
    "phase23_feedback_control_history_acceptance_report_path",
    "phase24_feedback_control_history_daily_summary_path",
]
ALLOWED_STATUS = {"success", "failure"}


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_row(row: Any) -> Dict[str, Any]:
    if not isinstance(row, dict):
        raise RuntimeError("phase25 feedback release snapshot payload must be an object")
    return dict(row)


def _require_field(record: Dict[str, Any], field_name: str) -> None:
    if field_name not in record:
        raise RuntimeError(f"required field missing: {field_name}")


def validate_phase26_feedback_release_snapshot_payload(*, snapshot_payload: dict) -> dict:
    snapshot = _normalize_row(snapshot_payload or {})
    for field_name in REQUIRED_SNAPSHOT_FIELDS:
        _require_field(snapshot, field_name)

    status = _safe_text(snapshot.get("status"))
    if status not in ALLOWED_STATUS:
        raise RuntimeError("invalid status")

    for field_name in REQUIRED_PATH_FIELDS:
        if not _safe_text(snapshot.get(field_name)):
            raise RuntimeError(f"required field missing: {field_name}")

    if not _safe_text(snapshot.get("created_at")):
        raise RuntimeError("required field missing: created_at")

    records_count = snapshot.get("records_count")
    if records_count not in (None, ""):
        try:
            records_count = int(records_count)
        except Exception as exc:
            raise RuntimeError("invalid records_count") from exc

    latest_run_id = snapshot.get("latest_run_id")
    if latest_run_id is not None and not _safe_text(latest_run_id):
        raise RuntimeError("invalid latest_run_id")

    return {
        "status": "success",
        "records_count": records_count,
        "latest_run_id": latest_run_id,
    }
