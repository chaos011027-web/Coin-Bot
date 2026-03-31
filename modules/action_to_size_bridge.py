from __future__ import annotations

from typing import Any, Dict

from modules.position_sizing_policy import build_position_sizing_decision
from modules.strategy_state import AnalysisPathKind


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
    raise TypeError(f"unsupported action-to-size row type: {type(row)!r}")


def _is_legacy_row(row: Dict[str, Any]) -> bool:
    if _safe_bool(row.get("legacy_path")):
        return True
    return _safe_text(row.get("path_kind")).upper() == "LEGACY_DIRECT_ENTER"


def _matches_identity(row: Dict[str, Any], *, analysis_run_id: int, ca: str) -> bool:
    if _is_legacy_row(row):
        return False
    if _safe_text(row.get("ca")) != ca:
        return False
    row_run_id = row.get("analysis_run_id")
    if row_run_id is None or row_run_id == "":
        return True
    return _safe_int(row_run_id, analysis_run_id) == analysis_run_id


def build_action_to_size_decision(
    *,
    analysis_run_id: Any,
    ca: Any,
    state: Any,
    cash: Any,
    equity: Any,
    reserve_cash_sol: Any,
    token_score_snapshot=None,
    token_risk_flag_rows=None,
    wallet_label_rows=None,
    current_position_value: Any = 0.0,
    position_id: Any = "",
    trace_link: Any = "",
    sample_id: Any = "",
    path_kind: Any = "",
    legacy_path: Any = False,
) -> Dict[str, Any]:
    resolved_analysis_run_id = _safe_int(analysis_run_id, 0)
    resolved_ca = _safe_text(ca)
    resolved_path_kind = _safe_text(path_kind)
    resolved_legacy = _safe_bool(legacy_path) or resolved_path_kind == AnalysisPathKind.LEGACY_DIRECT_ENTER.value

    if resolved_legacy:
        return {
            "analysis_run_id": resolved_analysis_run_id,
            "ca": resolved_ca,
            "identity_key": f"{resolved_analysis_run_id}:{resolved_ca}",
            "position_id": _safe_text(position_id),
            "trace_link": _safe_text(trace_link),
            "sample_id": _safe_text(sample_id),
            "new_entry_size": 0.0,
            "max_add_size": 0.0,
            "available_cash": max(0.0, float(cash or 0.0) - float(reserve_cash_sol or 0.0)),
            "max_position_value": 0.0,
            "size_clamp_reason": "legacy_path_excluded",
            "budget_reason": "legacy_path_excluded",
            "hard_veto_risk_flags": [],
            "clamp_risk_flags": [],
            "wallet_adjustment_labels": [],
        }

    matched_score_row = _normalize_row(token_score_snapshot or {})
    matched_risk_rows = [
        _normalize_row(raw)
        for raw in list(token_risk_flag_rows or [])
        if _matches_identity(
            _normalize_row(raw),
            analysis_run_id=resolved_analysis_run_id,
            ca=resolved_ca,
        )
    ]
    matched_wallet_rows = [
        _normalize_row(raw)
        for raw in list(wallet_label_rows or [])
        if not _is_legacy_row(_normalize_row(raw))
    ]

    decision = build_position_sizing_decision(
        state=state,
        cash=cash,
        equity=equity,
        reserve_cash_sol=reserve_cash_sol,
        current_position_value=current_position_value,
        token_score_snapshot=matched_score_row,
        token_risk_flags=matched_risk_rows,
        wallet_labels=matched_wallet_rows,
    )
    return {
        "analysis_run_id": resolved_analysis_run_id,
        "ca": resolved_ca,
        "identity_key": f"{resolved_analysis_run_id}:{resolved_ca}",
        "position_id": _safe_text(position_id),
        "trace_link": _safe_text(trace_link),
        "sample_id": _safe_text(sample_id),
        **decision,
    }
