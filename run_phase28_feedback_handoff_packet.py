from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

from modules.phase27_feedback_release_daily_summary import DEFAULT_SUMMARY_OUTPUT_PATH as PHASE27_SUMMARY_OUTPUT_PATH
from modules.phase28_feedback_handoff_packet import (
    DEFAULT_PACKET_OUTPUT_PATH,
    build_phase28_feedback_handoff_packet,
    write_phase28_feedback_handoff_packet,
)
from run_phase14_feedback_export import DEFAULT_DATA_DIR


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _resolve_data_dir(data_dir: str = "data") -> Path:
    return Path(_safe_text(data_dir) or str(DEFAULT_DATA_DIR)).resolve()


def _load_phase27_summary(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"phase27 feedback release daily summary missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("phase27 feedback release daily summary payload must be an object")
    return dict(payload)


def run_phase28_feedback_handoff_packet(data_dir="data") -> dict:
    resolved_data_dir = _resolve_data_dir(str(data_dir))
    phase27_summary_path = resolved_data_dir / PHASE27_SUMMARY_OUTPUT_PATH.name
    packet_output_path = resolved_data_dir / DEFAULT_PACKET_OUTPUT_PATH.name

    phase27_summary = _load_phase27_summary(phase27_summary_path)
    packet = build_phase28_feedback_handoff_packet(
        phase27_summary=phase27_summary,
        phase27_summary_path=str(phase27_summary_path),
    )
    resolved_packet_path = write_phase28_feedback_handoff_packet(
        packet,
        output_path=str(packet_output_path),
    )
    return {
        "phase27_feedback_release_daily_summary_path": str(phase27_summary_path.resolve()),
        "packet_path": str(resolved_packet_path),
        "packet": packet,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the phase28 feedback handoff packet from frozen phase27 summary.")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    result = run_phase28_feedback_handoff_packet(data_dir=str(args.data_dir))
    print(json.dumps(result["packet"], ensure_ascii=False, indent=2))
