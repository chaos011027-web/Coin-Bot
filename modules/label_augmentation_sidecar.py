from __future__ import annotations

from typing import Any, Dict, List


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


def _safe_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    return []


def _normalize_row(row: Any) -> Dict[str, Any]:
    if isinstance(row, dict):
        return dict(row)
    try:
        return dict(row)
    except Exception:
        pass
    if hasattr(row, "keys"):
        return {key: row[key] for key in row.keys()}
    raise TypeError(f"unsupported label augmentation row type: {type(row)!r}")


def build_label_augmentation_record(
    *,
    label_row,
    strategy_feedback_row,
    sizing_feedback_row,
) -> Dict[str, Any]:
    label = _normalize_row(label_row)
    strategy_feedback = _normalize_row(strategy_feedback_row)
    sizing_feedback = _normalize_row(sizing_feedback_row)

    return {
        "sample_id": _safe_text(label.get("sample_id")),
        "analysis_run_id": label.get("analysis_run_id"),
        "ca": _safe_text(label.get("ca")),
        "label_kind": _safe_text(label.get("label_kind")).lower(),
        "label_source": _safe_text(label.get("label_source")),
        "feedback_class": _safe_text(strategy_feedback.get("feedback_class")),
        "position_ids": list(label.get("position_ids") or strategy_feedback.get("position_ids") or []),
        "trade_close_ids": list(strategy_feedback.get("trade_close_ids") or []),
        "close_legs": int(label.get("close_legs") or 0),
        "close_reasons": list(label.get("close_reasons") or []),
        "realized_pnl_sol": round(_safe_float(label.get("realized_pnl_sol"), 0.0), 6),
        "realized_return_pct": round(_safe_float(label.get("realized_return_pct"), 0.0), 6),
        "requested_entry_size": round(_safe_float(sizing_feedback.get("requested_entry_size"), 0.0), 6),
        "effective_allocated_size": round(_safe_float(sizing_feedback.get("effective_allocated_size"), 0.0), 6),
        "requested_max_add_size": round(_safe_float(sizing_feedback.get("requested_max_add_size"), 0.0), 6),
        "effective_add_size": round(_safe_float(sizing_feedback.get("effective_add_size"), 0.0), 6),
        "budget_reason": _safe_text(sizing_feedback.get("budget_reason")),
        "size_clamp_reason": _safe_text(sizing_feedback.get("size_clamp_reason")),
        "hard_veto_risk_flags": [
            _safe_text(value)
            for value in _safe_list(sizing_feedback.get("hard_veto_risk_flags"))
            if _safe_text(value)
        ],
        "clamp_risk_flags": [
            _safe_text(value)
            for value in _safe_list(sizing_feedback.get("clamp_risk_flags"))
            if _safe_text(value)
        ],
    }
