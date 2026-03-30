from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from modules.database import db
from modules.db_schema import (
    PAPER_CASH_LEDGER_TABLE,
    PAPER_FILLS_TABLE,
    PAPER_ORDERS_TABLE,
    PAPER_POSITIONS_LEDGER_TABLE,
    PAPER_TRADE_CLOSES_TABLE,
)
from modules.paper_ledger_models import (
    PaperCashLedgerRecord,
    PaperLedgerFillRecord,
    PaperLedgerOrderRecord,
    PaperPositionLedgerRecord,
    PaperTradeCloseRecord,
)


def _json_payload(value: Any) -> Optional[str]:
    if value is None:
        return None
    return json.dumps(value)


class DatabasePaperLedgerRepository:
    async def append_order(self, record: PaperLedgerOrderRecord) -> None:
        await db.execute(
            f"""
            INSERT INTO {PAPER_ORDERS_TABLE}
            (
                order_id, analysis_run_id, ca, position_id, side, intent,
                requested_qty, requested_notional_sol, requested_price, strategy_id,
                source, path_kind, legacy_path, reason, metadata
            )
            VALUES
            (
                $1, $2, $3, $4, $5, $6,
                $7, $8, $9, $10,
                $11, $12, $13, $14, $15::jsonb
            )
            """,
            record.order_id,
            record.analysis_run_id,
            record.ca,
            record.position_id,
            record.side,
            record.intent,
            record.requested_qty,
            record.requested_notional_sol,
            record.requested_price,
            record.strategy_id,
            record.source,
            record.path_kind,
            bool(record.legacy_path),
            record.reason,
            _json_payload(record.metadata or {}),
        )

    async def append_fill(self, record: PaperLedgerFillRecord) -> None:
        await db.execute(
            f"""
            INSERT INTO {PAPER_FILLS_TABLE}
            (
                fill_id, order_id, analysis_run_id, ca, position_id, side,
                fill_qty, fill_price, gross_notional_sol, fee_sol,
                slippage_sol, fixed_cost_sol, total_cost_sol,
                source, path_kind, legacy_path, metadata
            )
            VALUES
            (
                $1, $2, $3, $4, $5, $6,
                $7, $8, $9, $10,
                $11, $12, $13,
                $14, $15, $16, $17::jsonb
            )
            """,
            record.fill_id,
            record.order_id,
            record.analysis_run_id,
            record.ca,
            record.position_id,
            record.side,
            record.fill_qty,
            record.fill_price,
            record.gross_notional_sol,
            record.fee_sol,
            record.slippage_sol,
            record.fixed_cost_sol,
            record.total_cost_sol,
            record.source,
            record.path_kind,
            bool(record.legacy_path),
            _json_payload(record.metadata or {}),
        )

    async def append_position_event(self, record: PaperPositionLedgerRecord) -> None:
        await db.execute(
            f"""
            INSERT INTO {PAPER_POSITIONS_LEDGER_TABLE}
            (
                position_event_id, position_id, order_id, fill_id, analysis_run_id, ca,
                event_type, qty_delta, qty_after, invested_sol_after,
                realized_pnl_sol_after, avg_entry_price_after,
                source, path_kind, legacy_path, metadata
            )
            VALUES
            (
                $1, $2, $3, $4, $5, $6,
                $7, $8, $9, $10,
                $11, $12,
                $13, $14, $15, $16::jsonb
            )
            """,
            record.position_event_id,
            record.position_id,
            record.order_id,
            record.fill_id,
            record.analysis_run_id,
            record.ca,
            record.event_type,
            record.qty_delta,
            record.qty_after,
            record.invested_sol_after,
            record.realized_pnl_sol_after,
            record.avg_entry_price_after,
            record.source,
            record.path_kind,
            bool(record.legacy_path),
            _json_payload(record.metadata or {}),
        )

    async def append_cash_event(self, record: PaperCashLedgerRecord) -> None:
        await db.execute(
            f"""
            INSERT INTO {PAPER_CASH_LEDGER_TABLE}
            (
                cash_event_id, ref_type, ref_id, analysis_run_id, ca, position_id,
                event_type, delta_sol, balance_after_sol,
                source, path_kind, legacy_path, metadata
            )
            VALUES
            (
                $1, $2, $3, $4, $5, $6,
                $7, $8, $9,
                $10, $11, $12, $13::jsonb
            )
            """,
            record.cash_event_id,
            record.ref_type,
            record.ref_id,
            record.analysis_run_id,
            record.ca,
            record.position_id,
            record.event_type,
            record.delta_sol,
            record.balance_after_sol,
            record.source,
            record.path_kind,
            bool(record.legacy_path),
            _json_payload(record.metadata or {}),
        )

    async def append_trade_close(self, record: PaperTradeCloseRecord) -> None:
        await db.execute(
            f"""
            INSERT INTO {PAPER_TRADE_CLOSES_TABLE}
            (
                trade_close_id, position_id, order_id, fill_id, analysis_run_id, ca,
                strategy, opened_at, closed_at, close_reason,
                partial, close_ratio, entry_notional_sol, exit_notional_sol,
                total_fee_sol, realized_pnl_sol, realized_return_pct,
                source, path_kind, legacy_path, metadata
            )
            VALUES
            (
                $1, $2, $3, $4, $5, $6,
                $7, $8, $9, $10,
                $11, $12, $13, $14,
                $15, $16, $17,
                $18, $19, $20, $21::jsonb
            )
            """,
            record.trade_close_id,
            record.position_id,
            record.order_id,
            record.fill_id,
            record.analysis_run_id,
            record.ca,
            record.strategy,
            record.opened_at,
            record.closed_at,
            record.close_reason,
            bool(record.partial),
            record.close_ratio,
            record.entry_notional_sol,
            record.exit_notional_sol,
            record.total_fee_sol,
            record.realized_pnl_sol,
            record.realized_return_pct,
            record.source,
            record.path_kind,
            bool(record.legacy_path),
            _json_payload(record.metadata or {}),
        )


class InMemoryPaperLedgerRepository:
    def __init__(self):
        self.orders: List[Dict[str, Any]] = []
        self.fills: List[Dict[str, Any]] = []
        self.positions_ledger: List[Dict[str, Any]] = []
        self.cash_ledger: List[Dict[str, Any]] = []
        self.trade_closes: List[Dict[str, Any]] = []

    async def append_order(self, record: PaperLedgerOrderRecord) -> None:
        self.orders.append(
            {
                "order_id": record.order_id,
                "analysis_run_id": record.analysis_run_id,
                "ca": record.ca,
                "position_id": record.position_id,
                "side": record.side,
                "intent": record.intent,
                "requested_qty": record.requested_qty,
                "requested_notional_sol": record.requested_notional_sol,
                "requested_price": record.requested_price,
                "strategy_id": record.strategy_id,
                "source": record.source,
                "path_kind": record.path_kind,
                "legacy_path": record.legacy_path,
                "reason": record.reason,
                "metadata": dict(record.metadata or {}),
            }
        )

    async def append_fill(self, record: PaperLedgerFillRecord) -> None:
        self.fills.append(
            {
                "fill_id": record.fill_id,
                "order_id": record.order_id,
                "analysis_run_id": record.analysis_run_id,
                "ca": record.ca,
                "position_id": record.position_id,
                "side": record.side,
                "fill_qty": record.fill_qty,
                "fill_price": record.fill_price,
                "gross_notional_sol": record.gross_notional_sol,
                "fee_sol": record.fee_sol,
                "slippage_sol": record.slippage_sol,
                "fixed_cost_sol": record.fixed_cost_sol,
                "total_cost_sol": record.total_cost_sol,
                "source": record.source,
                "path_kind": record.path_kind,
                "legacy_path": record.legacy_path,
                "metadata": dict(record.metadata or {}),
            }
        )

    async def append_position_event(self, record: PaperPositionLedgerRecord) -> None:
        self.positions_ledger.append(
            {
                "position_event_id": record.position_event_id,
                "position_id": record.position_id,
                "order_id": record.order_id,
                "fill_id": record.fill_id,
                "analysis_run_id": record.analysis_run_id,
                "ca": record.ca,
                "event_type": record.event_type,
                "qty_delta": record.qty_delta,
                "qty_after": record.qty_after,
                "invested_sol_after": record.invested_sol_after,
                "realized_pnl_sol_after": record.realized_pnl_sol_after,
                "avg_entry_price_after": record.avg_entry_price_after,
                "source": record.source,
                "path_kind": record.path_kind,
                "legacy_path": record.legacy_path,
                "metadata": dict(record.metadata or {}),
            }
        )

    async def append_cash_event(self, record: PaperCashLedgerRecord) -> None:
        self.cash_ledger.append(
            {
                "cash_event_id": record.cash_event_id,
                "ref_type": record.ref_type,
                "ref_id": record.ref_id,
                "analysis_run_id": record.analysis_run_id,
                "ca": record.ca,
                "position_id": record.position_id,
                "event_type": record.event_type,
                "delta_sol": record.delta_sol,
                "balance_after_sol": record.balance_after_sol,
                "source": record.source,
                "path_kind": record.path_kind,
                "legacy_path": record.legacy_path,
                "metadata": dict(record.metadata or {}),
            }
        )

    async def append_trade_close(self, record: PaperTradeCloseRecord) -> None:
        self.trade_closes.append(
            {
                "trade_close_id": record.trade_close_id,
                "position_id": record.position_id,
                "order_id": record.order_id,
                "fill_id": record.fill_id,
                "analysis_run_id": record.analysis_run_id,
                "ca": record.ca,
                "strategy": record.strategy,
                "opened_at": record.opened_at,
                "closed_at": record.closed_at,
                "close_reason": record.close_reason,
                "partial": record.partial,
                "close_ratio": record.close_ratio,
                "entry_notional_sol": record.entry_notional_sol,
                "exit_notional_sol": record.exit_notional_sol,
                "total_fee_sol": record.total_fee_sol,
                "realized_pnl_sol": record.realized_pnl_sol,
                "realized_return_pct": record.realized_return_pct,
                "source": record.source,
                "path_kind": record.path_kind,
                "legacy_path": record.legacy_path,
                "metadata": dict(record.metadata or {}),
            }
        )


paper_ledger_repository = DatabasePaperLedgerRepository()
