import aiohttp
import asyncio
import os
import logging
import time
import re
import json
import random
import hashlib
from typing import Optional, Dict, Any, List

from DrissionPage import ChromiumPage, ChromiumOptions
from DrissionPage.errors import PageDisconnectedError

logger = logging.getLogger("DataFetcher")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
]

def _to_float(x, default=0.0) -> float:
    try:
        if not x:
            return default
        if isinstance(x, str):
            x = x.replace(",", "").replace("$", "").strip()
            if "K" in x.upper():
                x = float(x.replace("K", "").replace("k", "")) * 1000
            elif "M" in x.upper():
                x = float(x.replace("M", "").replace("m", "")) * 1000000
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
        
        os.makedirs(self.img_dir, exist_ok=True)
        os.makedirs(self.avatar_dir, exist_ok=True)
        os.makedirs(self.profile_dir, exist_ok=True)

        self.dex_api_url = "https://api.dexscreener.com/latest/dex/tokens/{}"
        self.birdeye_api_key = os.getenv("BIRDEYE_API_KEY", "")
        self.goplus_app_key = os.getenv("GOPLUS_APP_KEY", "")
        self.goplus_app_secret = os.getenv("GOPLUS_APP_SECRET", "")
        
        self._goplus_token = ""
        self._goplus_token_expire = 0
        
        self._session: Optional[aiohttp.ClientSession] = None
        self._browser: Optional[ChromiumPage] = None
        self._browser_lock = asyncio.Lock()
        self._ca_locks: Dict[str, asyncio.Lock] = {}
        self._ca_locks_lock = asyncio.Lock()

        self.helius_api_key = (os.getenv("HELIUS_API_KEY") or "").strip()
        self.helius_rpc_url = f"https://mainnet.helius-rpc.com/?api-key={self.helius_api_key}" if self.helius_api_key else ""

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
        return self._session

    async def prepare_browser_profile(self):
        # 🟢 修改 1：取消繁琐的手动配置窗口。后续由屏幕外隐形浏览器自动处理页面抓取
        if not os.path.exists(self.profile_dir):
            os.makedirs(self.profile_dir, exist_ok=True)
        logger.info("✅ 浏览器持久化引擎已就绪 (屏幕外隐形模式)")
        return

    def _init_browser_sync(self) -> bool:
        try:
            if self._browser and getattr(self._browser, "process_id", None):
                return True
            co = ChromiumOptions().set_user_data_path(self.profile_dir)
            
            # 🟢 修改 2：关闭无头模式以绕过 CF 盾，并将窗口推至屏幕外 32000 像素，实现绝对隐形
            co.headless(False) 
            co.set_argument('--window-position=-32000,-32000') 
            
            # 🟢 修改 3：强制锁死 1080P 分辨率渲染，防止屏幕外页面排版折叠导致抓取失败
            co.set_argument('--window-size=1920,1080') 
            co.set_argument('--disable-popup-blocking')
            co.set_argument('--disable-notifications')
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
            self._browser = None

    async def _get_ca_lock(self, ca):
        async with self._ca_locks_lock:
            if ca not in self._ca_locks:
                self._ca_locks[ca] = asyncio.Lock()
            return self._ca_locks[ca]

    def _avatar_path(self, ca):
        return os.path.join(self.avatar_dir, f"{re.sub(r'[^a-zA-Z0-9]', '', ca)[:80]}.jpg")
    
    def _normalize_image_url(self, url: str) -> str:
        if not url:
            return ""
        u = str(url).strip()
        if u.startswith("ipfs://"):
            return "https://ipfs.io/ipfs/" + u.replace("ipfs://", "").lstrip("/")
        return u

    async def _download_image_cached(self, ca, url):
        url = self._normalize_image_url(url)
        if not url.startswith("http"):
            return None
            
        path = self._avatar_path(ca)
        lock = await self._get_ca_lock(f"avatar:{ca}")
        
        async with lock:
            if os.path.exists(path) and os.path.getsize(path) > 50:
                return path
            try:
                session = await self._get_session()
                headers = {
                    "User-Agent": random.choice(USER_AGENTS),
                    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8"
                }
                async with session.get(url, headers=headers, ssl=False, timeout=8) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        if len(data) > 50: 
                            with open(path, "wb") as f:
                                f.write(data)
                            return path
                    else:
                        logger.debug(f"头像下载失败 HTTP {resp.status}: {url}")
            except Exception as e: 
                logger.debug(f"头像下载异常 {url}: {e}")
            return None

    async def _fetch_birdeye_overview(self, mint: str) -> Optional[Dict]:
        if not self.birdeye_api_key:
            return None
        try:
            session = await self._get_session()
            headers = {
                "X-API-KEY": self.birdeye_api_key, 
                "accept": "application/json", 
                "x-chain": "solana"
            }
            async with session.get(f"https://public-api.birdeye.so/defi/token_overview?address={mint}", headers=headers, timeout=5) as resp:
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
            async with session.post(self.helius_rpc_url, json={"jsonrpc":"2.0","id":1,"method":method,"params":params}) as r:
                if r.status == 200:
                    return (await r.json()).get("result")
        except Exception:
            pass
        return None

    async def get_market_data(self, ca: str) -> Optional[Dict[str, Any]]:
        async def _fetch_dexscreener():
            try:
                session = await self._get_session()
                headers = {"User-Agent": random.choice(USER_AGENTS)}
                async with session.get(f"{self.dex_api_url.format(ca)}?t={int(time.time())}", headers=headers, timeout=5) as resp:
                    if resp.status == 200:
                        return await resp.json()
            except Exception:
                pass
            return None

        ds_data, be_data = await asyncio.gather(_fetch_dexscreener(), self._fetch_birdeye_overview(ca))
        result = {}
        pairs = ds_data.get("pairs", []) if ds_data else []
        
        if pairs:
            valid = [p for p in pairs if _to_float((p.get("liquidity") or {}).get("usd")) > 100.0]
            if not valid:
                valid = pairs 
                
            best = max(valid, key=lambda p: _to_float((p.get("liquidity") or {}).get("usd")))
            info = best.get("info", {})
            is_dex_paid = bool(info.get("imageUrl") or info.get("socials") or info.get("websites"))

            result = {
                "symbol": (best.get("baseToken") or {}).get("symbol", "UNK"),
                "name": (best.get("baseToken") or {}).get("name", ""),
                "price_usd": best.get("priceUsd", "0"),
                "liquidity_usd": _to_float((best.get("liquidity") or {}).get("usd"), 0),
                "mcap": _to_float(best.get("marketCap") or best.get("fdv"), 0),
                "pair_address": best.get("pairAddress"),
                "dex_id": best.get("dexId", "").lower(),
                "token_image_url": info.get("imageUrl") or (best.get("baseToken") or {}).get("logoURI"),
                "chg_5m": (best.get("priceChange") or {}).get("m5"),
                "chg_1h": (best.get("priceChange") or {}).get("h1"),
                "chg_6h": (best.get("priceChange") or {}).get("h6"),
                "chg_24h": (best.get("priceChange") or {}).get("h24"),
                "volume_h24": _to_float((best.get("volume") or {}).get("h24"), 0),
                "txns": best.get("txns", {}),
                "dex_paid": is_dex_paid
            }
            
            h24 = result["txns"].get("h24", {})
            result["buys_24h"] = _to_int(h24.get("buys", 0))
            result["sells_24h"] = _to_int(h24.get("sells", 0))
            result["buy_sell_ratio"] = result["buys_24h"] / result["sells_24h"] if result["sells_24h"] > 0 else 999.0
            
            created = best.get("pairCreatedAt")
            result["token_age_min"] = max(0, int((time.time() * 1000 - created) / 60000)) if created else 0
        else:
            result = {
                "liquidity_usd": 0, 
                "token_age_min": 0, 
                "symbol": "UNK"
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

        if not result.get("token_image_url") and ca.lower().endswith("pump"):
            try:
                session = await self._get_session()
                headers = {"User-Agent": random.choice(USER_AGENTS)}
                async with session.get(f"https://frontend-api.pump.fun/coins/{ca}", headers=headers, timeout=3.0) as resp:
                    if resp.status == 200:
                        pump_data = await resp.json()
                        result["token_image_url"] = pump_data.get("image_uri")
                        if result.get("symbol") == "UNK":
                            result["symbol"] = pump_data.get("symbol", "UNK")
                        if not result.get("name"):
                            result["name"] = pump_data.get("name", "")
            except Exception as e:
                logger.debug(f"⚠️ Pump底层接口抓取头像失败: {e}")
                
        if result.get("token_image_url"):
            result["token_image_path"] = await self._download_image_cached(ca, result["token_image_url"])
            
        result["cap_usd"] = result.get("mcap") or result.get("fdv") or 0
        return result 

    async def _get_goplus_token(self) -> Optional[str]:
        if not self.goplus_app_key or not self.goplus_app_secret:
            return None
            
        now = time.time()
        if self._goplus_token and now < self._goplus_token_expire:
            return self._goplus_token
            
        t = str(int(now))
        sign_str = self.goplus_app_key + t + self.goplus_app_secret
        sign = hashlib.sha1(sign_str.encode('utf-8')).hexdigest()
        
        try:
            session = await self._get_session()
            payload = {"app_key": self.goplus_app_key, "sign": sign, "time": t}
            async with session.post("https://api.gopluslabs.io/api/v1/token", json=payload, timeout=5) as r:
                if r.status == 200:
                    data = await r.json()
                    if data.get("code") == 1:
                        token_info = data.get("result") or data.get("data") or {}
                        self._goplus_token = token_info.get("access_token")
                        self._goplus_token_expire = now + float(token_info.get("expires_in", 7200)) - 60
                        logger.info("🔐 GoPlus 鉴权成功")
                        return self._goplus_token
        except Exception as e:
            logger.error(f"⚠️ GoPlus Token 获取失败: {e}")
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
            async with session.get(f"https://api.gopluslabs.io/api/v1/token_security/solana?contract_addresses={ca}", headers=headers, timeout=5) as r:
                if r.status == 200:
                    d = await r.json()
                    res = d.get("result", {}).get(ca.lower(), {})
                    return {
                        "is_honeypot": res.get("is_honeypot") == "1", 
                        "is_blacklisted": res.get("is_blacklisted") == "1",
                        "is_mintable": res.get("is_mintable") == "1",
                        "transfer_pausable": res.get("transfer_pausable") == "1"
                    }
        except Exception:
            pass
        return {}

    async def fetch_rugcheck_data(self, mint: str) -> Dict[str, Any]:
        if not mint:
            return {}
            
        headers = {
            "User-Agent": random.choice(USER_AGENTS), 
            "Accept": "application/json"
        }
        
        try:
            session = await self._get_session()
            async with session.get(f"https://api.rugcheck.xyz/v1/tokens/{mint}/report", headers=headers, timeout=5) as r:
                if r.status == 200:
                    d = await r.json()
                    m = (d.get("markets") or [{}])[0]
                    return {
                        "lp_locked_pct": m.get("lpLockedPct", 0), 
                        "lp_burned_pct": m.get("lpBurnedPct", 0), 
                        "rugcheck_score": d.get("score", 0)
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
        top10_ratio = None
        
        acc = await self._helius_rpc("getAccountInfo", [mint, {"encoding": "jsonParsed"}])
        try:
            info = acc.get("value", {}).get("data", {}).get("parsed", {}).get("info", {})
            mint_authority_present = bool(info.get("mintAuthority"))
            freeze_authority_present = bool(info.get("freezeAuthority"))
            supply_ui = float(info.get("supply", 0)) / (10 ** int(info.get("decimals", 9)))
        except Exception:
            supply_ui = 0
        
        largest = await self._helius_rpc("getTokenLargestAccounts", [mint])
        try:
            vals = (largest or {}).get("value") or []
            sum_ui = 0.0
            valid_count = 0
            for x in vals:
                amt = float(x.get("uiAmount") or 0)
                pct = (amt / supply_ui) * 100.0 if supply_ui > 0 else 0
                if pct > 45.0:
                    continue
                sum_ui += amt
                valid_count += 1
                if valid_count >= 10:
                    break

            if supply_ui > 0: 
                ratio = (sum_ui / supply_ui) * 100.0
                top10_ratio = f"{ratio if ratio <= 100 else 100:.1f}%"
        except Exception:
            pass
        
        return {
            "mint_authority_present": mint_authority_present,
            "freeze_authority_present": freeze_authority_present,
            "top10_ratio": top10_ratio,
            "is_mint_renounced": not mint_authority_present
        }

    def _sync_scrape_gmgn(self, ca: str) -> Dict[str, Any]:
        result = {
            "is_burned": None, 
            "dex_paid": None, 
            "header_liq_usd": 0, 
            "top10_ratio": None, 
            "raw_data": {}
        }
        if not self._browser:
            return result
        
        tab = None 
        try:
            # 🟢 并发隔离：虽然转成了后台静默运行，但底层依然会新开“隐形”标签页防止多币种串行冲突
            tab = self._browser.new_tab(f"https://gmgn.ai/sol/token/{ca}?chain=sol")
            
            # 🟢 核心修复3：光速注入 LocalStorage，彻底封印新手引导教程和免责声明弹窗
            try:
                tab.run_js("""
                    localStorage.setItem('has_seen_welcome', 'true');
                    localStorage.setItem('driver_tutorial_token_sol', 'true');
                    localStorage.setItem('risk_warning_accepted', 'true');
                """)
            except Exception:
                pass

            try:
                tab.wait.ele("tag:body", timeout=10)
            except Exception:
                pass
            
            # ⚠️ 严格遵照你的要求：保持 3.5 秒等待和原版代码逻辑不动
            time.sleep(3.5) 
            
            # 🟢 核心修复4：主动扫荡页面上的残留防空炮弹窗（针对突发的 TG加群 / 登录注册 遮罩层）
            try:
                for selector in ['.ant-modal-close-x', 'text=Skip', 'text=Got it', 'text=Next', 'text=I Agree']:
                    btn = tab.ele(selector, timeout=0.2)
                    if btn:
                        btn.click(by_js=True)
            except Exception:
                pass
            
            page_text = tab.ele("tag:body").text if tab.ele("tag:body") else ""
            title_text = tab.title or ""

            m_sym = re.search(r"^([^\s\$]+)", title_text)
            if m_sym:
                result["symbol"] = m_sym.group(1)

            for tf in ["1m", "5m", "15m", "30m", "1h", "6h", "24h"]:
                m_tf = re.search(rf"{tf}\s*([+-]?[\d\.]+%?)", page_text, re.IGNORECASE)
                if m_tf:
                    result[f"chg_{tf}"] = m_tf.group(1)

            m_liq = re.search(r"池子\s*\$?([0-9\.\,KkMmBb]+)", page_text)
            if m_liq:
                result["header_liq_usd"] = _to_float(m_liq.group(1))

            if re.search(r"Dex付费\s*(?:\$299|CTO)", page_text, re.IGNORECASE):
                result["dex_paid"] = True
            elif re.search(r"Dex付费", page_text):
                result["dex_paid"] = False

            if re.search(r"烧池子[\s\S]{0,10}100%", page_text) or re.search(r"Liquidity Burned", page_text, re.IGNORECASE):
                result["is_burned"] = True
            elif re.search(r"烧池子", page_text):
                result["is_burned"] = False

            m_top = re.search(r"Top\s*10[\s\S]{0,10}?([\d\.]+%)", page_text, re.IGNORECASE)
            if m_top:
                result["top10_ratio"] = m_top.group(1)

            raw = {}
            def check(key, kws):
                p = "|".join([re.escape(k) for k in kws])
                m = re.search(rf"(?:{p})\s+(\d+)(?!\s*%)", page_text, re.IGNORECASE)
                raw[key] = int(m.group(1)) if m else 0
                
            check("smart", ["Smart Money", "聪明钱"])
            check("rat", ["Rat Farm", "老鼠仓"])
            check("sniper", ["Sniper", "狙击手", "狙击者"])
            check("dev", ["Developer", "Dev", "开发者"])
            check("bundle", ["捆绑交易", "Bundle"])
            check("kol", ["KOL"])
            check("blue_chip", ["蓝筹持有者", "Blue Chip"])
            check("phishing_wallets", ["钓鱼钱包", "Phishing"])
            result["raw_data"] = raw

            if not result.get("token_image_url"):
                try:
                    imgs = tab.eles('tag:img')
                    for img in imgs:
                        src = img.attr("src")
                        if src and src.startswith("http") and ".svg" not in src.lower() and "logo" not in src.lower():
                            result["token_image_url"] = src
                            break
                except Exception:
                    pass

            tab.close()
        except Exception as e:
            if tab: 
                try:
                    tab.close()
                except Exception:
                    pass
            if "PageDisconnectedError" in str(e):
                self._browser = None
                
        return result

    async def fetch_gmgn_analytics(self, ca: str) -> Dict[str, Any]:
        if not ca:
            return {}
        if not await self._ensure_browser():
            return {}
        return await asyncio.to_thread(self._sync_scrape_gmgn, ca)

    # 🟢 新增：极速单值查价接口，供主程序防刷屏与轮询使用
    async def get_price_only(self, ca: str) -> tuple:
        """极速单值查价接口：仅返回 (price, mcap)，供高频轮询与验价引擎使用"""
        if not ca: return 0.0, 0.0
        try:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{ca}"
            session = await self._get_session()
            headers = {"User-Agent": random.choice(USER_AGENTS)}
            # 限制 3 秒内必须返回，绝不阻塞主线程
            async with session.get(url, headers=headers, timeout=3.0) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    pairs = data.get("pairs", [])
                    if pairs:
                        # 优先选择 Solana 链的池子
                        sol_pairs = [p for p in pairs if p.get("chainId") == "solana"]
                        best_pair = sol_pairs[0] if sol_pairs else pairs[0]
                        price = float(best_pair.get("priceUsd", 0) or 0)
                        mcap = float(best_pair.get("fdv", 0) or best_pair.get("marketCap", 0) or 0)
                        return price, mcap
            return 0.0, 0.0
        except Exception as e:
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

# 🟢 暴露全局接口给主程序
async def get_price_only(ca: str):
    return await fetcher.get_price_only(ca)