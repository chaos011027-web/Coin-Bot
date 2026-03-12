import aiohttp
import asyncio
import os
import logging
import time
import re
import json
import random
import hashlib
from io import BytesIO
from typing import Optional, Dict, Any, List, Tuple
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

from PIL import Image

from DrissionPage import ChromiumPage, ChromiumOptions
from DrissionPage.errors import PageDisconnectedError

logger = logging.getLogger("DataFetcher")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
]


def _to_float(x, default=0.0) -> float:
    try:
        if x is None or x == "":
            return default
        if isinstance(x, str):
            x = x.replace(",", "").replace("$", "").strip()
            if x.endswith("%"):
                x = x[:-1].strip()
            if "K" in x.upper():
                x = float(x.replace("K", "").replace("k", "")) * 1000
            elif "M" in x.upper():
                x = float(x.replace("M", "").replace("m", "")) * 1000000
            elif "B" in x.upper():
                x = float(x.replace("B", "").replace("b", "")) * 1000000000
        return float(x)
    except Exception:
        return default


def _to_int(x, default=0) -> int:
    try:
        return int(float(x)) if x is not None else default
    except Exception:
        return default


class DataFetcher:
    def __init__(self):
        self.img_dir = "data/charts"
        self.avatar_dir = "data/token_avatars"
        self.profile_dir = os.path.abspath("data/browser_profile")
        self.gmgn_template_token = "So11111111111111111111111111111111111111112"
        self.gmgn_state_path = os.path.join(self.profile_dir, "gmgn_runtime_state.json")
        self.gmgn_marker_path = os.path.join(self.profile_dir, ".gmgn_profile_ready")

        os.makedirs(self.img_dir, exist_ok=True)
        os.makedirs(self.avatar_dir, exist_ok=True)
        os.makedirs(self.profile_dir, exist_ok=True)

        self.dex_api_url = "https://api.dexscreener.com/latest/dex/tokens/{}"
        self.birdeye_api_key = os.getenv("BIRDEYE_API_KEY", "")
        self.goplus_app_key = os.getenv("GOPLUS_APP_KEY", "")
        self.goplus_app_secret = os.getenv("GOPLUS_APP_SECRET", "")

        self.jup_api_key = (os.getenv("JUP_API_KEY") or os.getenv("JUPITER_API_KEY") or "").strip()
        self.jup_price_url = "https://api.jup.ag/price/v3"
        self.jup_lite_price_url = "https://lite-api.jup.ag/price/v3"

        self._goplus_token = ""
        self._goplus_token_expire = 0

        self._session: Optional[aiohttp.ClientSession] = None
        self._browser: Optional[ChromiumPage] = None
        self._gmgn_tab = None
        self._browser_lock = asyncio.Lock()
        self._gmgn_lock = asyncio.Lock()
        self._ca_locks: Dict[str, asyncio.Lock] = {}
        self._ca_locks_lock = asyncio.Lock()

        self._market_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        self._market_cache_ttl = float(os.getenv("DEX_MARKET_CACHE_TTL", "8") or 8.0)

        self.helius_api_key = (os.getenv("HELIUS_API_KEY") or "").strip()
        self.helius_rpc_url = f"https://mainnet.helius-rpc.com/?api-key={self.helius_api_key}" if self.helius_api_key else ""

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10),
                trust_env=True
            )
        return self._session

    def _has_saved_gmgn_profile(self) -> bool:
        try:
            if not os.path.isdir(self.profile_dir):
                return False
            if not os.path.exists(self.gmgn_marker_path):
                return False
            return bool(self._load_gmgn_saved_state())
        except Exception:
            return False

    async def prepare_browser_profile(self):
        os.makedirs(self.profile_dir, exist_ok=True)
        logger.info("✅ 浏览器持久化引擎已就绪 (GMGN simple mode)")
        return

    def _init_browser_sync(self) -> bool:
        try:
            if self._browser and getattr(self._browser, "process_id", None):
                return True
            co = ChromiumOptions().set_user_data_path(self.profile_dir).auto_port()
            co.headless(False)
            co.set_argument("--window-position=-32000,-32000")
            co.set_argument("--window-size=1920,1080")
            co.set_argument("--disable-popup-blocking")
            co.set_argument("--disable-notifications")
            co.mute(True)
            self._browser = ChromiumPage(co)
            return True
        except Exception as e:
            logger.error(f"❌ 浏览器初始化失败: {e}")
            return False

    async def _ensure_browser(self):
        async with self._browser_lock:
            if self._browser and getattr(self._browser, "process_id", None):
                return True
            return await asyncio.to_thread(self._init_browser_sync)

    async def _reset_browser(self):
        async with self._browser_lock:
            if self._browser:
                try:
                    await asyncio.to_thread(self._browser.quit)
                except Exception:
                    pass
            self._gmgn_tab = None
            self._browser = None

    def _default_gmgn_layout_url(self) -> str:
        return f"https://gmgn.ai/sol/token/{self.gmgn_template_token}?chain=sol"

    def _extract_token_from_gmgn_url(self, url: str) -> str:
        try:
            m = re.search(r"/sol/token/([^/?#]+)", str(url or ""), re.IGNORECASE)
            return (m.group(1) if m else "").strip()
        except Exception:
            return ""

    def _load_gmgn_saved_state(self) -> Dict[str, Any]:
        try:
            if not os.path.exists(self.gmgn_state_path):
                return {}

            with open(self.gmgn_state_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if not isinstance(data, dict):
                return {}

            url = str(data.get("url") or "").strip()
            if not url.startswith("http") or "gmgn.ai" not in url:
                return {}

            local_storage = data.get("local_storage") or {}
            session_storage = data.get("session_storage") or {}
            if not isinstance(local_storage, dict):
                local_storage = {}
            if not isinstance(session_storage, dict):
                session_storage = {}

            template_token = str(
                data.get("template_token")
                or self._extract_token_from_gmgn_url(url)
                or self.gmgn_template_token
            ).strip()

            return {
                "url": url,
                "title": str(data.get("title") or ""),
                "template_token": template_token or self.gmgn_template_token,
                "local_storage": {str(k): "" if v is None else str(v) for k, v in local_storage.items()},
                "session_storage": {str(k): "" if v is None else str(v) for k, v in session_storage.items()},
                "saved_at": data.get("saved_at"),
            }
        except Exception as e:
            logger.warning(f"⚠️ GMGN 页面状态读取失败: {e}")
            return {}

    def _capture_gmgn_runtime_state(self, tab) -> Dict[str, Any]:
        if not tab:
            return {}

        try:
            raw = tab.run_js("""
                const dump = (store) => {
                    const out = {};
                    try {
                        for (let i = 0; i < store.length; i++) {
                            const key = store.key(i);
                            out[key] = store.getItem(key);
                        }
                    } catch (e) {}
                    return out;
                };

                return {
                    url: location.href || '',
                    title: document.title || '',
                    local_storage: dump(window.localStorage),
                    session_storage: dump(window.sessionStorage),
                };
            """) or {}
        except Exception as e:
            logger.warning(f"⚠️ GMGN 页面状态抓取失败: {e}")
            return {}

        if not isinstance(raw, dict):
            return {}

        url = str(raw.get("url") or "").strip()
        if not url.startswith("http") or "gmgn.ai" not in url:
            return {}

        return {
            "url": url,
            "title": str(raw.get("title") or ""),
            "template_token": self._extract_token_from_gmgn_url(url) or self.gmgn_template_token,
            "local_storage": raw.get("local_storage") if isinstance(raw.get("local_storage"), dict) else {},
            "session_storage": raw.get("session_storage") if isinstance(raw.get("session_storage"), dict) else {},
            "saved_at": int(time.time()),
        }

    def _persist_gmgn_runtime_state(self, tab) -> bool:
        state = self._capture_gmgn_runtime_state(tab)
        if not state:
            return False

        try:
            os.makedirs(self.profile_dir, exist_ok=True)
            tmp_path = f"{self.gmgn_state_path}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.gmgn_state_path)

            with open(self.gmgn_marker_path, "w", encoding="utf-8") as f:
                f.write(str(state.get("saved_at") or int(time.time())))
                f.flush()
                os.fsync(f.fileno())
            return True
        except Exception as e:
            logger.warning(f"⚠️ GMGN 页面状态保存失败: {e}")
            return False

    def _apply_gmgn_saved_state(self, tab, state: Optional[Dict[str, Any]] = None, include_session: bool = True) -> bool:
        if not tab:
            return False

        self._inject_gmgn_local_flags(tab)
        state = state or self._load_gmgn_saved_state()
        if not state:
            return False

        payload_js = json.dumps({
            "local": state.get("local_storage") or {},
            "session": state.get("session_storage") or {},
            "include_session": bool(include_session),
        }, ensure_ascii=False)

        try:
            tab.run_js(f"""
                const payload = {payload_js};
                const applyStore = (store, data) => {{
                    if (!data || typeof data !== 'object') return;
                    for (const [k, v] of Object.entries(data)) {{
                        try {{
                            store.setItem(String(k), v == null ? '' : String(v));
                        }} catch (e) {{}}
                    }}
                }};

                applyStore(window.localStorage, payload.local);
                if (payload.include_session) {{
                    applyStore(window.sessionStorage, payload.session);
                }}
                localStorage.setItem('has_seen_welcome', 'true');
                localStorage.setItem('driver_tutorial_token_sol', 'true');
                localStorage.setItem('risk_warning_accepted', 'true');
                return true;
            """)
            return True
        except Exception:
            return False

    def _build_gmgn_token_url(self, ca: str, state: Optional[Dict[str, Any]] = None) -> str:
        target_ca = (ca or "").strip() or self.gmgn_template_token
        state = state or self._load_gmgn_saved_state()

        seed_url = str((state or {}).get("url") or self._default_gmgn_layout_url()).strip()
        if not seed_url.startswith("http"):
            seed_url = self._default_gmgn_layout_url()

        parsed = urlparse(seed_url)
        scheme = parsed.scheme or "https"
        netloc = parsed.netloc or "gmgn.ai"
        path = parsed.path or f"/sol/token/{target_ca}"

        if re.search(r"/sol/token/[^/?#]+", path, re.IGNORECASE):
            path = re.sub(r"/sol/token/[^/?#]+", f"/sol/token/{target_ca}", path, count=1, flags=re.IGNORECASE)
        else:
            path = f"/sol/token/{target_ca}"

        query_items = parse_qsl(parsed.query, keep_blank_values=True)
        rebuilt_query = []
        has_chain = False
        for key, value in query_items:
            low_key = key.lower()
            if low_key in {"token", "address", "ca", "mint", "contract_address"}:
                rebuilt_query.append((key, target_ca))
                continue
            if low_key == "chain":
                rebuilt_query.append((key, "sol"))
                has_chain = True
                continue
            rebuilt_query.append((key, value))
        if not has_chain:
            rebuilt_query.append(("chain", "sol"))

        fragment = parsed.fragment or ""
        old_token = str((state or {}).get("template_token") or self._extract_token_from_gmgn_url(seed_url) or "").strip()
        if old_token and fragment:
            fragment = fragment.replace(old_token, target_ca)

        return urlunparse((scheme, netloc, path, "", urlencode(rebuilt_query, doseq=True), fragment))

    def _bootstrap_gmgn_tab_layout(self, tab, state: Optional[Dict[str, Any]] = None) -> bool:
        if not tab:
            return False

        state = state or self._load_gmgn_saved_state()
        template_url = self._build_gmgn_token_url(
            (state or {}).get("template_token") or self.gmgn_template_token,
            state=state,
        )

        try:
            tab.get("https://gmgn.ai/")
            tab.wait.ele("tag:body", timeout=10)
        except Exception:
            return False

        self._apply_gmgn_saved_state(tab, state)

        try:
            tab.get(template_url)
            tab.wait.ele("tag:body", timeout=10)
        except Exception:
            return False

        self._apply_gmgn_saved_state(tab, state)

        try:
            self._finish_gmgn_walkthrough(tab, max_clicks=12, interval=0.30)
        except Exception:
            pass

        return True

    def _wait_gmgn_target_page(self, tab, ca: str, timeout: float = 10.0, interval: float = 0.4) -> bool:
        if not tab or not ca:
            return False

        deadline = time.time() + max(1.0, timeout)
        ca_low = str(ca).lower()
        short_prefix = ca_low[:6]
        short_suffix = ca_low[-4:] if len(ca_low) >= 4 else ca_low
        core_markers = [
            "市值", "Market Cap", "MCap", "MC",
            "池子", "Liquidity", "LP",
            "Dex付费", "Dex Paid",
            "Top 10", "Top10", "持有者", "Holder", "Holders",
            "DEV", "狙击者", "老鼠仓", "捆绑交易", "钓鱼钱包",
            "Mint丢弃", "无黑名单", "烧池子",
        ]
        tf_markers = ["1m", "5m", "15m", "30m", "1h", "4h", "6h", "24h", "1D"]

        while time.time() < deadline:
            try:
                current_url = str(tab.url or "")
            except Exception:
                current_url = ""

            try:
                title_text = str(tab.title or "")
            except Exception:
                title_text = ""

            page_text = self._extract_visible_text(tab)
            combined = "\n".join([current_url, title_text, page_text])
            combined_low = combined.lower()
            core_hits = sum(1 for x in core_markers if x.lower() in combined_low)
            tf_hits = sum(1 for x in tf_markers if x.lower() in combined_low)

            id_hits = 0
            if ca_low in current_url.lower():
                id_hits += 3
            if ca_low in combined_low:
                id_hits += 3
            if short_prefix and short_prefix in combined_low:
                id_hits += 1
            if short_suffix and short_suffix in combined_low:
                id_hits += 1

            if (id_hits >= 3 and core_hits >= 2) or (core_hits >= 5 and tf_hits >= 2):
                return True

            try:
                self._finish_gmgn_walkthrough(tab, max_clicks=2, interval=0.15)
            except Exception:
                pass

            time.sleep(interval)

        return False

    async def _get_ca_lock(self, ca: str):
        async with self._ca_locks_lock:
            if ca not in self._ca_locks:
                self._ca_locks[ca] = asyncio.Lock()
            return self._ca_locks[ca]

    def _avatar_path(self, ca: str):
        return os.path.join(self.avatar_dir, f"{re.sub(r'[^a-zA-Z0-9]', '', ca)[:80]}.jpg")

    def _screenshot_path(self, ca: str):
        return os.path.join(self.img_dir, f"{re.sub(r'[^a-zA-Z0-9]', '', ca)[:80]}_chart.png")

    def _existing_avatar_path(self, ca: str) -> Optional[str]:
        path = self._avatar_path(ca)
        try:
            if os.path.exists(path) and os.path.getsize(path) > 200:
                with Image.open(path) as im:
                    im.verify()
                return path
        except Exception:
            try:
                os.remove(path)
            except Exception:
                pass
        return None

    def _existing_chart_path(self, ca: str) -> Optional[str]:
        path = self._screenshot_path(ca)
        try:
            if os.path.exists(path) and os.path.getsize(path) > 500:
                return path
        except Exception:
            pass
        return None

    def _normalize_image_url(self, url: str) -> str:
        if not url:
            return ""
        u = str(url).strip()
        if u.startswith("ipfs://"):
            return "https://ipfs.io/ipfs/" + u.replace("ipfs://", "").lstrip("/")
        return u

    def _looks_like_html(self, data: bytes) -> bool:
        head = (data[:256] or b"").lstrip().lower()
        return head.startswith(b"<!doctype html") or head.startswith(b"<html") or b"<html" in head

    def _verify_and_convert_to_jpeg(self, data: bytes) -> Optional[bytes]:
        try:
            im = Image.open(BytesIO(data))
            im.verify()
        except Exception:
            return None
        try:
            im = Image.open(BytesIO(data))
            im = im.convert("RGB")
            out = BytesIO()
            im.save(out, format="JPEG", quality=92, optimize=True)
            return out.getvalue()
        except Exception:
            return None

    async def _download_image_cached(self, ca: str, url: str) -> Optional[str]:
        url = self._normalize_image_url(url)
        if not url.startswith("http"):
            return None

        path = self._avatar_path(ca)
        lock = await self._get_ca_lock(f"avatar:{ca}")

        async with lock:
            existing = self._existing_avatar_path(ca)
            if existing:
                return existing

            urls_to_try = [url]
            if "ipfs" in url.lower():
                hash_part = url.split("/ipfs/")[-1] if "/ipfs/" in url else url.split("/")[-1]
                urls_to_try = [
                    f"https://ipfs.io/ipfs/{hash_part}",
                    f"https://dweb.link/ipfs/{hash_part}",
                    f"https://gateway.pinata.cloud/ipfs/{hash_part}",
                    url,
                ]

            session = await self._get_session()
            headers = {
                "User-Agent": random.choice(USER_AGENTS),
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            }

            for try_url in urls_to_try:
                try:
                    async with session.get(try_url, headers=headers, ssl=False, timeout=6) as resp:
                        if resp.status != 200:
                            continue

                        ctype = (resp.headers.get("Content-Type") or "").lower()
                        if ctype and ("image/" not in ctype):
                            continue

                        data = await resp.read()
                        if not data or len(data) < 256:
                            continue
                        if self._looks_like_html(data):
                            continue

                        jpeg_bytes = self._verify_and_convert_to_jpeg(data)
                        if not jpeg_bytes or len(jpeg_bytes) < 300:
                            continue

                        tmp_path = f"{path}.tmp"
                        with open(tmp_path, "wb") as f:
                            f.write(jpeg_bytes)
                            f.flush()
                            os.fsync(f.fileno())
                        os.replace(tmp_path, path)
                        return path
                except Exception:
                    continue

            return None

    async def ensure_token_avatar(self, ca: str, token_image_url: str) -> Optional[str]:
        existing = self._existing_avatar_path(ca)
        if existing:
            return existing
        if not token_image_url:
            return None
        return await self._download_image_cached(ca, token_image_url)

    async def _fetch_birdeye_overview(self, mint: str) -> Optional[Dict]:
        if not self.birdeye_api_key:
            return None
        try:
            session = await self._get_session()
            headers = {
                "X-API-KEY": self.birdeye_api_key,
                "accept": "application/json",
                "x-chain": "solana",
            }
            async with session.get(
                f"https://public-api.birdeye.so/defi/token_overview?address={mint}",
                headers=headers,
                timeout=5
            ) as resp:
                if resp.status == 200:
                    return (await resp.json()).get("data", {})
        except Exception:
            pass
        return None

    async def _helius_rpc(self, method, params):
        if not self.helius_rpc_url:
            return None
        try:
            session = await self._get_session()
            async with session.post(
                self.helius_rpc_url,
                json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
            ) as r:
                if r.status == 200:
                    return (await r.json()).get("result")
        except Exception:
            pass
        return None

    def _cache_get_market(self, ca: str) -> Optional[Dict[str, Any]]:
        try:
            ts, payload = self._market_cache.get(ca, (0.0, None))
            if payload and (time.time() - ts) <= self._market_cache_ttl:
                out = dict(payload)
                if isinstance(out.get("txns"), dict):
                    out["txns"] = dict(out["txns"])
                return out
        except Exception:
            pass
        return None

    def _cache_set_market(self, ca: str, payload: Dict[str, Any]):
        try:
            self._market_cache[ca] = (time.time(), dict(payload))
        except Exception:
            pass

    async def _fetch_dexscreener(self, ca: str) -> Optional[Dict[str, Any]]:
        try:
            session = await self._get_session()
            headers = {"User-Agent": random.choice(USER_AGENTS)}
            async with session.get(
                f"{self.dex_api_url.format(ca)}?t={int(time.time())}",
                headers=headers,
                timeout=6
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
        except Exception:
            pass
        return None

    async def get_market_data(self, ca: str, force: bool = False) -> Optional[Dict[str, Any]]:
        ca = (ca or "").strip()
        if not ca:
            return None

        lock = await self._get_ca_lock(f"market:{ca}")
        async with lock:
            if not force:
                cached = self._cache_get_market(ca)
                if cached is not None:
                    return cached

            ds_data, be_data = await asyncio.gather(
                self._fetch_dexscreener(ca),
                self._fetch_birdeye_overview(ca),
            )

            result: Dict[str, Any] = {}
            pairs = ds_data.get("pairs", []) if ds_data else []

            if pairs:
                valid = [p for p in pairs if _to_float((p.get("liquidity") or {}).get("usd")) > 100.0]
                if not valid:
                    valid = pairs

                best = max(valid, key=lambda p: _to_float((p.get("liquidity") or {}).get("usd")))
                info = best.get("info", {}) or {}
                is_dex_paid = bool(info.get("imageUrl") or info.get("socials") or info.get("websites"))

                result = {
                    "symbol": (best.get("baseToken") or {}).get("symbol", "UNK"),
                    "name": (best.get("baseToken") or {}).get("name", ""),
                    "price_usd": best.get("priceUsd", "0"),
                    "liquidity_usd": _to_float((best.get("liquidity") or {}).get("usd"), 0),
                    "mcap": _to_float(best.get("marketCap") or best.get("fdv"), 0),
                    "pair_address": best.get("pairAddress"),
                    "dex_id": (best.get("dexId") or "").lower(),
                    "token_image_url": info.get("imageUrl") or (best.get("baseToken") or {}).get("logoURI"),
                    "chg_5m": (best.get("priceChange") or {}).get("m5"),
                    "chg_1h": (best.get("priceChange") or {}).get("h1"),
                    "chg_6h": (best.get("priceChange") or {}).get("h6"),
                    "chg_24h": (best.get("priceChange") or {}).get("h24"),
                    "volume_h24": _to_float((best.get("volume") or {}).get("h24"), 0),
                    "txns": best.get("txns", {}) or {},
                    "dex_paid": is_dex_paid,
                }

                h24 = result["txns"].get("h24", {}) if isinstance(result.get("txns"), dict) else {}
                result["buys_24h"] = _to_int(h24.get("buys", 0))
                result["sells_24h"] = _to_int(h24.get("sells", 0))
                result["buy_sell_ratio"] = result["buys_24h"] / result["sells_24h"] if result["sells_24h"] > 0 else 999.0

                created = best.get("pairCreatedAt")
                result["token_age_min"] = max(0, int((time.time() * 1000 - created) / 60000)) if created else 0
            else:
                result = {
                    "liquidity_usd": 0,
                    "token_age_min": 0,
                    "symbol": "UNK",
                }

            if be_data:
                result["chg_1m"] = be_data.get("priceChange1mPercent")
                result["chg_15m"] = be_data.get("priceChange15mPercent")
                result["chg_30m"] = be_data.get("priceChange30mPercent")

                be_liq = _to_float(be_data.get("liquidity"), 0)
                if be_liq > result.get("liquidity_usd", 0):
                    result["liquidity_usd"] = be_liq
                    result["price_usd"] = be_data.get("price") or result.get("price_usd")
                    result["mcap"] = be_data.get("mc") or result.get("mcap")

                if not result.get("token_image_url") and be_data.get("logoURI"):
                    result["token_image_url"] = be_data.get("logoURI")

            if ca.lower().endswith("pump") and (not result.get("token_image_url") or result.get("mcap", 0) == 0):
                try:
                    session = await self._get_session()
                    headers = {"User-Agent": random.choice(USER_AGENTS)}
                    async with session.get(
                        f"https://frontend-api.pump.fun/coins/{ca}",
                        headers=headers,
                        timeout=3.0
                    ) as resp:
                        if resp.status == 200:
                            pump_data = await resp.json()

                            if not result.get("token_image_url"):
                                result["token_image_url"] = pump_data.get("image_uri")
                            if result.get("symbol") == "UNK":
                                result["symbol"] = pump_data.get("symbol", "UNK")
                            if not result.get("name"):
                                result["name"] = pump_data.get("name", "")

                            if result.get("mcap", 0) == 0 and pump_data.get("usd_market_cap"):
                                result["mcap"] = float(pump_data.get("usd_market_cap"))
                                result["cap_usd"] = result["mcap"]

                            if result.get("token_age_min", 0) == 0 and pump_data.get("created_timestamp"):
                                created_ts = float(pump_data.get("created_timestamp")) / 1000
                                result["token_age_min"] = max(0, int((time.time() - created_ts) / 60))
                except Exception as e:
                    logger.debug(f"⚠️ Pump官方直连接口调用异常: {e}")

            existing_avatar = self._existing_avatar_path(ca)
            if existing_avatar:
                result["token_image_path"] = existing_avatar

            result["cap_usd"] = result.get("mcap") or result.get("fdv") or 0

            self._cache_set_market(ca, result)
            return dict(result)

    async def _get_goplus_token(self) -> Optional[str]:
        if not self.goplus_app_key or not self.goplus_app_secret:
            logger.warning("⚠️ GoPlus 未配置 APP_KEY / APP_SECRET")
            return None

        now = time.time()
        if self._goplus_token and now < self._goplus_token_expire:
            return self._goplus_token

        t = str(int(now))
        sign_str = self.goplus_app_key + t + self.goplus_app_secret
        sign = hashlib.sha1(sign_str.encode("utf-8")).hexdigest()

        try:
            session = await self._get_session()
            payload = {"app_key": self.goplus_app_key, "sign": sign, "time": t}
            async with session.post(
                "https://api.gopluslabs.io/api/v1/token",
                json=payload,
                timeout=5
            ) as r:
                text = await r.text()
                if r.status != 200:
                    logger.error(f"⚠️ GoPlus Token 获取失败: HTTP {r.status} | body={text[:300]}")
                    return None

                try:
                    data = json.loads(text)
                except Exception:
                    logger.error(f"⚠️ GoPlus Token 获取失败: 非JSON响应 | body={text[:300]}")
                    return None

                if data.get("code") != 1:
                    logger.error(f"⚠️ GoPlus Token 获取失败: code={data.get('code')} | body={text[:300]}")
                    return None

                token_info = data.get("result") or data.get("data") or {}
                self._goplus_token = token_info.get("access_token", "")
                if not self._goplus_token:
                    logger.error(f"⚠️ GoPlus Token 获取失败: access_token 为空 | body={text[:300]}")
                    return None

                self._goplus_token_expire = now + float(token_info.get("expires_in", 7200)) - 60
                logger.info("🔐 GoPlus 鉴权成功")
                return self._goplus_token
        except Exception as e:
            logger.error(f"⚠️ GoPlus Token 获取异常: {e}")
            return None

    async def fetch_goplus_security(self, ca: str) -> Dict[str, Any]:
        if not ca:
            return {}

        token = await self._get_goplus_token()
        headers = {"User-Agent": random.choice(USER_AGENTS)}

        if token:
            if token.startswith("Bearer"):
                headers["Authorization"] = token
            else:
                headers["Authorization"] = f"Bearer {token}"

        try:
            session = await self._get_session()
            async with session.get(
                f"https://api.gopluslabs.io/api/v1/token_security/solana?contract_addresses={ca}",
                headers=headers,
                timeout=5
            ) as r:
                text = await r.text()
                if r.status != 200:
                    logger.error(f"⚠️ GoPlus Security 请求失败: HTTP {r.status} | body={text[:300]}")
                    return {}

                try:
                    d = json.loads(text)
                except Exception:
                    logger.error(f"⚠️ GoPlus Security 请求失败: 非JSON响应 | body={text[:300]}")
                    return {}

                res = (d.get("result", {}) or {}).get(ca.lower(), {})
                return {
                    "is_honeypot": res.get("is_honeypot") == "1",
                    "is_blacklisted": res.get("is_blacklisted") == "1",
                    "is_mintable": res.get("is_mintable") == "1",
                    "transfer_pausable": res.get("transfer_pausable") == "1",
                }
        except Exception as e:
            logger.error(f"⚠️ GoPlus Security 请求异常: {e}")
        return {}

    async def fetch_rugcheck_data(self, mint: str) -> Dict[str, Any]:
        if not mint:
            return {}

        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "application/json",
        }

        try:
            session = await self._get_session()
            async with session.get(
                f"https://api.rugcheck.xyz/v1/tokens/{mint}/report",
                headers=headers,
                timeout=5
            ) as r:
                if r.status == 200:
                    d = await r.json()
                    m = (d.get("markets") or [{}])[0]
                    return {
                        "lp_locked_pct": m.get("lpLockedPct", 0),
                        "lp_burned_pct": m.get("lpBurnedPct", 0),
                        "rugcheck_score": d.get("score", 0),
                    }
        except Exception:
            pass
        return {}

    async def get_helius_security(self, mint: str) -> Dict[str, Any]:
        mint = (mint or "").strip()
        if not mint:
            return {}

        mint_authority_present = None
        freeze_authority_present = None

        acc = await self._helius_rpc("getAccountInfo", [mint, {"encoding": "jsonParsed"}])
        try:
            info = acc.get("value", {}).get("data", {}).get("parsed", {}).get("info", {})
            mint_authority_present = bool(info.get("mintAuthority"))
            freeze_authority_present = bool(info.get("freezeAuthority"))
        except Exception:
            pass

        return {
            "mint_authority_present": mint_authority_present,
            "freeze_authority_present": freeze_authority_present,
            "top10_ratio": None,
            "is_mint_renounced": (not mint_authority_present) if mint_authority_present is not None else None,
        }

    def _pick_gmgn_avatar(self, tab) -> str:
        def _norm_img_url(u: str) -> str:
            u = (u or "").strip()
            if not u:
                return ""
            if u.startswith("//"):
                return "https:" + u
            return u

        def _usable(u: str) -> bool:
            u = _norm_img_url(u)
            if not u:
                return False
            if u.startswith("data:image/"):
                return True
            if not (u.startswith("http://") or u.startswith("https://")):
                return False
            low = u.lower()
            if "gmgn.ai/static" in low or "favicon" in low:
                return False
            return True

        candidate_selectors = [
            'css:img[class*="token"]',
            'css:img[class*="logo"]',
            'css:img[class*="avatar"]',
            'css:img[alt*="token"]',
            'css:img[alt*="logo"]',
            'css:img[alt*="avatar"]',
        ]

        for selector in candidate_selectors:
            try:
                els = tab.eles(selector)
                for img in els or []:
                    for attr in ("src", "data-src", "srcset"):
                        src = _norm_img_url(img.attr(attr) or "")
                        if attr == "srcset" and src:
                            src = _norm_img_url(src.split(",")[0].strip().split(" ")[0])
                        if _usable(src):
                            return src
            except Exception:
                pass

        try:
            meta = tab.run_js("""
                const m = document.querySelector('meta[property="og:image"], meta[name="twitter:image"], meta[property="twitter:image"]');
                return m ? (m.content || '') : '';
            """)
            meta = _norm_img_url(str(meta or ""))
            if _usable(meta):
                return meta
        except Exception:
            pass

        try:
            imgs = tab.eles("tag:img")
            for img in imgs or []:
                cls = (img.attr("class") or "").lower()
                alt = (img.attr("alt") or "").lower()
                for attr in ("src", "data-src", "srcset"):
                    src = _norm_img_url(img.attr(attr) or "")
                    if attr == "srcset" and src:
                        src = _norm_img_url(src.split(",")[0].strip().split(" ")[0])
                    if not _usable(src):
                        continue
                    if any(k in cls for k in ["avatar", "token", "logo"]) or any(k in alt for k in ["avatar", "token", "logo"]):
                        return src

            for img in imgs or []:
                for attr in ("src", "data-src", "srcset"):
                    src = _norm_img_url(img.attr(attr) or "")
                    if attr == "srcset" and src:
                        src = _norm_img_url(src.split(",")[0].strip().split(" ")[0])
                    if _usable(src):
                        return src
        except Exception:
            pass

        return ""

    def _extract_visible_text(self, tab) -> str:
        texts = []

        try:
            body = tab.ele("tag:body")
            if body and body.text:
                texts.append(body.text)
        except Exception:
            pass

        js_snippets = [
            "return document.body ? document.body.innerText : ''",
            "return document.documentElement ? document.documentElement.innerText : ''",
            """
            return Array.from(document.querySelectorAll('main, section, div, aside, span, p, a'))
                .map(el => (el.innerText || '').trim())
                .filter(Boolean)
                .filter(t => t.length >= 2)
                .slice(0, 600)
                .join('\n');
            """,
        ]

        for js in js_snippets:
            try:
                val = tab.run_js(js)
                if val:
                    texts.append(str(val))
            except Exception:
                pass

        uniq = []
        seen = set()
        for t in texts:
            t = (t or "").strip()
            if not t:
                continue
            if t not in seen:
                uniq.append(t)
                seen.add(t)

        return "\n".join(uniq)

    def _normalize_pct_value(self, raw: str) -> Optional[str]:
        if raw is None:
            return None
        s = str(raw).strip()
        if not s:
            return None

        s = (
            s.replace("＋", "+")
             .replace("－", "-")
             .replace("−", "-")
             .replace("–", "-")
             .replace("—", "-")
             .replace("％", "%")
             .replace(" ", "")
        )

        m = re.search(r"([+-]?\d+(?:\.\d+)?)%?$", s)
        if not m:
            return None
        return f"{m.group(1)}%"

    def _extract_gmgn_money_value(self, text: str, labels: List[str], max_gap: int = 18) -> Optional[float]:
        if not text or not labels:
            return None

        txt = str(text).replace("\u00A0", " ")
        label_pat = "|".join(re.escape(x) for x in labels if x)
        patterns = [
            rf"(?:{label_pat})[^\n]{{0,{max_gap}}}?\$?([0-9][0-9\.,]*[KkMmBb]?)",
            rf"(?:{label_pat})\s*[:：]?\s*\$?([0-9][0-9\.,]*[KkMmBb]?)",
        ]

        for pat in patterns:
            m = re.search(pat, txt, re.IGNORECASE)
            if m:
                val = _to_float(m.group(1), 0.0)
                if val > 0:
                    return val
        return None

    def _is_gmgn_shell_page(self, title_text: str, page_text: str) -> bool:
        title_low = str(title_text or "").lower()
        text_low = str(page_text or "").lower()

        generic_title = (
            "fast trade" in title_low and
            "fast copy trade" in title_low and
            "afk automation" in title_low
        )
        content_markers = [
            "top 10", "top10", "holders", "holder", "dev", "smart money", "dex paid",
            "liquidity", "market cap", "24h volume", "价格", "市值", "池子", "持有者",
            "狙击者", "老鼠仓", "捆绑交易", "钓鱼钱包", "dex付费", "烧池子"
        ]
        marker_hits = sum(1 for x in content_markers if x in text_low)
        return generic_title and marker_hits < 3

    def _extract_gmgn_pct(self, text: str, label: str) -> Optional[str]:
        if not text:
            return None

        txt = (
            str(text)
            .replace("\u00A0", " ")
            .replace("＋", "+")
            .replace("－", "-")
            .replace("−", "-")
            .replace("–", "-")
            .replace("—", "-")
            .replace("％", "%")
        )

        label_re = re.escape(label)
        patterns = [
            rf"(?<![A-Za-z0-9]){label_re}(?![A-Za-z0-9])\s*[\.\:：·•\|\-/–—]*\s*([+\-]?\d+(?:\.\d+)?)\s*%",
            rf"(?<![A-Za-z0-9]){label_re}(?![A-Za-z0-9])[\s\r\n]*([+\-]?\d+(?:\.\d+)?)\s*%",
        ]

        for pat in patterns:
            m = re.search(pat, txt, re.IGNORECASE)
            if m:
                return self._normalize_pct_value(m.group(1))

        return None

    def _extract_gmgn_timeframe_changes(self, text: str) -> Dict[str, Any]:
        mapping = [
            ("1m", "chg_1m", "price_change_m1"),
            ("5m", "chg_5m", "price_change_m5"),
            ("15m", "chg_15m", "price_change_m15"),
            ("30m", "chg_30m", "price_change_m30"),
            ("1h", "chg_1h", "price_change_h1"),
            ("3h", "chg_3h", "price_change_h3"),
            ("6h", "chg_6h", "price_change_h6"),
            ("24h", "chg_24h", "price_change_h24"),
        ]

        out: Dict[str, Any] = {}
        for label, key1, key2 in mapping:
            pct = self._extract_gmgn_pct(text, label)
            if pct is not None:
                out[key1] = pct
                out[key2] = pct
        return out

    def _extract_gmgn_top10_ratio(self, text: str) -> Optional[str]:
        if not text:
            return None

        txt = (
            str(text)
            .replace("\u00A0", " ")
            .replace("＋", "+")
            .replace("－", "-")
            .replace("−", "-")
            .replace("–", "-")
            .replace("—", "-")
            .replace("％", "%")
        )

        patterns = [
            r"(?:Top\s*10(?:\s*Holders?)?|Top10(?:\s*Holders?)?|前\s*10(?:持仓|地址|持有者)?|前十(?:持仓|地址|持有者)?)[^\n%]{0,40}?([+\-]?\d+(?:\.\d+)?)\s*%",
            r"(?:Holder(?:s)?\s*Concentration|Top\s*Holder(?:s)?)[^\n%]{0,40}?([+\-]?\d+(?:\.\d+)?)\s*%",
        ]
        for pat in patterns:
            m = re.search(pat, txt, re.IGNORECASE)
            if m:
                return self._normalize_pct_value(m.group(1))

        for line in txt.splitlines():
            line = line.strip()
            if not line:
                continue
            if re.search(r"(?:Top\s*10|Top10|前\s*10|前十)", line, re.IGNORECASE):
                m = re.search(r"([+\-]?\d+(?:\.\d+)?)\s*%", line)
                if m:
                    return self._normalize_pct_value(m.group(1))

        return None

    def _try_save_chart_screenshot(self, tab, ca: str) -> Optional[str]:
        stable_path = self._screenshot_path(ca)
        ca_key = re.sub(r'[^a-zA-Z0-9]', '', ca)[:80]
        unique_path = os.path.join(self.img_dir, f"{ca_key}_{int(time.time() * 1000)}_chart.png")

        try:
            tmp = f"{unique_path}.tmp"
            tab.get_screenshot(path=tmp, full_page=False)

            if os.path.exists(tmp) and os.path.getsize(tmp) > 500:
                os.replace(tmp, unique_path)

                try:
                    stable_tmp = f"{stable_path}.tmp"
                    with open(unique_path, "rb") as src, open(stable_tmp, "wb") as dst:
                        dst.write(src.read())
                        dst.flush()
                        os.fsync(dst.fileno())
                    os.replace(stable_tmp, stable_path)
                except Exception:
                    pass

                return unique_path

            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass

        return self._existing_chart_path(ca)

    def _extract_tag_count(self, text: str, keywords: List[str]) -> Optional[int]:
        if not text:
            return None

        variants = [re.escape(k) for k in keywords if k]
        if not variants:
            return None
        p = "|".join(variants)

        patterns = [
            rf"(?:{p})\s*[:：xX×]?\s*(\d{{1,4}})(?!\s*%)",
            rf"(\d{{1,4}})\s*(?:个|名|位)?\s*(?:{p})",
            rf"(?:{p})[\s\S]{{0,8}}?(\d{{1,4}})(?!\s*%)",
        ]

        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                try:
                    return int(m.group(1))
                except Exception:
                    pass
        return None

    def _inject_gmgn_local_flags(self, tab):
        if not tab:
            return
        try:
            tab.run_js("""
                localStorage.setItem('has_seen_welcome', 'true');
                localStorage.setItem('driver_tutorial_token_sol', 'true');
                localStorage.setItem('risk_warning_accepted', 'true');
            """)
        except Exception:
            pass

    def _wait_gmgn_metrics_ready(self, tab, timeout: float = 4.0, interval: float = 0.35) -> bool:
        if not tab:
            return False

        deadline = time.time() + max(0.5, timeout)
        core_markers = [
            "市值", "market cap", "mcap", "mc",
            "池子", "liquidity", "lp",
            "24h成交额", "24h volume", "volume",
            "top 10", "top10", "持有者", "holder", "holders",
            "dev", "狙击者", "老鼠仓", "捆绑交易", "钓鱼钱包",
            "dex付费", "dex paid", "mint丢弃", "无黑名单", "烧池子",
        ]
        tf_markers = ["1m", "5m", "15m", "30m", "1h", "4h", "6h", "24h", "1d"]

        while time.time() < deadline:
            try:
                txt = self._extract_visible_text(tab)
                title = str(tab.title or "")
                combined = "\n".join([title, txt]).lower()
                if not combined:
                    time.sleep(interval)
                    continue

                core_hits = sum(1 for x in core_markers if x in combined)
                tf_hits = sum(1 for x in tf_markers if x in combined)

                if core_hits >= 3:
                    return True
                if core_hits >= 2 and tf_hits >= 2:
                    return True
                if self._is_gmgn_shell_page(title, txt):
                    return False
            except Exception:
                pass
            time.sleep(interval)

        return False

    def _finish_gmgn_walkthrough(self, tab, max_clicks: int = 12, interval: float = 0.35) -> int:
        if not tab or max_clicks <= 0:
            return 0

        clicked = 0
        selectors = [
            "text=完成",
            "text=Finish",
            "text=Done",
            "text=下一个",
            "text=下一步",
            "text=Next",
            "text=继续",
            "text=Continue",
            "text=Got it",
            "text=I Agree",
            "text=Skip",
            ".ant-modal-close-x",
        ]

        for _ in range(max_clicks):
            clicked_this_round = False

            for selector in selectors:
                try:
                    btn = tab.ele(selector, timeout=0.2)
                    if btn:
                        btn.click(by_js=True)
                        clicked += 1
                        clicked_this_round = True
                        time.sleep(interval)
                        break
                except Exception:
                    pass

            if clicked_this_round:
                continue

            try:
                js_clicked = tab.run_js("""
                    const labels = ['完成', 'Finish', 'Done', '下一个', '下一步', 'Next', '继续', 'Continue', 'Got it', 'I Agree', 'Skip'];
                    const isVisible = (el) => {
                        if (!el) return false;
                        const rect = el.getBoundingClientRect();
                        const style = window.getComputedStyle(el);
                        return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
                    };

                    const roots = Array.from(document.querySelectorAll('.ant-modal, .ant-modal-root, [role="dialog"], .driver-popover, .shepherd-element, .react-joyride__tooltip, .ant-tour, .tour'));
                    for (const label of labels) {
                        for (const root of roots) {
                            if (!isVisible(root)) continue;
                            const nodes = Array.from(root.querySelectorAll('button, [role="button"], .ant-btn, span, div, a'));
                            for (const node of nodes) {
                                const txt = (node.innerText || node.textContent || '').trim();
                                if (!txt || !isVisible(node)) continue;
                                if (txt === label || txt.includes(label)) {
                                    node.click();
                                    return label;
                                }
                            }
                        }
                    }

                    const closeBtn = document.querySelector('.ant-modal-close-x, .ant-modal-close');
                    if (closeBtn && isVisible(closeBtn)) {
                        closeBtn.click();
                        return '__close__';
                    }

                    return '';
                """)
                if js_clicked:
                    clicked += 1
                    time.sleep(interval)
                    continue
            except Exception:
                pass

            break

        return clicked

    def _get_or_create_gmgn_tab(self):
        if not self._browser:
            return None

        saved_state = self._load_gmgn_saved_state()

        if self._gmgn_tab:
            try:
                _ = self._gmgn_tab.url
                self._inject_gmgn_local_flags(self._gmgn_tab)
                if saved_state:
                    self._apply_gmgn_saved_state(self._gmgn_tab, saved_state, include_session=False)
                return self._gmgn_tab
            except Exception:
                self._gmgn_tab = None

        try:
            tab = self._browser.new_tab("https://gmgn.ai/")
            self._gmgn_tab = tab
        except Exception:
            return None

        try:
            tab.wait.ele("tag:body", timeout=6)
        except Exception:
            pass

        self._inject_gmgn_local_flags(tab)
        if saved_state:
            try:
                self._apply_gmgn_saved_state(tab, saved_state, include_session=False)
            except Exception:
                pass

        try:
            self._finish_gmgn_walkthrough(tab, max_clicks=8, interval=0.20)
        except Exception:
            pass

        return tab

    def _sync_scrape_gmgn(self, ca: str) -> Dict[str, Any]:
        result = {
            "is_burned": None,
            "dex_paid": None,
            "header_liq_usd": 0,
            "top10_ratio": None,
            "raw_data": {},
            "screenshot": "",
        }
        if not self._browser:
            return result

        target_url = f"https://gmgn.ai/sol/token/{ca}?chain=sol"
        tab = None
        try:
            tab = self._browser.new_tab(target_url)
            if not tab:
                return result

            try:
                if not tab.ele("css:canvas", timeout=8):
                    tab.ele("tag:body", timeout=6)
            except Exception:
                logger.warning(f"GMGN page wait timed out; continuing best-effort parse: {ca[:8]}...")

            time.sleep(0.8)

            try:
                self._finish_gmgn_walkthrough(tab, max_clicks=12, interval=0.20)
            except Exception:
                pass

            try:
                btn = tab.ele("text:/^(持有者|Holders?|Holder)(\\s|\\d|$)/i", timeout=2.5)
                if btn:
                    btn.click(by_js=True)
                else:
                    arrows = tab.eles("css:.arco-icon-down")
                    for arrow in arrows or []:
                        try:
                            arrow.click(by_js=True)
                        except Exception:
                            pass
                    time.sleep(0.4)
                    btn = tab.ele("text:/^(持有者|Holders?|Holder)/i", timeout=1.5)
                    if btn:
                        btn.click(by_js=True)
            except Exception:
                pass

            try:
                time.sleep(0.3)
                all_btn = tab.ele("text:/^(全部|All)$/i", timeout=1.5)
                if all_btn:
                    all_btn.click(by_js=True)
            except Exception:
                pass

            try:
                self._finish_gmgn_walkthrough(tab, max_clicks=6, interval=0.18)
            except Exception:
                pass

            scroll = 0
            while scroll < 2400:
                try:
                    tab.scroll.down(400)
                except Exception:
                    pass
                scroll += 400
                time.sleep(0.1)
            time.sleep(1.0)

            current_url = str(getattr(tab, "url", "") or "")
            title_text = str(tab.title or "")

            page_text = ""
            try:
                body = tab.ele("tag:body", timeout=1)
                if body and body.text:
                    page_text = body.text
            except Exception:
                page_text = ""

            extra_text = ""
            if not page_text:
                extra_text = self._extract_visible_text(tab)
                if extra_text:
                    logger.warning(f"GMGN body.text unavailable; using visible-text fallback: {ca[:8]}...")
            else:
                try:
                    extra_text = self._extract_visible_text(tab)
                except Exception:
                    extra_text = ""

            combined_parts = [current_url, title_text]
            if page_text:
                combined_parts.append(page_text)
            if extra_text and extra_text != page_text:
                combined_parts.append(extra_text)
            combined_text = "\n".join(part for part in combined_parts if part)

            chart_path = self._try_save_chart_screenshot(tab, ca)
            if chart_path:
                result["screenshot"] = chart_path

            m_sym = re.search(r"^([^\s\$\|]+)", title_text)
            if m_sym:
                result["symbol"] = m_sym.group(1)

            price_val = self._extract_gmgn_money_value(combined_text, ["价格", "price"], max_gap=12)
            if price_val is not None:
                result["price"] = str(price_val)

            mcap_val = self._extract_gmgn_money_value(combined_text, ["市值", "market cap", "mcap", "mc"], max_gap=16)
            if mcap_val is None:
                m_title_cap = re.search(r"\|\s*\$([0-9][0-9\.,]*[KkMmBb]?)\s*\|\s*GMGN", title_text, re.IGNORECASE)
                if m_title_cap:
                    mcap_val = _to_float(m_title_cap.group(1), 0.0)
            if mcap_val is not None and mcap_val > 0:
                result["fdv"] = mcap_val

            vol_val = self._extract_gmgn_money_value(combined_text, ["24h成交额", "24h volume", "volume"], max_gap=16)
            if vol_val is not None:
                result["volume_24h"] = vol_val

            m_age = re.search(r"(?:龄|age)\s*[:：]?\s*(\d+)\s*(m|h|d)", combined_text, re.IGNORECASE)
            if not m_age:
                m_age = re.search(r"(\d+)(m|h|d)\s+(?:Pump|Raydium|Meteora|Moonshot)", combined_text, re.IGNORECASE)
            if m_age:
                val = int(m_age.group(1))
                unit = m_age.group(2).lower()
                if unit == "h":
                    val *= 60
                elif unit == "d":
                    val *= 1440
                result["age_min"] = val

            tf_changes = self._extract_gmgn_timeframe_changes(combined_text)
            if tf_changes:
                result.update(tf_changes)

            liq_val = self._extract_gmgn_money_value(combined_text, ["池子", "liquidity", "lp"], max_gap=12)
            if liq_val is not None:
                result["header_liq_usd"] = liq_val

            m_dex_paid = re.search(r"(?:Dex付费|Dex Paid)[^\n]{0,20}?\$([0-9][0-9\.,]*[KkMmBb]?)", combined_text, re.IGNORECASE)
            if m_dex_paid:
                result["dex_paid"] = _to_float(m_dex_paid.group(1), 0.0) > 0
            elif re.search(r"(?:Dex付费|Dex Paid)", combined_text, re.IGNORECASE):
                result["dex_paid"] = False

            if re.search(r"(?:烧池子|Liquidity Burned|LP Burned)[\s\S]{0,12}?100%", combined_text, re.IGNORECASE):
                result["is_burned"] = True
            elif re.search(r"(?:烧池子|Liquidity Burned|LP Burned)", combined_text, re.IGNORECASE):
                result["is_burned"] = False

            m_top = re.search(r"Top\s*10[\s\S]{0,10}?([\d\.]+%)", page_text or combined_text, re.IGNORECASE)
            if m_top:
                result["top10_ratio"] = self._normalize_pct_value(m_top.group(1))
            else:
                gmgn_top10 = self._extract_gmgn_top10_ratio(combined_text)
                if gmgn_top10:
                    result["top10_ratio"] = gmgn_top10

            raw = {}
            def _count_label(kws: List[str]) -> int:
                p = "|".join(re.escape(k) for k in kws if k)
                for txt in (page_text, combined_text):
                    if not txt or not p:
                        continue
                    m = re.search(rf"(?:{p})[^0-9\n<]*([0-9]+)", txt, re.IGNORECASE)
                    if m:
                        try:
                            return int(m.group(1))
                        except Exception:
                            pass
                cnt = self._extract_tag_count(combined_text, kws)
                return cnt if cnt is not None else 0

            tag_map = {
                "smart": ["Smart Money", "聪明钱", "Smart", "GGer", "GG者", "GG"],
                "rat": ["Rat Farm", "老鼠仓", "Rat"],
                "sniper": ["Sniper", "狙击手", "狙击者"],
                "dev": ["Developer", "Dev", "开发者", "DEV"],
                "bundle": ["Bundled", "Bundle", "Bundler", "捆绑", "捆绑交易", "捆绑者"],
                "kol": ["KOL"],
                "blue_chip": ["Blue Chip", "蓝筹", "蓝筹持有者"],
                "phishing_wallets": ["Phishing", "Fish", "钓鱼钱包"],
            }
            for key, kws in tag_map.items():
                raw[key] = _count_label(kws)
            result["raw_data"] = raw

            token_image_url = self._pick_gmgn_avatar(tab)
            if token_image_url:
                result["logo"] = token_image_url
                result["token_image_url"] = token_image_url
                existing_avatar = self._existing_avatar_path(ca)
                if existing_avatar:
                    result["token_image_path"] = existing_avatar

            raw_alias = result.get("raw_data") or {}
            result["smart_count"] = raw_alias.get("smart")
            result["kol_count"] = raw_alias.get("kol")
            result["blue_chip_count"] = raw_alias.get("blue_chip")
            result["sniper_count"] = raw_alias.get("sniper")
            result["phishing_wallets"] = raw_alias.get("phishing_wallets")
            result["rat_traders"] = raw_alias.get("rat")
            result["dev_count"] = raw_alias.get("dev")
            result["bundle_count"] = raw_alias.get("bundle")
        except Exception as e:
            if "PageDisconnectedError" in str(e) or isinstance(e, PageDisconnectedError):
                self._gmgn_tab = None
                self._browser = None
            logger.debug(f"⚠️ GMGN 抓取异常 ({ca[:6]}...): {e}")
        finally:
            if tab:
                try:
                    tab.close()
                except Exception:
                    pass

        return result

    async def fetch_gmgn_analytics(self, ca: str) -> Dict[str, Any]:
        if not ca:
            return {}
        async with self._gmgn_lock:
            for attempt in range(2):
                if not await self._ensure_browser():
                    return {}
                try:
                    result = await asyncio.to_thread(self._sync_scrape_gmgn, ca)
                except PageDisconnectedError:
                    logger.warning(f"GMGN page disconnected; resetting browser and retrying: {ca[:8]}...")
                    result = {}
                except Exception as e:
                    logger.warning(f"GMGN scrape attempt failed ({attempt + 1}/2): {ca[:8]}... | {e}")
                    result = {}

                raw_data = result.get("raw_data") if isinstance(result, dict) else {}
                has_raw_signal = isinstance(raw_data, dict) and any(_to_int(v, 0) > 0 for v in raw_data.values())
                if result.get("top10_ratio") or result.get("screenshot") or has_raw_signal:
                    return result

                if attempt == 0:
                    logger.warning(f"GMGN scrape returned empty payload; resetting browser and retrying: {ca[:8]}...")
                    await self._reset_browser()
                    continue

                return result if isinstance(result, dict) else {}

            return {}

    async def _get_jupiter_price_only(self, ca: str) -> Tuple[float, str]:
        if not ca:
            return 0.0, ""

        session = await self._get_session()
        headers = {"Accept": "application/json"}
        url = self.jup_lite_price_url
        source = "jupiter_lite"

        if self.jup_api_key:
            url = self.jup_price_url
            headers["x-api-key"] = self.jup_api_key
            source = "jupiter"

        try:
            async with session.get(
                url,
                params={"ids": ca},
                headers=headers,
                timeout=3.0
            ) as resp:
                if resp.status != 200:
                    return 0.0, ""
                data = await resp.json()

                node = None
                if isinstance(data, dict):
                    if ca in data:
                        node = data.get(ca)
                    elif "data" in data and isinstance(data["data"], dict):
                        node = data["data"].get(ca)

                if not isinstance(node, dict):
                    return 0.0, ""

                price = _to_float(node.get("usdPrice"), 0.0)
                return price, source if price > 0 else ""
        except Exception:
            return 0.0, ""

    async def get_price_only(self, ca: str) -> tuple:
        if not ca:
            return 0.0, 0.0

        jup_price, jup_source = await self._get_jupiter_price_only(ca)

        try:
            ds_data = await self._fetch_dexscreener(ca)
            pairs = ds_data.get("pairs", []) if ds_data else []
            if pairs:
                sol_pairs = [p for p in pairs if p.get("chainId") == "solana"]
                best_pair = sol_pairs[0] if sol_pairs else pairs[0]
                dex_price = _to_float(best_pair.get("priceUsd"), 0.0)
                mcap = _to_float(best_pair.get("fdv") or best_pair.get("marketCap"), 0.0)

                if jup_price > 0:
                    logger.debug(f"✅ 极速查价来源: {jup_source} | {ca[:6]}... | price={jup_price}")
                    return jup_price, mcap

                return dex_price, mcap

            if jup_price > 0:
                logger.debug(f"✅ 极速查价来源: {jup_source} | {ca[:6]}... | price={jup_price}")
                return jup_price, 0.0

            return 0.0, 0.0
        except Exception as e:
            if jup_price > 0:
                logger.debug(f"✅ 极速查价来源: {jup_source} | {ca[:6]}... | price={jup_price}")
                return jup_price, 0.0
            logger.debug(f"⚠️ 极速查价 API 超时或失败 ({ca[:6]}...): {e}")
            return 0.0, 0.0

    async def close(self):
        await self._reset_browser()
        if self._session:
            await self._session.close()


fetcher = DataFetcher()


async def get_market_data(ca: str):
    return await fetcher.get_market_data(ca)


async def get_gmgn_analytics(ca: str):
    return await fetcher.fetch_gmgn_analytics(ca)


async def get_helius_security(ca: str):
    return await fetcher.get_helius_security(ca)


async def get_rugcheck_data(ca: str):
    return await fetcher.fetch_rugcheck_data(ca)


async def get_goplus_security(ca: str):
    return await fetcher.fetch_goplus_security(ca)


async def get_price_only(ca: str):
    return await fetcher.get_price_only(ca)
