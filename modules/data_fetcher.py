import aiohttp
import asyncio
import os
import logging
import time
import re
import json
from typing import Optional, Dict, Any

from DrissionPage import ChromiumPage, ChromiumOptions
from DrissionPage.errors import PageDisconnectedError

logger = logging.getLogger("DataFetcher")


def _to_float(x, default=0.0) -> float:
    try:
        if x is None:
            return default
        return float(x)
    except:
        return default


def _to_int(x, default=0) -> int:
    try:
        if x is None:
            return default
        return int(float(x))
    except:
        return default


class DataFetcher:
    def __init__(self):
        self.img_dir = "data/charts"
        os.makedirs(self.img_dir, exist_ok=True)
        self.api_url = "https://api.dexscreener.com/latest/dex/tokens/{}"
        self._session: Optional[aiohttp.ClientSession] = None
        self._browser: Optional[ChromiumPage] = None
        self._browser_lock = asyncio.Lock()
        self._ca_locks: Dict[str, asyncio.Lock] = {}
        self._ca_locks_lock = asyncio.Lock()
        self.screenshot_ttl_sec = 120

        # 选池配置
        self.min_liq_usd_filter = 100.0
        self.min_liq_usd_for_hot = 1000.0

        # 浏览器配置
        self.headless = False  # 调试模式设为 False
        self.window_w = 1280
        self.window_h = 800

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
        return self._session

    def _init_browser_sync(self) -> bool:
        try:
            if self._browser and getattr(self._browser, "process_id", None):
                return True
            logger.info("🚀 启动浏览器 (DrissionPage)...")
            co = ChromiumOptions()
            co.headless(self.headless)
            co.auto_port()
            co.set_argument("--no-sandbox")
            co.set_argument("--disable-gpu")
            co.set_argument("--start-maximized")
            co.set_argument("--disable-notifications")
            co.mute(True)

            self._browser = ChromiumPage(co)
            self._browser.set.window.size(self.window_w, self.window_h)
            return True
        except Exception as e:
            logger.error(f"❌ 浏览器启动失败: {e}")
            self._browser = None
            return False

    async def _ensure_browser(self) -> bool:
        async with self._browser_lock:
            if self._browser and getattr(self._browser, "process_id", None):
                return True
            return await asyncio.to_thread(self._init_browser_sync)

    async def _reset_browser(self):
        async with self._browser_lock:
            if self._browser:
                try:
                    await asyncio.to_thread(self._browser.quit)
                except:
                    pass
            self._browser = None

    async def _get_ca_lock(self, ca: str) -> asyncio.Lock:
        async with self._ca_locks_lock:
            if ca not in self._ca_locks:
                self._ca_locks[ca] = asyncio.Lock()
            return self._ca_locks[ca]

    # -----------------------
    # DexScreener (保持不变)
    # -----------------------
    def _pair_score(self, p: Dict[str, Any]) -> float:
        liq = _to_float((p.get("liquidity") or {}).get("usd"), 0.0)
        vol24 = _to_float((p.get("volume") or {}).get("h24"), 0.0)
        tx = (p.get("txns") or {}).get("m5") or {}
        m5 = _to_int(tx.get("buys")) + _to_int(tx.get("sells"))
        hot_weight = 1.0 if liq >= self.min_liq_usd_for_hot else 0.2
        import math
        return math.log1p(liq) * 4.0 + math.log1p(vol24) * 2.0 + math.log1p(m5) * 3.0 * hot_weight

    async def get_market_data(self, ca: str) -> Optional[Dict[str, Any]]:
        ca = (ca or "").strip()
        if not ca:
            return None
        try:
            session = await self._get_session()
            url = f"{self.api_url.format(ca)}?t={int(time.time()*1000)}"
            async with session.get(url, headers={"Cache-Control": "no-cache"}) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                pairs = data.get("pairs", [])
                if not pairs:
                    return None
                valid = [p for p in pairs if _to_float((p.get("liquidity") or {}).get("usd")) > self.min_liq_usd_filter] or pairs
                best = max(valid, key=self._pair_score)

                fdv = _to_float(best.get("fdv"), 0.0)
                mcap = _to_float(best.get("marketCap"), 0.0)
                cap_usd = fdv if fdv > 0 else mcap

                return {
                    "symbol": (best.get("baseToken") or {}).get("symbol", "UNK"),
                    "name": (best.get("baseToken") or {}).get("name", "Unknown"),
                    "price_usd": best.get("priceUsd", "0"),
                    "fdv": fdv, "mcap": mcap, "cap_usd": cap_usd,
                    "liquidity_usd": _to_float((best.get("liquidity") or {}).get("usd"), 0.0),
                    "volume_h24": _to_float((best.get("volume") or {}).get("h24"), 0.0),
                    "pair_url": best.get("url", "")
                }
        except:
            return None

    # -----------------------
    # ✅ GMGN Scraper（弹窗关闭增强）
    # -----------------------
    def _popup_killer(self, tab, rounds: int = 10) -> None:
        """
        DrissionPage 版本“像人一样”的关弹窗：
        - 多轮处理（Next->Next->Done）
        - 先删遮罩，再点 close icon，再点文本按钮，最后 ESC
        """
        # 覆盖更多常见遮罩/弹窗容器
        remove_selectors = [
            ".arco-modal-mask",
            ".arco-modal-wrapper",
            ".guide-modal",
            "div[role='dialog']",
            "div[aria-modal='true']",
            "div[class*='overlay']",
            "div[class*='modal']",
            "div[class*='dialog']",
            "div[class*='mask']",
            "div[class*='backdrop']",
        ]

        # 文本按钮（多语种）
        text_btns = [
            "Skip", "Close", "Next", "Done", "OK", "Got it", "I know", "Agree", "Continue",
            "跳过", "关闭", "下一步", "完成", "知道了", "确定", "同意", "继续"
        ]

        # icon close（无文本）
        icon_selectors = [
            "[aria-label*='close' i]",
            "[aria-label*='关闭' i]",
            "[title*='close' i]",
            "[title*='关闭' i]",
            "[data-testid*='close' i]",
            "[class*='close' i]",
            "button[aria-label]",
            "button[title]"
        ]

        for _ in range(max(1, rounds)):
            # 1) 删除遮罩/弹窗容器
            for sel in remove_selectors:
                try:
                    ele = tab.ele(f"css:{sel}", timeout=0.1)
                    if ele:
                        tab.run_js("arguments[0].remove()", ele)
                except:
                    pass

            # 2) 点 icon close（最像“×”）
            clicked = False
            for sel in icon_selectors:
                try:
                    btn = tab.ele(f"css:{sel}", timeout=0.15)
                    if btn:
                        btn.click(by_js=True)
                        clicked = True
                        break
                except:
                    pass
            if clicked:
                time.sleep(0.2)
                continue

            # 3) 点文本按钮（可能需要多次 Next）
            for t in text_btns:
                try:
                    btn = tab.ele(f"text:{t}", timeout=0.15)
                    if btn:
                        btn.click(by_js=True)
                        clicked = True
                        break
                except:
                    pass
            if clicked:
                time.sleep(0.2)
                continue

            # 4) ESC（部分弹窗支持）
            try:
                tab.run_js(
                    "document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',code:'Escape',keyCode:27,which:27,bubbles:true}));"
                )
            except:
                pass

            time.sleep(0.15)

    def _sync_scrape_gmgn(self, ca: str, file_path: str, meta_path: str) -> Dict[str, Any]:
        result = {"screenshot": None, "tags": [], "top10": None, "avg_hold": None, "raw_data": {}}
        if not self._browser:
            return result

        url = f"https://gmgn.ai/sol/token/{ca}?chain=sol"
        tab = None
        try:
            tab = self._browser.new_tab(url)

            # 等待一个关键元素出现（canvas 或 body），更稳
            if not tab.ele("css:canvas", timeout=12):
                tab.ele("tag:body", timeout=6)

            # ✅ 关键：多轮关弹窗（比你原来的一次性更稳）
            self._popup_killer(tab, rounds=12)

            # 点击 Holders
            try:
                btn = tab.ele("text:/^(持有者|Holders?|Holder)(\\s|\\d|$)/i", timeout=3)
                if btn:
                    btn.click(by_js=True)
                else:
                    arrows = tab.eles("css:.arco-icon-down")
                    for a in arrows:
                        try:
                            a.click(by_js=True)
                        except:
                            pass
                    time.sleep(0.5)
                    btn2 = tab.ele("text:/^(持有者|Holders?|Holder)/i", timeout=2)
                    if btn2:
                        btn2.click(by_js=True)
            except:
                pass

            # 点击 All/全部
            try:
                time.sleep(0.4)
                all_btn = tab.ele("text:/^(全部|All)$/i", timeout=2)
                if all_btn:
                    all_btn.click(by_js=True)
            except:
                pass

            # 再关一次弹窗（切tab/筛选后可能再弹）
            self._popup_killer(tab, rounds=6)

            # 滚动
            scroll = 0
            while scroll < 2500:
                try:
                    tab.scroll.down(400)
                except:
                    pass
                scroll += 400
                time.sleep(0.1)
            time.sleep(1.2)

            # ✅ 获取文本（你的兼容方案保留）
            page_text = ""
            try:
                if hasattr(tab, "text"):
                    page_text = tab.text
                elif tab.ele("tag:body"):
                    page_text = tab.ele("tag:body").text
                elif hasattr(tab, "raw_text"):
                    page_text = tab.raw_text
            except Exception as e:
                logger.warning(f"⚠️ 获取页面文本受阻: {e}")

            if not page_text:
                page_text = ""

            # 提取数据
            def get_cnt(kws):
                p = "|".join([re.escape(k) for k in kws])
                m = re.search(f"(?:{p})[^0-9\\n<]*([0-9]+)", page_text, re.IGNORECASE)
                return int(m.group(1)) if m else 0

            tags = []
            raw = {}

            def process_tag(emoji, name, keys, key_name):
                c = get_cnt(keys)
                raw[key_name] = c
                if c > 0:
                    tags.append(f"{emoji} {name}({c})")

            process_tag("🧠", "聪明钱", ["Smart Money", "聪明钱"], "smart")
            process_tag("💎", "蓝筹", ["Blue Chip", "蓝筹"], "blue_chip")
            process_tag("🐀", "老鼠仓", ["Rat Farm", "老鼠仓"], "rat")
            process_tag("👨‍💻", "KOL", ["KOL"], "kol")
            process_tag("🔫", "狙击手", ["Sniper", "狙击手"], "sniper")
            process_tag("🤖", "Bot", ["Bot Degen"], "degen")
            process_tag("📦", "捆绑", ["Bundled", "捆绑"], "bundle")
            process_tag("👨‍🔧", "DEV", ["Developer", "Dev", "开发者"], "dev")

            result["tags"] = tags
            result["raw_data"] = raw

            try:
                m = re.search(r"Top\s*10\s*[:\s]*([\d\.]+%?)", page_text, re.IGNORECASE)
                if m:
                    result["top10"] = m.group(1)
            except:
                pass

            try:
                m = re.search(r"(?:人均持币|Avg Amount|Avg Cost)(?:金额)?\s*\$?([\d,.]+)", page_text, re.IGNORECASE)
                if m:
                    result["avg_hold"] = f"${m.group(1)}"
            except:
                pass

            logger.info(f"🏷️ GMGN: {tags} | Top10: {result['top10']}")

            tab.get_screenshot(path=file_path, full_page=False)
            result["screenshot"] = file_path

            meta = {
                "ts": time.time(),
                "ca": ca,
                "tags": result["tags"],
                "top10": result.get("top10"),
                "avg_hold": result.get("avg_hold"),
                "raw_data": raw,
            }
            try:
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump(meta, f, ensure_ascii=False, indent=2)
            except:
                pass

        except Exception as e:
            logger.error(f"GMGN Scrape Error: {e}")
        finally:
            if tab:
                try:
                    tab.close()
                except:
                    pass
        return result

    # -----------------------
    # Async Entry
    # -----------------------
    def _safe_ca_for_filename(self, ca: str) -> str:
        safe = re.sub(r"[^1-9A-HJ-NP-Za-km-z]", "", ca or "")
        return safe[:80] if safe else "unknown"

    def _is_cache_valid(self, file_path: str) -> bool:
        try:
            if not os.path.exists(file_path):
                return False
            return (time.time() - os.path.getmtime(file_path)) <= self.screenshot_ttl_sec
        except:
            return False

    def _read_meta(self, meta_path: str) -> Dict[str, Any]:
        try:
            if not os.path.exists(meta_path):
                return {}
            with open(meta_path, "r", encoding="utf-8") as f:
                return json.load(f) or {}
        except:
            return {}

    async def fetch_gmgn_analytics(self, ca: str) -> Dict[str, Any]:
        ca = (ca or "").strip()
        if not ca:
            return {}
        safe_ca = self._safe_ca_for_filename(ca)
        file_path = os.path.join(self.img_dir, f"{safe_ca}.png")
        meta_path = os.path.join(self.img_dir, f"{safe_ca}.json")

        lock = await self._get_ca_lock(safe_ca)
        async with lock:
            if self._is_cache_valid(file_path):
                meta = self._read_meta(meta_path)
                return {
                    "screenshot": file_path,
                    "tags": meta.get("tags", []),
                    "top10": meta.get("top10"),
                    "avg_hold": meta.get("avg_hold"),
                    "raw_data": meta.get("raw_data", {}),
                    "cached": True
                }

            if not await self._ensure_browser():
                return {}

            for attempt in range(2):
                try:
                    return await asyncio.to_thread(self._sync_scrape_gmgn, ca, file_path, meta_path)
                except PageDisconnectedError:
                    await self._reset_browser()
                    if attempt == 0 and await self._ensure_browser():
                        continue
                    return {}
                except Exception as e:
                    logger.error(f"fetch_gmgn_analytics error: {e}")
                    await self._reset_browser()
                    if attempt == 0 and await self._ensure_browser():
                        continue
                    return {}
            return {}

    async def close(self):
        await self._reset_browser()
        if self._session:
            try:
                await self._session.close()
            except:
                pass
            self._session = None


fetcher = DataFetcher()

async def get_market_data(ca: str):
    return await fetcher.get_market_data(ca)

async def get_gmgn_analytics(ca: str):
    return await fetcher.fetch_gmgn_analytics(ca)
