class InsightXAgent:
    def __init__(self):
        self.api_key = os.getenv("INSIGHTX_API_KEY")
        self.base_url = "https://api.insightx.io/v1"
        self.headers = {"x-api-key": self.api_key}

    async def fetch_deep_analysis(self, ca: str) -> dict:
        endpoint = f"{self.base_url}/token/{ca}/risk-report"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(endpoint, headers=self.headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return self._clean_data(data)
                    else:
                        print(f"⚠️ InsightX API 错误: {resp.status}")
                        return None
        except Exception as e:
            print(f"⚠️ InsightX 连接失败: {e}")
            return None

    def _clean_data(self, raw_data):
        return {
            "smart_money_count": raw_data.get("smart_money", {}).get("count", 0),
            "fresh_wallet_percent": raw_data.get("holders", {}).get("fresh_percent", 0),
            "rug_history": raw_data.get("creator", {}).get("rug_history_count", 0),
            "insider_ratio": raw_data.get("distribution", {}).get("insider_pct", 0),
            "bundled_sniper": raw_data.get("sniper", {}).get("is_bundled", False)
        }
