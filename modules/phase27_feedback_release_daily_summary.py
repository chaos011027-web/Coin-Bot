from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from modules.phase25_feedback_release_snapshot import DEFAULT_SNAPSHOT_OUTPUT_PATH
from run_phase26_feedback_release_snapshot_acceptance import DEFAULT_REPORT_OUTPUT_NAME


DEFAULT_SUMMARY_OUTPUT_PATH = Path("data/phase27_feedback_release_daily_summary.json")


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _resolve_path(value: Any, *, default_path: Path) -> str:
    text = _safe_text(value)
    target = Path(text) if text else default_path
    return str(target.resolve())


def _manual_check_points(stage: str) -> list[str]:
    if stage == "success":
        return [
            "check phase25 release snapshot completed before phase26 acceptance",
            "check phase26 acceptance report points to the phase25 snapshot",
            "check phase27 summary preserves records_count and latest_run_id",
        ]
    if stage == "phase25_release_snapshot":
        return [
            "check phase25_feedback_release_snapshot.json generation",
            "check phase25 snapshot source still points to phase24 summary",
            "check the phase25 run stayed inside data/",
        ]
    return [
        "check phase26 acceptance report generation",
        "check phase25_feedback_release_snapshot.json still exists",
        "check phase26 acceptance remains read-only",
    ]


def build_phase27_feedback_release_daily_success_summary(*, phase25_result: dict, phase26_result: dict) -> dict:
    phase25 = dict(phase25_result or {})
    phase26 = dict(phase26_result or {})
    snapshot = dict(phase25.get("snapshot") or {})
    return {
        "status": "success",
        "failed_stage": None,
        "error_type": None,
        "error_message": None,
        "phase25_feedback_release_snapshot_path": _resolve_path(
            phase25.get("snapshot_path") or phase26.get("phase25_feedback_release_snapshot_path"),
            default_path=Path(DEFAULT_SNAPSHOT_OUTPUT_PATH.name),
        ),
        "phase26_feedback_release_snapshot_acceptance_report_path": _resolve_path(
            phase26.get("report_path"),
            default_path=Path(DEFAULT_REPORT_OUTPUT_NAME),
        ),
        "records_count": phase26.get("records_count", snapshot.get("records_count")),
        "latest_run_id": phase26.get("latest_run_id", snapshot.get("latest_run_id")),
        "manual_check_points": _manual_check_points("success"),
    }


def build_phase27_feedback_release_daily_failure_summary(
    *,
    failed_stage: str,
    error: Exception,
    data_dir: str = "data",
    phase25_result: dict | None = None,
) -> dict:
    resolved_data_dir = Path(_safe_text(data_dir) or "data").resolve()
    phase25 = dict(phase25_result or {})
    snapshot = dict(phase25.get("snapshot") or {})
    return {
        "status": "failure",
        "failed_stage": _safe_text(failed_stage),
        "error_type": type(error).__name__,
        "error_message": str(error),
        "phase25_feedback_release_snapshot_path": _resolve_path(
            phase25.get("snapshot_path"),
            default_path=resolved_data_dir / DEFAULT_SNAPSHOT_OUTPUT_PATH.name,
        ),
        "phase26_feedback_release_snapshot_acceptance_report_path": str(
            (resolved_data_dir / DEFAULT_REPORT_OUTPUT_NAME).resolve()
        ),
        "records_count": snapshot.get("records_count"),
        "latest_run_id": snapshot.get("latest_run_id"),
        "manual_check_points": _manual_check_points(_safe_text(failed_stage)),
    }


def write_phase27_feedback_release_daily_summary(summary: Dict[str, Any], *, output_path: str = "") -> Path:
    target = Path(_safe_text(output_path) or str(DEFAULT_SUMMARY_OUTPUT_PATH))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(summary or {}), ensure_ascii=False, indent=2), encoding="utf-8")
    return target.resolve()
