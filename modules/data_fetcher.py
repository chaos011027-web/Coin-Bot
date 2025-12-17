import aiohttp
import asyncio
import os
import logging
from DrissionPage import ChromiumPage, ChromiumOptions

logger = logging.getLogger("DataFetcher")

class DataFetcher:
    def __init__(self):
        # 1. 基础配置
        self.img_dir = "data/charts"
        os.makedirs(self.img_dir, exist_ok=True)
        self.api_url = "https://api.dexscreener.com/latest/dex/tokens/{}"

        # 2. 初始化 DrissionPage 配置 (单例模式，避免重复开关浏览器)
        # 使用无头模式 (Headless) 在后台运行
        co = ChromiumOptions()
        co.headless(True)  # 开启无头模式 (不显示界面)
        co.set_argument('--no-sandbox')  # Linux 服务器防报错
        co.set_argument('--disable-gpu')
        
        # 自动静音音频
        co.mute(True)
        
        # 初始化浏览器对象
        # 注意: 第一次运行时会自动寻找本地 Chrome/Edge
        try:
            self.page = ChromiumPage(co)
            # 设置一个较小的视窗，模拟手机/平板，减少截图体积
            self.page.set.window.size(1280, 800)
        except Exception as e:
            logger.error(f"浏览器初始化失败: {e}")
            self.page = None

    async def get_market_data(self, ca: str):
        """
        获取基础市场数据 (API) - 保持异步高并发
        """
        url = self.api_url.format(ca)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=8) as resp:
                    if resp.status != 200:
                        logger.warning(f"DexScreener API 状态码: {resp.status}")
                        return None
                    
                    data = await resp.json()
                    pairs = data.get("pairs", [])
                    
                    if not pairs:
                        logger.info(f"API 返回为空，可能代币未收录: {ca}")
                        return None

                    # 逻辑优化：寻找 liquidity 最大的 Sol 交易对，而不是无脑取第一个
                    # 有时候第一个可能是 Raydium 的小池子，我们要找主池
                    best_pair = max(pairs, key=lambda x: x.get("liquidity", {}).get("usd", 0))

                    return {
                        "symbol": best_pair.get("baseToken", {}).get("symbol", "UNK"),
                        "name": best_pair.get("baseToken", {}).get("name", "Unknown"),
                        "price": best_pair.get("priceUsd", "0"),
                        "mcap": best_pair.get("fdv", 0), # FDV ≈ Mcap for new coins
                        "liquidity": best_pair.get("liquidity", {}).get("usd", 0),
                        "volume_h1": best_pair.get("volume", {}).get("h1", 0),
                        "volume_h24": best_pair.get("volume", {}).get("h24", 0),
                        "pair_created_at": best_pair.get("pairCreatedAt", 0),
                        "url": best_pair.get("url", "")
                    }
        except asyncio.TimeoutError:
            logger.warning(f"API 请求超时: {ca}")
            return None
        except Exception as e:
            logger.error(f"获取市场数据异常 [{ca}]: {e}")
            return None

    def _sync_take_screenshot(self, ca: str, file_path: str):
        """
        [同步内部函数] 实际执行截图逻辑
        DrissionPage 是同步库，必须放在这里面跑
        """
        if not self.page:
            return None

        # 构造 URL (DexScreener Embed 模式，干净无广告)
        target_url = f"https://dexscreener.com/solana/{ca}?embed=1&theme=dark&info=0"
        
        try:
            # 新建标签页，防止干扰
            tab = self.page.new_tab(target_url)
            
            # 等待加载策略：等待 K 线画布 (Canvas) 出现
            # 最多等 8 秒，等不到就硬截
            if tab.wait.ele('css:canvas', timeout=8):
                # 额外给 1.5 秒让 K 线画完
                tab.wait(1.5)
            
            # 截图
            tab.get_screenshot(path=file_path, full_page=False)
            
            # 关掉标签页释放内存
            tab.close()
            
            return file_path
        except Exception as e:
            logger.error(f"截图过程出错: {e}")
            # 尝试关闭可能卡死的标签页
            try:
                if 'tab' in locals(): tab.close()
            except: 
                pass
            return None

    async def get_chart_screenshot(self, ca: str):
        """
        [异步入口] 将同步的截图任务扔到线程池运行
        避免卡死主线程
        """
        file_path = os.path.join(self.img_dir, f"{ca}.png")
        
        # 检查文件是否已存在（避免重复截图）
        if os.path.exists(file_path):
            return file_path

        try:
            # 核心优化：asyncio.to_thread (Python 3.9+)
            # 这行代码让 DrissionPage 在后台跑，不影响 Listener 监听
            result = await asyncio.to_thread(self._sync_take_screenshot, ca, file_path)
            
            if result:
                logger.info(f"📸 K线截图成功: {ca}")
            return result
        except Exception as e:
            logger.error(f"异步截图调度失败: {e}")
            return None

# 单例导出
fetcher = DataFetcher()

async def get_market_data(ca):
    return await fetcher.get_market_data(ca)

async def get_chart_screenshot(ca):
    return await fetcher.get_chart_screenshot(ca)