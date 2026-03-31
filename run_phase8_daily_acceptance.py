from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

from run_phase5_data_pipeline import (
    DEFAULT_MANIFEST_OUTPUT,
    DEFAULT_REPLAY_DATASET_OUTPUT,
    DEFAULT_TRAINING_DATASET_OUTPUT,
    DEFAULT_TRAINING_REPLAY_OUTPUT,
    run_phase5_data_pipeline,
)
from run_phase7_data_quality_check import DEFAULT_REPORT_OUTPUT_PATH, run_phase7_data_quality_check


DEFAULT_SUMMARY_OUTPUT_PATH = Path("data/phase8_daily_acceptance_summary.json")


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def write_phase8_daily_acceptance_summary(summary: Dict[str, Any], *, output_path: str = "") -> Path:
    target = Path(_safe_text(output_path) or str(DEFAULT_SUMMARY_OUTPUT_PATH))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(summary or {}), ensure_ascii=False, indent=2), encoding="utf-8")
    return target.resolve()


def _resolve_output_path(value: str, default_path: Path) -> str:
    return str(Path(_safe_text(value) or str(default_path)).resolve())


def _phase5_manual_check_points() -> list[str]:
    return [
        "check training_replay_records.json was generated",
        "check training_dataset_bridge.csv was generated",
        "check replay_dataset_bridge.json was generated",
        "check phase5 manifest was generated",
    ]


def _phase7_manual_check_points() -> list[str]:
    return [
        "check phase7 report was generated",
        "check Phase 5 outputs exist",
        "check validator inputs are complete",
    ]


def _build_success_summary(phase5_result: Dict[str, Any], phase7_result: Dict[str, Any]) -> Dict[str, Any]:
    phase5_manifest = dict(phase5_result.get("manifest") or {})
    phase7_report = dict(phase7_result.get("report") or {})
    return {
        "status": "success",
        "phase5_manifest_path": str(Path(phase5_result["manifest_path"]).resolve()),
        "phase7_report_path": str(Path(phase7_result["report_path"]).resolve()),
        "training_replay_records_path": str(Path(phase5_result["training_replay_records_path"]).resolve()),
        "training_dataset_path": str(Path(phase5_result["training_dataset_path"]).resolve()),
        "replay_dataset_path": str(Path(phase5_result["replay_dataset_path"]).resolve()),
        "labels_count": phase5_result.get("labels_count"),
        "samples_count": phase7_report.get("samples_count", phase5_manifest.get("samples_count")),
        "trade_closed_count": phase7_report.get("trade_closed_count", phase5_manifest.get("trade_closed_count")),
        "no_trade_count": phase7_report.get("no_trade_count", phase5_manifest.get("no_trade_count")),
        "no_fill_count": phase7_report.get("no_fill_count", phase5_manifest.get("no_fill_count")),
        "training_rows_count": phase7_report.get("training_rows_count", phase5_manifest.get("training_rows_count")),
        "replay_rows_count": phase7_report.get("replay_rows_count", phase5_manifest.get("replay_rows_count")),
    }


def _build_phase5_failure_summary(
    error: Exception,
    *,
    training_replay_output_path: str,
    training_dataset_output_path: str,
    replay_dataset_output_path: str,
    manifest_output_path: str,
) -> Dict[str, Any]:
    return {
        "status": "failed",
        "failed_stage": "phase5",
        "error_type": type(error).__name__,
        "error_message": str(error),
        "training_replay_records_path": _resolve_output_path(training_replay_output_path, DEFAULT_TRAINING_REPLAY_OUTPUT),
        "training_dataset_path": _resolve_output_path(training_dataset_output_path, DEFAULT_TRAINING_DATASET_OUTPUT),
        "replay_dataset_path": _resolve_output_path(replay_dataset_output_path, DEFAULT_REPLAY_DATASET_OUTPUT),
        "phase5_manifest_path": _resolve_output_path(manifest_output_path, DEFAULT_MANIFEST_OUTPUT),
        "manual_check_points": _phase5_manual_check_points(),
    }


def _build_phase7_failure_summary(
    error: Exception,
    *,
    phase5_result: Dict[str, Any],
    phase7_report_output_path: str,
) -> Dict[str, Any]:
    return {
        "status": "failed",
        "failed_stage": "phase7",
        "error_type": type(error).__name__,
        "error_message": str(error),
        "phase5_manifest_path": str(Path(phase5_result["manifest_path"]).resolve()),
        "phase7_report_path": _resolve_output_path(phase7_report_output_path, DEFAULT_REPORT_OUTPUT_PATH),
        "training_replay_records_path": str(Path(phase5_result["training_replay_records_path"]).resolve()),
        "training_dataset_path": str(Path(phase5_result["training_dataset_path"]).resolve()),
        "replay_dataset_path": str(Path(phase5_result["replay_dataset_path"]).resolve()),
        "manual_check_points": _phase7_manual_check_points(),
    }


def run_phase8_daily_acceptance(
    *,
    training_replay_output_path: str = "",
    training_dataset_output_path: str = "",
    replay_dataset_output_path: str = "",
    manifest_output_path: str = "",
    phase7_report_output_path: str = "",
    summary_output_path: str = "",
    sample_repository=None,
    label_repository=None,
    paper_ledger_repository=None,
) -> Dict[str, Any]:
    try:
        phase5_result = run_phase5_data_pipeline(
            training_replay_output_path=_safe_text(training_replay_output_path),
            training_dataset_output_path=_safe_text(training_dataset_output_path),
            replay_dataset_output_path=_safe_text(replay_dataset_output_path),
            manifest_output_path=_safe_text(manifest_output_path),
            sample_repository=sample_repository,
            label_repository=label_repository,
            paper_ledger_repository=paper_ledger_repository,
        )
    except Exception as error:
        failure_summary = _build_phase5_failure_summary(
            error,
            training_replay_output_path=training_replay_output_path,
            training_dataset_output_path=training_dataset_output_path,
            replay_dataset_output_path=replay_dataset_output_path,
            manifest_output_path=manifest_output_path,
        )
        write_phase8_daily_acceptance_summary(failure_summary, output_path=summary_output_path)
        raise

    try:
        phase7_result = run_phase7_data_quality_check(
            training_replay_records_path=str(phase5_result["training_replay_records_path"]),
            training_dataset_path=str(phase5_result["training_dataset_path"]),
            replay_dataset_path=str(phase5_result["replay_dataset_path"]),
            output_path=_safe_text(phase7_report_output_path),
        )
    except Exception as error:
        failure_summary = _build_phase7_failure_summary(
            error,
            phase5_result=phase5_result,
            phase7_report_output_path=phase7_report_output_path,
        )
        write_phase8_daily_acceptance_summary(failure_summary, output_path=summary_output_path)
        raise

    summary = _build_success_summary(phase5_result, phase7_result)
    summary_path = write_phase8_daily_acceptance_summary(summary, output_path=summary_output_path)

    return {
        "summary_path": str(summary_path),
        "summary": summary,
        "phase5": phase5_result,
        "phase7": phase7_result,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the phase8 daily acceptance flow over phase5 and phase7.")
    parser.add_argument("--training-replay-output", default="")
    parser.add_argument("--training-dataset-output", default="")
    parser.add_argument("--replay-dataset-output", default="")
    parser.add_argument("--manifest-output", default="")
    parser.add_argument("--phase7-report-output", default="")
    parser.add_argument("--summary-output", default=str(DEFAULT_SUMMARY_OUTPUT_PATH))
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    result = run_phase8_daily_acceptance(
        training_replay_output_path=str(args.training_replay_output),
        training_dataset_output_path=str(args.training_dataset_output),
        replay_dataset_output_path=str(args.replay_dataset_output),
        manifest_output_path=str(args.manifest_output),
        phase7_report_output_path=str(args.phase7_report_output),
        summary_output_path=str(args.summary_output),
    )
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
