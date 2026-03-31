from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

from modules.phase6_data_quality_validator import build_phase6_data_quality_report


DEFAULT_TRAINING_REPLAY_RECORDS_PATH = Path("data/training_replay_records.json")
DEFAULT_TRAINING_DATASET_PATH = Path("data/training_dataset_bridge.csv")
DEFAULT_REPLAY_DATASET_PATH = Path("data/replay_dataset_bridge.json")
DEFAULT_REPORT_OUTPUT_PATH = Path("data/phase7_data_quality_report.json")


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def write_phase7_data_quality_report(report: Dict[str, Any], *, output_path: str = "") -> Path:
    target = Path(_safe_text(output_path) or str(DEFAULT_REPORT_OUTPUT_PATH))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(report or {}), ensure_ascii=False, indent=2), encoding="utf-8")
    return target.resolve()


def run_phase7_data_quality_check(
    *,
    training_replay_records_path: str = "",
    training_dataset_path: str = "",
    replay_dataset_path: str = "",
    output_path: str = "",
) -> Dict[str, Any]:
    report = build_phase6_data_quality_report(
        training_replay_records_path=_safe_text(training_replay_records_path) or str(DEFAULT_TRAINING_REPLAY_RECORDS_PATH),
        training_dataset_path=_safe_text(training_dataset_path) or str(DEFAULT_TRAINING_DATASET_PATH),
        replay_dataset_path=_safe_text(replay_dataset_path) or str(DEFAULT_REPLAY_DATASET_PATH),
    )
    report_path = write_phase7_data_quality_report(report, output_path=output_path)
    return {
        "report_path": str(report_path),
        "report": report,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run phase7 data quality acceptance checks over existing bridge outputs.")
    parser.add_argument("--training-replay-records", default=str(DEFAULT_TRAINING_REPLAY_RECORDS_PATH))
    parser.add_argument("--training-dataset", default=str(DEFAULT_TRAINING_DATASET_PATH))
    parser.add_argument("--replay-dataset", default=str(DEFAULT_REPLAY_DATASET_PATH))
    parser.add_argument("--output", default=str(DEFAULT_REPORT_OUTPUT_PATH))
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    result = run_phase7_data_quality_check(
        training_replay_records_path=str(args.training_replay_records),
        training_dataset_path=str(args.training_dataset),
        replay_dataset_path=str(args.replay_dataset),
        output_path=str(args.output),
    )
    print(json.dumps(result["report"], ensure_ascii=False, indent=2))
