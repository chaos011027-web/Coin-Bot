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
    raise TypeError(f"unsupported strategy feedback row type: {type(row)!r}")


def _safe_int(value: Any, default: int | None = None) -> int | None:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except Exception:
        return default


def _is_legacy_row(row: Dict[str, Any]) -> bool:
    if bool(row.get("legacy_path")):
        return True
    return _safe_text(row.get("path_kind")).upper() == "LEGACY_DIRECT_ENTER"


def _matches_analysis_identity(row: Dict[str, Any], *, analysis_run_id: int, ca: str) -> bool:
    if _is_legacy_row(row):
        return False
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


def _build_state_path(state_rows: List[Dict[str, Any]], fallback: List[str]) -> List[str]:
    if fallback:
        return list(fallback)
    path: List[str] = []
    ordered = sorted(
        list(state_rows or []),
        key=lambda row: (_safe_text(row.get("created_at")), _safe_text(row.get("to_state"))),
    )
    for row in ordered:
        from_state = _safe_text(row.get("from_state"))
        to_state = _safe_text(row.get("to_state"))
        if from_state and (not path or path[-1] != from_state):
            path.append(from_state)
        if to_state and (not path or path[-1] != to_state):
            path.append(to_state)
    return path


def build_strategy_feedback_snapshot(
    *,
    sample_row,
    label_row,
    execution_outcome_row,
    decision_event_rows=None,
    state_transition_rows=None,
) -> Dict[str, Any]:
    sample = _normalize_row(sample_row)
    label = _normalize_row(label_row)
    outcome = _normalize_row(execution_outcome_row)
    analysis_run_id = int(_safe_int(sample.get("analysis_run_id"), 0) or 0)
    ca = _safe_text(sample.get("ca"))

    matched_decision_rows = [
        _normalize_row(raw)
        for raw in list(decision_event_rows or [])
        if _matches_analysis_identity(
            _normalize_row(raw),
            analysis_run_id=analysis_run_id,
            ca=ca,
        )
    ]
    matched_state_rows = [
        _normalize_row(raw)
        for raw in list(state_transition_rows or [])
        if _matches_analysis_identity(
            _normalize_row(raw),
            analysis_run_id=analysis_run_id,
            ca=ca,
        )
    ]
    latest_decision = _latest_row(matched_decision_rows, "created_at")
    state_path = _build_state_path(matched_state_rows, list(outcome.get("state_path") or []))

    return {
        "sample_id": _safe_text(sample.get("sample_id")),
        "analysis_run_id": analysis_run_id,
        "ca": ca,
        "trace_link": _safe_text(sample.get("trace_link")),
        "path_kind": _safe_text(sample.get("path_kind")),
        "final_action": _safe_text(latest_decision.get("final_action") or sample.get("final_action")),
        "strategy_id": _safe_text(latest_decision.get("strategy_id") or sample.get("strategy_id")),
        "candidate_action": _safe_text(latest_decision.get("candidate_action")),
        "ai_verdict": _safe_text(latest_decision.get("ai_verdict")),
        "risk_adjusted_action": _safe_text(latest_decision.get("risk_adjusted_action")),
        "decision_score": round(_safe_float(latest_decision.get("score"), 0.0), 6),
        "decision_reason": _safe_text(latest_decision.get("reason")),
        "decision_risk_flags": [
            _safe_text(value)
            for value in _safe_list(latest_decision.get("risk_flags"))
            if _safe_text(value)
        ],
        "label_kind": _safe_text(label.get("label_kind")).lower(),
        "feedback_class": _safe_text(outcome.get("feedback_class")),
        "state_path": state_path,
        "final_state": _safe_text(outcome.get("final_state")),
        "outcome_reason": _safe_text(outcome.get("outcome_reason")),
        "close_reasons": list(outcome.get("close_reasons") or []),
        "position_ids": list(outcome.get("position_ids") or []),
        "trade_close_ids": list(outcome.get("trade_close_ids") or []),
        "realized_pnl_sol": round(_safe_float(outcome.get("realized_pnl_sol"), 0.0), 6),
        "realized_return_pct": round(_safe_float(outcome.get("realized_return_pct"), 0.0), 6),
    }
