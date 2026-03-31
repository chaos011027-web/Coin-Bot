from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from modules.phase18_feedback_history_daily_summary import (
    DEFAULT_SUMMARY_OUTPUT_PATH,
    build_phase18_feedback_history_daily_failure_summary,
    build_phase18_feedback_history_daily_success_summary,
    write_phase18_feedback_history_daily_summary,
)
from run_phase14_feedback_export import DEFAULT_DATA_DIR
from run_phase16_feedback_daily_history import run_phase16_feedback_daily_history
from run_phase17_feedback_history_acceptance import run_phase17_feedback_history_acceptance


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _resolve_data_dir(data_dir: str = "data") -> Path:
    return Path(_safe_text(data_dir) or str(DEFAULT_DATA_DIR)).resolve()


def run_phase18_feedback_history_daily(data_dir="data") -> dict:
    resolved_data_dir = _resolve_data_dir(str(data_dir))
    summary_output_path = resolved_data_dir / DEFAULT_SUMMARY_OUTPUT_PATH.name

    try:
        phase16_result = run_phase16_feedback_daily_history(data_dir=str(resolved_data_dir))
    except Exception as error:
        failure_summary = build_phase18_feedback_history_daily_failure_summary(
            failed_stage="phase16_history_daily",
            error=error,
            data_dir=str(resolved_data_dir),
        )
        write_phase18_feedback_history_daily_summary(failure_summary, output_path=str(summary_output_path))
        raise

    try:
        phase17_result = run_phase17_feedback_history_acceptance(data_dir=str(resolved_data_dir))
    except Exception as error:
        failure_summary = build_phase18_feedback_history_daily_failure_summary(
            failed_stage="phase17_history_acceptance",
            error=error,
            data_dir=str(resolved_data_dir),
            phase16_result=phase16_result,
        )
        write_phase18_feedback_history_daily_summary(failure_summary, output_path=str(summary_output_path))
        raise

    summary = build_phase18_feedback_history_daily_success_summary(
        phase16_result=phase16_result,
        phase17_result=phase17_result,
    )
    resolved_summary_path = write_phase18_feedback_history_daily_summary(
        summary,
        output_path=str(summary_output_path),
    )
    return {
        "summary_path": str(resolved_summary_path),
        "summary": summary,
        "phase16": phase16_result,
        "phase17": phase17_result,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the phase18 feedback history daily orchestration over frozen phase16 and phase17 flows.")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    result = run_phase18_feedback_history_daily(data_dir=str(args.data_dir))
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
