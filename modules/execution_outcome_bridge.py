from __future__ import annotations

from typing import Any, Dict, Iterable, List, Set

from modules.strategy_state import StrategySignalState, normalize_strategy_state


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


def _safe_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = _safe_text(value).lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off", ""}:
        return False
    return bool(value)


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
    raise TypeError(f"unsupported execution outcome row type: {type(row)!r}")


def _is_legacy_row(row: Dict[str, Any]) -> bool:
    if _safe_bool(row.get("legacy_path")):
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


def _matches_position_identity(
    row: Dict[str, Any],
    *,
    analysis_run_id: int,
    ca: str,
    position_ids: Set[str],
) -> bool:
    if not _matches_analysis_identity(row, analysis_run_id=analysis_run_id, ca=ca):
        return False
    if not position_ids:
        return True
    return _safe_text(row.get("position_id")) in position_ids


def _latest_timestamp(rows: Iterable[Dict[str, Any]], *field_names: str) -> str:
    latest = ""
    for row in rows:
        for field_name in field_names:
            candidate = _safe_text(row.get(field_name))
            if candidate and candidate > latest:
                latest = candidate
    return latest


def _ordered_rows(rows: Iterable[Dict[str, Any]], *field_names: str) -> List[Dict[str, Any]]:
    enumerated = list(enumerate(list(rows or [])))
    return [
        row
        for _, row in sorted(
            enumerated,
            key=lambda item: (
                _latest_timestamp([item[1]], *field_names),
                item[0],
            ),
        )
    ]


def _build_state_path(rows: List[Dict[str, Any]]) -> List[str]:
    path: List[str] = []
    for row in _ordered_rows(rows, "created_at", "event_at", "recorded_at"):
        from_state = normalize_strategy_state(row.get("from_state"), "")
        to_state = normalize_strategy_state(row.get("to_state"), "")
        if from_state and (not path or path[-1] != from_state):
            path.append(from_state)
        if to_state and (not path or path[-1] != to_state):
            path.append(to_state)
    return path


def _latest_state(rows: List[Dict[str, Any]], execution_event_rows: List[Dict[str, Any]], label_kind: str) -> str:
    ordered_transitions = _ordered_rows(rows, "created_at", "event_at", "recorded_at")
    if ordered_transitions:
        latest = normalize_strategy_state(ordered_transitions[-1].get("to_state"), "")
        if latest:
            return latest

    ordered_execution = _ordered_rows(execution_event_rows, "created_at", "recorded_at")
    if ordered_execution:
        latest = normalize_strategy_state(ordered_execution[-1].get("signal_state"), "")
        if latest:
            return latest

    if label_kind == "trade_closed":
        return StrategySignalState.EXITED.value
    if label_kind == "no_fill":
        return StrategySignalState.ARMED.value
    return StrategySignalState.REJECTED.value


def _feedback_class(label_row: Dict[str, Any], trade_close_rows: List[Dict[str, Any]]) -> str:
    label_kind = _safe_text(label_row.get("label_kind")).lower()
    if label_kind == "trade_closed":
        realized_pnl = _safe_float(label_row.get("realized_pnl_sol"), 0.0)
        has_partial = any(_safe_bool(row.get("partial")) for row in trade_close_rows)
        if not has_partial and int(label_row.get("close_legs") or 0) > 1:
            has_partial = True
        if realized_pnl > 0 and has_partial:
            return "entered_partial_win"
        if realized_pnl > 0:
            return "entered_profit"
        return "entered_loss"
    if label_kind == "no_fill":
        return "armed_no_fill"
    return "observe_reject"


def _dedupe_texts(values: Iterable[Any]) -> List[str]:
    out: List[str] = []
    seen: Set[str] = set()
    for value in values:
        text = _safe_text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def build_execution_outcome_bucket(
    *,
    sample_row,
    label_row,
    state_transition_rows=None,
    decision_event_rows=None,
    execution_event_rows=None,
    trade_close_rows=None,
) -> Dict[str, Any]:
    sample = _normalize_row(sample_row)
    label = _normalize_row(label_row)
    analysis_run_id = int(_safe_int(sample.get("analysis_run_id"), 0) or 0)
    ca = _safe_text(sample.get("ca"))
    position_ids = {
        _safe_text(value)
        for value in _safe_list(label.get("position_ids"))
        if _safe_text(value)
    }

    matched_state_rows = [
        _normalize_row(raw)
        for raw in list(state_transition_rows or [])
        if _matches_analysis_identity(
            _normalize_row(raw),
            analysis_run_id=analysis_run_id,
            ca=ca,
        )
    ]
    matched_execution_rows = [
        _normalize_row(raw)
        for raw in list(execution_event_rows or [])
        if _matches_analysis_identity(
            _normalize_row(raw),
            analysis_run_id=analysis_run_id,
            ca=ca,
        )
    ]
    matched_trade_close_rows = [
        _normalize_row(raw)
        for raw in list(trade_close_rows or [])
        if _matches_position_identity(
            _normalize_row(raw),
            analysis_run_id=analysis_run_id,
            ca=ca,
            position_ids=position_ids,
        )
    ]

    transition_reasons = _dedupe_texts(row.get("transition_reason") for row in matched_state_rows)
    execution_statuses = _dedupe_texts(row.get("status") for row in matched_execution_rows)
    close_reasons = _dedupe_texts(
        list(label.get("close_reasons") or []) + [row.get("close_reason") for row in matched_trade_close_rows]
    )
    trade_close_ids = _dedupe_texts(row.get("trade_close_id") for row in matched_trade_close_rows)
    if not position_ids:
        position_ids = {
            _safe_text(row.get("position_id"))
            for row in matched_trade_close_rows
            if _safe_text(row.get("position_id"))
        }

    label_kind = _safe_text(label.get("label_kind")).lower()
    feedback_class = _feedback_class(label, matched_trade_close_rows)
    state_path = _build_state_path(matched_state_rows)
    final_state = _latest_state(matched_state_rows, matched_execution_rows, label_kind)
    outcome_reason = ""
    if feedback_class == "observe_reject":
        outcome_reason = transition_reasons[-1] if transition_reasons else "observe_reject"
    elif feedback_class == "armed_no_fill":
        outcome_reason = "armed_without_effective_fill"
    else:
        outcome_reason = " | ".join(close_reasons) if close_reasons else "trade_closed"

    return {
        "sample_id": _safe_text(sample.get("sample_id")),
        "analysis_run_id": analysis_run_id,
        "ca": ca,
        "trace_link": _safe_text(sample.get("trace_link")),
        "label_kind": label_kind,
        "feedback_class": feedback_class,
        "position_ids": sorted(position_ids),
        "trade_close_ids": trade_close_ids,
        "state_path": state_path,
        "final_state": final_state,
        "transition_reasons": transition_reasons,
        "execution_statuses": execution_statuses,
        "close_reasons": close_reasons,
        "outcome_reason": outcome_reason,
        "realized_pnl_sol": round(_safe_float(label.get("realized_pnl_sol"), 0.0), 6),
        "realized_return_pct": round(_safe_float(label.get("realized_return_pct"), 0.0), 6),
        "snapshot_at": _latest_timestamp(
            matched_trade_close_rows + matched_execution_rows + matched_state_rows,
            "closed_at",
            "recorded_at",
            "created_at",
            "event_at",
        ),
    }
