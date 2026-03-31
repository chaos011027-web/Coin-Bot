from __future__ import annotations

from typing import Any, Dict, Iterable, List

from modules.strategy_state import StrategySignalState, normalize_primary_strategy_state


BLOCKING_RISK_FLAGS = {
    "AUTHORITY_RISK",
    "SOURCE_CONFLICT",
    "TOP10_SEMANTIC_CONFLICT",
}
BLOCKING_WALLET_LABELS = {
    "SUSPICIOUS_CLUSTER_WALLET",
}
MIN_ARMED_TOTAL_SCORE = 0.75
MIN_BLOCKING_WALLET_CONFIDENCE = 0.7


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
    raise TypeError(f"unsupported strategy bridge row type: {type(row)!r}")


def _is_legacy_row(row: Dict[str, Any]) -> bool:
    if _safe_bool(row.get("legacy_path")):
        return True
    return _safe_text(row.get("path_kind")).upper() == "LEGACY_DIRECT_ENTER"


def _safe_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except Exception:
        return None


def _matches_identity(
    row: Dict[str, Any],
    *,
    analysis_run_id: int,
    ca: str,
    position_id: str = "",
) -> bool:
    if _is_legacy_row(row):
        return False
    if _safe_text(row.get("ca")) != ca:
        return False

    row_run_id = _safe_int(row.get("analysis_run_id"))
    if row_run_id is not None and row_run_id != analysis_run_id:
        return False

    requested_position_id = _safe_text(position_id)
    row_position_id = _safe_text(row.get("position_id"))
    if requested_position_id and row_position_id and row_position_id != requested_position_id:
        return False
    return True


def _latest_timestamp(rows: Iterable[Dict[str, Any]], *field_names: str) -> str:
    latest = ""
    for row in rows:
        for field_name in field_names:
            candidate = _safe_text(row.get(field_name))
            if candidate and candidate > latest:
                latest = candidate
    return latest


def build_strategy_state_identity(
    *,
    analysis_run_id: Any,
    ca: Any,
    position_id: Any = "",
    trace_link: Any = "",
    sample_id: Any = "",
) -> Dict[str, Any]:
    resolved_analysis_run_id = _safe_int(analysis_run_id)
    resolved_ca = _safe_text(ca)
    if resolved_analysis_run_id is None:
        raise ValueError("strategy state identity missing analysis_run_id")
    if not resolved_ca:
        raise ValueError("strategy state identity missing ca")

    return {
        "analysis_run_id": resolved_analysis_run_id,
        "ca": resolved_ca,
        "identity_key": f"{resolved_analysis_run_id}:{resolved_ca}",
        "position_id": _safe_text(position_id),
        "trace_link": _safe_text(trace_link),
        "sample_id": _safe_text(sample_id),
    }


def evaluate_observing_state_transition(
    *,
    analysis_run_id: Any,
    ca: Any,
    token_risk_flag_rows=None,
    token_score_snapshot_rows=None,
    wallet_label_rows=None,
) -> Dict[str, Any]:
    identity = build_strategy_state_identity(analysis_run_id=analysis_run_id, ca=ca)
    matched_risk_rows = [
        _normalize_row(raw)
        for raw in list(token_risk_flag_rows or [])
        if _matches_identity(
            _normalize_row(raw),
            analysis_run_id=identity["analysis_run_id"],
            ca=identity["ca"],
        )
    ]
    matched_score_rows = [
        _normalize_row(raw)
        for raw in list(token_score_snapshot_rows or [])
        if _matches_identity(
            _normalize_row(raw),
            analysis_run_id=identity["analysis_run_id"],
            ca=identity["ca"],
        )
    ]
    matched_wallet_label_rows = [
        _normalize_row(raw)
        for raw in list(wallet_label_rows or [])
        if not _is_legacy_row(_normalize_row(raw))
    ]

    blocking_risk_flags = sorted(
        {
            _safe_text(row.get("risk_flag"))
            for row in matched_risk_rows
            if _safe_text(row.get("risk_flag")) in BLOCKING_RISK_FLAGS
        }
    )
    blocking_wallet_labels = sorted(
        {
            _safe_text(row.get("label_name"))
            for row in matched_wallet_label_rows
            if _safe_text(row.get("label_name")) in BLOCKING_WALLET_LABELS
            and _safe_float(row.get("confidence") or row.get("confidence_score"), 0.0) >= MIN_BLOCKING_WALLET_CONFIDENCE
        }
    )

    latest_score_row = {}
    latest_score_timestamp = ""
    for row in matched_score_rows:
        candidate_timestamp = _safe_text(row.get("snapshot_at") or row.get("created_at"))
        if not latest_score_row or candidate_timestamp >= latest_score_timestamp:
            latest_score_row = row
            latest_score_timestamp = candidate_timestamp
    total_score = _safe_float(latest_score_row.get("total_score"), 0.0)

    next_state = StrategySignalState.OBSERVING.value
    reason = "observe_score_below_arm_threshold"
    if blocking_risk_flags:
        next_state = StrategySignalState.REJECTED.value
        reason = "reject_blocking_risk_flags"
    elif blocking_wallet_labels:
        next_state = StrategySignalState.REJECTED.value
        reason = "reject_blocking_wallet_labels"
    elif not latest_score_row:
        reason = "observe_score_snapshot_missing"
    elif total_score >= MIN_ARMED_TOTAL_SCORE:
        next_state = StrategySignalState.ARMED.value
        reason = "armed_by_stable_inputs"

    return {
        **identity,
        "current_state": StrategySignalState.OBSERVING.value,
        "next_state": next_state,
        "reason": reason,
        "total_score": total_score,
        "blocking_risk_flags": blocking_risk_flags,
        "blocking_wallet_labels": blocking_wallet_labels,
        "snapshot_at": latest_score_timestamp,
    }


def bridge_ledger_primary_state(
    *,
    analysis_run_id: Any,
    ca: Any,
    current_state: Any,
    paper_fill_rows=None,
    paper_position_rows=None,
    paper_trade_close_rows=None,
    position_id: Any = "",
) -> Dict[str, Any]:
    identity = build_strategy_state_identity(
        analysis_run_id=analysis_run_id,
        ca=ca,
        position_id=position_id,
    )
    resolved_current_state = normalize_primary_strategy_state(current_state)

    matched_fill_rows = [
        _normalize_row(raw)
        for raw in list(paper_fill_rows or [])
        if _matches_identity(
            _normalize_row(raw),
            analysis_run_id=identity["analysis_run_id"],
            ca=identity["ca"],
            position_id=identity["position_id"],
        )
    ]
    matched_position_rows = [
        _normalize_row(raw)
        for raw in list(paper_position_rows or [])
        if _matches_identity(
            _normalize_row(raw),
            analysis_run_id=identity["analysis_run_id"],
            ca=identity["ca"],
            position_id=identity["position_id"],
        )
    ]
    matched_trade_close_rows = [
        _normalize_row(raw)
        for raw in list(paper_trade_close_rows or [])
        if _matches_identity(
            _normalize_row(raw),
            analysis_run_id=identity["analysis_run_id"],
            ca=identity["ca"],
            position_id=identity["position_id"],
        )
    ]

    resolved_position_id = identity["position_id"]
    for row in matched_fill_rows + matched_position_rows + matched_trade_close_rows:
        candidate_position_id = _safe_text(row.get("position_id"))
        if candidate_position_id:
            resolved_position_id = candidate_position_id
            break

    has_buy_fill = any(_safe_text(row.get("side")).upper() == "BUY" for row in matched_fill_rows)
    has_position_opened = any(_safe_text(row.get("event_type")).upper() == "OPENED" for row in matched_position_rows)
    has_position_updated = any(_safe_text(row.get("event_type")).upper() == "UPDATED" for row in matched_position_rows)
    has_position_closed = any(_safe_text(row.get("event_type")).upper() == "CLOSED" for row in matched_position_rows)
    has_partial_close = any(_safe_bool(row.get("partial")) for row in matched_trade_close_rows)
    has_full_close = any(not _safe_bool(row.get("partial")) for row in matched_trade_close_rows) or has_position_closed

    next_state = resolved_current_state
    reason = "ledger_state_unchanged"
    if has_full_close:
        next_state = StrategySignalState.EXITED.value
        reason = "ledger_position_closed"
    elif resolved_current_state == StrategySignalState.ARMED.value and (has_buy_fill or has_position_opened):
        next_state = StrategySignalState.ENTERED.value
        reason = "ledger_open_fill_or_position_opened"
    elif resolved_current_state in {StrategySignalState.ENTERED.value, StrategySignalState.MANAGING.value}:
        if has_partial_close or has_position_updated or has_position_opened or has_buy_fill:
            next_state = StrategySignalState.MANAGING.value
            reason = "ledger_position_still_open"

    return {
        **identity,
        "position_id": resolved_position_id,
        "current_state": resolved_current_state,
        "next_state": next_state,
        "reason": reason,
        "snapshot_at": _latest_timestamp(
            matched_fill_rows + matched_position_rows + matched_trade_close_rows,
            "filled_at",
            "event_at",
            "recorded_at",
        ),
        "has_buy_fill": has_buy_fill,
        "has_position_opened": has_position_opened,
        "has_position_updated": has_position_updated,
        "has_partial_close": has_partial_close,
        "has_full_close": has_full_close,
    }
