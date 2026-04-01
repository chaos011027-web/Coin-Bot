from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

from modules.phase24_feedback_control_history_daily_summary import DEFAULT_SUMMARY_OUTPUT_PATH as PHASE24_SUMMARY_OUTPUT_PATH
from modules.phase25_feedback_release_snapshot import (
    DEFAULT_SNAPSHOT_OUTPUT_PATH,
    build_phase25_feedback_release_snapshot,
    write_phase25_feedback_release_snapshot,
)
from run_phase14_feedback_export import DEFAULT_DATA_DIR


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _resolve_data_dir(data_dir: str = "data") -> Path:
    return Path(_safe_text(data_dir) or str(DEFAULT_DATA_DIR)).resolve()


def _load_phase24_summary(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"phase24 feedback control history daily summary missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("phase24 feedback control history daily summary payload must be an object")
    return dict(payload)


def run_phase25_feedback_release_snapshot(data_dir="data") -> dict:
    resolved_data_dir = _resolve_data_dir(str(data_dir))
    phase24_summary_path = resolved_data_dir / PHASE24_SUMMARY_OUTPUT_PATH.name
    snapshot_output_path = resolved_data_dir / DEFAULT_SNAPSHOT_OUTPUT_PATH.name

    phase24_summary = _load_phase24_summary(phase24_summary_path)
    snapshot = build_phase25_feedback_release_snapshot(
        phase24_summary=phase24_summary,
        phase24_summary_path=str(phase24_summary_path),
    )
    resolved_snapshot_path = write_phase25_feedback_release_snapshot(
        snapshot,
        output_path=str(snapshot_output_path),
    )
    return {
        "phase24_feedback_control_history_daily_summary_path": str(phase24_summary_path.resolve()),
        "snapshot_path": str(resolved_snapshot_path),
        "snapshot": snapshot,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the phase25 feedback release snapshot from frozen phase24 summary.")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    result = run_phase25_feedback_release_snapshot(data_dir=str(args.data_dir))
    print(json.dumps(result["snapshot"], ensure_ascii=False, indent=2))
