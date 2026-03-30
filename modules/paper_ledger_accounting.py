from __future__ import annotations

import time
from typing import Any, Dict, Optional

from modules.paper_ledger_models import FinalCloseSettlement, OpenSettlement, PartialCloseSettlement


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def _cost_breakdown(gross_notional_sol: float, fee_rate_per_side: float, slippage_rate_per_side: float, fixed_cost_per_order_sol: float):
    fee_sol = gross_notional_sol * _safe_float(fee_rate_per_side, 0.0)
    slippage_sol = gross_notional_sol * _safe_float(slippage_rate_per_side, 0.0)
    fixed_cost_sol = _safe_float(fixed_cost_per_order_sol, 0.0)
    total_cost_sol = fee_sol + slippage_sol + fixed_cost_sol
    return fee_sol, slippage_sol, fixed_cost_sol, total_cost_sol


def build_open_settlement(
    *,
    cash_before: float,
    alloc_sol: float,
    entry_price: float,
    entry_mcap: float,
    fee_rate_per_side: float,
    slippage_rate_per_side: float,
    fixed_cost_per_order_sol: float,
) -> OpenSettlement:
    alloc_sol = _safe_float(alloc_sol, 0.0)
    entry_price = _safe_float(entry_price, 0.0)
    if alloc_sol <= 0 or entry_price <= 0:
        raise ValueError("invalid open settlement inputs")

    fee_sol, slippage_sol, fixed_cost_sol, total_cost_sol = _cost_breakdown(
        alloc_sol,
        fee_rate_per_side,
        slippage_rate_per_side,
        fixed_cost_per_order_sol,
    )
    qty = alloc_sol / entry_price
    cash_after = _safe_float(cash_before, 0.0) - (alloc_sol + total_cost_sol)
    return OpenSettlement(
        alloc_sol=alloc_sol,
        qty=qty,
        fee_sol=fee_sol,
        slippage_sol=slippage_sol,
        fixed_cost_sol=fixed_cost_sol,
        total_cost_sol=total_cost_sol,
        cash_after=cash_after,
        entry_price=entry_price,
        entry_mcap=_safe_float(entry_mcap, 0.0),
    )


def build_partial_close_settlement(
    *,
    position: Dict[str, Any],
    cash_before: float,
    exit_price: float,
    exit_mcap: float,
    ratio: float,
    fee_rate_per_side: float,
    slippage_rate_per_side: float,
    fixed_cost_per_order_sol: float,
    closed_at: Optional[float] = None,
    exit_reason: str = "",
) -> PartialCloseSettlement:
    pos = position or {}
    remaining_qty = _safe_float(pos.get("remaining_qty"), 0.0)
    total_qty = _safe_float(pos.get("qty"), 0.0)
    invested_sol = _safe_float(pos.get("invested_sol"), 0.0)
    ratio = max(0.0, min(1.0, _safe_float(ratio, 0.0)))
    exit_price = _safe_float(exit_price, 0.0)

    if remaining_qty <= 0 or total_qty <= 0 or exit_price <= 0 or ratio <= 0:
        raise ValueError("invalid partial close inputs")

    sell_qty = remaining_qty * ratio
    gross_exit_sol = sell_qty * exit_price
    fee_sol, slippage_sol, fixed_cost_sol, total_cost_sol = _cost_breakdown(
        gross_exit_sol,
        fee_rate_per_side,
        slippage_rate_per_side,
        fixed_cost_per_order_sol,
    )
    allocated_invested_sol = invested_sol * (sell_qty / total_qty) if total_qty > 0 else 0.0
    net_pnl_sol = gross_exit_sol - total_cost_sol - allocated_invested_sol
    net_return_pct = (net_pnl_sol / allocated_invested_sol * 100.0) if allocated_invested_sol > 0 else 0.0
    cash_delta_sol = max(0.0, gross_exit_sol - total_cost_sol)
    cash_after = _safe_float(cash_before, 0.0) + cash_delta_sol
    remaining_qty_after = max(0.0, remaining_qty - sell_qty)
    invested_sol_after = max(0.0, invested_sol - allocated_invested_sol)
    realized_pnl_sol_after = _safe_float(pos.get("realized_pnl_sol"), 0.0) + net_pnl_sol
    realized_fee_sol_after = _safe_float(pos.get("realized_fee_sol"), 0.0) + total_cost_sol
    avg_entry_price_after = _safe_float(pos.get("entry_price"), 0.0) if remaining_qty_after > 0 else 0.0
    now = _safe_float(closed_at, time.time())
    return PartialCloseSettlement(
        sell_qty=sell_qty,
        gross_exit_sol=gross_exit_sol,
        fee_sol=fee_sol,
        slippage_sol=slippage_sol,
        fixed_cost_sol=fixed_cost_sol,
        total_cost_sol=total_cost_sol,
        allocated_invested_sol=allocated_invested_sol,
        net_pnl_sol=net_pnl_sol,
        net_return_pct=net_return_pct,
        cash_delta_sol=cash_delta_sol,
        cash_after=cash_after,
        remaining_qty_after=remaining_qty_after,
        invested_sol_after=invested_sol_after,
        realized_pnl_sol_after=realized_pnl_sol_after,
        realized_fee_sol_after=realized_fee_sol_after,
        avg_entry_price_after=avg_entry_price_after,
        exit_price=exit_price,
        exit_mcap=_safe_float(exit_mcap, 0.0),
        opened_at=_safe_float(pos.get("opened_at"), time.time()),
        closed_at=now,
        exit_reason=str(exit_reason or ""),
        ratio=ratio,
    )


def build_final_close_settlement(
    *,
    position: Dict[str, Any],
    cash_before: float,
    exit_price: float,
    exit_mcap: float,
    fee_rate_per_side: float,
    slippage_rate_per_side: float,
    fixed_cost_per_order_sol: float,
    closed_at: Optional[float] = None,
    exit_reason: str = "",
) -> FinalCloseSettlement:
    pos = position or {}
    remaining_qty = _safe_float(pos.get("remaining_qty"), 0.0)
    total_qty = _safe_float(pos.get("qty"), 0.0)
    invested_sol = _safe_float(pos.get("invested_sol"), 0.0)
    exit_price = _safe_float(exit_price, 0.0)

    if remaining_qty <= 0 or total_qty <= 0 or exit_price <= 0:
        raise ValueError("invalid final close inputs")

    gross_exit_sol = remaining_qty * exit_price
    fee_sol, slippage_sol, fixed_cost_sol, total_cost_sol = _cost_breakdown(
        gross_exit_sol,
        fee_rate_per_side,
        slippage_rate_per_side,
        fixed_cost_per_order_sol,
    )
    allocated_invested_sol = invested_sol * (remaining_qty / total_qty) if total_qty > 0 else 0.0
    net_pnl_sol = gross_exit_sol - total_cost_sol - allocated_invested_sol
    realized_pnl_sol_after = _safe_float(pos.get("realized_pnl_sol"), 0.0) + net_pnl_sol
    net_return_pct = (net_pnl_sol / allocated_invested_sol * 100.0) if allocated_invested_sol > 0 else 0.0
    cash_delta_sol = max(0.0, gross_exit_sol - total_cost_sol)
    cash_after = _safe_float(cash_before, 0.0) + cash_delta_sol
    return FinalCloseSettlement(
        sell_qty=remaining_qty,
        gross_exit_sol=gross_exit_sol,
        fee_sol=fee_sol,
        slippage_sol=slippage_sol,
        fixed_cost_sol=fixed_cost_sol,
        total_cost_sol=total_cost_sol,
        allocated_invested_sol=allocated_invested_sol,
        net_pnl_sol=net_pnl_sol,
        realized_pnl_sol_after=realized_pnl_sol_after,
        net_return_pct=net_return_pct,
        cash_delta_sol=cash_delta_sol,
        cash_after=cash_after,
        exit_price=exit_price,
        exit_mcap=_safe_float(exit_mcap, 0.0),
        opened_at=_safe_float(pos.get("opened_at"), time.time()),
        closed_at=_safe_float(closed_at, time.time()),
        exit_reason=str(exit_reason or ""),
    )


def compute_current_equity(cash_sol: float, open_positions: Dict[str, Dict[str, Any]], mark_prices: Optional[Dict[str, float]] = None) -> float:
    total = _safe_float(cash_sol, 0.0)
    mark_prices = mark_prices or {}
    for ca, pos in (open_positions or {}).items():
        px = _safe_float(
            mark_prices.get(ca),
            _safe_float(pos.get("current_price"), _safe_float(pos.get("entry_price"), 0.0)),
        )
        qty = _safe_float(pos.get("remaining_qty"), 0.0)
        total += qty * px
    return total


def compute_portfolio_summary(
    *,
    initial_capital_sol: float,
    cash_sol: float,
    open_positions: Dict[str, Dict[str, Any]],
    closed_legs: list[Dict[str, Any]],
) -> Dict[str, Any]:
    trades = closed_legs or []
    total_trades = len(trades)
    wins = [t for t in trades if _safe_float(t.get("net_pnl_sol"), 0.0) > 0]
    total_net = sum(_safe_float(t.get("net_pnl_sol"), 0.0) for t in trades)
    total_cost = sum(_safe_float(t.get("total_cost_sol"), 0.0) for t in trades)

    running = _safe_float(initial_capital_sol, 0.0)
    peak = running
    max_dd = 0.0
    ordered = sorted(trades, key=lambda row: _safe_float(row.get("closed_at"), 0.0))
    for row in ordered:
        running += _safe_float(row.get("net_pnl_sol"), 0.0)
        if running > peak:
            peak = running
        dd = (peak - running) / peak if peak > 0 else 0.0
        max_dd = max(max_dd, dd)

    by_strategy: Dict[str, Dict[str, Any]] = {}
    for row in ordered:
        strategy = str(row.get("strategy") or "MIXED")
        bucket = by_strategy.setdefault(strategy, {"trades": 0, "wins": 0, "net_pnl_sol": 0.0, "cost_sol": 0.0})
        bucket["trades"] += 1
        pnl = _safe_float(row.get("net_pnl_sol"), 0.0)
        bucket["net_pnl_sol"] += pnl
        bucket["cost_sol"] += _safe_float(row.get("total_cost_sol"), 0.0)
        if pnl > 0:
            bucket["wins"] += 1

    for row in by_strategy.values():
        row["win_rate_pct"] = round((row["wins"] / row["trades"] * 100.0), 2) if row["trades"] > 0 else 0.0
        row["net_pnl_sol"] = round(row["net_pnl_sol"], 6)
        row["cost_sol"] = round(row["cost_sol"], 6)

    equity = compute_current_equity(cash_sol, open_positions)
    initial_capital_sol = _safe_float(initial_capital_sol, 0.0)
    return {
        "initial_capital_sol": round(initial_capital_sol, 6),
        "cash_sol": round(_safe_float(cash_sol), 6),
        "equity_sol": round(equity, 6),
        "open_positions": len(open_positions or {}),
        "closed_trades": total_trades,
        "win_rate_pct": round((len(wins) / total_trades * 100.0), 2) if total_trades > 0 else 0.0,
        "total_net_pnl_sol": round(total_net, 6),
        "total_cost_sol": round(total_cost, 6),
        "roi_pct": round(((equity - initial_capital_sol) / initial_capital_sol * 100.0), 2) if initial_capital_sol > 0 else 0.0,
        "max_drawdown_pct": round(max_dd * 100.0, 2),
        "by_strategy": by_strategy,
    }


def build_portfolio_projection(
    *,
    initial_capital_sol: float,
    positions_ledger: list[Dict[str, Any]],
    cash_ledger: list[Dict[str, Any]],
    trade_closes: list[Dict[str, Any]],
    mark_prices: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    cash_sol = _safe_float(initial_capital_sol, 0.0)
    if cash_ledger:
        cash_sol = _safe_float(cash_ledger[-1].get("balance_after_sol"), cash_sol)

    latest_positions: Dict[str, Dict[str, Any]] = {}
    for row in positions_ledger:
        latest_positions[str(row.get("position_id") or "")] = {
            "position_id": str(row.get("position_id") or ""),
            "ca": str(row.get("ca") or ""),
            "qty_after": _safe_float(row.get("qty_after"), 0.0),
            "invested_sol_after": _safe_float(row.get("invested_sol_after"), 0.0),
            "realized_pnl_sol_after": _safe_float(row.get("realized_pnl_sol_after"), 0.0),
            "avg_entry_price_after": _safe_float(row.get("avg_entry_price_after"), 0.0),
        }

    positions_by_ca: Dict[str, Dict[str, Any]] = {}
    for row in latest_positions.values():
        if row["qty_after"] <= 1e-12:
            continue
        positions_by_ca[row["ca"]] = row

    mark_prices = mark_prices or {}
    equity_sol = cash_sol
    for ca, row in positions_by_ca.items():
        px = _safe_float(mark_prices.get(ca), row.get("avg_entry_price_after"))
        equity_sol += _safe_float(row.get("qty_after"), 0.0) * px

    total_realized_pnl_sol = sum(_safe_float(row.get("realized_pnl_sol"), 0.0) for row in (trade_closes or []))
    return {
        "cash_sol": cash_sol,
        "equity_sol": equity_sol,
        "closed_trades": len(trade_closes or []),
        "total_realized_pnl_sol": total_realized_pnl_sol,
        "positions": positions_by_ca,
    }
