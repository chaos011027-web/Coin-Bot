from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

from modules.phase25_feedback_release_snapshot import DEFAULT_SNAPSHOT_OUTPUT_PATH
from modules.phase26_feedback_release_snapshot_validator import validate_phase26_feedback_release_snapshot_payload
from run_phase14_feedback_export import DEFAULT_DATA_DIR


DEFAULT_REPORT_OUTPUT_NAME = "phase26_feedback_release_snapshot_acceptance_report.json"


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _resolve_data_dir(data_dir: str = "data") -> Path:
    return Path(_safe_text(data_dir) or str(DEFAULT_DATA_DIR)).resolve()


def _load_json_object(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"phase25 feedback release snapshot missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("phase25 feedback release snapshot payload must be an object")
    return dict(payload)


def _manual_check_points(stage: str) -> list[str]:
    if stage == "success":
        return [
            "check phase25 release snapshot remains compact and stable",
            "check required snapshot paths remain non-empty",
            "spot-check records_count and latest_run_id",
        ]
    if stage == "phase25_release_snapshot_load":
        return [
            "check phase25_feedback_release_snapshot.json exists",
            "check the file is readable JSON",
            "check the path still points inside data/",
        ]
    return [
        "check required snapshot fields remain present",
        "check created_at remains non-empty",
        "check path fields remain non-empty",
    ]


def _write_report(report: Dict[str, Any], *, report_path: Path) -> Path:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(dict(report or {}), ensure_ascii=False, indent=2), encoding="utf-8")
    return report_path.resolve()


def _build_failure_report(*, failed_stage: str, error: Exception, snapshot_path: Path) -> Dict[str, Any]:
    return {
        "status": "failure",
        "failed_stage": failed_stage,
        "error_type": type(error).__name__,
        "error_message": str(error),
        "phase25_feedback_release_snapshot_path": str(snapshot_path.resolve()),
        "records_count": None,
        "latest_run_id": None,
        "manual_check_points": _manual_check_points(failed_stage),
    }


def run_phase26_feedback_release_snapshot_acceptance(data_dir="data") -> dict:
    resolved_data_dir = _resolve_data_dir(str(data_dir))
    snapshot_path = resolved_data_dir / DEFAULT_SNAPSHOT_OUTPUT_PATH.name
    report_path = resolved_data_dir / DEFAULT_REPORT_OUTPUT_NAME

    try:
        snapshot_payload = _load_json_object(snapshot_path)
    except Exception as error:
        _write_report(
            _build_failure_report(
                failed_stage="phase25_release_snapshot_load",
                error=error,
                snapshot_path=snapshot_path,
            ),
            report_path=report_path,
        )
        raise

    try:
        validation = validate_phase26_feedback_release_snapshot_payload(snapshot_payload=snapshot_payload)
    except Exception as error:
        _write_report(
            _build_failure_report(
                failed_stage="phase26_release_snapshot_validator",
                error=error,
                snapshot_path=snapshot_path,
            ),
            report_path=report_path,
        )
        raise

    success_report = {
        "status": "success",
        "failed_stage": None,
        "error_type": None,
        "error_message": None,
        "phase25_feedback_release_snapshot_path": str(snapshot_path.resolve()),
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
    parser = argparse.ArgumentParser(description="Run the phase26 feedback release snapshot acceptance over frozen phase25 artifacts.")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    result = run_phase26_feedback_release_snapshot_acceptance(data_dir=str(args.data_dir))
    print(json.dumps(result, ensure_ascii=False, indent=2))
