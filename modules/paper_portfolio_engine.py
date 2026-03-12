import os
import json
import time
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple


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

        qty = alloc_sol / entry_price
        now = opened_at or time.time()

        self.cash_sol -= (alloc_sol + entry_cost)
        self.open_positions[ca] = {
            "ca": ca,
            "symbol": symbol or "UNK",
            "strategy": strategy or "MIXED",
            "opened_at": now,
            "entry_price": entry_price,
            "entry_mcap": _safe_float(entry_mcap, 0.0),
            "qty": qty,
            "remaining_qty": qty,
            "invested_sol": alloc_sol,
            "entry_cost_sol": entry_cost,
            "realized_pnl_sol": 0.0,
            "realized_fee_sol": entry_cost,
            "peak_price": entry_price,
            "peak_mcap": _safe_float(entry_mcap, 0.0),
            "tp1_done": False,
            "tp2_done": False,
        }
        self.save()

        return {
            "ok": True,
            "allocated_sol": round(alloc_sol, 6),
            "entry_cost_sol": round(entry_cost, 6),
            "qty": round(qty, 8),
            "cash_left_sol": round(self.cash_sol, 6),
        }

    def mark_price(self, ca: str, current_price: float, current_mcap: float = 0.0) -> None:
        pos = self.open_positions.get(ca)
        if not pos:
            return

        current_price = _safe_float(current_price, 0.0)
        current_mcap = _safe_float(current_mcap, 0.0)

        if current_price > 0:
            pos["peak_price"] = max(_safe_float(pos.get("peak_price"), current_price), current_price)
        if current_mcap > 0:
            pos["peak_mcap"] = max(_safe_float(pos.get("peak_mcap"), current_mcap), current_mcap)

    def partial_take_profit(
        self,
        ca: str,
        exit_price: float,
        exit_mcap: float,
        ratio: float,
        exit_reason: str,
        closed_at: Optional[float] = None,
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

        gross_exit_sol = sell_qty * exit_price
        exit_cost = self._exit_cost_sol(gross_exit_sol)

        total_qty = _safe_float(pos.get("qty"), 0.0)
        invested_sol = _safe_float(pos.get("invested_sol"), 0.0)
        allocated_invest_cost = invested_sol * (sell_qty / total_qty) if total_qty > 0 else 0.0

        net_pnl_sol = gross_exit_sol - exit_cost - allocated_invest_cost
        net_return_pct = (net_pnl_sol / allocated_invest_cost * 100.0) if allocated_invest_cost > 0 else 0.0

        self.cash_sol += max(0.0, gross_exit_sol - exit_cost)
        pos["remaining_qty"] = max(0.0, remaining_qty - sell_qty)
        pos["realized_pnl_sol"] = _safe_float(pos.get("realized_pnl_sol"), 0.0) + net_pnl_sol
        pos["realized_fee_sol"] = _safe_float(pos.get("realized_fee_sol"), 0.0) + exit_cost

        leg = ClosedLeg(
            ca=ca,
            symbol=str(pos.get("symbol") or "UNK"),
            strategy=str(pos.get("strategy") or "MIXED"),
            opened_at=_safe_float(pos.get("opened_at"), time.time()),
            closed_at=closed_at or time.time(),
            entry_price=_safe_float(pos.get("entry_price"), 0.0),
            exit_price=exit_price,
            entry_mcap=_safe_float(pos.get("entry_mcap"), 0.0),
            exit_mcap=exit_mcap,
            qty=sell_qty,
            invested_sol=allocated_invest_cost,
            gross_exit_sol=gross_exit_sol,
            total_cost_sol=exit_cost,
            net_pnl_sol=net_pnl_sol,
            net_return_pct=net_return_pct,
            exit_reason=exit_reason,
            partial=True,
            partial_ratio=ratio,
        )
        self.closed_legs.append(asdict(leg))

        if pos["remaining_qty"] <= 1e-12:
            self.open_positions.pop(ca, None)

        self.save()
        return {
            "ok": True,
            "partial": True,
            "net_pnl_sol": round(net_pnl_sol, 6),
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

        gross_exit_sol = remaining_qty * exit_price
        exit_cost = self._exit_cost_sol(gross_exit_sol)

        total_qty = _safe_float(pos.get("qty"), 0.0)
        invested_sol = _safe_float(pos.get("invested_sol"), 0.0)
        allocated_invest_sol = invested_sol * (remaining_qty / total_qty) if total_qty > 0 else 0.0

        net_pnl_sol = gross_exit_sol - exit_cost - allocated_invest_sol
        net_return_pct = (net_pnl_sol / allocated_invest_sol * 100.0) if allocated_invest_sol > 0 else 0.0

        self.cash_sol += max(0.0, gross_exit_sol - exit_cost)

        leg = ClosedLeg(
            ca=ca,
            symbol=str(pos.get("symbol") or "UNK"),
            strategy=str(pos.get("strategy") or "MIXED"),
            opened_at=_safe_float(pos.get("opened_at"), time.time()),
            closed_at=closed_at or time.time(),
            entry_price=_safe_float(pos.get("entry_price"), 0.0),
            exit_price=exit_price,
            entry_mcap=_safe_float(pos.get("entry_mcap"), 0.0),
            exit_mcap=exit_mcap,
            qty=remaining_qty,
            invested_sol=allocated_invest_sol,
            gross_exit_sol=gross_exit_sol,
            total_cost_sol=exit_cost,
            net_pnl_sol=net_pnl_sol,
            net_return_pct=net_return_pct,
            exit_reason=exit_reason,
            partial=False,
            partial_ratio=1.0,
        )
        self.closed_legs.append(asdict(leg))
        self.open_positions.pop(ca, None)
        self.save()

        return {
            "ok": True,
            "partial": False,
            "net_pnl_sol": round(net_pnl_sol, 6),
            "net_return_pct": round(net_return_pct, 2),
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
        )

    # =========================
    # 组合统计
    # =========================
    def current_equity(self, mark_prices: Optional[Dict[str, float]] = None) -> float:
        total = self.cash_sol
        mark_prices = mark_prices or {}

        for ca, pos in self.open_positions.items():
            px = _safe_float(mark_prices.get(ca), _safe_float(pos.get("entry_price"), 0.0))
            qty = _safe_float(pos.get("remaining_qty"), 0.0)
            total += qty * px

        return total

    def summary(self) -> Dict[str, Any]:
        trades = self.closed_legs
        total_trades = len(trades)

        wins = [t for t in trades if _safe_float(t.get("net_pnl_sol"), 0.0) > 0]
        losses = [t for t in trades if _safe_float(t.get("net_pnl_sol"), 0.0) <= 0]

        total_net = sum(_safe_float(t.get("net_pnl_sol"), 0.0) for t in trades)
        total_cost = sum(_safe_float(t.get("total_cost_sol"), 0.0) for t in trades)

        running = self.initial_capital_sol
        peak = running
        max_dd = 0.0

        ordered = sorted(trades, key=lambda x: _safe_float(x.get("closed_at"), 0.0))
        for t in ordered:
            running += _safe_float(t.get("net_pnl_sol"), 0.0)
            if running > peak:
                peak = running
            dd = (peak - running) / peak if peak > 0 else 0.0
            max_dd = max(max_dd, dd)

        by_strategy: Dict[str, Dict[str, Any]] = {}
        for t in ordered:
            strategy = str(t.get("strategy") or "MIXED")
            row = by_strategy.setdefault(
                strategy,
                {"trades": 0, "wins": 0, "net_pnl_sol": 0.0, "cost_sol": 0.0}
            )
            row["trades"] += 1
            pnl = _safe_float(t.get("net_pnl_sol"), 0.0)
            row["net_pnl_sol"] += pnl
            row["cost_sol"] += _safe_float(t.get("total_cost_sol"), 0.0)
            if pnl > 0:
                row["wins"] += 1

        for strategy, row in by_strategy.items():
            row["win_rate_pct"] = round((row["wins"] / row["trades"] * 100.0), 2) if row["trades"] > 0 else 0.0
            row["net_pnl_sol"] = round(row["net_pnl_sol"], 6)
            row["cost_sol"] = round(row["cost_sol"], 6)

        equity = self.current_equity()

        return {
            "initial_capital_sol": round(self.initial_capital_sol, 6),
            "cash_sol": round(self.cash_sol, 6),
            "equity_sol": round(equity, 6),
            "open_positions": len(self.open_positions),
            "closed_trades": total_trades,
            "win_rate_pct": round((len(wins) / total_trades * 100.0), 2) if total_trades > 0 else 0.0,
            "total_net_pnl_sol": round(total_net, 6),
            "total_cost_sol": round(total_cost, 6),
            "roi_pct": round(((equity - self.initial_capital_sol) / self.initial_capital_sol * 100.0), 2) if self.initial_capital_sol > 0 else 0.0,
            "max_drawdown_pct": round(max_dd * 100.0, 2),
            "by_strategy": by_strategy,
        }

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