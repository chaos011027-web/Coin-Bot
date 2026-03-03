import os
import aiohttp
import asyncio
import time
import logging
from collections import deque

logger = logging.getLogger("InsightX")

class InsightXAgent:
    def __init__(self):
        self.api_key = os.getenv("INSIGHTX_API_KEY", "")
        self.base_url = "https://api.insightx.io/v1"
        self.headers = {"x-api-key": self.api_key}
        
        # 🛡️ 严格频率控制：5次/分钟 (免费版限制)
        self._lock = asyncio.Lock()
        self._request_timestamps = deque()
        self._max_rpm = 5

    async def _wait_for_rate_limit(self):
        """控制请求频率，保护免费额度"""
        async with self._lock:
            now = time.time()
            # 移除60秒之前的记录
            while self._request_timestamps and now - self._request_timestamps[0] > 60:
                self._request_timestamps.popleft()
            
            if len(self._request_timestamps) >= self._max_rpm:
                # 计算需要等待的时间
                sleep_time = 60 - (now - self._request_timestamps[0])
                if sleep_time > 0:
                    logger.warning(f"⏳ InsightX 触发频率限制(5次/分)，保护等待 {sleep_time:.1f} 秒...")
                    await asyncio.sleep(sleep_time)
                # 醒来后重新清理
                now = time.time()
                while self._request_timestamps and now - self._request_timestamps[0] > 60:
                    self._request_timestamps.popleft()
            
            self._request_timestamps.append(time.time())

    async def fetch_deep_analysis(self, ca: str) -> dict:
        if not self.api_key:
            return {}
            
        await self._wait_for_rate_limit()
        
        endpoint = f"{self.base_url}/token/{ca}/risk-report"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(endpoint, headers=self.headers, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return self._clean_data(data)
                    else:
                        logger.warning(f"⚠️ InsightX API 错误: {resp.status}")
                        return {}
        except Exception as e:
            logger.error(f"⚠️ InsightX 连接失败: {e}")
            return {}

    def _clean_data(self, raw_data):
        """解析并清洗出我们需要的集群和Gini数据"""
        return {
            "smart_money_count": raw_data.get("smart_money", {}).get("count", 0),
            "fresh_wallet_percent": raw_data.get("holders", {}).get("fresh_percent", 0),
            "rug_history": raw_data.get("creator", {}).get("rug_history_count", 0),
            "insider_ratio": raw_data.get("distribution", {}).get("insider_pct", 0),
            "bundled_sniper": raw_data.get("sniper", {}).get("is_bundled", False),
            # 提取集群与筹码分散度
            "gini_coefficient": raw_data.get("distribution", {}).get("gini", 0.0),
            "clusters": raw_data.get("clusters", []) # 预期格式: [{"cluster_id": "xxx", "wallets": ["addr1", "addr2"]}]
        }

# 全局单例
insightx_agent = InsightXAgent()