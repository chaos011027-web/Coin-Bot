from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Dict, List


DEFAULT_INPUT = Path("data/training_replay_records.json")
DEFAULT_OUTPUT = Path("data/training_dataset_bridge.csv")
LEGACY_OUTPUT_NAMES = {"ml_training_dataset.csv"}

FEATURE_COLUMNS = [
    "market_cap_at_snap",
    "liquidity_at_snap",
    "smart_money_delta",
    "maker_vol_ratio",
    "overhang_ratio",
    "breakout_vol_ratio",
]


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_row(row: Any) -> Dict[str, Any]:
    if isinstance(row, dict):
        return dict(row)
    try:
        return dict(row)
    except Exception:
        pass
    if hasattr(row, "keys"):
        return {key: row[key] for key in row.keys()}
    raise TypeError(f"unsupported training bridge row type: {type(row)!r}")


def _load_phase3_records(input_path: str = "") -> List[Dict[str, Any]]:
    source = Path(input_path) if input_path else DEFAULT_INPUT
    raw = json.loads(source.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        records = raw.get("records", []) or []
    elif isinstance(raw, list):
        records = raw
    else:
        raise ValueError("training replay export must be a list or {'records': [...]}")
    return [_normalize_row(row) for row in records]


def _is_legacy_record(record: Dict[str, Any]) -> bool:
    path_kind = _safe_text(record.get("path_kind")).upper()
    return path_kind == "LEGACY_DIRECT_ENTER"


def _feature_value(features: Dict[str, Any], *keys: str) -> float:
    for key in keys:
        value = _safe_float(features.get(key), None)
        if value is not None:
            return value
    return 0.0


def build_training_dataset_rows(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for raw in records or []:
        record = _normalize_row(raw)
        if _is_legacy_record(record):
            continue

        label = _normalize_row(record.get("label") or {})
        label_kind = _safe_text(label.get("label_kind"))
        if label_kind != "trade_closed":
            continue

        features = _normalize_row(record.get("frozen_features") or {})
        realized_pnl_sol = _safe_float(label.get("realized_pnl_sol"), 0.0)
        row = {
            "sample_id": _safe_text(record.get("sample_id")),
            "analysis_run_id": record.get("analysis_run_id"),
            "ca": _safe_text(record.get("ca")),
            "strategy_id": _safe_text(record.get("strategy_id")),
            "market_cap_at_snap": _feature_value(features, "market_cap_at_snap", "cap_usd"),
            "liquidity_at_snap": _feature_value(features, "liquidity_at_snap", "pair_liquidity_usd", "liquidity_usd"),
            "smart_money_delta": _feature_value(features, "smart_money_delta"),
            "maker_vol_ratio": _feature_value(features, "maker_vol_ratio"),
            "overhang_ratio": _feature_value(features, "overhang_ratio"),
            "breakout_vol_ratio": _feature_value(features, "breakout_vol_ratio"),
            "label": 1 if realized_pnl_sol > 0 else 0,
        }
        rows.append(row)
    return rows


def export_training_dataset_bridge(
    *,
    input_path: str = "",
    output_path: str = "",
) -> Path:
    target = Path(output_path) if output_path else DEFAULT_OUTPUT
    if target.name in LEGACY_OUTPUT_NAMES:
        raise ValueError("training bridge output must not overwrite legacy ml_training_dataset.csv")

    rows = build_training_dataset_rows(_load_phase3_records(input_path))
    target.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["sample_id", "analysis_run_id", "ca", "strategy_id", *FEATURE_COLUMNS, "label"]
    with target.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return target


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export flat training CSV from phase-3 training replay records.")
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="Input training_replay_records JSON path.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output bridge CSV path.")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    path = export_training_dataset_bridge(input_path=str(args.input), output_path=str(args.output))
    print(str(path))
