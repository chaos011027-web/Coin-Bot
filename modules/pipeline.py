# modules/pipeline.py
import re
import logging
from typing import Any, Dict, Optional

from modules.data_fetcher import get_market_data, get_gmgn_analytics
from modules.brain import brain
from modules.notifier import notify_user

logger = logging.getLogger("Pipeline")

def parse_external_pnl(raw_message: str) -> Optional[float]:
    if not raw_message:
        return None
    m = re.search(r"(?:涨幅|Increase|Profit)[:：]?\s*([0-9\.,]+)%", raw_message, re.IGNORECASE)
    if not m:
        m = re.search(r"\+([0-9\.,]+)%", raw_message)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except Exception:
        return None

def normalize_token_data(ca: str, raw: Optional[Dict[str, Any]], source: str, chat_id: int, msg_id: int) -> Dict[str, Any]:
    raw = raw or {}
    return {
        "address": ca,
        "symbol": raw.get("symbol", "UNK"),
        "name": raw.get("name", "Unknown"),
        "price_usd": raw.get("price_usd") or raw.get("priceUsd") or raw.get("price") or 0,
        "cap_usd": raw.get("cap_usd") or raw.get("mcap") or raw.get("fdv") or 0,
        "liquidity_usd": raw.get("liquidity_usd", 0),
        "volume_h24": raw.get("volume_h24", 0),
        "pair_url": raw.get("pair_url", ""),
        "token_image_url": raw.get("token_image_url"),  # ✅ 代币图片
        "source": source,
        "reply_chat_id": chat_id,
        "reply_to_message_id": msg_id,
    }

async def analyze_and_notify(
    ca: str,
    source: str,
    chat_id: int,
    msg_id: int,
    raw_message: str = "",
    trigger_mode: str = "auto",
):
    """
    ✅ 唯一分析入口：抓市场数据 + GMGN标签 + AI + 推送
    - 不做去重（去重由外部决定）
    """
    raw_market = await get_market_data(ca)
    token_data = normalize_token_data(ca, raw_market, source, chat_id, msg_id)
    token_data["trigger_mode"] = trigger_mode
    token_data["external_pnl"] = parse_external_pnl(raw_message)

    # ✅ GMGN：只要标签/Top10/avg_hold，不要截图
    analytics = await get_gmgn_analytics(ca)
    if analytics:
        token_data["gmgn_tags"] = analytics.get("tags", [])
        token_data["top10_ratio"] = analytics.get("top10")
        token_data["avg_hold"] = analytics.get("avg_hold")

        # 如果你做了结构化字段（smart/kol/sniper...），这里也可以顺带注入
        raw_data = analytics.get("raw_data") or {}
        token_data["gmgn_smart"] = raw_data.get("smart", 0)
        token_data["gmgn_kol"] = raw_data.get("kol", 0)
        token_data["gmgn_sniper"] = raw_data.get("sniper", 0)
        token_data["gmgn_degen"] = raw_data.get("degen", 0)
        token_data["gmgn_rat"] = raw_data.get("rat", 0)
        token_data["gmgn_dev"] = raw_data.get("dev", 0)
        token_data["gmgn_bundle"] = raw_data.get("bundle", 0)

    decision = await brain.analyze_token(token_data)
    if not isinstance(decision, dict):
        decision = {"action": "PASS", "score": 0, "reason": "AI异常", "risk_flags": ["AI_ERROR"]}

    # ✅ 注意：不再传 visual_score 截图，notifier 会改为使用 token_image_url 发图
    await notify_user(ca=ca, token_data=token_data, visual_score=None, decision=decision)
    logger.info(f"✅ 分析推送完成: {ca} | source={source} mode={trigger_mode}")
