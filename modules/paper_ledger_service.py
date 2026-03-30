from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional
from uuid import uuid4

from modules.lifecycle_models import LifecycleContext
from modules.paper_ledger_accounting import build_portfolio_projection
from modules.paper_ledger_models import (
    FinalCloseSettlement,
    OpenSettlement,
    PaperCashLedgerRecord,
    PaperLedgerFillRecord,
    PaperLedgerOrderRecord,
    PaperPositionLedgerRecord,
    PaperTradeCloseRecord,
    PartialCloseSettlement,
)
from modules.paper_ledger_repository import paper_ledger_repository
from modules.strategy_state import get_current_lifecycle_context

logger = logging.getLogger("PaperLedgerService")


def _default_repository(repository):
    return repository or paper_ledger_repository


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _current_context(context: Optional[LifecycleContext] = None) -> LifecycleContext:
    return context or get_current_lifecycle_context() or LifecycleContext()


def _merged_metadata(ctx: LifecycleContext, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload = dict(ctx.metadata or {})
    payload.update(dict(metadata or {}))
    return payload


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def _skip_ledger(ctx: LifecycleContext) -> bool:
    return bool(ctx.legacy_path)


async def create_paper_order(
    *,
    ca: str,
    side: str,
    intent: str,
    requested_qty: Optional[float] = None,
    requested_notional_sol: Optional[float] = None,
    requested_price: Optional[float] = None,
    strategy_id: str = "",
    position_id: Optional[str] = None,
    reason: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    repository=None,
    context: Optional[LifecycleContext] = None,
) -> Optional[str]:
    ctx = _current_context(context)
    if _skip_ledger(ctx):
        return None

    order_id = _new_id("ord")
    record = PaperLedgerOrderRecord(
        order_id=order_id,
        ca=_safe_text(ca),
        position_id=_safe_text(position_id) or order_id,
        side=_safe_text(side),
        intent=_safe_text(intent),
        requested_qty=requested_qty,
        requested_notional_sol=requested_notional_sol,
        requested_price=requested_price,
        strategy_id=_safe_text(strategy_id),
        source=_safe_text(ctx.source),
        path_kind=_safe_text(ctx.path_kind),
        analysis_run_id=ctx.analysis_run_id,
        legacy_path=bool(ctx.legacy_path),
        reason=_safe_text(reason),
        metadata=_merged_metadata(ctx, metadata),
    )
    repo = _default_repository(repository)
    try:
        await repo.append_order(record)
        return order_id
    except Exception as exc:
        logger.warning("paper order append failed | ca=%s | err=%s", ca, exc, exc_info=True)
        return None


async def _record_open_fill(
    *,
    ca: str,
    symbol: str,
    strategy: str,
    order_id: str,
    position_id: str,
    settlement: OpenSettlement,
    repository=None,
    context: Optional[LifecycleContext] = None,
) -> bool:
    ctx = _current_context(context)
    if _skip_ledger(ctx) or not order_id or not position_id:
        return False

    repo = _default_repository(repository)
    fill_id = _new_id("fill")
    payload = _merged_metadata(ctx, {"symbol": _safe_text(symbol), "strategy": _safe_text(strategy)})
    try:
        await repo.append_fill(
            PaperLedgerFillRecord(
                fill_id=fill_id,
                order_id=order_id,
                ca=_safe_text(ca),
                position_id=position_id,
                side="BUY",
                fill_qty=settlement.qty,
                fill_price=settlement.entry_price,
                gross_notional_sol=settlement.alloc_sol,
                fee_sol=settlement.fee_sol,
                slippage_sol=settlement.slippage_sol,
                fixed_cost_sol=settlement.fixed_cost_sol,
                total_cost_sol=settlement.total_cost_sol,
                source=_safe_text(ctx.source),
                path_kind=_safe_text(ctx.path_kind),
                analysis_run_id=ctx.analysis_run_id,
                legacy_path=bool(ctx.legacy_path),
                metadata=payload,
            )
        )
        await repo.append_position_event(
            PaperPositionLedgerRecord(
                position_event_id=_new_id("posevt"),
                position_id=position_id,
                order_id=order_id,
                fill_id=fill_id,
                ca=_safe_text(ca),
                event_type="OPENED",
                qty_delta=settlement.qty,
                qty_after=settlement.qty,
                invested_sol_after=settlement.alloc_sol,
                realized_pnl_sol_after=0.0,
                avg_entry_price_after=settlement.entry_price,
                source=_safe_text(ctx.source),
                path_kind=_safe_text(ctx.path_kind),
                analysis_run_id=ctx.analysis_run_id,
                legacy_path=bool(ctx.legacy_path),
                metadata=payload,
            )
        )
        await repo.append_cash_event(
            PaperCashLedgerRecord(
                cash_event_id=_new_id("cashevt"),
                ref_type="order",
                ref_id=order_id,
                ca=_safe_text(ca),
                position_id=position_id,
                event_type="OPEN_SETTLED",
                delta_sol=-(settlement.alloc_sol + settlement.total_cost_sol),
                balance_after_sol=settlement.cash_after,
                source=_safe_text(ctx.source),
                path_kind=_safe_text(ctx.path_kind),
                analysis_run_id=ctx.analysis_run_id,
                legacy_path=bool(ctx.legacy_path),
                metadata=payload,
            )
        )
        return True
    except Exception as exc:
        logger.warning("paper open settlement append failed | ca=%s | err=%s", ca, exc, exc_info=True)
        return False


async def _record_partial_close(
    *,
    ca: str,
    symbol: str,
    strategy: str,
    order_id: str,
    position_id: str,
    settlement: PartialCloseSettlement,
    repository=None,
    context: Optional[LifecycleContext] = None,
) -> bool:
    ctx = _current_context(context)
    if _skip_ledger(ctx) or not order_id or not position_id:
        return False

    repo = _default_repository(repository)
    fill_id = _new_id("fill")
    payload = _merged_metadata(
        ctx,
        {"symbol": _safe_text(symbol), "strategy": _safe_text(strategy), "close_reason": settlement.exit_reason},
    )
    try:
        await repo.append_fill(
            PaperLedgerFillRecord(
                fill_id=fill_id,
                order_id=order_id,
                ca=_safe_text(ca),
                position_id=position_id,
                side="SELL",
                fill_qty=settlement.sell_qty,
                fill_price=settlement.exit_price,
                gross_notional_sol=settlement.gross_exit_sol,
                fee_sol=settlement.fee_sol,
                slippage_sol=settlement.slippage_sol,
                fixed_cost_sol=settlement.fixed_cost_sol,
                total_cost_sol=settlement.total_cost_sol,
                source=_safe_text(ctx.source),
                path_kind=_safe_text(ctx.path_kind),
                analysis_run_id=ctx.analysis_run_id,
                legacy_path=bool(ctx.legacy_path),
                metadata=payload,
            )
        )
        await repo.append_position_event(
            PaperPositionLedgerRecord(
                position_event_id=_new_id("posevt"),
                position_id=position_id,
                order_id=order_id,
                fill_id=fill_id,
                ca=_safe_text(ca),
                event_type="UPDATED",
                qty_delta=-settlement.sell_qty,
                qty_after=settlement.remaining_qty_after,
                invested_sol_after=settlement.invested_sol_after,
                realized_pnl_sol_after=settlement.realized_pnl_sol_after,
                avg_entry_price_after=settlement.avg_entry_price_after,
                source=_safe_text(ctx.source),
                path_kind=_safe_text(ctx.path_kind),
                analysis_run_id=ctx.analysis_run_id,
                legacy_path=bool(ctx.legacy_path),
                metadata=payload,
            )
        )
        await repo.append_cash_event(
            PaperCashLedgerRecord(
                cash_event_id=_new_id("cashevt"),
                ref_type="order",
                ref_id=order_id,
                ca=_safe_text(ca),
                position_id=position_id,
                event_type="REDUCE_SETTLED",
                delta_sol=settlement.cash_delta_sol,
                balance_after_sol=settlement.cash_after,
                source=_safe_text(ctx.source),
                path_kind=_safe_text(ctx.path_kind),
                analysis_run_id=ctx.analysis_run_id,
                legacy_path=bool(ctx.legacy_path),
                metadata=payload,
            )
        )
        await repo.append_trade_close(
            PaperTradeCloseRecord(
                trade_close_id=_new_id("close"),
                position_id=position_id,
                order_id=order_id,
                fill_id=fill_id,
                ca=_safe_text(ca),
                strategy=_safe_text(strategy),
                opened_at=settlement.opened_at,
                closed_at=settlement.closed_at,
                close_reason=settlement.exit_reason,
                partial=True,
                close_ratio=settlement.ratio,
                entry_notional_sol=settlement.allocated_invested_sol,
                exit_notional_sol=settlement.gross_exit_sol,
                total_fee_sol=settlement.total_cost_sol,
                realized_pnl_sol=settlement.net_pnl_sol,
                realized_return_pct=settlement.net_return_pct,
                source=_safe_text(ctx.source),
                path_kind=_safe_text(ctx.path_kind),
                analysis_run_id=ctx.analysis_run_id,
                legacy_path=bool(ctx.legacy_path),
                metadata=payload,
            )
        )
        return True
    except Exception as exc:
        logger.warning("paper partial close append failed | ca=%s | err=%s", ca, exc, exc_info=True)
        return False


async def _record_final_close(
    *,
    ca: str,
    symbol: str,
    strategy: str,
    order_id: str,
    position_id: str,
    settlement: FinalCloseSettlement,
    repository=None,
    context: Optional[LifecycleContext] = None,
) -> bool:
    ctx = _current_context(context)
    if _skip_ledger(ctx) or not order_id or not position_id:
        return False

    repo = _default_repository(repository)
    fill_id = _new_id("fill")
    payload = _merged_metadata(
        ctx,
        {"symbol": _safe_text(symbol), "strategy": _safe_text(strategy), "close_reason": settlement.exit_reason},
    )
    try:
        await repo.append_fill(
            PaperLedgerFillRecord(
                fill_id=fill_id,
                order_id=order_id,
                ca=_safe_text(ca),
                position_id=position_id,
                side="SELL",
                fill_qty=settlement.sell_qty,
                fill_price=settlement.exit_price,
                gross_notional_sol=settlement.gross_exit_sol,
                fee_sol=settlement.fee_sol,
                slippage_sol=settlement.slippage_sol,
                fixed_cost_sol=settlement.fixed_cost_sol,
                total_cost_sol=settlement.total_cost_sol,
                source=_safe_text(ctx.source),
                path_kind=_safe_text(ctx.path_kind),
                analysis_run_id=ctx.analysis_run_id,
                legacy_path=bool(ctx.legacy_path),
                metadata=payload,
            )
        )
        await repo.append_position_event(
            PaperPositionLedgerRecord(
                position_event_id=_new_id("posevt"),
                position_id=position_id,
                order_id=order_id,
                fill_id=fill_id,
                ca=_safe_text(ca),
                event_type="CLOSED",
                qty_delta=-settlement.sell_qty,
                qty_after=0.0,
                invested_sol_after=0.0,
                realized_pnl_sol_after=settlement.realized_pnl_sol_after,
                avg_entry_price_after=0.0,
                source=_safe_text(ctx.source),
                path_kind=_safe_text(ctx.path_kind),
                analysis_run_id=ctx.analysis_run_id,
                legacy_path=bool(ctx.legacy_path),
                metadata=payload,
            )
        )
        await repo.append_cash_event(
            PaperCashLedgerRecord(
                cash_event_id=_new_id("cashevt"),
                ref_type="order",
                ref_id=order_id,
                ca=_safe_text(ca),
                position_id=position_id,
                event_type="CLOSE_SETTLED",
                delta_sol=settlement.cash_delta_sol,
                balance_after_sol=settlement.cash_after,
                source=_safe_text(ctx.source),
                path_kind=_safe_text(ctx.path_kind),
                analysis_run_id=ctx.analysis_run_id,
                legacy_path=bool(ctx.legacy_path),
                metadata=payload,
            )
        )
        await repo.append_trade_close(
            PaperTradeCloseRecord(
                trade_close_id=_new_id("close"),
                position_id=position_id,
                order_id=order_id,
                fill_id=fill_id,
                ca=_safe_text(ca),
                strategy=_safe_text(strategy),
                opened_at=settlement.opened_at,
                closed_at=settlement.closed_at,
                close_reason=settlement.exit_reason,
                partial=False,
                close_ratio=1.0,
                entry_notional_sol=settlement.allocated_invested_sol,
                exit_notional_sol=settlement.gross_exit_sol,
                total_fee_sol=settlement.total_cost_sol,
                realized_pnl_sol=settlement.net_pnl_sol,
                realized_return_pct=settlement.net_return_pct,
                source=_safe_text(ctx.source),
                path_kind=_safe_text(ctx.path_kind),
                analysis_run_id=ctx.analysis_run_id,
                legacy_path=bool(ctx.legacy_path),
                metadata=payload,
            )
        )
        return True
    except Exception as exc:
        logger.warning("paper final close append failed | ca=%s | err=%s", ca, exc, exc_info=True)
        return False


def record_paper_open_fill_sync(
    *,
    ca: str,
    symbol: str,
    strategy: str,
    order_id: Optional[str],
    position_id: Optional[str],
    settlement: OpenSettlement,
    repository=None,
    context: Optional[LifecycleContext] = None,
) -> None:
    ctx = _current_context(context)
    if _skip_ledger(ctx) or not order_id or not position_id:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(
        _record_open_fill(
            ca=ca,
            symbol=symbol,
            strategy=strategy,
            order_id=_safe_text(order_id),
            position_id=_safe_text(position_id),
            settlement=settlement,
            repository=repository,
            context=ctx,
        )
    )


def record_paper_partial_close_sync(
    *,
    ca: str,
    symbol: str,
    strategy: str,
    order_id: Optional[str],
    position_id: Optional[str],
    settlement: PartialCloseSettlement,
    repository=None,
    context: Optional[LifecycleContext] = None,
) -> None:
    ctx = _current_context(context)
    if _skip_ledger(ctx) or not order_id or not position_id:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(
        _record_partial_close(
            ca=ca,
            symbol=symbol,
            strategy=strategy,
            order_id=_safe_text(order_id),
            position_id=_safe_text(position_id),
            settlement=settlement,
            repository=repository,
            context=ctx,
        )
    )


def record_paper_final_close_sync(
    *,
    ca: str,
    symbol: str,
    strategy: str,
    order_id: Optional[str],
    position_id: Optional[str],
    settlement: FinalCloseSettlement,
    repository=None,
    context: Optional[LifecycleContext] = None,
) -> None:
    ctx = _current_context(context)
    if _skip_ledger(ctx) or not order_id or not position_id:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(
        _record_final_close(
            ca=ca,
            symbol=symbol,
            strategy=strategy,
            order_id=_safe_text(order_id),
            position_id=_safe_text(position_id),
            settlement=settlement,
            repository=repository,
            context=ctx,
        )
    )


def build_paper_ledger_projection(
    *,
    initial_capital_sol: float,
    repository=None,
    mark_prices: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    repo = _default_repository(repository)
    if not all(hasattr(repo, attr) for attr in ("positions_ledger", "cash_ledger", "trade_closes")):
        raise RuntimeError("paper ledger projection requires an in-memory repository")
    return build_portfolio_projection(
        initial_capital_sol=initial_capital_sol,
        positions_ledger=list(getattr(repo, "positions_ledger", []) or []),
        cash_ledger=list(getattr(repo, "cash_ledger", []) or []),
        trade_closes=list(getattr(repo, "trade_closes", []) or []),
        mark_prices=mark_prices or {},
    )
