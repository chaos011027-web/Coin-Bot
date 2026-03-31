from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from run_phase14_feedback_acceptance import DEFAULT_REPORT_OUTPUT_NAME
from run_phase14_feedback_export import (
    DEFAULT_DATA_DIR,
    DEFAULT_MANIFEST_OUTPUT_NAME,
    DEFAULT_RECORDS_OUTPUT_NAME,
)


DEFAULT_SUMMARY_OUTPUT_PATH = Path("data/phase15_feedback_daily_summary.json")


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _resolve_path(value: Any, *, default_path: Path) -> str:
    text = _safe_text(value)
    target = Path(text) if text else default_path
    return str(target.resolve())


def _resolve_data_dir(data_dir: str = "data") -> Path:
    return Path(_safe_text(data_dir) or str(DEFAULT_DATA_DIR)).resolve()


def _manual_check_points(stage: str) -> list[str]:
    if stage == "success":
        return [
            "check phase14 feedback export completed before acceptance",
            "check phase14 acceptance reused exported payloads with skip_export=True",
            "check phase15 daily summary points to phase14 artifacts",
        ]
    if stage == "phase14_export":
        return [
            "check phase14 export inputs are readable",
            "check feedback_export_records.json generation",
            "check phase14_feedback_manifest.json generation",
        ]
    return [
        "check phase14 feedback acceptance report was written",
        "check feedback_export_records.json still exists",
        "check phase14_feedback_manifest.json still exists",
    ]


def build_phase15_feedback_daily_success_summary(
    *,
    phase14_export_result: dict,
    phase14_acceptance_result: dict,
) -> dict:
    export_result = dict(phase14_export_result or {})
    acceptance_result = dict(phase14_acceptance_result or {})
    return {
        "status": "success",
        "failed_stage": None,
        "error_type": None,
        "error_message": None,
        "feedback_export_records_path": _resolve_path(
            export_result.get("feedback_export_records_path") or acceptance_result.get("feedback_export_records_path"),
            default_path=Path(DEFAULT_RECORDS_OUTPUT_NAME),
        ),
        "feedback_manifest_path": _resolve_path(
            export_result.get("feedback_manifest_path") or acceptance_result.get("feedback_manifest_path"),
            default_path=Path(DEFAULT_MANIFEST_OUTPUT_NAME),
        ),
        "phase14_feedback_acceptance_report_path": _resolve_path(
            acceptance_result.get("report_path"),
            default_path=Path(DEFAULT_REPORT_OUTPUT_NAME),
        ),
        "manual_check_points": _manual_check_points("success"),
        "records_count": acceptance_result.get("records_count"),
    }


def build_phase15_feedback_daily_failure_summary(
    *,
    failed_stage: str,
    error: Exception,
    data_dir: str = "data",
    phase14_export_result: dict | None = None,
) -> dict:
    resolved_data_dir = _resolve_data_dir(data_dir)
    export_result = dict(phase14_export_result or {})
    return {
        "status": "failure",
        "failed_stage": _safe_text(failed_stage),
        "error_type": type(error).__name__,
        "error_message": str(error),
        "feedback_export_records_path": _resolve_path(
            export_result.get("feedback_export_records_path"),
            default_path=resolved_data_dir / DEFAULT_RECORDS_OUTPUT_NAME,
        ),
        "feedback_manifest_path": _resolve_path(
            export_result.get("feedback_manifest_path"),
            default_path=resolved_data_dir / DEFAULT_MANIFEST_OUTPUT_NAME,
        ),
        "phase14_feedback_acceptance_report_path": str((resolved_data_dir / DEFAULT_REPORT_OUTPUT_NAME).resolve()),
        "manual_check_points": _manual_check_points(_safe_text(failed_stage)),
        "records_count": None,
    }


def write_phase15_feedback_daily_summary(summary: Dict[str, Any], *, output_path: str = "") -> Path:
    target = Path(_safe_text(output_path) or str(DEFAULT_SUMMARY_OUTPUT_PATH))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(summary or {}), ensure_ascii=False, indent=2), encoding="utf-8")
    return target.resolve()
