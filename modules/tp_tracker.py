import time
import json
import os
import asyncio
from typing import Optional, Dict

FILE = "data/tp_tracker.json"

class TPTracker:
    def __init__(self):
        self.data = {}
        self._lock = asyncio.Lock() # ✅ 并发锁
        self._load()

    def _load(self):
        if os.path.exists(FILE):
            try:
                with open(FILE, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
            except Exception:
                self.data = {}

    def _save(self):
        # 注意：实际高频IO场景建议异步写文件，这里简化处理
        os.makedirs("data", exist_ok=True)
        with open(FILE, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    async def init_position(self, ca: str, entry_price: float, strategy_id: str, config: dict):
        """
        初始化仓位，根据策略配置动态设定止盈止损位
        """
        async with self._lock:
            if ca in self.data:
                return # 已存在
            
            # 从配置中读取动态阈值
            tp_targets = config.get("tp_targets", [1.3])
            sl_threshold = config.get("sl_threshold", 0.85)

            self.data[ca] = {
                "strategy": strategy_id,
                "entry": entry_price,
                "tp_targets": tp_targets, # [1.25, 1.5]
                "sl_price": entry_price * sl_threshold,
                "tp_hit_index": -1,       # 当前触发到第几个TP
                "status": "ACTIVE",       # ACTIVE, WIN, LOSS
                "start_time": time.time()
            }
            self._save()

    async def update(self, ca: str, current_price: float) -> Optional[dict]:
        """
        检查价格，返回触发事件 (None 或 结果字典)
        """
        async with self._lock:
            pos = self.data.get(ca)
            if not pos or pos["status"] != "ACTIVE":
                return None

            result = None
            entry = pos["entry"]
            tp_targets = pos["tp_targets"]
            
            # 1. 检查止损
            if current_price <= pos["sl_price"]:
                pos["status"] = "LOSS"
                result = {
                    "event": "SL", 
                    "pnl": (current_price - entry)/entry*100,
                    "strategy": pos["strategy"]
                }
            
            # 2. 检查止盈 (支持多阶 TP)
            # 检查是否达到下一个 TP 目标
            next_tp_idx = pos["tp_hit_index"] + 1
            if next_tp_idx < len(tp_targets):
                target_price = entry * tp_targets[next_tp_idx]
                if current_price >= target_price:
                    pos["tp_hit_index"] = next_tp_idx
                    # 如果是最后一个 TP，标记为 WIN
                    if next_tp_idx == len(tp_targets) - 1:
                        pos["status"] = "WIN"
                    
                    result = {
                        "event": f"TP{next_tp_idx+1}",
                        "pnl": (current_price - entry)/entry*100,
                        "strategy": pos["strategy"]
                    }

            if result:
                self._save()
            
            return result

tp_tracker = TPTracker()