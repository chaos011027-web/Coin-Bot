from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict


DEFAULT_MAX_POSITION_PCT_OF_EQUITY = 0.18
DEFAULT_MAX_NEW_ENTRY_PCT_OF_AVAILABLE_CASH = 0.40
DEFAULT_MAX_ADD_PCT = 0.50
DEFAULT_RISK_PER_TRADE = 0.02


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


@dataclass(frozen=True)
class RiskBudget:
    cash: float
    equity: float
    reserve_cash_sol: float
    available_cash: float
    current_position_value: float
    max_position_pct_of_equity: float
    max_new_entry_pct_of_available_cash: float
    max_add_pct: float
    risk_per_trade: float
    max_position_value: float
    new_entry_budget: float
    add_budget: float


def build_risk_budget(
    *,
    cash: Any,
    equity: Any,
    reserve_cash_sol: Any,
    current_position_value: Any = 0.0,
) -> Dict[str, Any]:
    resolved_cash = max(0.0, _safe_float(cash, 0.0))
    resolved_equity = max(0.0, _safe_float(equity, resolved_cash))
    resolved_reserve_cash = max(0.0, _safe_float(reserve_cash_sol, 0.0))
    resolved_current_position_value = max(0.0, _safe_float(current_position_value, 0.0))

    available_cash = max(0.0, resolved_cash - resolved_reserve_cash)
    max_position_value = resolved_equity * DEFAULT_MAX_POSITION_PCT_OF_EQUITY
    new_entry_budget = min(
        max_position_value,
        available_cash * DEFAULT_MAX_NEW_ENTRY_PCT_OF_AVAILABLE_CASH,
    )
    add_budget = min(
        max(0.0, max_position_value - resolved_current_position_value),
        available_cash * DEFAULT_MAX_ADD_PCT,
    )

    budget = RiskBudget(
        cash=round(resolved_cash, 6),
        equity=round(resolved_equity, 6),
        reserve_cash_sol=round(resolved_reserve_cash, 6),
        available_cash=round(available_cash, 6),
        current_position_value=round(resolved_current_position_value, 6),
        max_position_pct_of_equity=DEFAULT_MAX_POSITION_PCT_OF_EQUITY,
        max_new_entry_pct_of_available_cash=DEFAULT_MAX_NEW_ENTRY_PCT_OF_AVAILABLE_CASH,
        max_add_pct=DEFAULT_MAX_ADD_PCT,
        risk_per_trade=DEFAULT_RISK_PER_TRADE,
        max_position_value=round(max_position_value, 6),
        new_entry_budget=round(max(0.0, new_entry_budget), 6),
        add_budget=round(max(0.0, add_budget), 6),
    )
    return asdict(budget)
