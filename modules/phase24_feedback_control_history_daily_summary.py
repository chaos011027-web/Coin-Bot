from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from modules.phase22_feedback_control_history import DEFAULT_HISTORY_OUTPUT_PATH, DEFAULT_LATEST_OUTPUT_PATH
from run_phase23_feedback_control_history_acceptance import DEFAULT_REPORT_OUTPUT_NAME


DEFAULT_SUMMARY_OUTPUT_PATH = Path("data/phase24_feedback_control_history_daily_summary.json")


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
            "check phase22 control history completed before phase23 acceptance",
            "check phase23 acceptance report points to the phase22 artifacts",
            "check phase24 summary preserves records_count and latest_run_id",
        ]
    if stage == "phase22_control_history":
        return [
            "check phase22_feedback_control_history.json generation",
            "check phase22_feedback_control_latest.json generation",
            "check the phase22 run stayed inside data/",
        ]
    return [
        "check phase23 acceptance report generation",
        "check phase22 history/latest files still exist",
        "check phase23 acceptance remains read-only",
    ]


def build_phase24_feedback_control_history_daily_success_summary(*, phase22_result: dict, phase23_result: dict) -> dict:
    phase22 = dict(phase22_result or {})
    phase23 = dict(phase23_result or {})
    history = dict(phase22.get("history") or {})
    return {
        "status": "success",
        "failed_stage": None,
        "error_type": None,
        "error_message": None,
        "phase22_feedback_control_history_path": _resolve_path(
            phase22.get("history_path") or phase23.get("phase22_feedback_control_history_path"),
            default_path=Path(DEFAULT_HISTORY_OUTPUT_PATH.name),
        ),
        "phase22_feedback_control_latest_path": _resolve_path(
            phase22.get("latest_path") or phase23.get("phase22_feedback_control_latest_path"),
            default_path=Path(DEFAULT_LATEST_OUTPUT_PATH.name),
        ),
        "phase23_feedback_control_history_acceptance_report_path": _resolve_path(
            phase23.get("report_path"),
            default_path=Path(DEFAULT_REPORT_OUTPUT_NAME),
        ),
        "records_count": phase23.get("records_count", history.get("records_count")),
        "latest_run_id": phase23.get("latest_run_id", history.get("latest_run_id")),
        "manual_check_points": _manual_check_points("success"),
    }


def build_phase24_feedback_control_history_daily_failure_summary(
    *,
    failed_stage: str,
    error: Exception,
    data_dir: str = "data",
    phase22_result: dict | None = None,
) -> dict:
    resolved_data_dir = Path(_safe_text(data_dir) or "data").resolve()
    phase22 = dict(phase22_result or {})
    history = dict(phase22.get("history") or {})
    return {
        "status": "failure",
        "failed_stage": _safe_text(failed_stage),
        "error_type": type(error).__name__,
        "error_message": str(error),
        "phase22_feedback_control_history_path": _resolve_path(
            phase22.get("history_path"),
            default_path=resolved_data_dir / DEFAULT_HISTORY_OUTPUT_PATH.name,
        ),
        "phase22_feedback_control_latest_path": _resolve_path(
            phase22.get("latest_path"),
            default_path=resolved_data_dir / DEFAULT_LATEST_OUTPUT_PATH.name,
        ),
        "phase23_feedback_control_history_acceptance_report_path": str(
            (resolved_data_dir / DEFAULT_REPORT_OUTPUT_NAME).resolve()
        ),
        "records_count": history.get("records_count"),
        "latest_run_id": history.get("latest_run_id"),
        "manual_check_points": _manual_check_points(_safe_text(failed_stage)),
    }


def write_phase24_feedback_control_history_daily_summary(summary: Dict[str, Any], *, output_path: str = "") -> Path:
    target = Path(_safe_text(output_path) or str(DEFAULT_SUMMARY_OUTPUT_PATH))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(summary or {}), ensure_ascii=False, indent=2), encoding="utf-8")
    return target.resolve()
