import os
import json
import time
import math
import asyncio
import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger("TPTracker")


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except Exception:
        return default


class TPTracker:
    """
    目标：
    1) 保持原有外部调用方式尽量不变
    2) 修复“占位态锁死”：
       - observe_price() 对新 CA 仅创建轻量占位态
       - init_position() 如发现现有仓位是占位态，允许真实仓位覆盖
    3) 提供 main.py / notifier.py 所需接口：
       - init_position
       - observe_price
       - get_baseline_metrics
       - update
       - update_custom_image
       - data 字典
    """

    def __init__(self, path: str = "data/tp_tracker.json"):
        self.path = path
        self.data: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self._loaded = False
        self._save_task: Optional[asyncio.Task] = None

        os.makedirs(os.path.dirname(self.path), exist_ok=True)

    # ----------------------------
    # 基础持久化
    # ----------------------------
    async def _ensure_loaded(self):
        if self._loaded:
            return
        async with self._lock:
            if self._loaded:
                return
            try:
                if os.path.exists(self.path):
                    with open(self.path, "r", encoding="utf-8") as f:
                        raw = json.load(f)
                        if isinstance(raw, dict):
                            self.data = raw
                        else:
                            self.data = {}
                else:
                    self.data = {}
            except Exception as e:
                logger.error(f"⚠️ TPTracker 读取存档失败: {e}")
                self.data = {}
            self._loaded = True


    async def _save(self):
        await self._ensure_loaded()
        async with self._lock:
            last_err = None
            for attempt in range(3):
                try:
                    tmp = f"{self.path}.tmp"
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump(self.data, f, ensure_ascii=False, indent=2)
                        f.flush()
                        os.fsync(f.fileno())
                    os.replace(tmp, self.path)
                    return
                except PermissionError as e:
                    last_err = e
                    await asyncio.sleep(0.12 * (attempt + 1))
                except Exception as e:
                    last_err = e
                    break
            if last_err:
                logger.error(f"⚠️ TPTracker 保存失败: {last_err}")


    async def _save_debounced(self):
        # 极轻量去抖，避免极高频全量写盘
        if self._save_task and not self._save_task.done():
            return

        async def _worker():
            try:
                await asyncio.sleep(0.15)
                await self._save()
            except Exception as e:
                logger.error(f"⚠️ TPTracker 延迟保存失败: {e}")

        self._save_task = asyncio.create_task(_worker())

    # ----------------------------
    # 内部工具
    # ----------------------------
    def _is_placeholder(self, pos: Optional[dict]) -> bool:
        if not pos or not isinstance(pos, dict):
            return True

        entry = _safe_float(pos.get("entry"), 0.0)
        status = str(pos.get("status", "")).upper()
        strategy = str(pos.get("strategy") or pos.get("strategy_id") or "").upper()
        sl_price = _safe_float(pos.get("sl_price"), 0.0)
        tp_targets = pos.get("tp_targets") or []

        return (
            entry <= 0
            and sl_price <= 0
            and status == "OBSERVE"
            and strategy in {"", "UNKNOWN", "UNK"}
            and (not tp_targets)
        )

    def _default_strategy_config(self, strategy_id: str) -> Dict[str, Any]:
        sid = str(strategy_id or "DEFAULT").upper()

        # 尽量温和：不替代你已有策略，只做缺省配置
        presets = {
            "SMART_TREND": {"tp_targets": [1.30, 1.60, 2.00], "sl_pct": 0.12},
            "SNIPER_PLAY": {"tp_targets": [1.20, 1.45, 1.80], "sl_pct": 0.10},
            "BUNDLE_CTRL": {"tp_targets": [1.18, 1.35, 1.60], "sl_pct": 0.09},
            "MIXED": {"tp_targets": [1.22, 1.45, 1.75], "sl_pct": 0.10},
            "DEFAULT": {"tp_targets": [1.20, 1.50, 2.00], "sl_pct": 0.10},
        }
        return dict(presets.get(sid, presets["DEFAULT"]))

    def _merged_config(self, strategy_id: str, config: Optional[dict]) -> Dict[str, Any]:
        base = self._default_strategy_config(strategy_id)
        user_cfg = config or {}

        tp_targets = user_cfg.get("tp_targets") or user_cfg.get("tps") or base["tp_targets"]
        tp_targets = [float(x) for x in tp_targets if _safe_float(x, 0) > 0]

        sl_pct = _safe_float(user_cfg.get("sl_pct"), _safe_float(user_cfg.get("stop_loss_pct"), base["sl_pct"]))
        if sl_pct <= 0:
            sl_pct = base["sl_pct"]

        return {
            "tp_targets": tp_targets if tp_targets else base["tp_targets"],
            "sl_pct": sl_pct,
        }

    def _make_placeholder(self, ca: str, current_price: float) -> Dict[str, Any]:
        now = time.time()
        return {
            "ca": ca,
            "created_at": now,
            "updated_at": now,
            "status": "OBSERVE",
            "strategy": "UNKNOWN",
            "strategy_id": "UNKNOWN",
            "entry": 0.0,
            "entry_price": 0.0,
            "current_price": current_price if current_price > 0 else 0.0,
            "peak_price": current_price if current_price > 0 else 0.0,
            "peak_multiplier": 1.0,
            "peak_change_pct": 0.0,
            "rel_change_pct": 0.0,
            "sl_price": 0.0,
            "sl_pct": 0.0,
            "tp_targets": [],
            "tp_hit_index": -1,
            "sl_moved_to_entry": False,
            "reply_chat_id": None,
            "reply_msg_id": None,
            "initial_mcap": 0.0,
            "current_mcap": 0.0,
            "custom_image": "",
        }

    def _apply_observation(self, pos: Dict[str, Any], current_price: float):
        if current_price <= 0:
            return

        pos["updated_at"] = time.time()
        pos["current_price"] = current_price

        peak = _safe_float(pos.get("peak_price"), 0.0)
        if peak <= 0 or current_price > peak:
            pos["peak_price"] = current_price
            peak = current_price

        entry = _safe_float(pos.get("entry"), 0.0)

        if entry > 0:
            rel_change_pct = (current_price - entry) / entry * 100.0
            peak_change_pct = (peak - entry) / entry * 100.0
            peak_multiplier = peak / entry if entry > 0 else 1.0
        else:
            rel_change_pct = 0.0
            peak_change_pct = 0.0
            peak_multiplier = 1.0

        pos["rel_change_pct"] = rel_change_pct
        pos["peak_change_pct"] = peak_change_pct
        pos["peak_multiplier"] = peak_multiplier

    # ----------------------------
    # 对外接口
    # ----------------------------
    async def init_position(
        self,
        ca: str,
        entry_price: float,
        strategy_id: str,
        config: Optional[dict] = None,
        initial_mcap: float = 0.0,
        reply_chat_id: Optional[int] = None,
        reply_msg_id: Optional[int] = None,
    ):
        """
        关键修复：
        如果当前已存在仓位，但只是占位态，则允许被真实仓位覆盖。
        """
        await self._ensure_loaded()
        ca = (ca or "").strip()
        if not ca:
            return

        entry_price = _safe_float(entry_price, 0.0)
        if entry_price <= 0:
            return

        strategy_id = str(strategy_id or "DEFAULT")
        merged = self._merged_config(strategy_id, config)

        existing = self.data.get(ca)
        if existing and not self._is_placeholder(existing):
            # 已经是真实仓位：只补充缺失信息，不重置状态
            if reply_chat_id is not None:
                existing["reply_chat_id"] = reply_chat_id
            if reply_msg_id is not None:
                existing["reply_msg_id"] = reply_msg_id
            if _safe_float(existing.get("initial_mcap"), 0.0) <= 0 and initial_mcap > 0:
                existing["initial_mcap"] = float(initial_mcap)
            existing["updated_at"] = time.time()
            await self._save_debounced()
            return

        now = time.time()
        peak_price = entry_price
        sl_pct = _safe_float(merged.get("sl_pct"), 0.10)
        sl_price = entry_price * (1.0 - sl_pct)
        tp_targets = merged.get("tp_targets") or [1.2, 1.5, 2.0]

        new_pos = {
            "ca": ca,
            "created_at": existing.get("created_at", now) if isinstance(existing, dict) else now,
            "updated_at": now,
            "status": "ACTIVE",
            "strategy": strategy_id,
            "strategy_id": strategy_id,
            "entry": entry_price,
            "entry_price": entry_price,
            "current_price": entry_price,
            "peak_price": peak_price,
            "peak_multiplier": 1.0,
            "peak_change_pct": 0.0,
            "rel_change_pct": 0.0,
            "sl_price": sl_price,
            "sl_pct": sl_pct,
            "tp_targets": tp_targets,
            "tp_hit_index": -1,
            "sl_moved_to_entry": False,
            "reply_chat_id": reply_chat_id,
            "reply_msg_id": reply_msg_id,
            "initial_mcap": float(initial_mcap or 0.0),
            "current_mcap": float(initial_mcap or 0.0),
            "custom_image": (existing.get("custom_image") if isinstance(existing, dict) else "") or "",
        }

        self.data[ca] = new_pos
        await self._save_debounced()

    async def observe_price(self, ca: str, current_price: float):
        await self._ensure_loaded()
        ca = (ca or "").strip()
        if not ca:
            return

        current_price = _safe_float(current_price, 0.0)
        if current_price <= 0:
            return

        pos = self.data.get(ca)
        if not pos:
            # 只创建占位态，不抢先伪造真实仓位
            self.data[ca] = self._make_placeholder(ca, current_price)
            await self._save_debounced()
            return

        self._apply_observation(pos, current_price)
        await self._save_debounced()

    async def get_baseline_metrics(self, ca: str, current_price: Optional[float] = None) -> Dict[str, Any]:
        await self._ensure_loaded()
        ca = (ca or "").strip()
        if not ca or ca not in self.data:
            return {}

        pos = self.data[ca]
        cp = _safe_float(current_price, _safe_float(pos.get("current_price"), 0.0))
        if cp > 0:
            self._apply_observation(pos, cp)

        return {
            "entry_price": _safe_float(pos.get("entry"), 0.0),
            "current_price": _safe_float(pos.get("current_price"), 0.0),
            "peak_price": _safe_float(pos.get("peak_price"), 0.0),
            "rel_change_pct": _safe_float(pos.get("rel_change_pct"), 0.0),
            "peak_change_pct": _safe_float(pos.get("peak_change_pct"), 0.0),
            "peak_multiplier": _safe_float(pos.get("peak_multiplier"), 1.0),
        }

    async def update_custom_image(self, ca: str, img_path: str):
        await self._ensure_loaded()
        ca = (ca or "").strip()
        if not ca or ca not in self.data:
            return
        self.data[ca]["custom_image"] = img_path or ""
        self.data[ca]["updated_at"] = time.time()
        await self._save_debounced()

    async def update(self, ca: str, curr_price: float, curr_mcap: float = 0.0) -> Optional[Dict[str, Any]]:
        """
        返回事件：
        - {"event": "MILESTONE", "multiplier": 2, "pnl": 123.4}
        - {"event": "止盈1", "pnl": 20.5}
        - {"event": "CLOSED_TP", "pnl_percentage": 105.2}
        - {"event": "CLOSED_SL", "pnl_percentage": -9.8}
        或 None
        """
        await self._ensure_loaded()
        ca = (ca or "").strip()
        if not ca:
            return None

        pos = self.data.get(ca)
        if not pos:
            return None

        curr_price = _safe_float(curr_price, 0.0)
        if curr_price <= 0:
            return None

        self._apply_observation(pos, curr_price)

        if curr_mcap > 0:
            pos["current_mcap"] = float(curr_mcap)

        status = str(pos.get("status", "ACTIVE")).upper()
        if status not in {"ACTIVE", "OBSERVE"}:
            await self._save_debounced()
            return None

        entry = _safe_float(pos.get("entry"), 0.0)
        if entry <= 0:
            await self._save_debounced()
            return None

        pnl_pct = (curr_price - entry) / entry * 100.0
        peak_multiplier = _safe_float(pos.get("peak_multiplier"), 1.0)
        prev_peak_mult = _safe_float(pos.get("last_notified_peak_multiplier"), 1.0)

        # 里程碑：只在突破新的整数倍时触发
        milestone_event = None
        if peak_multiplier >= 2.0 and int(peak_multiplier) > int(prev_peak_mult):
            new_mult = int(peak_multiplier)
            pos["last_notified_peak_multiplier"] = float(new_mult)
            milestone_event = {
                "event": "MILESTONE",
                "multiplier": new_mult,
                "pnl": pnl_pct,
            }

        # 止盈逻辑
        tp_targets: List[float] = pos.get("tp_targets") or []
        tp_hit_index = int(pos.get("tp_hit_index", -1))
        next_idx = tp_hit_index + 1

        if 0 <= next_idx < len(tp_targets):
            tp_mult = _safe_float(tp_targets[next_idx], 0.0)
            if tp_mult > 0 and curr_price >= entry * tp_mult:
                pos["tp_hit_index"] = next_idx

                # 第一次止盈后，SL 抬到保本
                if next_idx >= 0 and not bool(pos.get("sl_moved_to_entry")):
                    pos["sl_price"] = entry
                    pos["sl_moved_to_entry"] = True

                # 最后一个 TP 触发，视作全量落袋
                if next_idx >= len(tp_targets) - 1:
                    pos["status"] = "WIN"
                    await self._save_debounced()
                    return {
                        "event": "CLOSED_TP",
                        "pnl_percentage": pnl_pct,
                    }

                await self._save_debounced()
                return {
                    "event": f"止盈{next_idx + 1}",
                    "pnl": pnl_pct,
                }

        # 止损逻辑
        sl_price = _safe_float(pos.get("sl_price"), 0.0)
        if sl_price > 0 and curr_price <= sl_price:
            pos["status"] = "LOSS" if pnl_pct < 0 else "WIN"
            await self._save_debounced()
            return {
                "event": "CLOSED_SL",
                "pnl_percentage": pnl_pct,
            }

        await self._save_debounced()
        return milestone_event


    def _is_pre_entry_state(self, pos: Optional[dict]) -> bool:
        if not pos or not isinstance(pos, dict):
            return True

        entry = _safe_float(pos.get("entry"), 0.0)
        status = str(pos.get("status", "")).upper()
        return entry <= 0 and status in {"OBSERVE", "ARMED"}

    def _make_placeholder(self, ca: str, current_price: float) -> Dict[str, Any]:
        now = time.time()
        return {
            "ca": ca,
            "created_at": now,
            "updated_at": now,
            "status": "OBSERVE",
            "signal_state": "OBSERVING",
            "strategy": "UNKNOWN",
            "strategy_id": "UNKNOWN",
            "entry": 0.0,
            "entry_price": 0.0,
            "anchor_price": current_price if current_price > 0 else 0.0,
            "current_price": current_price if current_price > 0 else 0.0,
            "peak_price": current_price if current_price > 0 else 0.0,
            "peak_multiplier": 1.0,
            "peak_change_pct": 0.0,
            "rel_change_pct": 0.0,
            "sl_price": 0.0,
            "sl_pct": 0.0,
            "tp_targets": [],
            "tp_hit_index": -1,
            "sl_moved_to_entry": False,
            "reply_chat_id": None,
            "reply_msg_id": None,
            "initial_mcap": 0.0,
            "current_mcap": 0.0,
            "custom_image": "",
        }

    def _apply_observation(self, pos: Dict[str, Any], current_price: float):
        if current_price <= 0:
            return

        pos["updated_at"] = time.time()
        pos["current_price"] = current_price

        peak = _safe_float(pos.get("peak_price"), 0.0)
        if peak <= 0 or current_price > peak:
            pos["peak_price"] = current_price
            peak = current_price

        entry = _safe_float(pos.get("entry"), 0.0)
        if entry <= 0:
            entry = _safe_float(pos.get("anchor_price"), 0.0)

        if entry > 0:
            rel_change_pct = (current_price - entry) / entry * 100.0
            peak_change_pct = (peak - entry) / entry * 100.0
            peak_multiplier = peak / entry if entry > 0 else 1.0
        else:
            rel_change_pct = 0.0
            peak_change_pct = 0.0
            peak_multiplier = 1.0

        pos["rel_change_pct"] = rel_change_pct
        pos["peak_change_pct"] = peak_change_pct
        pos["peak_multiplier"] = peak_multiplier

    async def init_position(
        self,
        ca: str,
        entry_price: float,
        strategy_id: str,
        config: Optional[dict] = None,
        initial_mcap: float = 0.0,
        reply_chat_id: Optional[int] = None,
        reply_msg_id: Optional[int] = None,
    ):
        await self._ensure_loaded()
        ca = (ca or "").strip()
        if not ca:
            return

        entry_price = _safe_float(entry_price, 0.0)
        if entry_price <= 0:
            return

        strategy_id = str(strategy_id or "DEFAULT")
        merged = self._merged_config(strategy_id, config)

        existing = self.data.get(ca)
        if existing and not self._is_pre_entry_state(existing):
            if reply_chat_id is not None:
                existing["reply_chat_id"] = reply_chat_id
            if reply_msg_id is not None:
                existing["reply_msg_id"] = reply_msg_id
            if _safe_float(existing.get("initial_mcap"), 0.0) <= 0 and initial_mcap > 0:
                existing["initial_mcap"] = float(initial_mcap)
            existing["signal_state"] = "ENTERED"
            existing["updated_at"] = time.time()
            await self._save_debounced()
            return

        now = time.time()
        peak_price = entry_price
        sl_pct = _safe_float(merged.get("sl_pct"), 0.10)
        sl_price = entry_price * (1.0 - sl_pct)
        tp_targets = merged.get("tp_targets") or [1.2, 1.5, 2.0]

        new_pos = {
            "ca": ca,
            "created_at": existing.get("created_at", now) if isinstance(existing, dict) else now,
            "updated_at": now,
            "status": "ACTIVE",
            "signal_state": "ENTERED",
            "strategy": strategy_id,
            "strategy_id": strategy_id,
            "entry": entry_price,
            "entry_price": entry_price,
            "anchor_price": _safe_float((existing or {}).get("anchor_price"), entry_price),
            "current_price": entry_price,
            "peak_price": peak_price,
            "peak_multiplier": 1.0,
            "peak_change_pct": 0.0,
            "rel_change_pct": 0.0,
            "sl_price": sl_price,
            "sl_pct": sl_pct,
            "tp_targets": tp_targets,
            "tp_hit_index": -1,
            "sl_moved_to_entry": False,
            "reply_chat_id": reply_chat_id,
            "reply_msg_id": reply_msg_id,
            "initial_mcap": float(initial_mcap or 0.0),
            "current_mcap": float(initial_mcap or 0.0),
            "custom_image": (existing.get("custom_image") if isinstance(existing, dict) else "") or "",
        }

        self.data[ca] = new_pos
        await self._save_debounced()

    async def ensure_observing(
        self,
        ca: str,
        current_price: float = 0.0,
        *,
        anchor_price: float = 0.0,
        reply_chat_id: Optional[int] = None,
        reply_msg_id: Optional[int] = None,
    ):
        await self._ensure_loaded()
        ca = (ca or "").strip()
        if not ca:
            return

        current_price = _safe_float(current_price, 0.0)
        anchor_price = _safe_float(anchor_price, current_price)
        existing = self.data.get(ca)
        if existing and not self._is_pre_entry_state(existing):
            if reply_chat_id is not None:
                existing["reply_chat_id"] = reply_chat_id
            if reply_msg_id is not None:
                existing["reply_msg_id"] = reply_msg_id
            existing["signal_state"] = "ENTERED" if str(existing.get("status", "")).upper() == "ACTIVE" else existing.get("signal_state", "OBSERVING")
            if current_price > 0:
                self._apply_observation(existing, current_price)
            await self._save_debounced()
            return

        pos = dict(existing) if isinstance(existing, dict) else self._make_placeholder(ca, current_price)
        pos["status"] = "OBSERVE"
        pos["signal_state"] = "OBSERVING"
        pos["entry"] = 0.0
        pos["entry_price"] = 0.0
        pos["sl_price"] = 0.0
        pos["sl_pct"] = 0.0
        pos["tp_targets"] = []
        if anchor_price > 0 and (_safe_float(pos.get("anchor_price"), 0.0) <= 0 or not existing):
            pos["anchor_price"] = anchor_price
        if current_price > 0:
            pos["current_price"] = current_price
            pos["peak_price"] = max(_safe_float(pos.get("peak_price"), 0.0), current_price)
            self._apply_observation(pos, current_price)
        if reply_chat_id is not None:
            pos["reply_chat_id"] = reply_chat_id
        if reply_msg_id is not None:
            pos["reply_msg_id"] = reply_msg_id
        self.data[ca] = pos
        await self._save_debounced()

    async def arm_position(
        self,
        ca: str,
        strategy_id: str,
        config: Optional[dict] = None,
        *,
        current_price: float = 0.0,
        current_mcap: float = 0.0,
        reply_chat_id: Optional[int] = None,
        reply_msg_id: Optional[int] = None,
    ):
        await self._ensure_loaded()
        ca = (ca or "").strip()
        if not ca:
            return

        existing = self.data.get(ca)
        if existing and not self._is_pre_entry_state(existing):
            if reply_chat_id is not None:
                existing["reply_chat_id"] = reply_chat_id
            if reply_msg_id is not None:
                existing["reply_msg_id"] = reply_msg_id
            await self._save_debounced()
            return

        merged = self._merged_config(strategy_id, config)
        pos = dict(existing) if isinstance(existing, dict) else self._make_placeholder(ca, _safe_float(current_price, 0.0))
        pos["status"] = "ARMED"
        pos["signal_state"] = "ARMED"
        pos["strategy"] = strategy_id or "DEFAULT"
        pos["strategy_id"] = strategy_id or "DEFAULT"
        pos["tp_targets"] = merged.get("tp_targets") or []
        pos["sl_pct"] = _safe_float(merged.get("sl_pct"), 0.10)
        pos["sl_price"] = 0.0
        pos["entry"] = 0.0
        pos["entry_price"] = 0.0
        if _safe_float(pos.get("anchor_price"), 0.0) <= 0 and _safe_float(current_price, 0.0) > 0:
            pos["anchor_price"] = _safe_float(current_price, 0.0)
        if _safe_float(current_price, 0.0) > 0:
            self._apply_observation(pos, _safe_float(current_price, 0.0))
        if _safe_float(current_mcap, 0.0) > 0:
            pos["initial_mcap"] = _safe_float(pos.get("initial_mcap"), _safe_float(current_mcap, 0.0)) or _safe_float(current_mcap, 0.0)
            pos["current_mcap"] = _safe_float(current_mcap, 0.0)
        if reply_chat_id is not None:
            pos["reply_chat_id"] = reply_chat_id
        if reply_msg_id is not None:
            pos["reply_msg_id"] = reply_msg_id
        pos["updated_at"] = time.time()
        self.data[ca] = pos
        await self._save_debounced()

    async def reset_to_observing(
        self,
        ca: str,
        current_price: float = 0.0,
        *,
        anchor_price: float = 0.0,
        reply_chat_id: Optional[int] = None,
        reply_msg_id: Optional[int] = None,
    ):
        await self._ensure_loaded()
        ca = (ca or "").strip()
        if not ca:
            return

        existing = self.data.get(ca)
        pos = self._make_placeholder(ca, _safe_float(current_price, 0.0))
        if isinstance(existing, dict):
            pos["created_at"] = existing.get("created_at", pos["created_at"])
            pos["custom_image"] = existing.get("custom_image", "")
            pos["reply_chat_id"] = existing.get("reply_chat_id")
            pos["reply_msg_id"] = existing.get("reply_msg_id")
            pos["initial_mcap"] = _safe_float(existing.get("initial_mcap"), 0.0)
            pos["current_mcap"] = _safe_float(existing.get("current_mcap"), 0.0)
            pos["anchor_price"] = _safe_float(existing.get("anchor_price"), _safe_float(anchor_price, _safe_float(current_price, 0.0)))
        if reply_chat_id is not None:
            pos["reply_chat_id"] = reply_chat_id
        if reply_msg_id is not None:
            pos["reply_msg_id"] = reply_msg_id
        if _safe_float(anchor_price, 0.0) > 0:
            pos["anchor_price"] = _safe_float(anchor_price, 0.0)
        if _safe_float(current_price, 0.0) > 0:
            self._apply_observation(pos, _safe_float(current_price, 0.0))
        self.data[ca] = pos
        await self._save_debounced()

    async def get_baseline_metrics(self, ca: str, current_price: Optional[float] = None) -> Dict[str, Any]:
        await self._ensure_loaded()
        ca = (ca or "").strip()
        if not ca or ca not in self.data:
            return {}

        pos = self.data[ca]
        cp = _safe_float(current_price, _safe_float(pos.get("current_price"), 0.0))
        if cp > 0:
            self._apply_observation(pos, cp)

        return {
            "entry_price": _safe_float(pos.get("entry"), _safe_float(pos.get("anchor_price"), 0.0)),
            "current_price": _safe_float(pos.get("current_price"), 0.0),
            "peak_price": _safe_float(pos.get("peak_price"), 0.0),
            "rel_change_pct": _safe_float(pos.get("rel_change_pct"), 0.0),
            "peak_change_pct": _safe_float(pos.get("peak_change_pct"), 0.0),
            "peak_multiplier": _safe_float(pos.get("peak_multiplier"), 1.0),
        }


tp_tracker = TPTracker()
