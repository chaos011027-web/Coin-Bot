from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class PaperLedgerOrderRecord:
    order_id: str
    ca: str
    position_id: str
    side: str
    intent: str
    requested_qty: Optional[float] = None
    requested_notional_sol: Optional[float] = None
    requested_price: Optional[float] = None
    strategy_id: str = ""
    source: str = ""
    path_kind: str = ""
    analysis_run_id: Optional[int] = None
    legacy_path: bool = False
    reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PaperLedgerFillRecord:
    fill_id: str
    order_id: str
    ca: str
    position_id: str
    side: str
    fill_qty: float
    fill_price: float
    gross_notional_sol: float
    fee_sol: float
    slippage_sol: float
    fixed_cost_sol: float
    total_cost_sol: float
    source: str = ""
    path_kind: str = ""
    analysis_run_id: Optional[int] = None
    legacy_path: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PaperPositionLedgerRecord:
    position_event_id: str
    position_id: str
    order_id: str
    fill_id: str
    ca: str
    event_type: str
    qty_delta: float
    qty_after: float
    invested_sol_after: float
    realized_pnl_sol_after: float
    avg_entry_price_after: float
    source: str = ""
    path_kind: str = ""
    analysis_run_id: Optional[int] = None
    legacy_path: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PaperCashLedgerRecord:
    cash_event_id: str
    ref_type: str
    ref_id: str
    ca: str
    position_id: str
    event_type: str
    delta_sol: float
    balance_after_sol: float
    source: str = ""
    path_kind: str = ""
    analysis_run_id: Optional[int] = None
    legacy_path: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PaperTradeCloseRecord:
    trade_close_id: str
    position_id: str
    order_id: str
    fill_id: str
    ca: str
    strategy: str
    opened_at: float
    closed_at: float
    close_reason: str
    partial: bool
    close_ratio: float
    entry_notional_sol: float
    exit_notional_sol: float
    total_fee_sol: float
    realized_pnl_sol: float
    realized_return_pct: float
    source: str = ""
    path_kind: str = ""
    analysis_run_id: Optional[int] = None
    legacy_path: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OpenSettlement:
    alloc_sol: float
    qty: float
    fee_sol: float
    slippage_sol: float
    fixed_cost_sol: float
    total_cost_sol: float
    cash_after: float
    entry_price: float
    entry_mcap: float


@dataclass(frozen=True)
class PartialCloseSettlement:
    sell_qty: float
    gross_exit_sol: float
    fee_sol: float
    slippage_sol: float
    fixed_cost_sol: float
    total_cost_sol: float
    allocated_invested_sol: float
    net_pnl_sol: float
    net_return_pct: float
    cash_delta_sol: float
    cash_after: float
    remaining_qty_after: float
    invested_sol_after: float
    realized_pnl_sol_after: float
    realized_fee_sol_after: float
    avg_entry_price_after: float
    exit_price: float
    exit_mcap: float
    opened_at: float
    closed_at: float
    exit_reason: str
    ratio: float


@dataclass(frozen=True)
class FinalCloseSettlement:
    sell_qty: float
    gross_exit_sol: float
    fee_sol: float
    slippage_sol: float
    fixed_cost_sol: float
    total_cost_sol: float
    allocated_invested_sol: float
    net_pnl_sol: float
    realized_pnl_sol_after: float
    net_return_pct: float
    cash_delta_sol: float
    cash_after: float
    exit_price: float
    exit_mcap: float
    opened_at: float
    closed_at: float
    exit_reason: str
