import os
import time
import asyncio
import logging
from collections import deque
from typing import Any, Dict, Optional, Tuple

import aiohttp

logger = logging.getLogger("InsightX")


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        if v is None or v == "":
            return default
        return int(float(v))
    except Exception:
        return default


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except Exception:
        return default


class InsightXAgent:
    """
    最小必要增强：
    1) 保持原有输出字段兼容
    2) 增加 in-flight 去重，避免同一 CA 重复请求风暴
    3) scanner-first：先拿轻量基础画像，再按剩余额度补 metrics
    4) 限流按“真实 HTTP 请求数”计，不再按“分析次数”计
    5) 429/部分成功显式上报，避免被下游误当成 0 风险
    """

    def __init__(self):
        self.api_key = (os.getenv("INSIGHTX_API_KEY") or "").strip()
        self.base_url = (os.getenv("INSIGHTX_BASE_URL") or "https://api.insightx.network").rstrip("/")
        self.network = (os.getenv("INSIGHTX_NETWORK") or "sol").strip()

        self._max_rpm = int(os.getenv("INSIGHTX_MAX_RPM", "5") or "5")
        self._max_block_wait = float(os.getenv("INSIGHTX_MAX_BLOCK_WAIT", "2.0") or 2.0)
        self._cache_ttl = float(os.getenv("INSIGHTX_CACHE_TTL", "60") or 60.0)
        self._request_timeout = aiohttp.ClientTimeout(total=12, connect=5, sock_read=10)

        self._lock = asyncio.Lock()
        self._request_timestamps = deque()
        self._cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        self._in_flight: Dict[str, asyncio.Task] = {}
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._request_timeout, trust_env=True)
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def aclose(self):
        await self.close()

    def _headers(self) -> Dict[str, str]:
        return {
            "x-api-key": self.api_key,
            "X-API-Key": self.api_key,
            "Accept": "application/json",
            "User-Agent": "SolanaHunter/InsightX",
        }

    async def _acquire_http_slot(self) -> Tuple[bool, float]:
        async with self._lock:
            now = time.time()
            while self._request_timestamps and now - self._request_timestamps[0] > 60:
                self._request_timestamps.popleft()

            if len(self._request_timestamps) < self._max_rpm:
                self._request_timestamps.append(now)
                return True, 0.0

            wait = 60 - (now - self._request_timestamps[0])
            return False, max(0.0, wait)

    async def _rate_limited_get_json(self, url: str) -> Tuple[int, Any]:
        allowed, wait_s = await self._acquire_http_slot()
        if not allowed:
            if wait_s <= self._max_block_wait:
                await asyncio.sleep(wait_s)
                allowed, _ = await self._acquire_http_slot()
            if not allowed:
                return 429, {"message": "local_rate_limit_guard"}

        session = await self._get_session()
        try:
            async with session.get(url, headers=self._headers()) as resp:
                status = resp.status
                if status == 200:
                    try:
                        return status, await resp.json()
                    except Exception:
                        txt = await resp.text()
                        return status, {"raw_text": txt[:500]}
                txt = await resp.text()
                return status, {"message": txt[:500]}
        except asyncio.TimeoutError:
            return 0, {"message": "timeout"}
        except Exception as e:
            return 0, {"message": str(e)}

    def _get_cached(self, ca: str) -> Optional[Dict[str, Any]]:
        try:
            ts, val = self._cache.get(ca, (0.0, None))
            if val and (time.time() - ts) <= self._cache_ttl:
                return dict(val)
        except Exception:
            pass
        return None

    def _set_cached(self, ca: str, val: Dict[str, Any]):
        try:
            self._cache[ca] = (time.time(), dict(val))
        except Exception:
            pass

    def _token_candidates(self, ca: str):
        cas = [ca]
        if ca.lower().endswith("pump") and len(ca) > 4:
            alt = ca[:-4].strip()
            if alt:
                cas.append(alt)
        return cas

    def _clean_data(
        self,
        overview: Any,
        distribution: Any,
        clusters: Any,
        bundlers: Any,
        scanner: Any,
        meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        meta = meta or {}
        out: Dict[str, Any] = {}

        sm = 0
        try:
            sm = _safe_int(((scanner or {}).get("smart_money") or {}).get("count"), 0)
        except Exception:
            sm = 0
        if sm <= 0:
            sm = _safe_int((overview or {}).get("smart_money_count"), 0) or _safe_int((overview or {}).get("smartMoneyCount"), 0)
        out["smart_money_count"] = sm

        fw = _safe_float((distribution or {}).get("fresh_percent"), 0.0) or _safe_float((distribution or {}).get("freshPercent"), 0.0)
        out["fresh_wallet_percent"] = fw

        rh = 0
        try:
            rh = _safe_int((((scanner or {}).get("creator") or {}).get("rug_history_count")), 0)
        except Exception:
            rh = 0
        out["rug_history"] = rh

        ir = _safe_float((distribution or {}).get("insider_pct"), 0.0) or _safe_float((distribution or {}).get("insiderPct"), 0.0)
        out["insider_ratio"] = ir

        gc = (
            _safe_float((distribution or {}).get("gini"), 0.0)
            or _safe_float((distribution or {}).get("gini_coefficient"), 0.0)
            or _safe_float((distribution or {}).get("giniCoefficient"), 0.0)
        )
        out["gini_coefficient"] = gc

        cls = []
        if isinstance(clusters, dict):
            cls = clusters.get("clusters") or clusters.get("data") or []
        elif isinstance(clusters, list):
            cls = clusters
        out["clusters"] = cls if isinstance(cls, list) else []

        bundled = False
        if isinstance(bundlers, dict):
            items = bundlers.get("bundlers") or bundlers.get("data") or bundlers.get("items")
            bundled = bool(items) if isinstance(items, list) else False
        elif isinstance(bundlers, list):
            bundled = len(bundlers) > 0
        out["bundled_sniper"] = bool(bundled)

        # 显式状态，供下游判定 unknown，而不是吞成 0 风险
        out["scanner_ok"] = bool(meta.get("scanner_ok"))
        out["metrics_ok"] = bool(meta.get("metrics_ok"))
        out["insightx_rate_limited"] = bool(meta.get("rate_limited"))
        out["insightx_partial"] = bool(meta.get("partial"))
        out["insightx_status"] = meta.get("status") or (
            "full_ok"
            if out["scanner_ok"] and out["metrics_ok"]
            else "partial_ok"
            if out["scanner_ok"]
            else "failed"
        )

        return out

    async def _fetch_one_ca(self, ca_try: str) -> Dict[str, Any]:
        scanner_url = f"{self.base_url}/scanner/v1/tokens/{self.network}/{ca_try}"
        overview_url = f"{self.base_url}/dex-metrics/v1/{self.network}/{ca_try}"
        dist_url = f"{self.base_url}/dex-metrics/v1/{self.network}/{ca_try}/distribution"
        clus_url = f"{self.base_url}/dex-metrics/v1/{self.network}/{ca_try}/clusters"
        bund_url = f"{self.base_url}/dex-metrics/v1/{self.network}/{ca_try}/bundlers"

        # scanner-first：先拿轻量画像
        scanner_status, scanner = await self._rate_limited_get_json(scanner_url)
        if scanner_status != 200 or not isinstance(scanner, dict):
            return {}

        rate_limited = False
        metrics_ok = False
        overview: Any = {}
        dist: Any = {}
        clus: Any = {}
        bund: Any = {}

        # metrics 串行补充，避免免费层一次并发 5 打满
        for url_name, url in [
            ("overview", overview_url),
            ("distribution", dist_url),
            ("clusters", clus_url),
            ("bundlers", bund_url),
        ]:
            status, payload = await self._rate_limited_get_json(url)
            if status == 200:
                metrics_ok = True
                if url_name == "overview":
                    overview = payload
                elif url_name == "distribution":
                    dist = payload
                elif url_name == "clusters":
                    clus = payload
                elif url_name == "bundlers":
                    bund = payload
            elif status == 429:
                rate_limited = True
            else:
                pass

        meta = {
            "scanner_ok": True,
            "metrics_ok": metrics_ok,
            "rate_limited": rate_limited,
            "partial": (not metrics_ok) or rate_limited,
            "status": "full_ok" if metrics_ok and not rate_limited else "rate_limited_partial" if rate_limited else "partial_ok",
        }
        return self._clean_data(overview, dist, clus, bund, scanner, meta=meta)

    async def _fetch_deep_analysis_impl(self, ca: str) -> Dict[str, Any]:
        ca = (ca or "").strip()
        if not ca or not self.api_key:
            return {}

        cached = self._get_cached(ca)
        if cached is not None:
            return cached

        for ca_try in self._token_candidates(ca):
            try:
                cleaned = await self._fetch_one_ca(ca_try)
                if cleaned:
                    self._set_cached(ca, cleaned)
                    return cleaned
            except Exception as e:
                logger.error(f"⚠️ InsightX 连接失败: {e}")
                continue

        return {}

    async def fetch_deep_analysis(self, ca: str) -> Dict[str, Any]:
        """
        保持原接口不变；增加同一 CA 的 in-flight 去重。
        """
        ca = (ca or "").strip()
        if not ca or not self.api_key:
            return {}

        cached = self._get_cached(ca)
        if cached is not None:
            return cached

        task = self._in_flight.get(ca)
        if task and not task.done():
            try:
                return await task
            except Exception:
                return {}

        loop = asyncio.get_running_loop()
        task = loop.create_task(self._fetch_deep_analysis_impl(ca), name=f"InsightX_{ca[:6]}")
        self._in_flight[ca] = task
        try:
            return await task
        finally:
            if self._in_flight.get(ca) is task:
                self._in_flight.pop(ca, None)


insightx_agent = InsightXAgent()