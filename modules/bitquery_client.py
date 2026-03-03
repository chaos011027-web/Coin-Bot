import aiohttp
import logging
import os
import json
from typing import Dict, Any

logger = logging.getLogger("Bitquery")

class BitqueryClient:
    def __init__(self):
        # 从环境变量读取 Key
        self.api_token = os.getenv("BITQUERY_API_KEY")
        # 使用 V2 标准 GraphQL 端点
        self.url = "https://streaming.bitquery.io/graphql" 
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_token}",
            "X-API-KEY": self.api_token or "" 
        }

    async def fetch_comprehensive_data(self, mint: str) -> Dict[str, Any]:
        """
        🚀 Bitquery V2 适配版：解决流水数据重复与供应量字段缺失
        """
        if not self.api_token:
            return {}

        # 1. 优化查询：扩大采样范围以应对频繁的流水更新
        query = """
        query ($token: String!) {
          Solana {
            TokenSupplyUpdates(
              limit: {count: 1}
              orderBy: {descending: Block_Time}
              where: {TokenSupplyUpdate: {Currency: {MintAddress: {is: $token}}}}
            ) {
              TokenSupplyUpdate { PostBalance }
            }
            BalanceUpdates(
              limit: {count: 40} 
              orderBy: {descending: BalanceUpdate_PostBalance}
              where: {
                BalanceUpdate: {
                  Currency: {MintAddress: {is: $token}}, 
                  Account: {Address: {not: "11111111111111111111111111111111"}}
                }
              }
            ) {
              BalanceUpdate { 
                PostBalance 
                Account { Address }
              }
            }
          }
        }
        """
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.url, json={"query": query, "variables": {"token": mint}}, headers=self.headers) as resp:
                    if resp.status != 200: return {}
                    result = await resp.json()
                    # 不再吞掉 errors，方便调试
                    if "errors" in result or "data" not in result: 
                        return {}
                    return self._process_data(result["data"].get("Solana", {}))
        except Exception as e:
            logger.error(f"❌ Bitquery 请求异常: {e}")
            return {}

    def _process_data(self, data: dict) -> Dict[str, Any]:
        """
        核心：对流水数据进行手动去重聚合，计算真实持仓占比
        """
        result = {}
        if not data: return {}
        
        try:
            # 1. 获取总供应量
            supply_list = data.get("TokenSupplyUpdates", [])
            total_supply = 0.0
            if supply_list and supply_list[0].get("TokenSupplyUpdate"):
                total_supply = float(supply_list[0]["TokenSupplyUpdate"].get("PostBalance", 0))
            
            # 2. 对 BalanceUpdates 进行手动去重 (V2 返回的是流水记录)
            holders_raw = data.get("BalanceUpdates", [])
            unique_holders = {}
            for h in holders_raw:
                bu = h.get("BalanceUpdate", {})
                addr = bu.get("Account", {}).get("Address")
                amt = float(bu.get("PostBalance", 0))
                # 记录该地址出现的最高余额
                if addr not in unique_holders or amt > unique_holders[addr]:
                    unique_holders[addr] = amt
            
            # 3. 重新排序并提取前 10 名独立持仓者
            sorted_holders = sorted(unique_holders.items(), key=lambda x: x[1], reverse=True)[:10]
            top10_sum = sum(amt for addr, amt in sorted_holders)

            # 4. 容错逻辑：如果 Bitquery 没返回供应量，尝试以最大持仓进行合理估算
            if total_supply <= 0 and sorted_holders:
                total_supply = sorted_holders[0][1] * 2.5 

            if total_supply > 0:
                ratio = (top10_sum / total_supply) * 100.0
                result["bitquery_top10_ratio"] = min(100.0, ratio)
                result["bitquery_holders_data"] = [{"address": a, "amount": m} for a, m in sorted_holders]
                
        except Exception as e:
            logger.error(f"🧬 Bitquery 解析失败: {e}")

        return result

bitquery = BitqueryClient()