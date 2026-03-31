from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List

from modules.risk_budget import build_risk_budget
from modules.strategy_state import StrategySignalState, normalize_primary_strategy_state


DEFAULT_TOTAL_SCORE = 0.75
HARD_VETO_RISK_FLAGS = {
    "AUTHORITY_RISK",
    "SOURCE_CONFLICT",
    "TOP10_SEMANTIC_CONFLICT",
}
CLAMP_RISK_MULTIPLIERS = {
    "LOW_LIQUIDITY": 0.50,
    "TOP10_CONCENTRATION": 0.60,
    "GMGN_BEHAVIOR_RISK": 0.75,
}


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


def _normalize_row(row: Any) -> Dict[str, Any]:
    if isinstance(row, dict):
        return dict(row)
    try:
        return dict(row)
    except Exception:
        pass
    if hasattr(row, "keys"):
        return {key: row[key] for key in row.keys()}
    raise TypeError(f"unsupported sizing policy row type: {type(row)!r}")


def _is_legacy_row(row: Dict[str, Any]) -> bool:
    if bool(row.get("legacy_path")):
        return True
    return _safe_text(row.get("path_kind")).upper() == "LEGACY_DIRECT_ENTER"


def _score_multiplier(token_score_snapshot: Dict[str, Any]) -> float:
    total_score = _safe_float(token_score_snapshot.get("total_score"), DEFAULT_TOTAL_SCORE)
    return max(0.0, min(1.0, total_score))


def _wallet_multiplier(wallet_label_rows: List[Dict[str, Any]]) -> tuple[float, List[str]]:
    multiplier = 1.0
    reasons: List[str] = []
    for row in wallet_label_rows:
        label_name = _safe_text(row.get("label_name")).upper()
        confidence = _safe_float(row.get("confidence") or row.get("confidence_score"), 0.0)
        if confidence < 0.7:
            continue
        if label_name == "SMART_MONEY_WALLET":
            multiplier *= 1.05
            reasons.append("SMART_MONEY_WALLET")
        elif label_name == "SUSPICIOUS_CLUSTER_WALLET":
            multiplier *= 0.60
            reasons.append("SUSPICIOUS_CLUSTER_WALLET")
    return max(0.30, min(1.10, multiplier)), reasons


@dataclass(frozen=True)
class SizingDecision:
    state: str
    cash: float
    equity: float
    available_cash: float
    current_position_value: float
    max_position_value: float
    max_position_pct_of_equity: float
    max_new_entry_pct_of_available_cash: float
    max_add_pct: float
    risk_per_trade: float
    conviction_score: float
    hard_veto_risk_flags: List[str]
    clamp_risk_flags: List[str]
    wallet_adjustment_labels: List[str]
    new_entry_size: float
    max_add_size: float
    size_clamp_reason: str
    budget_reason: str


def build_position_sizing_decision(
    *,
    state: Any,
    cash: Any,
    equity: Any,
    reserve_cash_sol: Any,
    current_position_value: Any = 0.0,
    token_score_snapshot=None,
    token_risk_flags=None,
    wallet_labels=None,
) -> Dict[str, Any]:
    resolved_state = normalize_primary_strategy_state(state)
    risk_budget = build_risk_budget(
        cash=cash,
        equity=equity,
        reserve_cash_sol=reserve_cash_sol,
        current_position_value=current_position_value,
    )
    score_row = _normalize_row(token_score_snapshot or {})
    risk_rows = [
        _normalize_row(raw)
        for raw in list(token_risk_flags or [])
        if not _is_legacy_row(_normalize_row(raw))
    ]
    label_rows = [
        _normalize_row(raw)
        for raw in list(wallet_labels or [])
        if not _is_legacy_row(_normalize_row(raw))
    ]

    hard_veto_risk_flags = sorted(
        {
            _safe_text(row.get("risk_flag"))
            for row in risk_rows
            if _safe_text(row.get("risk_flag")) in HARD_VETO_RISK_FLAGS
        }
    )
    clamp_risk_flags = sorted(
        {
            _safe_text(row.get("risk_flag"))
            for row in risk_rows
            if _safe_text(row.get("risk_flag")) in CLAMP_RISK_MULTIPLIERS
        }
    )
    conviction_score = round(_score_multiplier(score_row), 6)

    clamp_multiplier = 1.0
    for risk_flag in clamp_risk_flags:
        clamp_multiplier *= CLAMP_RISK_MULTIPLIERS.get(risk_flag, 1.0)

    wallet_multiplier, wallet_reasons = _wallet_multiplier(label_rows)
    total_multiplier = max(0.0, min(1.10, conviction_score * clamp_multiplier * wallet_multiplier))

    new_entry_size = 0.0
    max_add_size = 0.0
    size_clamp_reason = "no_clamp"
    budget_reason = "state_not_actionable"

    if hard_veto_risk_flags:
        size_clamp_reason = f"hard_veto:{','.join(hard_veto_risk_flags)}"
        budget_reason = "hard_veto_budget_zero"
    else:
        reasons: List[str] = []
        if clamp_risk_flags:
            reasons.append(f"risk_clamp:{','.join(clamp_risk_flags)}")
        if wallet_reasons:
            reasons.append(f"wallet_adjustment:{','.join(wallet_reasons)}")
        if reasons:
            size_clamp_reason = ";".join(reasons)

        if resolved_state == StrategySignalState.ARMED.value:
            new_entry_size = min(
                risk_budget["new_entry_budget"] * total_multiplier,
                risk_budget["available_cash"],
                risk_budget["max_position_value"],
            )
            budget_reason = "armed_new_entry_size"
        elif resolved_state == StrategySignalState.MANAGING.value:
            residual_budget = max(
                0.0,
                risk_budget["max_position_value"] - risk_budget["current_position_value"],
            )
            max_add_size = min(
                risk_budget["add_budget"] * total_multiplier,
                risk_budget["available_cash"],
                residual_budget,
            )
            budget_reason = "managing_max_add_size"

    decision = SizingDecision(
        state=resolved_state,
        cash=risk_budget["cash"],
        equity=risk_budget["equity"],
        available_cash=risk_budget["available_cash"],
        current_position_value=risk_budget["current_position_value"],
        max_position_value=risk_budget["max_position_value"],
        max_position_pct_of_equity=risk_budget["max_position_pct_of_equity"],
        max_new_entry_pct_of_available_cash=risk_budget["max_new_entry_pct_of_available_cash"],
        max_add_pct=risk_budget["max_add_pct"],
        risk_per_trade=risk_budget["risk_per_trade"],
        conviction_score=conviction_score,
        hard_veto_risk_flags=hard_veto_risk_flags,
        clamp_risk_flags=clamp_risk_flags,
        wallet_adjustment_labels=wallet_reasons,
        new_entry_size=round(max(0.0, new_entry_size), 6),
        max_add_size=round(max(0.0, max_add_size), 6),
        size_clamp_reason=size_clamp_reason,
        budget_reason=budget_reason,
    )
    return asdict(decision)
