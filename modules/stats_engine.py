import time
import json
import os
import asyncio
import logging
from collections import defaultdict
from typing import Optional, Dict, List

logger = logging.getLogger("StatsEngine")
FILE = "data/strategy_performance.json"
DAY = 86400


class PerformanceEngine:
    def __init__(self):
        self.data = defaultdict(list)
        self._lock = asyncio.Lock()
        self._load()

    def _load(self):
        if os.path.exists(FILE):
            try:
                with open(FILE, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                    self.data = defaultdict(list, {k: v for k, v in raw.items()})
            except Exception as e:
                logger.error(f"加载统计数据失败: {e}")
                self.data = defaultdict(list)

    def _save(self):
        os.makedirs("data", exist_ok=True)
        try:
            with open(FILE, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存统计数据失败: {e}")

    async def record_trade(self, strategy: str, result_type: str, pnl_percent: float):
        """记录交易结果（核心实现，保持不变）"""
        async with self._lock:
            now = time.time()
            record = {
                "time": now,
                "result": result_type,
                "pnl": float(pnl_percent)
            }
            self.data[strategy].append(record)
            if len(self.data[strategy]) > 1000:
                self.data[strategy] = self.data[strategy][-1000:]
            self._save()
            logger.info(f"📊 记账成功 [{strategy}]: {result_type} ({pnl_percent}%)")

    # =====================================================
    # ✅ 关键补丁：统一同步接口，供 main.py 调用
    # =====================================================
    def record(self, strategy: str, result_type: str, pnl_percent: float, ca: str = ""):
        """
        同步兼容入口：
        - main.py / tp_tracker 可直接调用 stats_engine.record(...)
        - 内部安全调度 async record_trade
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # 已在事件循环中 → 投递一个 task
            asyncio.create_task(
                self.record_trade(strategy, result_type, pnl_percent)
            )
        else:
            # 不在事件循环中（极少见）→ 新建 loop 执行
            asyncio.run(
                self.record_trade(strategy, result_type, pnl_percent)
            )

    # ==============================
    # 原有接口（保持不变）
    # ==============================
    def get_raw_stats(self, strategy: str) -> dict:
        """供 position_engine 使用，返回 {win_rate, total, is_new}"""
        records = self.data.get(strategy, [])
        total = len(records)

        if total == 0:
            return {"win_rate": 0, "total": 0, "is_new": True}

        wins = sum(1 for r in records if r.get("pnl", 0) > 0)
        win_rate = int((wins / total) * 100)

        return {
            "win_rate": win_rate,
            "total": total,
            "is_new": False
        }

    def get_tag(self, strategy: str) -> str:
        """供 Notifier 使用，返回简短标签"""
        stats = self.get_raw_stats(strategy)
        if stats["is_new"]:
            return "🆕 测试期"
        return f"🏆胜率{stats['win_rate']}%"

    def _calc_stats(self, records: List[dict], days: int) -> Optional[dict]:
        """计算详细核心指标"""
        if not records:
            return None
        cutoff = time.time() - days * DAY
        subset = [r for r in records if r["time"] >= cutoff]
        if not subset:
            return None

        total_trades = len(subset)
        if total_trades == 0:
            return None

        wins = [r for r in subset if r.get("pnl", 0) > 0]
        losses = [r for r in subset if r.get("pnl", 0) <= 0]

        win_rate = len(wins) / total_trades
        total_gain = sum(r.get("pnl", 0) for r in wins)
        total_loss = abs(sum(r.get("pnl", 0) for r in losses))

        profit_factor = total_gain / total_loss if total_loss > 0 else float("inf")
        if total_loss == 0 and total_gain == 0:
            profit_factor = 0

        avg_win = total_gain / len(wins) if wins else 0
        avg_loss = total_loss / len(losses) if losses else 0
        ev = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)

        return {
            "trades": total_trades,
            "win_rate": round(win_rate * 100, 1),
            "profit_factor": round(profit_factor, 2),
            "ev_per_trade": round(ev, 2)
        }

    def should_eliminate(self, strategy: str) -> bool:
        """淘汰规则"""
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


# 全局单例
stats_engine = PerformanceEngine()

