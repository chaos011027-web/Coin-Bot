import os
import json
import time
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple

from modules.execution_event_logger import log_execution_event_sync
from modules.paper_ledger_accounting import (
    build_final_close_settlement,
    build_open_settlement,
    build_partial_close_settlement,
    compute_current_equity,
    compute_portfolio_summary,
)
from modules.paper_ledger_service import (
    record_paper_final_close_sync,
    record_paper_open_fill_sync,
    record_paper_partial_close_sync,
)
from modules.strategy_state import ExecutionEventType, StrategyAction, StrategySignalState


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except Exception:
        return default


@dataclass
class ClosedLeg:
    ca: str
    symbol: str
    strategy: str
    opened_at: float
    closed_at: float
    entry_price: float
    exit_price: float
    entry_mcap: float
    exit_mcap: float
    qty: float
    invested_sol: float
    gross_exit_sol: float
    total_cost_sol: float
    net_pnl_sol: float
    net_return_pct: float
    exit_reason: str
    partial: bool = False
    partial_ratio: float = 1.0


class PaperPortfolioEngine:
    """
    1 SOL 纸面资金组合回测引擎（最小可用版）

    目标：
    1. 单账户、固定本金（默认 1 SOL）
    2. 每个策略分配不同 SOL 头寸
    3. 兼容当前系统“一币一仓位”的现实
    4. 支持部分止盈，用来评估“单次交易如何吃到更多”
    5. 把手续费 / 滑点 / 固定成本纳入净收益
    """

    def __init__(
        self,
        initial_capital_sol: float = 1.0,
        reserve_cash_sol: float = 0.25,
        max_open_positions: int = 3,
        fee_rate_per_side: float = 0.0030,
        slippage_rate_per_side: float = 0.0040,
        fixed_cost_per_order_sol: float = 0.00001,
        state_file: str = "data/paper_portfolio_state.json",
    ):
        self.initial_capital_sol = float(initial_capital_sol)
        self.reserve_cash_sol = float(reserve_cash_sol)
        self.max_open_positions = int(max_open_positions)

        self.fee_rate_per_side = float(fee_rate_per_side)
        self.slippage_rate_per_side = float(slippage_rate_per_side)
        self.fixed_cost_per_order_sol = float(fixed_cost_per_order_sol)

        self.state_file = state_file

        self.cash_sol: float = self.initial_capital_sol
        self.open_positions: Dict[str, Dict[str, Any]] = {}
        self.closed_legs: List[Dict[str, Any]] = []

        self._load()

    # =========================
    # 持久化
    # =========================
    def _load(self) -> None:
        if not os.path.exists(self.state_file):
            return
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                raw = json.load(f)
            self.cash_sol = _safe_float(raw.get("cash_sol"), self.initial_capital_sol)
            self.open_positions = raw.get("open_positions", {}) or {}
            self.closed_legs = raw.get("closed_legs", []) or []
        except Exception:
            self.cash_sol = self.initial_capital_sol
            self.open_positions = {}
            self.closed_legs = []

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
        payload = {
            "cash_sol": self.cash_sol,
            "open_positions": self.open_positions,
            "closed_legs": self.closed_legs,
        }
        tmp = f"{self.state_file}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.state_file)

    def reset(self) -> None:
        self.cash_sol = self.initial_capital_sol
        self.open_positions = {}
        self.closed_legs = []
        self.save()

    # =========================
    # 仓位规则
    # =========================
    def _strategy_alloc_sol(self, strategy: str, entry_mcap: float = 0.0) -> float:
        """
        你让我来定每种策略买多少 SOL。
        这里给的是适合当前系统的小资金测试版：
        - MIXED: 0.08
        - SNIPER_PLAY: 0.12
        - SMART_TREND: 0.18
        - BUNDLE_CTRL: 0.06
        再根据市值做轻微缩放。
        """
        strategy = str(strategy or "MIXED").upper()

        base = {
            "MIXED": 0.08,
            "SNIPER_PLAY": 0.12,
            "SMART_TREND": 0.18,
            "BUNDLE_CTRL": 0.06,
        }.get(strategy, 0.08)

        mcap = _safe_float(entry_mcap, 0.0)
        if mcap > 0:
            if mcap < 8000:
                base *= 0.85
            elif mcap > 50000:
                base *= 1.05

        return round(base, 4)

    def _entry_cost_sol(self, alloc_sol: float) -> float:
        return alloc_sol * (self.fee_rate_per_side + self.slippage_rate_per_side) + self.fixed_cost_per_order_sol

    def _exit_cost_sol(self, gross_exit_sol: float) -> float:
        return gross_exit_sol * (self.fee_rate_per_side + self.slippage_rate_per_side) + self.fixed_cost_per_order_sol

    def can_open(self, ca: str) -> Tuple[bool, str]:
        if not ca:
            return False, "CA为空"
        if ca in self.open_positions:
            return False, "该币已有纸面持仓"
        if len(self.open_positions) >= self.max_open_positions:
            return False, "达到最大同时持仓数"
        if self.cash_sol <= self.reserve_cash_sol:
            return False, "低于保留现金"
        return True, "OK"

    # =========================
    # 开仓 / 标记 / 平仓
    # =========================
    def open_position(
        self,
        ca: str,
        symbol: str,
        strategy: str,
        entry_price: float,
        entry_mcap: float,
        opened_at: Optional[float] = None,
        order_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        ok, reason = self.can_open(ca)
        if not ok:
            return {"ok": False, "reason": reason}

        entry_price = _safe_float(entry_price, 0.0)
        if entry_price <= 0:
            return {"ok": False, "reason": "entry_price 无效"}

        alloc_sol = self._strategy_alloc_sol(strategy, entry_mcap)
        free_cap = max(0.0, self.cash_sol - self.reserve_cash_sol)
        alloc_sol = min(alloc_sol, free_cap)

        if alloc_sol <= 0:
            return {"ok": False, "reason": "可用现金不足"}

        entry_cost = self._entry_cost_sol(alloc_sol)
        if alloc_sol + entry_cost > self.cash_sol:
            alloc_sol = max(0.0, self.cash_sol - self.reserve_cash_sol - entry_cost)

        if alloc_sol <= 0:
            return {"ok": False, "reason": "扣除成本后无可用头寸"}

        cash_before = self.cash_sol
        settlement = build_open_settlement(
            cash_before=cash_before,
            alloc_sol=alloc_sol,
            entry_price=entry_price,
            entry_mcap=entry_mcap,
            fee_rate_per_side=self.fee_rate_per_side,
            slippage_rate_per_side=self.slippage_rate_per_side,
            fixed_cost_per_order_sol=self.fixed_cost_per_order_sol,
        )
        entry_cost = settlement.total_cost_sol
        now = opened_at or time.time()
        position_id = str(order_id or "")
        ledger_excluded = not bool(position_id)

        self.cash_sol = settlement.cash_after
        self.open_positions[ca] = {
            "ca": ca,
            "symbol": symbol or "UNK",
            "strategy": strategy or "MIXED",
            "opened_at": now,
            "entry_price": entry_price,
            "entry_mcap": _safe_float(entry_mcap, 0.0),
            "current_price": entry_price,
            "current_mcap": _safe_float(entry_mcap, 0.0),
            "qty": settlement.qty,
            "remaining_qty": settlement.qty,
            "invested_sol": alloc_sol,
            "entry_cost_sol": entry_cost,
            "realized_pnl_sol": 0.0,
            "realized_fee_sol": entry_cost,
            "peak_price": entry_price,
            "peak_mcap": _safe_float(entry_mcap, 0.0),
            "tp1_done": False,
            "tp2_done": False,
            "position_id": position_id,
            "ledger_excluded": ledger_excluded,
        }
        self.save()
        record_paper_open_fill_sync(
            ca=ca,
            symbol=str(symbol or "UNK"),
            strategy=str(strategy or "MIXED"),
            order_id=order_id,
            position_id=position_id,
            settlement=settlement,
        )
        log_execution_event_sync(
            ca,
            ExecutionEventType.PAPER_OPEN.value,
            action=StrategyAction.ENTER.value,
            signal_state=StrategySignalState.ENTERED.value,
            status="OPEN",
            source="paper_portfolio_engine.open_position",
            metadata={
                "strategy": strategy or "MIXED",
                "entry_price": entry_price,
                "entry_mcap": _safe_float(entry_mcap, 0.0),
                "allocated_sol": alloc_sol,
                "entry_cost_sol": entry_cost,
            },
        )

        return {
            "ok": True,
            "allocated_sol": round(alloc_sol, 6),
            "entry_cost_sol": round(entry_cost, 6),
            "qty": round(settlement.qty, 8),
            "cash_left_sol": round(self.cash_sol, 6),
        }

    def mark_price(self, ca: str, current_price: float, current_mcap: float = 0.0) -> None:
        pos = self.open_positions.get(ca)
        if not pos:
            return

        current_price = _safe_float(current_price, 0.0)
        current_mcap = _safe_float(current_mcap, 0.0)

        if current_price > 0:
            pos["current_price"] = current_price
            pos["peak_price"] = max(_safe_float(pos.get("peak_price"), current_price), current_price)
        if current_mcap > 0:
            pos["current_mcap"] = current_mcap
            pos["peak_mcap"] = max(_safe_float(pos.get("peak_mcap"), current_mcap), current_mcap)

    def partial_take_profit(
        self,
        ca: str,
        exit_price: float,
        exit_mcap: float,
        ratio: float,
        exit_reason: str,
        closed_at: Optional[float] = None,
        order_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        部分止盈：
        ratio 表示卖出剩余仓位的比例，如 0.4 / 0.5
        """
        pos = self.open_positions.get(ca)
        if not pos:
            return {"ok": False, "reason": "无持仓"}

        exit_price = _safe_float(exit_price, 0.0)
        exit_mcap = _safe_float(exit_mcap, 0.0)
        ratio = max(0.0, min(1.0, _safe_float(ratio, 0.0)))

        if exit_price <= 0 or ratio <= 0:
            return {"ok": False, "reason": "参数无效"}

        remaining_qty = _safe_float(pos.get("remaining_qty"), 0.0)
        if remaining_qty <= 0:
            return {"ok": False, "reason": "无剩余仓位"}

        sell_qty = remaining_qty * ratio
        if sell_qty <= 0:
            return {"ok": False, "reason": "卖出数量无效"}

        settlement = build_partial_close_settlement(
            position=pos,
            cash_before=self.cash_sol,
            exit_price=exit_price,
            exit_mcap=exit_mcap,
            ratio=ratio,
            fee_rate_per_side=self.fee_rate_per_side,
            slippage_rate_per_side=self.slippage_rate_per_side,
            fixed_cost_per_order_sol=self.fixed_cost_per_order_sol,
            closed_at=closed_at,
            exit_reason=exit_reason,
        )

        self.cash_sol = settlement.cash_after
        pos["remaining_qty"] = settlement.remaining_qty_after
        pos["realized_pnl_sol"] = settlement.realized_pnl_sol_after
        pos["realized_fee_sol"] = settlement.realized_fee_sol_after

        leg = ClosedLeg(
            ca=ca,
            symbol=str(pos.get("symbol") or "UNK"),
            strategy=str(pos.get("strategy") or "MIXED"),
            opened_at=settlement.opened_at,
            closed_at=settlement.closed_at,
            entry_price=_safe_float(pos.get("entry_price"), 0.0),
            exit_price=settlement.exit_price,
            entry_mcap=_safe_float(pos.get("entry_mcap"), 0.0),
            exit_mcap=settlement.exit_mcap,
            qty=settlement.sell_qty,
            invested_sol=settlement.allocated_invested_sol,
            gross_exit_sol=settlement.gross_exit_sol,
            total_cost_sol=settlement.total_cost_sol,
            net_pnl_sol=settlement.net_pnl_sol,
            net_return_pct=settlement.net_return_pct,
            exit_reason=exit_reason,
            partial=True,
            partial_ratio=ratio,
        )
        self.closed_legs.append(asdict(leg))

        if pos["remaining_qty"] <= 1e-12:
            self.open_positions.pop(ca, None)

        self.save()
        record_paper_partial_close_sync(
            ca=ca,
            symbol=str(pos.get("symbol") or "UNK"),
            strategy=str(pos.get("strategy") or "MIXED"),
            order_id=order_id,
            position_id=str(pos.get("position_id") or ""),
            settlement=settlement,
        )
        log_execution_event_sync(
            ca,
            ExecutionEventType.PAPER_TP.value,
            action=StrategyAction.REDUCE.value,
            signal_state=StrategySignalState.MANAGING.value,
            status="PARTIAL_TP",
            source="paper_portfolio_engine.partial_take_profit",
            metadata={
                "exit_price": exit_price,
                "exit_mcap": exit_mcap,
                "ratio": ratio,
                "exit_reason": exit_reason,
                "net_pnl_sol": settlement.net_pnl_sol,
            },
        )
        return {
            "ok": True,
            "partial": True,
            "net_pnl_sol": round(settlement.net_pnl_sol, 6),
            "net_return_pct": round(settlement.net_return_pct, 2),
            "cash_sol": round(self.cash_sol, 6),
            "remaining_qty": round(pos.get("remaining_qty", 0.0), 8) if ca in self.open_positions else 0.0,
        }

    def close_position(
        self,
        ca: str,
        exit_price: float,
        exit_mcap: float,
        exit_reason: str,
        closed_at: Optional[float] = None,
        order_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        pos = self.open_positions.get(ca)
        if not pos:
            return {"ok": False, "reason": "无持仓"}

        exit_price = _safe_float(exit_price, 0.0)
        exit_mcap = _safe_float(exit_mcap, 0.0)
        if exit_price <= 0:
            return {"ok": False, "reason": "exit_price 无效"}

        remaining_qty = _safe_float(pos.get("remaining_qty"), 0.0)
        if remaining_qty <= 0:
            self.open_positions.pop(ca, None)
            self.save()
            return {"ok": False, "reason": "剩余仓位为0"}

        settlement = build_final_close_settlement(
            position=pos,
            cash_before=self.cash_sol,
            exit_price=exit_price,
            exit_mcap=exit_mcap,
            fee_rate_per_side=self.fee_rate_per_side,
            slippage_rate_per_side=self.slippage_rate_per_side,
            fixed_cost_per_order_sol=self.fixed_cost_per_order_sol,
            closed_at=closed_at,
            exit_reason=exit_reason,
        )
        self.cash_sol = settlement.cash_after

        leg = ClosedLeg(
            ca=ca,
            symbol=str(pos.get("symbol") or "UNK"),
            strategy=str(pos.get("strategy") or "MIXED"),
            opened_at=settlement.opened_at,
            closed_at=settlement.closed_at,
            entry_price=_safe_float(pos.get("entry_price"), 0.0),
            exit_price=settlement.exit_price,
            entry_mcap=_safe_float(pos.get("entry_mcap"), 0.0),
            exit_mcap=settlement.exit_mcap,
            qty=settlement.sell_qty,
            invested_sol=settlement.allocated_invested_sol,
            gross_exit_sol=settlement.gross_exit_sol,
            total_cost_sol=settlement.total_cost_sol,
            net_pnl_sol=settlement.net_pnl_sol,
            net_return_pct=settlement.net_return_pct,
            exit_reason=exit_reason,
            partial=False,
            partial_ratio=1.0,
        )
        self.closed_legs.append(asdict(leg))
        position_id = str(pos.get("position_id") or "")
        self.open_positions.pop(ca, None)
        self.save()
        record_paper_final_close_sync(
            ca=ca,
            symbol=str(pos.get("symbol") or "UNK"),
            strategy=str(pos.get("strategy") or "MIXED"),
            order_id=order_id,
            position_id=position_id,
            settlement=settlement,
        )
        log_execution_event_sync(
            ca,
            ExecutionEventType.PAPER_CLOSE.value,
            action=StrategyAction.EXIT.value,
            signal_state=StrategySignalState.EXITED.value,
            status="CLOSED",
            source="paper_portfolio_engine.close_position",
            metadata={
                "exit_price": exit_price,
                "exit_mcap": exit_mcap,
                "exit_reason": exit_reason,
                "net_pnl_sol": settlement.net_pnl_sol,
                "net_return_pct": settlement.net_return_pct,
            },
        )

        return {
            "ok": True,
            "partial": False,
            "net_pnl_sol": round(settlement.net_pnl_sol, 6),
            "net_return_pct": round(settlement.net_return_pct, 2),
            "cash_sol": round(self.cash_sol, 6),
        }

    def _resolve_tp_stage(self, event_type: str, pos: Optional[Dict[str, Any]] = None) -> int:
        """
        将主流程里的阶段止盈事件名映射为 TP1 / TP2。
        兼容：
        - 止盈1 / 止盈2
        - TP1 / TP2
        - 第一止盈 / 第二止盈
        如果事件名不明确，则按仓位状态自动推断。
        """
        s = str(event_type or "").strip().upper()
        pos = pos or {}

        stage1_keys = ["止盈1", "TP1", "第一止盈", "FIRST_TP", "FIRST TP"]
        stage2_keys = ["止盈2", "TP2", "第二止盈", "SECOND_TP", "SECOND TP"]

        if any(k.upper() in s for k in stage1_keys):
            return 1
        if any(k.upper() in s for k in stage2_keys):
            return 2

        if not bool(pos.get("tp1_done", False)):
            return 1
        if not bool(pos.get("tp2_done", False)):
            return 2
        return 0

    def on_tp_event(
        self,
        ca: str,
        exit_price: float,
        exit_mcap: float,
        event_type: str,
        closed_at: Optional[float] = None,
        order_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        兼容 main.py 的阶段止盈接口。
        - TP1: 卖出剩余仓位的 40%
        - TP2: 卖出剩余仓位的 50%
        """
        pos = self.open_positions.get(ca)
        if not pos:
            return {"ok": False, "reason": "无持仓"}

        stage = self._resolve_tp_stage(event_type, pos)
        if stage == 1:
            if bool(pos.get("tp1_done", False)):
                return {"ok": False, "reason": "TP1 已执行"}
            ratio = 0.40
        elif stage == 2:
            if bool(pos.get("tp2_done", False)):
                return {"ok": False, "reason": "TP2 已执行"}
            ratio = 0.50
        else:
            return {"ok": False, "reason": "无法识别止盈阶段或止盈已完成"}

        ret = self.partial_take_profit(
            ca=ca,
            exit_price=exit_price,
            exit_mcap=exit_mcap,
            ratio=ratio,
            exit_reason=str(event_type or f"TP{stage}"),
            closed_at=closed_at,
            order_id=order_id,
        )

        if ret.get("ok"):
            pos2 = self.open_positions.get(ca)
            if pos2:
                if stage == 1:
                    pos2["tp1_done"] = True
                elif stage == 2:
                    pos2["tp2_done"] = True
                self.save()

            ret["tp_stage"] = stage
            ret["tp_ratio"] = ratio

        return ret

    def on_final_close(
        self,
        ca: str,
        exit_price: float,
        exit_mcap: float,
        reason: str = "FINAL_CLOSE",
        closed_at: Optional[float] = None,
        order_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        兼容 main.py 的最终平仓接口。
        """
        return self.close_position(
            ca=ca,
            exit_price=exit_price,
            exit_mcap=exit_mcap,
            exit_reason=str(reason or "FINAL_CLOSE"),
            closed_at=closed_at,
            order_id=order_id,
        )

    # =========================
    # 组合统计
    # =========================
    def current_equity(self, mark_prices: Optional[Dict[str, float]] = None) -> float:
        return compute_current_equity(self.cash_sol, self.open_positions, mark_prices)

    def summary(self) -> Dict[str, Any]:
        return compute_portfolio_summary(
            initial_capital_sol=self.initial_capital_sol,
            cash_sol=self.cash_sol,
            open_positions=self.open_positions,
            closed_legs=self.closed_legs,
        )

    # =========================
    # 最小离线回测
    # =========================
    def backtest_from_records(self, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        最小离线回测接口。
        传入的 records 每条至少包含：
        {
          "ca","symbol","strategy",
          "entry_price","entry_mcap","exit_price","exit_mcap",
          "opened_at","closed_at","exit_reason"
        }
        """
        self.reset()

        ordered = sorted(records, key=lambda x: _safe_float(x.get("opened_at"), 0.0))
        for r in ordered:
            open_ret = self.open_position(
                ca=str(r.get("ca") or "").strip(),
                symbol=str(r.get("symbol") or "UNK"),
                strategy=str(r.get("strategy") or "MIXED"),
                entry_price=_safe_float(r.get("entry_price"), 0.0),
                entry_mcap=_safe_float(r.get("entry_mcap"), 0.0),
                opened_at=_safe_float(r.get("opened_at"), time.time()),
            )
            if not open_ret.get("ok"):
                continue

            self.close_position(
                ca=str(r.get("ca") or "").strip(),
                exit_price=_safe_float(r.get("exit_price"), 0.0),
                exit_mcap=_safe_float(r.get("exit_mcap"), 0.0),
                exit_reason=str(r.get("exit_reason") or "BACKTEST_EXIT"),
                closed_at=_safe_float(r.get("closed_at"), time.time()),
            )

        return self.summary()


paper_portfolio_engine = PaperPortfolioEngine()
