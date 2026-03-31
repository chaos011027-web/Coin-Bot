from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

from modules.phase15_feedback_daily_summary import (
    DEFAULT_SUMMARY_OUTPUT_PATH,
    build_phase15_feedback_daily_failure_summary,
    build_phase15_feedback_daily_success_summary,
    write_phase15_feedback_daily_summary,
)
from run_phase14_feedback_acceptance import run_phase14_feedback_acceptance
from run_phase14_feedback_export import DEFAULT_DATA_DIR, run_phase14_feedback_export


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _resolve_data_dir(data_dir: str = "data") -> Path:
    return Path(_safe_text(data_dir) or str(DEFAULT_DATA_DIR)).resolve()


def run_phase15_feedback_daily(data_dir="data") -> dict:
    resolved_data_dir = _resolve_data_dir(str(data_dir))
    summary_output_path = resolved_data_dir / DEFAULT_SUMMARY_OUTPUT_PATH.name

    try:
        phase14_export_result = run_phase14_feedback_export(data_dir=str(resolved_data_dir))
    except Exception as error:
        failure_summary = build_phase15_feedback_daily_failure_summary(
            failed_stage="phase14_export",
            error=error,
            data_dir=str(resolved_data_dir),
        )
        write_phase15_feedback_daily_summary(failure_summary, output_path=str(summary_output_path))
        raise

    try:
        phase14_acceptance_result = run_phase14_feedback_acceptance(
            data_dir=str(resolved_data_dir),
            skip_export=True,
        )
    except Exception as error:
        failure_summary = build_phase15_feedback_daily_failure_summary(
            failed_stage="phase14_acceptance",
            error=error,
            data_dir=str(resolved_data_dir),
            phase14_export_result=phase14_export_result,
        )
        write_phase15_feedback_daily_summary(failure_summary, output_path=str(summary_output_path))
        raise

    summary = build_phase15_feedback_daily_success_summary(
        phase14_export_result=phase14_export_result,
        phase14_acceptance_result=phase14_acceptance_result,
    )
    resolved_summary_path = write_phase15_feedback_daily_summary(
        summary,
        output_path=str(summary_output_path),
    )
    return {
        "summary_path": str(resolved_summary_path),
        "summary": summary,
        "phase14_export": phase14_export_result,
        "phase14_acceptance": phase14_acceptance_result,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the phase15 feedback daily orchestration over frozen phase14 flows.")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    result = run_phase15_feedback_daily(data_dir=str(args.data_dir))
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
