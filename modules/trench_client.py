import os
import aiohttp
import logging
import asyncio

logger = logging.getLogger("Trench")

class TrenchClient:
    def __init__(self):
        # 读取你在 .env 里配置的钥匙
        self.base_url = os.getenv("TRENCH_API_URL", "http://localhost:8080/v1")
        self.api_key = os.getenv("TRENCH_API_KEY", "")
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    async def _post(self, endpoint: str, payload: dict):
        if not self.api_key: 
            return
        url = f"{self.base_url}/{endpoint}"
        try:
            async with aiohttp.ClientSession() as session:
                # 限制3秒超时，绝不拖慢机器人的速度
                async with session.post(url, headers=self.headers, json=payload, timeout=3) as resp:
                    if resp.status not in (200, 202):
                        logger.warning(f"⚠️ Trench [{endpoint}] 写入失败: HTTP {resp.status}")
        except Exception as e:
            logger.error(f"⚠️ Trench 连接异常: {e}")

    async def track_event(self, event_name: str, properties: dict):
        """记录系统事件 (如: 发现金狗)"""
        payload = {
            "event": event_name,
            "properties": properties
        }
        await self._post("track", payload)

    async def identify_wallet(self, wallet_address: str, traits: dict):
        """为钱包打标签 (如: GMGN聪明钱、老鼠仓)"""
        payload = {
            "userId": wallet_address,
            "traits": traits
        }
        await self._post("identify", payload)

# 创造一个全局可用的“快递员”
trench_agent = TrenchClient()