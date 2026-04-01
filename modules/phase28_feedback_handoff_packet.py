from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


DEFAULT_PACKET_OUTPUT_PATH = Path("data/phase28_feedback_handoff_packet.json")


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
    raise TypeError(f"unsupported phase28 packet row type: {type(row)!r}")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _handoff_checklist() -> list[str]:
    return [
        "review phase25 release snapshot",
        "review phase26 acceptance report",
        "review phase27 release daily summary",
        "confirm all artifact paths remain inside data/",
        "confirm project is ready for unified local backfill",
    ]


def build_phase28_feedback_handoff_packet(
    *,
    phase27_summary: dict,
    phase27_summary_path,
    created_at: str = "",
) -> dict:
    summary = _normalize_row(phase27_summary or {})
    return {
        "status": _safe_text(summary.get("status")),
        "failed_stage": summary.get("failed_stage"),
        "error_type": summary.get("error_type"),
        "error_message": summary.get("error_message"),
        "phase25_feedback_release_snapshot_path": _safe_text(summary.get("phase25_feedback_release_snapshot_path")),
        "phase26_feedback_release_snapshot_acceptance_report_path": _safe_text(
            summary.get("phase26_feedback_release_snapshot_acceptance_report_path")
        ),
        "phase27_feedback_release_daily_summary_path": str(Path(str(phase27_summary_path)).resolve()),
        "records_count": summary.get("records_count"),
        "latest_run_id": summary.get("latest_run_id"),
        "handoff_checklist": _handoff_checklist(),
        "created_at": _safe_text(created_at) or _utc_now_iso(),
    }


def write_phase28_feedback_handoff_packet(packet: Dict[str, Any], *, output_path: str = "") -> Path:
    target = Path(_safe_text(output_path) or str(DEFAULT_PACKET_OUTPUT_PATH))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(packet or {}), ensure_ascii=False, indent=2), encoding="utf-8")
    return target.resolve()
