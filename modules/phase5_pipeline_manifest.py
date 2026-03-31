from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, List


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
    raise TypeError(f"unsupported phase5 manifest row type: {type(row)!r}")


def _load_training_replay_records(path: str) -> List[Dict[str, Any]]:
    source = Path(_safe_text(path))
    if not source.exists():
        raise FileNotFoundError(f"training replay records missing: {source}")

    raw = json.loads(source.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        records = raw
    elif isinstance(raw, dict) and isinstance(raw.get("records"), list):
        records = raw.get("records") or []
    else:
        raise ValueError("training replay records payload must be a list or {'records': [...]}")

    out: List[Dict[str, Any]] = []
    for row in records:
        normalized = _normalize_row(row)
        label = normalized.get("label")
        if not isinstance(label, dict):
            raise RuntimeError("training replay record missing label payload")
        out.append(normalized)
    return out


def _load_training_rows(path: str) -> List[Dict[str, Any]]:
    source = Path(_safe_text(path))
    if not source.exists():
        raise FileNotFoundError(f"training dataset bridge missing: {source}")

    with source.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError("training dataset bridge csv missing header")
        return [dict(row) for row in reader]


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
    return [_normalize_row(row) for row in rows]


def _is_legacy_record(record: Dict[str, Any]) -> bool:
    return _safe_text(record.get("path_kind")).upper() == "LEGACY_DIRECT_ENTER"


def build_phase5_pipeline_manifest(
    *,
    training_replay_records_path: str,
    training_dataset_path: str,
    replay_dataset_path: str,
) -> Dict[str, Any]:
    replay_records = [row for row in _load_training_replay_records(training_replay_records_path) if not _is_legacy_record(row)]
    training_rows = _load_training_rows(training_dataset_path)
    replay_rows = _load_replay_rows(replay_dataset_path)

    trade_closed_count = 0
    no_trade_count = 0
    no_fill_count = 0
    for row in replay_records:
        label = _normalize_row(row.get("label") or {})
        label_kind = _safe_text(label.get("label_kind"))
        if label_kind == "trade_closed":
            trade_closed_count += 1
        elif label_kind == "no_trade":
            no_trade_count += 1
        elif label_kind == "no_fill":
            no_fill_count += 1
        else:
            raise RuntimeError(f"unsupported label_kind in training replay records: {label_kind}")

    samples_count = len(replay_records)
    labels_count = len(replay_records)
    training_rows_count = len(training_rows)
    replay_rows_count = len(replay_rows)

    if labels_count > samples_count:
        raise RuntimeError("labels count exceeds samples count")
    if training_rows_count > trade_closed_count:
        raise RuntimeError("training rows exceed trade_closed samples")
    if replay_rows_count > trade_closed_count:
        raise RuntimeError("replay rows exceed trade_closed samples")

    return {
        "samples_count": samples_count,
        "labels_count": labels_count,
        "trade_closed_count": trade_closed_count,
        "no_trade_count": no_trade_count,
        "no_fill_count": no_fill_count,
        "training_replay_records_count": samples_count,
        "training_rows_count": training_rows_count,
        "replay_rows_count": replay_rows_count,
        "training_replay_records_path": str(Path(training_replay_records_path).resolve()),
        "training_dataset_path": str(Path(training_dataset_path).resolve()),
        "replay_dataset_path": str(Path(replay_dataset_path).resolve()),
    }


def write_phase5_pipeline_manifest(manifest: Dict[str, Any], *, output_path: str) -> Path:
    target = Path(_safe_text(output_path))
    if not target:
        raise ValueError("manifest output_path is required")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(manifest or {}), ensure_ascii=False, indent=2), encoding="utf-8")
    return target
