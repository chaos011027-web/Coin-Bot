from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, List


TRAINING_DATASET_REQUIRED_COLUMNS = {
    "sample_id",
    "analysis_run_id",
    "ca",
    "strategy_id",
    "market_cap_at_snap",
    "liquidity_at_snap",
    "smart_money_delta",
    "maker_vol_ratio",
    "overhang_ratio",
    "breakout_vol_ratio",
    "label",
}

REPLAY_DATASET_REQUIRED_FIELDS = {
    "sample_id",
    "analysis_run_id",
    "ca",
    "symbol",
    "strategy",
    "opened_at",
    "closed_at",
    "entry_price",
    "exit_price",
    "entry_mcap",
    "exit_mcap",
    "exit_reason",
}

ALLOWED_LABEL_KINDS = {"trade_closed", "no_trade", "no_fill"}


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_row(row: Any) -> Dict[str, Any]:
    if isinstance(row, dict):
        return dict(row)
    try:
        return dict(row)
    except Exception:
        pass
    if hasattr(row, "keys"):
        return {key: row[key] for key in row.keys()}
    raise TypeError(f"unsupported phase6 validator row type: {type(row)!r}")


def _load_training_replay_records(path: str) -> List[Dict[str, Any]]:
    source = Path(_safe_text(path))
    if not source.exists():
        raise FileNotFoundError(f"training replay records missing: {source}")

    raw = json.loads(source.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        rows = raw
    elif isinstance(raw, dict) and isinstance(raw.get("records"), list):
        rows = raw.get("records") or []
    else:
        raise ValueError("training replay records payload must be a list or {'records': [...]}") 

    if not rows:
        raise RuntimeError("training replay records empty")

    records: List[Dict[str, Any]] = []
    for row in rows:
        record = _normalize_row(row)
        sample_id = _safe_text(record.get("sample_id"))
        if not sample_id:
            raise RuntimeError("training replay record missing sample_id")
        label = record.get("label")
        if not isinstance(label, dict):
            raise RuntimeError("training replay record missing label payload")
        label_kind = _safe_text(label.get("label_kind"))
        if label_kind not in ALLOWED_LABEL_KINDS:
            raise RuntimeError(f"unsupported label_kind in training replay records: {label_kind}")
        records.append(record)
    return records


def _load_training_rows(path: str) -> List[Dict[str, Any]]:
    source = Path(_safe_text(path))
    if not source.exists():
        raise FileNotFoundError(f"training dataset bridge missing: {source}")

    with source.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        if not fieldnames:
            raise ValueError("training dataset bridge csv missing header")
        if not TRAINING_DATASET_REQUIRED_COLUMNS.issubset(set(fieldnames)):
            raise RuntimeError("training dataset bridge missing required columns")
        rows = [dict(row) for row in reader]

    for row in rows:
        missing = [
            field
            for field in [
                "sample_id",
                "analysis_run_id",
                "ca",
                "strategy_id",
                "market_cap_at_snap",
                "liquidity_at_snap",
                "smart_money_delta",
                "maker_vol_ratio",
                "overhang_ratio",
                "breakout_vol_ratio",
                "label",
            ]
            if not _safe_text(row.get(field))
        ]
        if missing:
            raise RuntimeError(f"training dataset bridge row missing required fields: {', '.join(missing)}")
    return rows


def _load_replay_rows(path: str) -> List[Dict[str, Any]]:
    source = Path(_safe_text(path))
    if not source.exists():
        raise FileNotFoundError(f"replay dataset bridge missing: {source}")

    raw = json.loads(source.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        rows = raw
    elif isinstance(raw, dict) and isinstance(raw.get("records"), list):
        rows = raw.get("records") or []
    else:
        raise ValueError("replay dataset bridge payload must be a list or {'records': [...]}") 

    normalized_rows = [_normalize_row(row) for row in rows]
    for row in normalized_rows:
        missing = [field for field in REPLAY_DATASET_REQUIRED_FIELDS if not _safe_text(row.get(field))]
        if missing:
            raise RuntimeError("replay dataset bridge row missing required fields")
    return normalized_rows


def _is_legacy_record(record: Dict[str, Any]) -> bool:
    if bool(record.get("legacy_path")):
        return True
    return _safe_text(record.get("path_kind")).upper() == "LEGACY_DIRECT_ENTER"


def build_phase6_data_quality_report(
    *,
    training_replay_records_path: str,
    training_dataset_path: str,
    replay_dataset_path: str,
) -> Dict[str, Any]:
    replay_records = _load_training_replay_records(training_replay_records_path)
    training_rows = _load_training_rows(training_dataset_path)
    replay_rows = _load_replay_rows(replay_dataset_path)

    legacy_records = [row for row in replay_records if _is_legacy_record(row)]
    if legacy_records:
        raise RuntimeError("legacy samples must be excluded")

    seen_sample_ids = set()
    trade_closed_sample_ids: List[str] = []
    trade_closed_count = 0
    no_trade_count = 0
    no_fill_count = 0

    for row in replay_records:
        sample_id = _safe_text(row.get("sample_id"))
        if sample_id in seen_sample_ids:
            raise RuntimeError(f"duplicate sample_id in training replay records: {sample_id}")
        seen_sample_ids.add(sample_id)

        label = _normalize_row(row.get("label") or {})
        label_kind = _safe_text(label.get("label_kind"))
        if label_kind == "trade_closed":
            trade_closed_count += 1
            trade_closed_sample_ids.append(sample_id)
        elif label_kind == "no_trade":
            no_trade_count += 1
        elif label_kind == "no_fill":
            no_fill_count += 1

    training_sample_ids = sorted(_safe_text(row.get("sample_id")) for row in training_rows if _safe_text(row.get("sample_id")))
    replay_sample_ids = sorted(_safe_text(row.get("sample_id")) for row in replay_rows if _safe_text(row.get("sample_id")))
    trade_closed_sample_ids = sorted(trade_closed_sample_ids)

    if len(training_rows) > trade_closed_count:
        raise RuntimeError("training rows exceed trade_closed samples")
    if len(replay_rows) > trade_closed_count:
        raise RuntimeError("replay rows exceed trade_closed samples")

    trade_closed_set = set(trade_closed_sample_ids)
    unknown_training_ids = sorted(sample_id for sample_id in training_sample_ids if sample_id not in trade_closed_set)
    unknown_replay_ids = sorted(sample_id for sample_id in replay_sample_ids if sample_id not in trade_closed_set)
    if unknown_training_ids:
        raise RuntimeError("training dataset bridge contains unknown sample_id")
    if unknown_replay_ids:
        raise RuntimeError("replay dataset bridge contains unknown sample_id")

    samples_count = len(replay_records)
    labels_count = len(replay_records)
    return {
        "samples_count": samples_count,
        "labels_count": labels_count,
        "trade_closed_count": trade_closed_count,
        "no_trade_count": no_trade_count,
        "no_fill_count": no_fill_count,
        "legacy_records_count": 0,
        "training_rows_count": len(training_rows),
        "replay_rows_count": len(replay_rows),
        "trade_closed_sample_ids": trade_closed_sample_ids,
        "training_sample_ids": training_sample_ids,
        "replay_sample_ids": replay_sample_ids,
        "training_replay_records_path": str(Path(training_replay_records_path).resolve()),
        "training_dataset_path": str(Path(training_dataset_path).resolve()),
        "replay_dataset_path": str(Path(replay_dataset_path).resolve()),
    }
