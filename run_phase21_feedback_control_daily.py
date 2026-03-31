from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from modules.phase21_feedback_control_daily_summary import (
    DEFAULT_SUMMARY_OUTPUT_PATH,
    build_phase21_feedback_control_daily_failure_summary,
    build_phase21_feedback_control_daily_success_summary,
    write_phase21_feedback_control_daily_summary,
)
from run_phase14_feedback_export import DEFAULT_DATA_DIR
from run_phase19_feedback_control_snapshot import run_phase19_feedback_control_snapshot
from run_phase20_feedback_control_snapshot_acceptance import run_phase20_feedback_control_snapshot_acceptance


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _resolve_data_dir(data_dir: str = "data") -> Path:
    return Path(_safe_text(data_dir) or str(DEFAULT_DATA_DIR)).resolve()


def run_phase21_feedback_control_daily(data_dir="data") -> dict:
    resolved_data_dir = _resolve_data_dir(str(data_dir))
    summary_output_path = resolved_data_dir / DEFAULT_SUMMARY_OUTPUT_PATH.name

    try:
        phase19_result = run_phase19_feedback_control_snapshot(data_dir=str(resolved_data_dir))
    except Exception as error:
        failure_summary = build_phase21_feedback_control_daily_failure_summary(
            failed_stage="phase19_snapshot",
            error=error,
            data_dir=str(resolved_data_dir),
        )
        write_phase21_feedback_control_daily_summary(failure_summary, output_path=str(summary_output_path))
        raise

    try:
        phase20_result = run_phase20_feedback_control_snapshot_acceptance(data_dir=str(resolved_data_dir))
    except Exception as error:
        failure_summary = build_phase21_feedback_control_daily_failure_summary(
            failed_stage="phase20_snapshot_acceptance",
            error=error,
            data_dir=str(resolved_data_dir),
            phase19_result=phase19_result,
        )
        write_phase21_feedback_control_daily_summary(failure_summary, output_path=str(summary_output_path))
        raise

    summary = build_phase21_feedback_control_daily_success_summary(
        phase19_result=phase19_result,
        phase20_result=phase20_result,
    )
    resolved_summary_path = write_phase21_feedback_control_daily_summary(
        summary,
        output_path=str(summary_output_path),
    )
    return {
        "summary_path": str(resolved_summary_path),
        "summary": summary,
        "phase19": phase19_result,
        "phase20": phase20_result,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the phase21 feedback control daily orchestration over frozen phase19 and phase20 flows.")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    result = run_phase21_feedback_control_daily(data_dir=str(args.data_dir))
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
