from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from modules.phase16_feedback_daily_history import DEFAULT_HISTORY_OUTPUT_PATH, DEFAULT_LATEST_OUTPUT_PATH
from run_phase17_feedback_history_acceptance import DEFAULT_REPORT_OUTPUT_NAME


DEFAULT_SUMMARY_OUTPUT_PATH = Path("data/phase18_feedback_history_daily_summary.json")


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
            "check phase16 history writer completed before phase17 acceptance",
            "check phase17 acceptance report points to phase16 artifacts",
            "check phase18 summary preserves latest_run_id and records_count",
        ]
    if stage == "phase16_history_daily":
        return [
            "check phase16 history writer inputs are readable",
            "check phase16_feedback_daily_history.json generation",
            "check phase16_feedback_daily_latest.json generation",
        ]
    return [
        "check phase17 acceptance report generation",
        "check phase16 history/latest files still exist",
        "check phase17 acceptance remains read-only",
    ]


def build_phase18_feedback_history_daily_success_summary(
    *,
    phase16_result: dict,
    phase17_result: dict,
) -> dict:
    phase16 = dict(phase16_result or {})
    phase17 = dict(phase17_result or {})
    phase16_history = dict(phase16.get("history") or {})
    return {
        "status": "success",
        "failed_stage": None,
        "error_type": None,
        "error_message": None,
        "phase16_feedback_daily_history_path": _resolve_path(
            phase16.get("history_path") or phase17.get("phase16_feedback_daily_history_path"),
            default_path=Path(DEFAULT_HISTORY_OUTPUT_PATH.name),
        ),
        "phase16_feedback_daily_latest_path": _resolve_path(
            phase16.get("latest_path") or phase17.get("phase16_feedback_daily_latest_path"),
            default_path=Path(DEFAULT_LATEST_OUTPUT_PATH.name),
        ),
        "phase17_feedback_history_acceptance_report_path": _resolve_path(
            phase17.get("report_path"),
            default_path=Path(DEFAULT_REPORT_OUTPUT_NAME),
        ),
        "records_count": phase17.get("records_count", phase16_history.get("records_count")),
        "latest_run_id": phase17.get("latest_run_id", phase16_history.get("latest_run_id")),
        "manual_check_points": _manual_check_points("success"),
    }


def build_phase18_feedback_history_daily_failure_summary(
    *,
    failed_stage: str,
    error: Exception,
    data_dir: str = "data",
    phase16_result: dict | None = None,
) -> dict:
    resolved_data_dir = Path(_safe_text(data_dir) or "data").resolve()
    phase16 = dict(phase16_result or {})
    phase16_history = dict(phase16.get("history") or {})
    return {
        "status": "failure",
        "failed_stage": _safe_text(failed_stage),
        "error_type": type(error).__name__,
        "error_message": str(error),
        "phase16_feedback_daily_history_path": _resolve_path(
            phase16.get("history_path"),
            default_path=resolved_data_dir / DEFAULT_HISTORY_OUTPUT_PATH.name,
        ),
        "phase16_feedback_daily_latest_path": _resolve_path(
            phase16.get("latest_path"),
            default_path=resolved_data_dir / DEFAULT_LATEST_OUTPUT_PATH.name,
        ),
        "phase17_feedback_history_acceptance_report_path": str((resolved_data_dir / DEFAULT_REPORT_OUTPUT_NAME).resolve()),
        "records_count": phase16_history.get("records_count"),
        "latest_run_id": phase16_history.get("latest_run_id"),
        "manual_check_points": _manual_check_points(_safe_text(failed_stage)),
    }


def write_phase18_feedback_history_daily_summary(summary: Dict[str, Any], *, output_path: str = "") -> Path:
    target = Path(_safe_text(output_path) or str(DEFAULT_SUMMARY_OUTPUT_PATH))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(summary or {}), ensure_ascii=False, indent=2), encoding="utf-8")
    return target.resolve()
