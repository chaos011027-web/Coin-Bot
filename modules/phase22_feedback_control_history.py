from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
from uuid import uuid4


DEFAULT_HISTORY_OUTPUT_PATH = Path("data/phase22_feedback_control_history.json")
DEFAULT_LATEST_OUTPUT_PATH = Path("data/phase22_feedback_control_latest.json")


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
    raise TypeError(f"unsupported phase22 history record type: {type(row)!r}")


def _resolve_output_path(value: str, *, default_path: Path) -> Path:
    return Path(_safe_text(value) or str(default_path)).resolve()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _new_run_id() -> str:
    return f"phase22-{uuid4().hex}"


def _safe_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except Exception:
        return None


def build_phase22_feedback_control_history_record(
    *,
    phase21_summary: dict,
    phase21_summary_path,
    run_id: str = "",
    created_at: str = "",
) -> dict:
    summary = _normalize_row(phase21_summary or {})
    return {
        "run_id": _safe_text(run_id) or _new_run_id(),
        "status": _safe_text(summary.get("status")),
        "failed_stage": summary.get("failed_stage"),
        "error_type": summary.get("error_type"),
        "error_message": summary.get("error_message"),
        "phase19_feedback_control_snapshot_path": _safe_text(summary.get("phase19_feedback_control_snapshot_path")),
        "phase20_feedback_control_snapshot_acceptance_report_path": _safe_text(
            summary.get("phase20_feedback_control_snapshot_acceptance_report_path")
        ),
        "phase21_feedback_control_daily_summary_path": str(Path(str(phase21_summary_path)).resolve()),
        "records_count": _safe_int(summary.get("records_count")),
        "latest_run_id": summary.get("latest_run_id"),
        "created_at": _safe_text(created_at) or _utc_now_iso(),
    }


def _load_history_payload(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"records": [], "records_count": 0, "latest_run_id": None}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("phase22 history payload must be an object")
    records = payload.get("records")
    if not isinstance(records, list):
        raise RuntimeError("phase22 history payload missing records")
    return {
        "records": [_normalize_row(row) for row in records],
        "records_count": int(payload.get("records_count") or len(records)),
        "latest_run_id": payload.get("latest_run_id"),
    }


def append_phase22_feedback_control_history(record: dict, *, output_path: str = "") -> dict:
    target = _resolve_output_path(output_path, default_path=DEFAULT_HISTORY_OUTPUT_PATH)
    payload = _load_history_payload(target)
    normalized_record = _normalize_row(record or {})
    records: List[Dict[str, Any]] = list(payload.get("records") or [])
    records.append(normalized_record)
    written = {
        "records": records,
        "records_count": len(records),
        "latest_run_id": normalized_record.get("run_id"),
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(written, ensure_ascii=False, indent=2), encoding="utf-8")
    return written


def write_phase22_feedback_control_latest(record: dict, *, output_path: str = "") -> Path:
    target = _resolve_output_path(output_path, default_path=DEFAULT_LATEST_OUTPUT_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(_normalize_row(record or {}), ensure_ascii=False, indent=2), encoding="utf-8")
    return target
