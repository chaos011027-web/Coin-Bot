from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

from modules.phase16_feedback_daily_history import (
    DEFAULT_HISTORY_OUTPUT_PATH,
    DEFAULT_LATEST_OUTPUT_PATH,
    append_phase16_feedback_daily_history,
    build_phase16_feedback_daily_history_record,
    write_phase16_feedback_daily_latest,
)
from modules.phase15_feedback_daily_summary import DEFAULT_SUMMARY_OUTPUT_PATH as PHASE15_SUMMARY_OUTPUT_PATH
from run_phase14_feedback_export import DEFAULT_DATA_DIR
from run_phase15_feedback_daily import run_phase15_feedback_daily


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _resolve_data_dir(data_dir: str = "data") -> Path:
    return Path(_safe_text(data_dir) or str(DEFAULT_DATA_DIR)).resolve()


def _load_phase15_summary(summary_path: Path) -> Dict[str, Any]:
    if not summary_path.exists():
        raise FileNotFoundError(f"phase15 daily summary missing: {summary_path}")
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("phase15 daily summary payload must be an object")
    return dict(payload)


def run_phase16_feedback_daily_history(data_dir="data") -> dict:
    resolved_data_dir = _resolve_data_dir(str(data_dir))
    history_output_path = resolved_data_dir / DEFAULT_HISTORY_OUTPUT_PATH.name
    latest_output_path = resolved_data_dir / DEFAULT_LATEST_OUTPUT_PATH.name
    phase15_summary_path = resolved_data_dir / PHASE15_SUMMARY_OUTPUT_PATH.name

    try:
        phase15_result = run_phase15_feedback_daily(data_dir=str(resolved_data_dir))
        phase15_summary = dict(phase15_result.get("summary") or {})
        phase15_summary_path = Path(str(phase15_result.get("summary_path") or phase15_summary_path)).resolve()
    except Exception:
        phase15_summary = _load_phase15_summary(phase15_summary_path)
        record = build_phase16_feedback_daily_history_record(
            phase15_summary=phase15_summary,
            phase15_summary_path=str(phase15_summary_path),
        )
        history_payload = append_phase16_feedback_daily_history(record, output_path=str(history_output_path))
        resolved_latest_path = write_phase16_feedback_daily_latest(record, output_path=str(latest_output_path)).resolve()
        raise

    record = build_phase16_feedback_daily_history_record(
        phase15_summary=phase15_summary,
        phase15_summary_path=str(phase15_summary_path),
    )
    history_payload = append_phase16_feedback_daily_history(record, output_path=str(history_output_path))
    resolved_latest_path = write_phase16_feedback_daily_latest(record, output_path=str(latest_output_path)).resolve()
    return {
        "history_path": str(history_output_path.resolve()),
        "latest_path": str(resolved_latest_path),
        "record": record,
        "history": history_payload,
        "phase15": phase15_result,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the phase16 feedback daily history orchestration over frozen phase15 flows.")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    result = run_phase16_feedback_daily_history(data_dir=str(args.data_dir))
    print(json.dumps(result["record"], ensure_ascii=False, indent=2))
