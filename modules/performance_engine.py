import time
import json
import os
from collections import defaultdict

FILE = "data/strategy_performance.json"

DAY = 86400


class PerformanceEngine:
    def __init__(self):
        self.data = defaultdict(list)
        self._load()

    def _load(self):
        if os.path.exists(FILE):
            try:
                with open(FILE, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                    self.data = defaultdict(list, {
                        k: v for k, v in raw.items()
                    })
            except Exception:
                self.data = defaultdict(list)

    def _save(self):
        os.makedirs("data", exist_ok=True)
        with open(FILE, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def record_trade(self, strategy: str, result: str):
        """
        result: TP1 / TP2 / SL
        """
        now = time.time()
        self.data[strategy].append({
            "time": now,
            "result": result
        })
        self._save()

    def _calc_stats(self, records, days: int):
        cutoff = time.time() - days * DAY
        subset = [r for r in records if r["time"] >= cutoff]

        if not subset:
            return None

        wins = sum(1 for r in subset if r["result"] in ("TP1", "TP2"))
        losses = sum(1 for r in subset if r["result"] == "SL")
        total = wins + losses
        if total == 0:
            return None

        win_rate = wins / total

        # 简化盈亏比假设
        # TP1 = +1R, TP2 = +2R, SL = -1R
        pnl = 0
        for r in subset:
            if r["result"] == "TP1":
                pnl += 1
            elif r["result"] == "TP2":
                pnl += 2
            elif r["result"] == "SL":
                pnl -= 1

        r_ratio = pnl / total

        return {
            "trades": total,
            "win_rate": round(win_rate * 100, 1),
            "r_ratio": round(r_ratio, 2),
        }

    def get_report(self, strategy: str):
        records = self.data.get(strategy, [])
        return {
            "7d": self._calc_stats(records, 7),
            "30d": self._calc_stats(records, 30)
        }

    def should_eliminate(self, strategy: str) -> bool:
        """
        淘汰规则：
        - 30d 交易 ≥ 8
        - 胜率 < 40%
        - R 倍 ≤ 0
        """
        rep = self.get_report(strategy).get("30d")
        if not rep:
            return False
        if rep["trades"] >= 8 and rep["win_rate"] < 40 and rep["r_ratio"] <= 0:
            return True
        return False


performance_engine = PerformanceEngine()
