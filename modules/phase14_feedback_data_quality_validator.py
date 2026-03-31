from __future__ import annotations

from typing import Any, Dict

from modules.phase14_feedback_manifest import build_phase14_feedback_manifest


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
    raise TypeError(f"unsupported phase14 validator row type: {type(row)!r}")


def validate_phase14_feedback_export_payloads(*, records_payload: dict, manifest_payload: dict) -> dict:
    records_wrapper = _normalize_row(records_payload or {})
    manifest = _normalize_row(manifest_payload or {})
    records = list(records_wrapper.get("records") or [])

    if not records:
        raise RuntimeError("feedback export records empty")

    for row in records:
        normalized = _normalize_row(row)
        path_kind = _safe_text(normalized.get("path_kind")).upper()
        if path_kind == "LEGACY_DIRECT_ENTER" or bool(normalized.get("legacy_path")):
            raise RuntimeError("legacy samples must be excluded")

    expected_manifest = build_phase14_feedback_manifest(
        records=[_normalize_row(row) for row in records],
        records_path=manifest.get("feedback_export_records_path") or "data/feedback_export_records.json",
    )

    for field_name in [
        "records_count",
        "label_kind_distribution",
        "feedback_class_distribution",
        "unique_sample_ids",
        "legacy_records_count",
    ]:
        if manifest.get(field_name) != expected_manifest.get(field_name):
            raise RuntimeError(f"manifest mismatch: {field_name}")

    if int(records_wrapper.get("records_count") or 0) != len(records):
        raise RuntimeError("records_count mismatch")

    return {
        "status": "success",
        "records_count": len(records),
    }
