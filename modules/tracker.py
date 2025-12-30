import json
import os
import time
import logging
import threading
from typing import Dict, Any, Optional

logger = logging.getLogger("Tracker")


class PriceTracker:
    def __init__(
        self,
        file_path: str = "data/price_history.json",
        save_interval: float = 5.0,          # 最短保存间隔（秒）
        fix_zero_entry: bool = True,         # entry_mcap=0 时，首次拿到有效 mcap 自动修正 entry
        max_tokens: Optional[int] = None,    # 可选：限制记录数量（按最老 time 淘汰）
        cleanup_days: int = 30,              # 30天没“被看到/更新”就清理
        cleanup_interval: float = 3600.0,    # 清理节流：默认每小时最多清理一次
        push_change_pct: float = 100.0       # 自动推送阈值：价格涨幅 >= 100% 才推（翻倍）
    ):
        self.file_path = file_path
        self.save_interval = float(save_interval)
        self.fix_zero_entry = bool(fix_zero_entry)
        self.max_tokens = max_tokens
        self.cleanup_days = int(cleanup_days)
        self.cleanup_interval = float(cleanup_interval)
        self.push_change_pct = float(push_change_pct)

        self.data: Dict[str, Dict[str, Any]] = {}
        self._dirty = False
        self._last_save_ts = 0.0
        self._last_cleanup_ts = 0.0
        self._lock = threading.RLock()

        self._ensure_dir()
        self._load()

    # ----------------------------
    # File / persistence
    # ----------------------------
    def _ensure_dir(self):
        folder = os.path.dirname(self.file_path) or "."
        os.makedirs(folder, exist_ok=True)

    def _atomic_write_json(self, path: str, payload: Any):
        tmp_path = f"{path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)

    def _maybe_save(self, force: bool = False):
        if not self._dirty and not force:
            return

        now = time.time()
        if (not force) and self.save_interval > 0 and (now - self._last_save_ts) < self.save_interval:
            return

        try:
            self._atomic_write_json(self.file_path, self.data)
            self._dirty = False
            self._last_save_ts = now
        except Exception as e:
            logger.error(f"保存记录失败: {e}")

    def flush(self):
        """程序退出前建议调用一次，确保落盘"""
        with self._lock:
            self._maybe_save(force=True)

    def _load(self):
        with self._lock:
            if not os.path.exists(self.file_path):
                self.data = {}
                return

            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    self.data = json.load(f) or {}
            except Exception as e:
                logger.error(f"加载记录失败，已回退为空数据: {e}")
                self.data = {}
                return

            now = time.time()
            for ca, entry in list(self.data.items()):
                if not isinstance(entry, dict):
                    self.data.pop(ca, None)
                    continue
                self._normalize_entry(entry, now)

    # ----------------------------
    # Data normalization / cleanup
    # ----------------------------
    def _normalize_entry(self, entry: Dict[str, Any], now: float):
        # 基础
        entry.setdefault("time", now)
        entry.setdefault("update_time", entry.get("time", now))

        entry.setdefault("entry_price", 0.0)
        entry.setdefault("entry_mcap", 0.0)

        # ATH
        entry.setdefault("ath_mcap", entry.get("entry_mcap", 0.0))
        entry.setdefault("ath_price", entry.get("entry_price", 0.0))

        # 手动查询/被看到（用于返回 cur/max pnl，也用于30天清理）
        entry.setdefault("last_seen_price", entry.get("entry_price", 0.0))
        entry.setdefault("last_seen_mcap", entry.get("entry_mcap", 0.0))
        entry.setdefault("last_seen_time", entry.get("time", now))

        # 自动推送基准（只在自动推送触发时更新）
        entry.setdefault("last_push_price", entry.get("entry_price", 0.0))
        entry.setdefault("last_push_time", 0.0)

    def _evict_if_needed(self):
        if not self.max_tokens or self.max_tokens <= 0:
            return
        if len(self.data) <= self.max_tokens:
            return
        items = sorted(self.data.items(), key=lambda kv: kv[1].get("time", 0))
        to_remove = len(self.data) - self.max_tokens
        for i in range(to_remove):
            self.data.pop(items[i][0], None)

    def _cleanup_stale(self, now: float):
        """清理 30 天没 seen 的代币（节流执行）"""
        if self.cleanup_days <= 0:
            return
        if self.cleanup_interval > 0 and (now - self._last_cleanup_ts) < self.cleanup_interval:
            return

        cutoff = now - (self.cleanup_days * 86400)
        removed = 0

        for ca, entry in list(self.data.items()):
            # ✅ 优先按 last_seen_time，其次 update_time，再次 time
            ts = entry.get("last_seen_time", entry.get("update_time", entry.get("time", 0)))
            try:
                ts = float(ts or 0.0)
            except Exception:
                ts = 0.0

            if ts < cutoff:
                self.data.pop(ca, None)
                removed += 1

        if removed:
            self._dirty = True
            logger.info(f"🧹 清理过期代币: {removed} 个（>{self.cleanup_days}天未 seen）")

        self._last_cleanup_ts = now
        self._maybe_save()

    # ----------------------------
    # Core logic
    # ----------------------------
    def _safe_float(self, v, default: float = 0.0) -> float:
        try:
            if v is None:
                return default
            return float(v)
        except Exception:
            return default

    def _format_duration(self, seconds: float) -> str:
        if seconds < 60:
            return f"{int(seconds)}秒"
        if seconds < 3600:
            return f"{int(seconds / 60)}分"
        if seconds < 86400:
            return f"{int(seconds / 3600)}小时"
        return f"{int(seconds / 86400)}天"

    def _compute_pnl(self, entry_mcap: float, current_mcap: float, ath_mcap: float):
        if entry_mcap > 0:
            cur_pnl = ((current_mcap - entry_mcap) / entry_mcap) * 100.0
            max_pnl = ((ath_mcap - entry_mcap) / entry_mcap) * 100.0
        else:
            cur_pnl = 0.0
            max_pnl = 0.0
        return cur_pnl, max_pnl

    def _auto_push_threshold(self, base_price: float) -> float:
        # base * (1 + pct/100), pct=100 => base*2
        return base_price * (1.0 + self.push_change_pct / 100.0)

    def observe(self, ca: str, current_price, current_mcap, manual: bool) -> dict:
        """
        manual=True  -> 用户手动查询：永远更新 last_seen / ATH / pnl，永远返回 cur/max pnl，不改 last_push
        manual=False -> 自动推送通道：只有翻倍触发才 should_push=True，并且只在触发时更新 last_push
        """
        ca = (ca or "").strip()
        if not ca:
            return {"ok": False, "reason": "empty_ca"}

        current_price = self._safe_float(current_price, 0.0)
        current_mcap = self._safe_float(current_mcap, 0.0)
        now = time.time()

        with self._lock:
            self._cleanup_stale(now)

            # 新代币：先落库
            if ca not in self.data:
                entry = {
                    "time": now,
                    "entry_price": current_price,
                    "entry_mcap": current_mcap,
                    "ath_mcap": current_mcap,
                    "ath_price": current_price,
                    "update_time": now,

                    "last_seen_price": current_price,
                    "last_seen_mcap": current_mcap,
                    "last_seen_time": now,

                    "last_push_price": current_price,
                    "last_push_time": 0.0,
                }
                self.data[ca] = entry
                self._dirty = True
                self._evict_if_needed()
                self._maybe_save()

                # 新币手动查询：pnl通常为0
                return {
                    "ok": True,
                    "is_new": True,
                    "is_new_ath": False,
                    "should_push": False,
                    "push_reason": "",
                    "entry_mcap": current_mcap,
                    "ath_mcap": current_mcap,
                    "cur_pnl": 0.0,
                    "max_pnl": 0.0,
                    "duration_str": "刚刚",
                }

            entry = self.data[ca]
            self._normalize_entry(entry, now)

            # -----------------
            # 手动查询：永远更新 last_seen & update_time
            # -----------------
            if manual:
                entry["last_seen_price"] = current_price
                entry["last_seen_mcap"] = current_mcap
                entry["last_seen_time"] = now
                entry["update_time"] = now
                self._dirty = True

            # entry/ath 计算（手动/自动都要能算出 pnl 给你展示或用于推送内容）
            entry_mcap = self._safe_float(entry.get("entry_mcap"), 0.0)
            ath_mcap = self._safe_float(entry.get("ath_mcap"), entry_mcap)

            # entry_mcap=0 修正（手动查询也允许修）
            if self.fix_zero_entry and entry_mcap <= 0 and current_mcap > 0:
                entry_mcap = current_mcap
                entry["entry_mcap"] = current_mcap
                entry["entry_price"] = current_price
                self._dirty = True

            # ATH 更新：手动查询也要更新
            is_new_ath = False
            if current_mcap > ath_mcap:
                ath_mcap = current_mcap
                entry["ath_mcap"] = current_mcap
                entry["ath_price"] = current_price
                is_new_ath = True
                self._dirty = True

            cur_pnl, max_pnl = self._compute_pnl(entry_mcap, current_mcap, ath_mcap)

            # -----------------
            # 自动推送：只有翻倍触发才更新 last_push & should_push=True
            # -----------------
            should_push = False
            push_reason = ""

            if not manual:
                base = self._safe_float(entry.get("last_push_price"), 0.0)
                if base <= 0:
                    base = self._safe_float(entry.get("entry_price"), 0.0)

                threshold = self._auto_push_threshold(base) if base > 0 else 0.0
                if threshold > 0 and current_price >= threshold:
                    should_push = True
                    push_reason = "price_up_100pct"
                    entry["last_push_price"] = current_price
                    entry["last_push_time"] = now
                    entry["update_time"] = now
                    # 自动推送触发也算“被看到”，避免误清理（可选但建议）
                    entry["last_seen_time"] = now
                    self._dirty = True

            self._maybe_save()

            return {
                "ok": True,
                "is_new": False,
                "is_new_ath": is_new_ath,
                "should_push": should_push,
                "push_reason": push_reason,
                "entry_mcap": entry_mcap,
                "ath_mcap": ath_mcap,
                "cur_pnl": cur_pnl,
                "max_pnl": max_pnl,
                "duration_str": self._format_duration(now - self._safe_float(entry.get("time"), now)),
                "last_push_price": self._safe_float(entry.get("last_push_price"), 0.0),
                "last_seen_time": self._safe_float(entry.get("last_seen_time"), 0.0),
            }

    # ----------------------------
    # Public APIs (recommended)
    # ----------------------------
    def track_auto(self, ca: str, current_price, current_mcap) -> dict:
        """自动推送通道：监听信号时调用（只在翻倍触发 should_push=True）"""
        return self.observe(ca, current_price, current_mcap, manual=False)

    def manual_query(self, ca: str, current_price, current_mcap) -> dict:
        """用户手动查询：用户发 CA 时调用（永远返回当前/最高涨幅）"""
        return self.observe(ca, current_price, current_mcap, manual=True)

    # ----------------------------
    # Backward compatible API
    # ----------------------------
    def check_and_record(self, ca: str, current_price: float, current_mcap: float) -> dict:
        """
        ✅ 兼容你原来的调用：把它视为“手动查询”
        - 用户再次发送 CA 后：记录并给出当前涨幅/最高涨幅
        """
        return self.manual_query(ca, current_price, current_mcap)


# ✅ 默认实例（你也可以自己在别处 new）
tracker = PriceTracker(
    file_path="data/price_history.json",
    save_interval=5.0,
    cleanup_days=30,
    cleanup_interval=3600.0,
    push_change_pct=100.0
)

"""
==== 你在 bot 里怎么用 ====

# 1) 自动推送（监听群消息/信号源）
r = tracker.track_auto(ca, price, mcap)
if r["should_push"]:
    # 推送内容可用 r["cur_pnl"], r["max_pnl"], r["is_new_ath"] 等
    ...

# 2) 用户手动查询（用户发 CA）
r = tracker.check_and_record(ca, price, mcap)   # 或 tracker.manual_query(...)
# 永远有：
# r["cur_pnl"] 当前涨幅
# r["max_pnl"] 最高涨幅
...
# 程序退出前：
tracker.flush()
"""
