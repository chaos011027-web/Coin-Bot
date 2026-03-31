from __future__ import annotations

from typing import Any, Dict, List, Set


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def _safe_int(value: Any, default: int | None = None) -> int | None:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except Exception:
        return default


def _normalize_row(row: Any) -> Dict[str, Any]:
    if isinstance(row, dict):
        return dict(row)
    try:
        return dict(row)
    except Exception:
        pass
    if hasattr(row, "keys"):
        return {key: row[key] for key in row.keys()}
    raise TypeError(f"unsupported sizing feedback row type: {type(row)!r}")


def _is_legacy_row(row: Dict[str, Any]) -> bool:
    if bool(row.get("legacy_path")):
        return True
    return _safe_text(row.get("path_kind")).upper() == "LEGACY_DIRECT_ENTER"


def _matches_sample_identity(row: Dict[str, Any], *, sample_id: str, analysis_run_id: int, ca: str) -> bool:
    if _is_legacy_row(row):
        return False
    row_sample_id = _safe_text(row.get("sample_id"))
    if row_sample_id:
        return row_sample_id == sample_id
    if _safe_text(row.get("ca")) not in {"", ca}:
        return False
    row_run_id = _safe_int(row.get("analysis_run_id"))
    if row_run_id is not None and row_run_id != analysis_run_id:
        return False
    return True


def _latest_row(rows: List[Dict[str, Any]], *field_names: str) -> Dict[str, Any]:
    latest: Dict[str, Any] = {}
    latest_stamp = ""
    for row in rows:
        stamp = ""
        for field_name in field_names:
            candidate = _safe_text(row.get(field_name))
            if candidate > stamp:
                stamp = candidate
        if not latest or stamp >= latest_stamp:
            latest = row
            latest_stamp = stamp
    return latest


def _safe_json_obj(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def build_sizing_feedback_snapshot(
    *,
    sample_row,
    execution_outcome_row,
    sizing_decision_rows=None,
    execution_event_rows=None,
) -> Dict[str, Any]:
    sample = _normalize_row(sample_row)
    outcome = _normalize_row(execution_outcome_row)
    sample_id = _safe_text(sample.get("sample_id"))
    analysis_run_id = int(_safe_int(sample.get("analysis_run_id"), 0) or 0)
    ca = _safe_text(sample.get("ca"))

    matched_sizing_rows = [
        _normalize_row(raw)
        for raw in list(sizing_decision_rows or [])
        if _matches_sample_identity(
            _normalize_row(raw),
            sample_id=sample_id,
            analysis_run_id=analysis_run_id,
            ca=ca,
        )
    ]
    matched_execution_rows = [
        _normalize_row(raw)
        for raw in list(execution_event_rows or [])
        if _matches_sample_identity(
            _normalize_row(raw),
            sample_id=sample_id,
            analysis_run_id=analysis_run_id,
            ca=ca,
        )
    ]

    entry_rows = [
        row for row in matched_sizing_rows
        if _safe_text(row.get("state")).upper() == "ARMED" or _safe_float(row.get("new_entry_size"), 0.0) > 0
    ]
    add_rows = [
        row for row in matched_sizing_rows
        if _safe_text(row.get("state")).upper() == "MANAGING" or _safe_float(row.get("max_add_size"), 0.0) > 0
    ]
    latest_entry_row = _latest_row(entry_rows, "created_at", "snapshot_at")
    latest_add_row = _latest_row(add_rows, "created_at", "snapshot_at")

    hard_veto_risk_flags: Set[str] = set()
    clamp_risk_flags: Set[str] = set()
    for row in matched_sizing_rows:
        for value in list(row.get("hard_veto_risk_flags") or []):
            text = _safe_text(value)
            if text:
                hard_veto_risk_flags.add(text)
        for value in list(row.get("clamp_risk_flags") or []):
            text = _safe_text(value)
            if text:
                clamp_risk_flags.add(text)

    effective_allocated_size = 0.0
    effective_add_size = 0.0
    for row in matched_execution_rows:
        metadata = _safe_json_obj(row.get("metadata"))
        action = _safe_text(row.get("action")).upper()
        event_type = _safe_text(row.get("event_type")).upper()
        signal_state = _safe_text(row.get("signal_state")).upper()
        if action == "ENTER" or event_type == "PAPER_OPEN" or signal_state == "ENTERED":
            effective_allocated_size += _safe_float(metadata.get("allocated_sol"), 0.0)
        if action == "ADD":
            effective_add_size += _safe_float(
                metadata.get("effective_add_size"),
                _safe_float(metadata.get("allocated_sol"), 0.0),
            )

    primary_budget_reason = _safe_text(
        latest_entry_row.get("budget_reason")
        or latest_add_row.get("budget_reason")
    )
    primary_size_clamp_reason = _safe_text(
        latest_entry_row.get("size_clamp_reason")
        or latest_add_row.get("size_clamp_reason")
    )

    return {
        "sample_id": sample_id,
        "analysis_run_id": analysis_run_id,
        "ca": ca,
        "trace_link": _safe_text(sample.get("trace_link")),
        "feedback_class": _safe_text(outcome.get("feedback_class")),
        "position_ids": list(outcome.get("position_ids") or []),
        "trade_close_ids": list(outcome.get("trade_close_ids") or []),
        "requested_entry_size": round(_safe_float(latest_entry_row.get("new_entry_size"), 0.0), 6),
        "effective_allocated_size": round(max(0.0, effective_allocated_size), 6),
        "requested_max_add_size": round(_safe_float(latest_add_row.get("max_add_size"), 0.0), 6),
        "effective_add_size": round(max(0.0, effective_add_size), 6),
        "budget_reason": primary_budget_reason,
        "size_clamp_reason": primary_size_clamp_reason,
        "hard_veto_risk_flags": sorted(hard_veto_risk_flags),
        "clamp_risk_flags": sorted(clamp_risk_flags),
        "realized_pnl_sol": round(_safe_float(outcome.get("realized_pnl_sol"), 0.0), 6),
        "realized_return_pct": round(_safe_float(outcome.get("realized_return_pct"), 0.0), 6),
    }
