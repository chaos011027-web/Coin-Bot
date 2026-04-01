from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from modules.phase27_feedback_release_daily_summary import (
    DEFAULT_SUMMARY_OUTPUT_PATH,
    build_phase27_feedback_release_daily_failure_summary,
    build_phase27_feedback_release_daily_success_summary,
    write_phase27_feedback_release_daily_summary,
)
from run_phase14_feedback_export import DEFAULT_DATA_DIR
from run_phase25_feedback_release_snapshot import run_phase25_feedback_release_snapshot
from run_phase26_feedback_release_snapshot_acceptance import run_phase26_feedback_release_snapshot_acceptance


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _resolve_data_dir(data_dir: str = "data") -> Path:
    return Path(_safe_text(data_dir) or str(DEFAULT_DATA_DIR)).resolve()


def run_phase27_feedback_release_daily(data_dir="data") -> dict:
    resolved_data_dir = _resolve_data_dir(str(data_dir))
    summary_output_path = resolved_data_dir / DEFAULT_SUMMARY_OUTPUT_PATH.name

    try:
        phase25_result = run_phase25_feedback_release_snapshot(data_dir=str(resolved_data_dir))
    except Exception as error:
        failure_summary = build_phase27_feedback_release_daily_failure_summary(
            failed_stage="phase25_release_snapshot",
            error=error,
            data_dir=str(resolved_data_dir),
        )
        write_phase27_feedback_release_daily_summary(failure_summary, output_path=str(summary_output_path))
        raise

    try:
        phase26_result = run_phase26_feedback_release_snapshot_acceptance(data_dir=str(resolved_data_dir))
    except Exception as error:
        failure_summary = build_phase27_feedback_release_daily_failure_summary(
            failed_stage="phase26_release_snapshot_acceptance",
            error=error,
            data_dir=str(resolved_data_dir),
            phase25_result=phase25_result,
        )
        write_phase27_feedback_release_daily_summary(failure_summary, output_path=str(summary_output_path))
        raise

    summary = build_phase27_feedback_release_daily_success_summary(
        phase25_result=phase25_result,
        phase26_result=phase26_result,
    )
    resolved_summary_path = write_phase27_feedback_release_daily_summary(
        summary,
        output_path=str(summary_output_path),
    )
    return {
        "summary_path": str(resolved_summary_path),
        "summary": summary,
        "phase25": phase25_result,
        "phase26": phase26_result,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the phase27 feedback release daily orchestration over frozen phase25 and phase26 flows.")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    result = run_phase27_feedback_release_daily(data_dir=str(args.data_dir))
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
