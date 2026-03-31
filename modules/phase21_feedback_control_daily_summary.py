from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from modules.phase19_feedback_control_snapshot import DEFAULT_SNAPSHOT_OUTPUT_PATH
from run_phase20_feedback_control_snapshot_acceptance import DEFAULT_REPORT_OUTPUT_NAME


DEFAULT_SUMMARY_OUTPUT_PATH = Path("data/phase21_feedback_control_daily_summary.json")


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
            "check phase19 snapshot completed before phase20 acceptance",
            "check phase20 acceptance report points to the phase19 snapshot",
            "check phase21 summary preserves records_count and latest_run_id",
        ]
    if stage == "phase19_snapshot":
        return [
            "check phase19_feedback_control_snapshot.json generation",
            "check phase19 snapshot source still points to phase18 summary",
            "check the phase19 run stayed inside data/",
        ]
    return [
        "check phase20 acceptance report generation",
        "check phase19_feedback_control_snapshot.json still exists",
        "check phase20 acceptance remains read-only",
    ]


def build_phase21_feedback_control_daily_success_summary(*, phase19_result: dict, phase20_result: dict) -> dict:
    phase19 = dict(phase19_result or {})
    phase20 = dict(phase20_result or {})
    snapshot = dict(phase19.get("snapshot") or {})
    return {
        "status": "success",
        "failed_stage": None,
        "error_type": None,
        "error_message": None,
        "phase19_feedback_control_snapshot_path": _resolve_path(
            phase19.get("snapshot_path") or phase20.get("phase19_feedback_control_snapshot_path"),
            default_path=Path(DEFAULT_SNAPSHOT_OUTPUT_PATH.name),
        ),
        "phase20_feedback_control_snapshot_acceptance_report_path": _resolve_path(
            phase20.get("report_path"),
            default_path=Path(DEFAULT_REPORT_OUTPUT_NAME),
        ),
        "records_count": phase20.get("records_count", snapshot.get("records_count")),
        "latest_run_id": phase20.get("latest_run_id", snapshot.get("latest_run_id")),
        "manual_check_points": _manual_check_points("success"),
    }


def build_phase21_feedback_control_daily_failure_summary(
    *,
    failed_stage: str,
    error: Exception,
    data_dir: str = "data",
    phase19_result: dict | None = None,
) -> dict:
    resolved_data_dir = Path(_safe_text(data_dir) or "data").resolve()
    phase19 = dict(phase19_result or {})
    snapshot = dict(phase19.get("snapshot") or {})
    return {
        "status": "failure",
        "failed_stage": _safe_text(failed_stage),
        "error_type": type(error).__name__,
        "error_message": str(error),
        "phase19_feedback_control_snapshot_path": _resolve_path(
            phase19.get("snapshot_path"),
            default_path=resolved_data_dir / DEFAULT_SNAPSHOT_OUTPUT_PATH.name,
        ),
        "phase20_feedback_control_snapshot_acceptance_report_path": str(
            (resolved_data_dir / DEFAULT_REPORT_OUTPUT_NAME).resolve()
        ),
        "records_count": snapshot.get("records_count"),
        "latest_run_id": snapshot.get("latest_run_id"),
        "manual_check_points": _manual_check_points(_safe_text(failed_stage)),
    }


def write_phase21_feedback_control_daily_summary(summary: Dict[str, Any], *, output_path: str = "") -> Path:
    target = Path(_safe_text(output_path) or str(DEFAULT_SUMMARY_OUTPUT_PATH))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(summary or {}), ensure_ascii=False, indent=2), encoding="utf-8")
    return target.resolve()
