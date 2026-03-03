import time
import json
import os
import asyncio
from typing import Optional, Dict, Any

FILE = "data/tp_tracker.json"


class TPTracker:
    def __init__(self):
        self.data: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self._load()

    # ===========================
    # Persistence
    # ===========================
    def _load(self):
        if os.path.exists(FILE):
            try:
                with open(FILE, "r", encoding="utf-8") as f:
                    self.data = json.load(f) or {}
            except Exception:
                self.data = {}

    def _save(self):
        os.makedirs("data", exist_ok=True)
        with open(FILE, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    # ===========================
    # ✅ 兼容旧 main.py：面板基线/峰值接口
    # ===========================
    async def observe_price(self, ca: str, price: float):
        """
        记录基线价 + 峰值价，用于刷新面板显示：
        """
        async with self._lock:
            ca = str(ca).strip()
            if not ca:
                return

            try:
                price = float(price or 0)
            except Exception:
                return
            if price <= 0:
                return

            pos = self.data.get(ca)
            if not pos:
                pos = {
                    "strategy": "UNKNOWN",
                    "entry": 0.0,
                    "tp_targets": [],
                    "sl_price": 0.0,
                    "tp_hit_index": -1,
                    "status": "OBSERVE",
                    "start_time": time.time(),
                }
                self.data[ca] = pos

            # 初始化基线/峰值
            if not pos.get("baseline_price"):
                pos["baseline_price"] = price
            if not pos.get("peak_price"):
                pos["peak_price"] = price

            # 更新峰值
            try:
                if price > float(pos.get("peak_price") or 0):
                    pos["peak_price"] = price
            except Exception:
                pos["peak_price"] = price

            pos["last_price"] = price
            pos["last_seen"] = time.time()
            self._save()

    async def get_baseline_metrics(self, ca: str, current_price: float) -> Dict[str, Any]:
        """返回面板需要的指标"""
        async with self._lock:
            ca = str(ca).strip()
            pos = self.data.get(ca) or {}

            try:
                current_price = float(current_price or 0)
            except Exception:
                current_price = 0.0

            baseline = float(pos.get("baseline_price") or 0.0)
            peak = float(pos.get("peak_price") or 0.0)

            rel_change_pct = 0.0
            peak_change_pct = 0.0

            if baseline > 0 and current_price > 0:
                rel_change_pct = (current_price - baseline) / baseline * 100.0

            if baseline > 0 and peak > 0:
                peak_change_pct = (peak - baseline) / baseline * 100.0

            return {
                "baseline_price": baseline,
                "peak_price": peak,
                "rel_change_pct": rel_change_pct,
                "peak_change_pct": peak_change_pct,
                "last_price": float(pos.get("last_price") or 0.0),
                "status": pos.get("status", ""),
            }

    # ===========================
    # Init position
    # ===========================
    async def init_position(
        self,
        ca: str,
        entry_price: float,
        strategy_id: str,
        config: dict,
        initial_mcap: float = 0.0,  # ✅ 新增：记录初始市值
        reply_chat_id: Optional[int] = None,
        reply_msg_id: Optional[int] = None,
    ):
        """
        初始化仓位追踪
        """
        async with self._lock:
            ca = str(ca).strip()
            if not ca:
                return

            # 已存在仓位 → 仅补充回调信息
            if ca in self.data:
                if reply_chat_id and not self.data[ca].get("reply_chat_id"):
                    try:
                        self.data[ca]["reply_chat_id"] = int(reply_chat_id)
                    except Exception:
                        self.data[ca]["reply_chat_id"] = None

                if reply_msg_id and not self.data[ca].get("reply_msg_id"):
                    try:
                        self.data[ca]["reply_msg_id"] = int(reply_msg_id)
                    except Exception:
                        self.data[ca]["reply_msg_id"] = None

                self._save()
                return

            config = config or {}

            tp_targets = config.get("tp_targets", [1.3])
            sl_threshold = config.get("sl_threshold", 0.85)

            move_sl_after_tp1 = bool(config.get("move_sl_to_entry_after_tp1", True))
            try:
                move_sl_buffer_pct = float(config.get("move_sl_buffer_pct", 0.0) or 0.0)
            except Exception:
                move_sl_buffer_pct = 0.0

            try:
                rcid = int(reply_chat_id) if reply_chat_id is not None else None
            except Exception:
                rcid = None

            try:
                rmid = int(reply_msg_id) if reply_msg_id is not None else None
            except Exception:
                rmid = None

            self.data[ca] = {
                "strategy": str(strategy_id),
                "entry": float(entry_price),
                "initial_mcap": float(initial_mcap) if initial_mcap > 0 else 1.0,  # ✅ 记录初始市值
                "last_milestone": 1,  # ✅ 记录当前最高里程碑倍数
                "custom_image": "",   # ✅ 预留字段，存放生成的战报图路径
                "tp_targets": tp_targets,
                "sl_price": float(entry_price) * float(sl_threshold),
                "tp_hit_index": -1,
                "status": "ACTIVE",
                "start_time": time.time(),

                "reply_chat_id": rcid,
                "reply_msg_id": rmid,

                "move_sl_to_entry_after_tp1": move_sl_after_tp1,
                "move_sl_buffer_pct": move_sl_buffer_pct,
                "sl_moved_to_entry": False,
            }

            self._save()

    # ===========================
    # Update price
    # ===========================
    async def update(self, ca: str, current_price: float, curr_mcap: float = 0.0) -> Optional[dict]:
        """
        根据当前价格检查 TP / SL 及 里程碑
        """
        async with self._lock:
            pos = self.data.get(ca)
            if not pos or pos.get("status") != "ACTIVE":
                return None

            entry = float(pos.get("entry") or 0)
            if entry <= 0:
                return None

            try:
                current_price = float(current_price)
            except Exception:
                return None

            if current_price <= 0:
                return None

            # =========================================
            # ✅ 新增：市值倍数里程碑检查 (2X, 3X, 4X...)
            # =========================================
            init_mcap = pos.get("initial_mcap", 1.0)
            last_ms = pos.get("last_milestone", 1)
            
            if curr_mcap > 0 and init_mcap > 0:
                current_multiplier = curr_mcap / init_mcap
                reached_ms = int(current_multiplier)
                
                # 如果突破了新的整数倍 (并且 >= 2X)
                if reached_ms > last_ms and reached_ms >= 2:
                    pos["last_milestone"] = reached_ms
                    self._save()
                    # 优先返回里程碑事件供 main.py 拦截画图
                    return {
                        "event": "MILESTONE",
                        "multiplier": reached_ms,
                        "pnl": (current_price - entry) / entry * 100,
                        "strategy": pos.get("strategy", "UNKNOWN"),
                    }

            result = None

            # ---------- 止损 ----------
            sl_price = float(pos.get("sl_price") or 0)
            if sl_price > 0 and current_price <= sl_price:
                pos["status"] = "LOSS"
                result = {
                    "event": "止损",
                    "pnl": (current_price - entry) / entry * 100,
                    "strategy": pos.get("strategy", "UNKNOWN"),
                }

            # ---------- 止盈 ----------
            if result is None:
                tp_targets = pos.get("tp_targets") or []
                next_tp_idx = int(pos.get("tp_hit_index") or -1) + 1

                if next_tp_idx < len(tp_targets):
                    try:
                        target_mult = float(tp_targets[next_tp_idx])
                    except Exception:
                        target_mult = None

                    if target_mult and target_mult > 0:
                        target_price = entry * target_mult
                        if current_price >= target_price:
                            pos["tp_hit_index"] = next_tp_idx

                            # TP1 后抬 SL 到成本
                            if (
                                next_tp_idx == 0
                                and pos.get("move_sl_to_entry_after_tp1")
                                and not pos.get("sl_moved_to_entry")
                            ):
                                buffer_pct = float(pos.get("move_sl_buffer_pct") or 0.0)
                                new_sl = entry * (1.0 + buffer_pct)
                                old_sl = float(pos.get("sl_price") or 0.0)
                                pos["sl_price"] = max(old_sl, new_sl)
                                pos["sl_moved_to_entry"] = True

                            if next_tp_idx == len(tp_targets) - 1:
                                pos["status"] = "WIN"

                            result = {
                                "event": f"止盈{next_tp_idx + 1}",
                                "pnl": (current_price - entry) / entry * 100,
                                "strategy": pos.get("strategy", "UNKNOWN"),
                            }

            if result:
                self._save()

            return result


tp_tracker = TPTracker()