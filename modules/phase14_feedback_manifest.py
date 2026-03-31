from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List


ALLOWED_LABEL_KINDS = {"trade_closed", "no_trade", "no_fill"}
ALLOWED_FEEDBACK_CLASSES = {
    "observe_reject",
    "armed_no_fill",
    "entered_profit",
    "entered_loss",
    "entered_partial_win",
}


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except Exception:
        return default


def _safe_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = _safe_text(value).lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off", ""}:
        return False
    return bool(value)


def _normalize_row(row: Any) -> Dict[str, Any]:
    if isinstance(row, dict):
        return dict(row)
    try:
        return dict(row)
    except Exception:
        pass
    if hasattr(row, "keys"):
        return {key: row[key] for key in row.keys()}
    raise TypeError(f"unsupported phase14 manifest row type: {type(row)!r}")


def _is_legacy_row(row: Dict[str, Any]) -> bool:
    if _safe_bool(row.get("legacy_path")):
        return True
    return _safe_text(row.get("path_kind")).upper() == "LEGACY_DIRECT_ENTER"


def _as_text_list(value: Any, *, field_name: str) -> List[str]:
    if not isinstance(value, list):
        raise RuntimeError(f"{field_name} must be a list")
    return [_safe_text(item) for item in value if _safe_text(item)]


def _require_text(record: Dict[str, Any], field_name: str) -> str:
    text = _safe_text(record.get(field_name))
    if not text:
        raise RuntimeError(f"required field missing: {field_name}")
    return text


def _nested_snapshot(record: Dict[str, Any], field_name: str) -> Dict[str, Any]:
    value = record.get(field_name)
    if not isinstance(value, dict):
        raise RuntimeError(f"required field missing: {field_name}")
    return dict(value)


def _validate_identity(root: Dict[str, Any], nested: Dict[str, Any]) -> None:
    pairs = [
        ("sample_id", _safe_text(root.get("sample_id")), _safe_text(nested.get("sample_id"))),
        ("analysis_run_id", _safe_int(root.get("analysis_run_id")), _safe_int(nested.get("analysis_run_id"))),
        ("ca", _safe_text(root.get("ca")), _safe_text(nested.get("ca"))),
    ]
    if "trace_link" in nested:
        pairs.append(("trace_link", _safe_text(root.get("trace_link")), _safe_text(nested.get("trace_link"))))

    for _, root_value, nested_value in pairs:
        if root_value != nested_value:
            raise RuntimeError("identity mismatch between root and nested feedback snapshots")


def _count_distribution(rows: Iterable[Dict[str, Any]], field_name: str) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for row in rows:
        key = _safe_text(row.get(field_name))
        counts[key] = counts.get(key, 0) + 1
    return {key: counts[key] for key in sorted(counts)}


def build_phase14_feedback_manifest(*, records: list[dict], records_path) -> dict:
    if not isinstance(records, list):
        raise RuntimeError("records must be a list")

    normalized_records = [_normalize_row(row) for row in records]
    sample_ids = set()
    legacy_records_count = 0

    for row in normalized_records:
        sample_id = _require_text(row, "sample_id")
        _require_text(row, "ca")
        _require_text(row, "trace_link")
        if row.get("analysis_run_id") is None or row.get("analysis_run_id") == "":
            raise RuntimeError("required field missing: analysis_run_id")
        if sample_id in sample_ids:
            raise RuntimeError(f"duplicate sample_id: {sample_id}")
        sample_ids.add(sample_id)

        label_kind = _safe_text(row.get("label_kind")).lower()
        if label_kind not in ALLOWED_LABEL_KINDS:
            raise RuntimeError(f"unsupported label_kind: {label_kind}")
        feedback_class = _safe_text(row.get("feedback_class"))
        if feedback_class not in ALLOWED_FEEDBACK_CLASSES:
            raise RuntimeError(f"unsupported feedback_class: {feedback_class}")

        position_ids = _as_text_list(row.get("position_ids"), field_name="position_ids")
        trade_close_ids = _as_text_list(row.get("trade_close_ids"), field_name="trade_close_ids")

        strategy_feedback = _nested_snapshot(row, "strategy_feedback")
        sizing_feedback = _nested_snapshot(row, "sizing_feedback")
        label_augmentation = _nested_snapshot(row, "label_augmentation")

        _validate_identity(row, strategy_feedback)
        _validate_identity(row, sizing_feedback)
        _validate_identity(row, label_augmentation)

        if _safe_text(strategy_feedback.get("feedback_class")) != feedback_class:
            raise RuntimeError("identity mismatch between root and nested feedback snapshots")
        if _safe_text(label_augmentation.get("feedback_class")) != feedback_class:
            raise RuntimeError("identity mismatch between root and nested feedback snapshots")
        if _safe_text(label_augmentation.get("label_kind")).lower() != label_kind:
            raise RuntimeError("identity mismatch between root and nested feedback snapshots")

        if _as_text_list(strategy_feedback.get("position_ids", []), field_name="position_ids") != position_ids:
            raise RuntimeError("identity mismatch between root and nested feedback snapshots")
        if _as_text_list(strategy_feedback.get("trade_close_ids", []), field_name="trade_close_ids") != trade_close_ids:
            raise RuntimeError("identity mismatch between root and nested feedback snapshots")
        if _as_text_list(sizing_feedback.get("position_ids", []), field_name="position_ids") != position_ids:
            raise RuntimeError("identity mismatch between root and nested feedback snapshots")
        if _as_text_list(sizing_feedback.get("trade_close_ids", []), field_name="trade_close_ids") != trade_close_ids:
            raise RuntimeError("identity mismatch between root and nested feedback snapshots")
        if _as_text_list(label_augmentation.get("position_ids", []), field_name="position_ids") != position_ids:
            raise RuntimeError("identity mismatch between root and nested feedback snapshots")
        if _as_text_list(label_augmentation.get("trade_close_ids", []), field_name="trade_close_ids") != trade_close_ids:
            raise RuntimeError("identity mismatch between root and nested feedback snapshots")

        if _is_legacy_row(row):
            legacy_records_count += 1

    resolved_records_path = Path(str(records_path or "data/feedback_export_records.json")).resolve()
    return {
        "records_count": len(normalized_records),
        "label_kind_distribution": _count_distribution(normalized_records, "label_kind"),
        "feedback_class_distribution": _count_distribution(normalized_records, "feedback_class"),
        "unique_sample_ids": len(sample_ids),
        "legacy_records_count": legacy_records_count,
        "feedback_export_records_path": str(resolved_records_path),
    }


def write_phase14_feedback_manifest(manifest: dict, *, output_path: str) -> Path:
    target = Path(_safe_text(output_path))
    if not _safe_text(output_path):
        raise ValueError("manifest output_path is required")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(manifest or {}), ensure_ascii=False, indent=2), encoding="utf-8")
    return target.resolve()
