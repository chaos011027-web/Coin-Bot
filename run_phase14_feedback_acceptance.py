from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

from modules.phase14_feedback_data_quality_validator import validate_phase14_feedback_export_payloads
from run_phase14_feedback_export import (
    DEFAULT_DATA_DIR,
    DEFAULT_MANIFEST_OUTPUT_NAME,
    DEFAULT_RECORDS_OUTPUT_NAME,
    run_phase14_feedback_export,
)


DEFAULT_REPORT_OUTPUT_NAME = "phase14_feedback_acceptance_report.json"


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _resolve_data_dir(data_dir: str = "data") -> Path:
    return Path(_safe_text(data_dir) or str(DEFAULT_DATA_DIR)).resolve()


def _load_json_object(path: Path, *, label: str) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"{label} missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{label} payload must be an object")
    return dict(payload)


def _manual_check_points(stage: str) -> list[str]:
    if stage == "phase14_export":
        return [
            "check training_samples and training_labels sources are readable",
            "check lifecycle event inputs are readable",
            "check feedback_export_records.json was generated",
            "check phase14_feedback_manifest.json was generated",
        ]
    if stage == "success":
        return [
            "review phase14_feedback_manifest.json distributions",
            "confirm label_kind and feedback_class remain separated",
            "spot-check legacy direct enter remains excluded",
        ]
    return [
        "check feedback_export_records.json exists",
        "check phase14_feedback_manifest.json exists",
        "check label_kind and feedback_class remain separated",
    ]


def _write_report(report: Dict[str, Any], *, report_path: Path) -> Path:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(dict(report or {}), ensure_ascii=False, indent=2), encoding="utf-8")
    return report_path.resolve()


def _failure_report(
    *,
    stage: str,
    error: Exception,
    data_dir: Path,
) -> Dict[str, Any]:
    return {
        "status": "failure",
        "failed_stage": stage,
        "error_type": type(error).__name__,
        "error_message": str(error),
        "feedback_export_records_path": str((data_dir / DEFAULT_RECORDS_OUTPUT_NAME).resolve()),
        "feedback_manifest_path": str((data_dir / DEFAULT_MANIFEST_OUTPUT_NAME).resolve()),
        "manual_check_points": _manual_check_points(stage),
    }


def run_phase14_feedback_acceptance(data_dir="data", skip_export: bool = False) -> dict:
    resolved_data_dir = _resolve_data_dir(str(data_dir))
    report_path = resolved_data_dir / DEFAULT_REPORT_OUTPUT_NAME

    try:
        if not skip_export:
            export_result = run_phase14_feedback_export(data_dir=str(resolved_data_dir))
        else:
            export_result = {
                "status": "success",
                "feedback_export_records_path": str((resolved_data_dir / DEFAULT_RECORDS_OUTPUT_NAME).resolve()),
                "feedback_manifest_path": str((resolved_data_dir / DEFAULT_MANIFEST_OUTPUT_NAME).resolve()),
            }
    except Exception as error:
        _write_report(_failure_report(stage="phase14_export", error=error, data_dir=resolved_data_dir), report_path=report_path)
        raise

    try:
        records_payload = _load_json_object(
            Path(export_result["feedback_export_records_path"]),
            label="feedback export records",
        )
        manifest_payload = _load_json_object(
            Path(export_result["feedback_manifest_path"]),
            label="feedback manifest",
        )
        validation = validate_phase14_feedback_export_payloads(
            records_payload=records_payload,
            manifest_payload=manifest_payload,
        )
    except Exception as error:
        _write_report(_failure_report(stage="phase14_validator", error=error, data_dir=resolved_data_dir), report_path=report_path)
        raise

    success_report = {
        "status": "success",
        "failed_stage": None,
        "error_type": None,
        "error_message": None,
        "feedback_export_records_path": str(Path(export_result["feedback_export_records_path"]).resolve()),
        "feedback_manifest_path": str(Path(export_result["feedback_manifest_path"]).resolve()),
        "manual_check_points": _manual_check_points("success"),
        "records_count": validation["records_count"],
    }
    resolved_report_path = _write_report(success_report, report_path=report_path)
    return {
        **success_report,
        "report_path": str(resolved_report_path),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run phase14 feedback acceptance over exported feedback payloads.")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--skip-export", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    result = run_phase14_feedback_acceptance(
        data_dir=str(args.data_dir),
        skip_export=bool(args.skip_export),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
