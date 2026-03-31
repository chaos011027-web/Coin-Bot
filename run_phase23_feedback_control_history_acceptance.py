from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

from modules.phase22_feedback_control_history import DEFAULT_HISTORY_OUTPUT_PATH, DEFAULT_LATEST_OUTPUT_PATH
from modules.phase23_feedback_control_history_validator import validate_phase23_feedback_control_history_payloads
from run_phase14_feedback_export import DEFAULT_DATA_DIR


DEFAULT_REPORT_OUTPUT_NAME = "phase23_feedback_control_history_acceptance_report.json"


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _resolve_data_dir(data_dir: str = "data") -> Path:
    return Path(_safe_text(data_dir) or str(DEFAULT_DATA_DIR)).resolve()


def _load_json_object(path: Path, *, missing_label: str) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"{missing_label} missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"{missing_label} payload must be an object")
    return dict(payload)


def _manual_check_points(stage: str) -> list[str]:
    if stage == "success":
        return [
            "check phase22 control history remains append-only",
            "check latest points to the final history record",
            "spot-check required history fields remain present",
        ]
    if stage == "phase22_control_history_load":
        return [
            "check phase22_feedback_control_history.json exists",
            "check the file is readable JSON",
            "check the path still points inside data/",
        ]
    if stage == "phase22_control_latest_load":
        return [
            "check phase22_feedback_control_latest.json exists",
            "check the file is readable JSON",
            "check the path still points inside data/",
        ]
    return [
        "check history records_count matches record length",
        "check latest_run_id matches the final history record",
        "check latest payload matches the final history record",
    ]


def _write_report(report: Dict[str, Any], *, report_path: Path) -> Path:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(dict(report or {}), ensure_ascii=False, indent=2), encoding="utf-8")
    return report_path.resolve()


def _build_failure_report(*, failed_stage: str, error: Exception, history_path: Path, latest_path: Path) -> Dict[str, Any]:
    return {
        "status": "failure",
        "failed_stage": failed_stage,
        "error_type": type(error).__name__,
        "error_message": str(error),
        "phase22_feedback_control_history_path": str(history_path.resolve()),
        "phase22_feedback_control_latest_path": str(latest_path.resolve()),
        "records_count": None,
        "latest_run_id": None,
        "manual_check_points": _manual_check_points(failed_stage),
    }


def run_phase23_feedback_control_history_acceptance(data_dir="data") -> dict:
    resolved_data_dir = _resolve_data_dir(str(data_dir))
    history_path = resolved_data_dir / DEFAULT_HISTORY_OUTPUT_PATH.name
    latest_path = resolved_data_dir / DEFAULT_LATEST_OUTPUT_PATH.name
    report_path = resolved_data_dir / DEFAULT_REPORT_OUTPUT_NAME

    try:
        history_payload = _load_json_object(history_path, missing_label="phase22 feedback control history")
    except Exception as error:
        _write_report(
            _build_failure_report(
                failed_stage="phase22_control_history_load",
                error=error,
                history_path=history_path,
                latest_path=latest_path,
            ),
            report_path=report_path,
        )
        raise

    try:
        latest_payload = _load_json_object(latest_path, missing_label="phase22 feedback control latest")
    except Exception as error:
        _write_report(
            _build_failure_report(
                failed_stage="phase22_control_latest_load",
                error=error,
                history_path=history_path,
                latest_path=latest_path,
            ),
            report_path=report_path,
        )
        raise

    try:
        validation = validate_phase23_feedback_control_history_payloads(
            history_payload=history_payload,
            latest_payload=latest_payload,
        )
    except Exception as error:
        _write_report(
            _build_failure_report(
                failed_stage="phase23_control_history_validator",
                error=error,
                history_path=history_path,
                latest_path=latest_path,
            ),
            report_path=report_path,
        )
        raise

    success_report = {
        "status": "success",
        "failed_stage": None,
        "error_type": None,
        "error_message": None,
        "phase22_feedback_control_history_path": str(history_path.resolve()),
        "phase22_feedback_control_latest_path": str(latest_path.resolve()),
        "records_count": validation["records_count"],
        "latest_run_id": validation["latest_run_id"],
        "manual_check_points": _manual_check_points("success"),
    }
    resolved_report_path = _write_report(success_report, report_path=report_path)
    return {
        **success_report,
        "report_path": str(resolved_report_path),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the phase23 feedback control history acceptance over frozen phase22 artifacts.")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    result = run_phase23_feedback_control_history_acceptance(data_dir=str(args.data_dir))
    print(json.dumps(result, ensure_ascii=False, indent=2))
