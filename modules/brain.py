import logging
import os
import json
import asyncio
from typing import Any, Dict, Optional
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("Brain")


def _safe(v: Any, default: str = "未知") -> str:
    if v is None:
        return default
    s = str(v).strip()
    return s if s else default


class SmartBrain:
    def __init__(self):
        self.api_key = os.getenv("DEEPSEEK_API_KEY")
        self.base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

        # 可配置
        self.model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        self.timeout_sec = int(os.getenv("BRAIN_TIMEOUT_SEC", "25"))
        self.max_retries = int(os.getenv("BRAIN_MAX_RETRIES", "2"))

        if not self.api_key:
            logger.warning("⚠️ 未检测到 DEEPSEEK_API_KEY：Brain 将返回降级结构化结果（不调用AI）。")
            self.client = None
        else:
            self.client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)

    def _fallback_json(self, m_data: Dict[str, Any]) -> Dict[str, Any]:
        """无AI时也保证返回 B版结构化结果"""
        return {
            "symbol": _safe(m_data.get("symbol"), "UNK"),
            "address": _safe(m_data.get("address"), "UNK"),
            "score": 0,
            "verdict": "NO_AI",
            "reason": "未配置 DEEPSEEK_API_KEY，无法进行AI评估。",
            "risk_flags": ["NO_AI"],
            "trade_plan": {
                "entry": "等待更多数据",
                "stop": "N/A",
                "take_profit": "N/A"
            }
        }

    def _build_prompt(self, m_data: Dict[str, Any]) -> str:
        # 你后续采集到的数据越多，这里越准；现在先兼容“少字段”
        payload = {
            "name": _safe(m_data.get("name")),
            "symbol": _safe(m_data.get("symbol"), "UNK"),
            "address": _safe(m_data.get("address"), "UNK"),
            "supply": _safe(m_data.get("supply")),
            "liquidity": _safe(m_data.get("liquidity")),
            "market_cap": _safe(m_data.get("market_cap")),
            "volume_24h": _safe(m_data.get("volume_24h")),
            "holders": _safe(m_data.get("holders")),
            "top10_pct": _safe(m_data.get("top10_pct")),
            "tax": _safe(m_data.get("tax")),
            "renounced": _safe(m_data.get("renounced")),
            "lp_burned": _safe(m_data.get("lp_burned")),
            "lp_locked": _safe(m_data.get("lp_locked")),
            "blacklist": _safe(m_data.get("blacklist")),
            "risk_score": _safe(m_data.get("risk_score")),
            "source": _safe(m_data.get("source"), "unknown"),
            "chain": "Solana",
        }

        return f"""
你是 Solana memecoin 的短线 Alpha 评估与合约安全审计专家。
请只基于给定数据做判断，不要编造不存在的数据。

【输入数据(JSON)】
{json.dumps(payload, ensure_ascii=False)}

【输出要求】
你必须输出严格 JSON（不要 markdown，不要多余文字），格式如下：
{{
  "symbol": "...",
  "address": "...",
  "score": 0-100,
  "verdict": "BUY" | "WATCH" | "AVOID",
  "reason": "一句话原因(<=60字)",
  "risk_flags": ["...","..."],
  "trade_plan": {{
    "entry": "以市值/价格表达的入场条件（若未知就写'数据不足'）",
    "stop": "止损条件（若未知就写'数据不足'）",
    "take_profit": "止盈条件（若未知就写'数据不足'）"
  }}
}}

评分规则（简化）：
- 明显合约风险/权限风险/黑名单/无法卖出迹象 => AVOID，分数<=30
- 数据不足但无明显致命风险 => WATCH，分数 31-69
- 风险可控且流动性/成交/持币/结构较健康 => BUY，分数>=70
""".strip()

    async def analyze_token(self, m_data: Dict[str, Any]) -> str:
        """
        返回：JSON字符串（B版推送更好用）
        """
        if not self.client:
            return json.dumps(self._fallback_json(m_data), ensure_ascii=False)

        prompt = self._build_prompt(m_data)

        last_err: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                logger.info(f"🧠 AI分析请求: {_safe(m_data.get('symbol'),'UNK')} attempt {attempt}/{self.max_retries}")

                coro = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": "你是一个专业的加密货币日内交易员与链上安全审计员。输出必须是严格JSON。"},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.4,
                    max_tokens=350
                )

                response = await asyncio.wait_for(coro, timeout=self.timeout_sec)
                content = response.choices[0].message.content.strip()

                # 尝试解析，确保是 JSON
                obj = json.loads(content)

                # 最低限度字段兜底
                obj.setdefault("symbol", _safe(m_data.get("symbol"), "UNK"))
                obj.setdefault("address", _safe(m_data.get("address"), "UNK"))
                obj.setdefault("score", 0)
                obj.setdefault("verdict", "WATCH")
                obj.setdefault("reason", "无原因")
                obj.setdefault("risk_flags", [])
                obj.setdefault("trade_plan", {"entry": "数据不足", "stop": "数据不足", "take_profit": "数据不足"})

                return json.dumps(obj, ensure_ascii=False)

            except Exception as e:
                last_err = e
                logger.error(f"❌ AI分析失败 attempt {attempt}: {str(e)[:120]}")
                await asyncio.sleep(0.8 * attempt)

        # 全部失败：降级结构化输出
        fb = self._fallback_json(m_data)
        fb["reason"] = f"AI分析失败，已降级。Err: {str(last_err)[:80] if last_err else 'unknown'}"
        fb["risk_flags"] = list(set(fb.get("risk_flags", []) + ["AI_ERROR"]))
        return json.dumps(fb, ensure_ascii=False)


brain = SmartBrain()
