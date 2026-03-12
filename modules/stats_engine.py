import time
import json
import os
import asyncio
import aiofiles
import logging
from collections import defaultdict
from typing import Optional, Dict, List, Any

logger = logging.getLogger("StatsEngine")

FILE = "data/strategy_performance.json"
DAY = 86400


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except Exception:
        return default


class PerformanceEngine:
    """
    目标：
    1) 保持现有接口兼容，不破坏 position_engine / main.py 现有调用
    2) 异步非阻塞写盘
    3) 在原有 win_rate / total 基础上，补充 EV / PF / avg_pnl 等统计能力
    4) 为后续与 paper_portfolio_engine 联动提供更完整摘要
    """

    def __init__(self):
        self.data = defaultdict(list)
        self._lock = asyncio.Lock()
        self._save_task: Optional[asyncio.Task] = None
        self._load_sync()

    # =========================
    # load / save
    # =========================
    def _load_sync(self):
        if os.path.exists(FILE):
            try:
                with open(FILE, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                    if isinstance(raw, dict):
                        self.data = defaultdict(list, {k: v for k, v in raw.items()})
                    else:
                        self.data = defaultdict(list)
            except Exception as e:
                logger.error(f"加载统计数据失败: {e}")
                self.data = defaultdict(list)

    async def _save(self):
        os.makedirs("data", exist_ok=True)
        try:
            async with aiofiles.open(FILE, "w", encoding="utf-8") as f:
                await f.write(json.dumps(self.data, ensure_ascii=False, indent=2))
        except Exception as e:
            logger.error(f"保存统计数据失败: {e}")

    async def _save_debounced(self):
        """
        极轻量去抖，避免频繁写盘压垮事件循环
        """
        if self._save_task and not self._save_task.done():
            return

        async def _worker():
            try:
                await asyncio.sleep(0.15)
                await self._save()
            except Exception as e:
                logger.error(f"延迟保存统计数据失败: {e}")

        self._save_task = asyncio.create_task(_worker())

    # =========================
    # record
    # =========================
    async def record_trade(self, strategy: str, result_type: str, pnl_percent: float, ca: str = ""):
        """
        记录交易结果
        """
        async with self._lock:
            now = time.time()
            strategy = str(strategy or "DEFAULT").upper()

            record = {
                "time": now,
                "result": str(result_type or ""),
                "pnl": float(pnl_percent),
                "ca": str(ca or ""),
            }

            self.data[strategy].append(record)

            # 截断，防止无限增长
            if len(self.data[strategy]) > 2000:
                self.data[strategy] = self.data[strategy][-2000:]

            await self._save_debounced()
            logger.info(f"📊 记账成功 [{strategy}]: {result_type} ({pnl_percent}%)")

    def record(self, strategy: str, result_type: str, pnl_percent: float, ca: str = ""):
        """
        安全投递，保持兼容旧调用方式
        """
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.record_trade(strategy, result_type, pnl_percent, ca))
        except RuntimeError:
            logger.error(f"❌ StatsEngine.record 必须在事件循环中调用！丢失记录: {strategy}")

    # =========================
    # core stats
    # =========================
    def _calc_stats(self, records: List[dict], days: Optional[int] = None) -> Optional[dict]:
        if not records:
            return None

        subset = records
        if days is not None:
            cutoff = time.time() - days * DAY
            subset = [r for r in records if _safe_float(r.get("time"), 0.0) >= cutoff]

        if not subset:
            return None

        total_trades = len(subset)
        if total_trades == 0:
            return None

        pnls = [_safe_float(r.get("pnl"), 0.0) for r in subset]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        win_rate = len(wins) / total_trades
        total_gain = sum(wins)
        total_loss = abs(sum(losses))

        if total_loss > 0:
            profit_factor = total_gain / total_loss
        elif total_gain > 0:
            profit_factor = float("inf")
        else:
            profit_factor = 0.0

        avg_win = total_gain / len(wins) if wins else 0.0
        avg_loss = total_loss / len(losses) if losses else 0.0
        avg_pnl = sum(pnls) / total_trades if total_trades > 0 else 0.0
        ev = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)

        return {
            "trades": total_trades,
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(win_rate * 100, 1),
            "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else float("inf"),
            "ev_per_trade": round(ev, 2),
            "avg_pnl": round(avg_pnl, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "total_gain": round(total_gain, 2),
            "total_loss": round(total_loss, 2),
        }

    def get_raw_stats(self, strategy: str) -> dict:
        """
        保持兼容 position_engine.py 的老接口：
        - win_rate
        - total
        - is_new
        """
        strategy = str(strategy or "DEFAULT").upper()
        records = self.data.get(strategy, [])
        total = len(records)

        if total == 0:
            return {
                "win_rate": 0,
                "total": 0,
                "is_new": True,
                "avg_pnl": 0.0,
                "profit_factor": 0.0,
                "ev_per_trade": 0.0,
            }

        stats = self._calc_stats(records, days=None) or {}
        return {
            "win_rate": int(stats.get("win_rate", 0)),
            "total": total,
            "is_new": False,
            "avg_pnl": stats.get("avg_pnl", 0.0),
            "profit_factor": stats.get("profit_factor", 0.0),
            "ev_per_trade": stats.get("ev_per_trade", 0.0),
        }

    def get_tag(self, strategy: str) -> str:
        strategy = str(strategy or "DEFAULT").upper()
        stats = self.get_raw_stats(strategy)
        if stats["is_new"]:
            return "🆕 测试期"
        return f"🏆胜率{stats['win_rate']}%"

    def should_eliminate(self, strategy: str) -> bool:
        """
        维持原有熔断思路，但稍微更稳：
        - 30天内交易数不足，不熔断
        - EV 明显为负，或胜率低且 PF 低，才熔断
        """
        strategy = str(strategy or "DEFAULT").upper()
        records = self.data.get(strategy, [])
        stats_30d = self._calc_stats(records, 30)

        if not stats_30d:
            return False

        if stats_30d["trades"] >= 8:
            if stats_30d["ev_per_trade"] < -0.5:
                return True
            if stats_30d["win_rate"] < 40 and stats_30d["profit_factor"] < 0.8:
                return True

        return False

    # =========================
    # extra summary APIs
    # =========================
    def get_strategy_summary(self, strategy: str) -> dict:
        strategy = str(strategy or "DEFAULT").upper()
        records = self.data.get(strategy, [])
        all_time = self._calc_stats(records, None) or {
            "trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0,
            "profit_factor": 0.0, "ev_per_trade": 0.0,
            "avg_pnl": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
            "total_gain": 0.0, "total_loss": 0.0,
        }
        d7 = self._calc_stats(records, 7)
        d30 = self._calc_stats(records, 30)

        return {
            "strategy": strategy,
            "all_time": all_time,
            "last_7d": d7,
            "last_30d": d30,
            "tag": self.get_tag(strategy),
            "should_eliminate": self.should_eliminate(strategy),
        }

    def get_all_summary(self) -> dict:
        out = {}
        for strategy in sorted(self.data.keys()):
            out[strategy] = self.get_strategy_summary(strategy)
        return out

    def export_records(self, strategy: Optional[str] = None) -> Dict[str, List[dict]]:
        if strategy:
            s = str(strategy).upper()
            return {s: list(self.data.get(s, []))}
        return {k: list(v) for k, v in self.data.items()}


# 全局单例
stats_engine = PerformanceEngine()