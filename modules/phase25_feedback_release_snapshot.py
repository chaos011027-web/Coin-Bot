from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


DEFAULT_SNAPSHOT_OUTPUT_PATH = Path("data/phase25_feedback_release_snapshot.json")


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
    raise TypeError(f"unsupported phase25 snapshot row type: {type(row)!r}")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_phase25_feedback_release_snapshot(
    *,
    phase24_summary: dict,
    phase24_summary_path,
    created_at: str = "",
) -> dict:
    summary = _normalize_row(phase24_summary or {})
    return {
        "status": _safe_text(summary.get("status")),
        "failed_stage": summary.get("failed_stage"),
        "error_type": summary.get("error_type"),
        "error_message": summary.get("error_message"),
        "phase22_feedback_control_history_path": _safe_text(summary.get("phase22_feedback_control_history_path")),
        "phase22_feedback_control_latest_path": _safe_text(summary.get("phase22_feedback_control_latest_path")),
        "phase23_feedback_control_history_acceptance_report_path": _safe_text(
            summary.get("phase23_feedback_control_history_acceptance_report_path")
        ),
        "phase24_feedback_control_history_daily_summary_path": str(Path(str(phase24_summary_path)).resolve()),
        "records_count": summary.get("records_count"),
        "latest_run_id": summary.get("latest_run_id"),
        "created_at": _safe_text(created_at) or _utc_now_iso(),
    }


def write_phase25_feedback_release_snapshot(snapshot: Dict[str, Any], *, output_path: str = "") -> Path:
    target = Path(_safe_text(output_path) or str(DEFAULT_SNAPSHOT_OUTPUT_PATH))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(snapshot or {}), ensure_ascii=False, indent=2), encoding="utf-8")
    return target.resolve()
