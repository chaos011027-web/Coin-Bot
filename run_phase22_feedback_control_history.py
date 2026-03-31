from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

from modules.phase21_feedback_control_daily_summary import DEFAULT_SUMMARY_OUTPUT_PATH as PHASE21_SUMMARY_OUTPUT_PATH
from modules.phase22_feedback_control_history import (
    DEFAULT_HISTORY_OUTPUT_PATH,
    DEFAULT_LATEST_OUTPUT_PATH,
    append_phase22_feedback_control_history,
    build_phase22_feedback_control_history_record,
    write_phase22_feedback_control_latest,
)
from run_phase14_feedback_export import DEFAULT_DATA_DIR
from run_phase21_feedback_control_daily import run_phase21_feedback_control_daily


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _resolve_data_dir(data_dir: str = "data") -> Path:
    return Path(_safe_text(data_dir) or str(DEFAULT_DATA_DIR)).resolve()


def _load_phase21_summary(summary_path: Path) -> Dict[str, Any]:
    if not summary_path.exists():
        raise FileNotFoundError(f"phase21 control daily summary missing: {summary_path}")
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("phase21 control daily summary payload must be an object")
    return dict(payload)


def run_phase22_feedback_control_history(data_dir="data") -> dict:
    resolved_data_dir = _resolve_data_dir(str(data_dir))
    history_output_path = resolved_data_dir / DEFAULT_HISTORY_OUTPUT_PATH.name
    latest_output_path = resolved_data_dir / DEFAULT_LATEST_OUTPUT_PATH.name
    phase21_summary_path = resolved_data_dir / PHASE21_SUMMARY_OUTPUT_PATH.name

    try:
        phase21_result = run_phase21_feedback_control_daily(data_dir=str(resolved_data_dir))
        phase21_summary = dict(phase21_result.get("summary") or {})
        phase21_summary_path = Path(str(phase21_result.get("summary_path") or phase21_summary_path)).resolve()
    except Exception:
        phase21_summary = _load_phase21_summary(phase21_summary_path)
        record = build_phase22_feedback_control_history_record(
            phase21_summary=phase21_summary,
            phase21_summary_path=str(phase21_summary_path),
        )
        history_payload = append_phase22_feedback_control_history(record, output_path=str(history_output_path))
        resolved_latest_path = write_phase22_feedback_control_latest(record, output_path=str(latest_output_path)).resolve()
        raise

    record = build_phase22_feedback_control_history_record(
        phase21_summary=phase21_summary,
        phase21_summary_path=str(phase21_summary_path),
    )
    history_payload = append_phase22_feedback_control_history(record, output_path=str(history_output_path))
    resolved_latest_path = write_phase22_feedback_control_latest(record, output_path=str(latest_output_path)).resolve()
    return {
        "history_path": str(history_output_path.resolve()),
        "latest_path": str(resolved_latest_path),
        "record": record,
        "history": history_payload,
        "phase21": phase21_result,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the phase22 feedback control history orchestration over frozen phase21 flows.")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    result = run_phase22_feedback_control_history(data_dir=str(args.data_dir))
    print(json.dumps(result["record"], ensure_ascii=False, indent=2))
