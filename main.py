import asyncio
import logging
import sys
import time
import re
import os
from typing import Dict, Any, Optional

# 核心模块
from modules.listener import start as start_listener
from modules.data_fetcher import get_market_data, get_gmgn_analytics
from modules.brain import brain
from modules.notifier import notify_user

# 闭环生态组件
from modules.strategy_engine import detect_strategy
from modules.tp_tracker import tp_tracker
from modules.stats_engine import stats_engine

# ✅ 适配你的文件名 (position_engine)
try:
    from modules.position_engine import calc_position_size
except ImportError:
    from modules.position_manager import calc_position_size

# =============================
# 日志配置
# =============================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("Main")

# =============================
# 并发与去重
# =============================
MAX_CONCURRENT_JOBS = 4
_job_sem = asyncio.Semaphore(MAX_CONCURRENT_JOBS)

MAIN_DEDUP_SEC = 60
_recent: Dict[str, float] = {}

def _should_skip_main(ca: str) -> bool:
    now = time.time()
    last = _recent.get(ca)
    if last and (now - last) < MAIN_DEDUP_SEC:
        return True
    _recent[ca] = now
    if len(_recent) > 1000:
        for k in list(_recent.keys())[:200]:
            del _recent[k]
    return False

async def safe_call(coro, timeout: int, label: str):
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        logger.error(f"⏱️ [{label}] 超时")
        return None
    except Exception as e:
        logger.error(f"💥 [{label}] 异常: {e}", exc_info=True)
        return None

def normalize_token_data(
    ca: str,
    raw: Optional[Dict[str, Any]],
    source: str,
    chat_id: int,
    msg_id: int,
) -> Dict[str, Any]:
    raw = raw or {}
    return {
        "address": ca,
        "symbol": raw.get("symbol", "UNK"),
        "name": raw.get("name", "Unknown"),
        "price_usd": raw.get("price_usd") or raw.get("price") or 0,
        "mcap": raw.get("cap_usd") or raw.get("mcap") or raw.get("fdv") or 0,
        "liquidity_usd": raw.get("liquidity_usd", 0),
        "volume_h24": raw.get("volume_h24", 0),
        "pair_url": raw.get("pair_url", ""),
        "source": source,
        "reply_chat_id": chat_id,
        "reply_to_message_id": msg_id,
        "gmgn_tags": []
    }

# =============================
# 核心流程 1: 处理新信号
# =============================
async def process_new_signal(
    ca: str,
    source: str,
    chat_id: int,
    msg_id: int,
    raw_message: str = "",
):
    async with _job_sem:
        if _should_skip_main(ca): return
        logger.info(f"🔥 新信号: {ca} | Src: {source}")

        # 1. 外部涨幅提取
        external_pnl = None
        if raw_message:
            match = re.search(r"(?:涨幅|Increase|Profit)[:：]?\s*([0-9\.,]+)%", raw_message, re.IGNORECASE)
            if not match: match = re.search(r"\+([0-9\.,]+)%", raw_message)
            if match: 
                try: external_pnl = match.group(1)
                except: pass

        # 2. 市场数据
        raw_market = await safe_call(get_market_data(ca), 12, "Market")
        token_data = normalize_token_data(ca, raw_market, source, chat_id, msg_id)
        token_data["external_pnl"] = external_pnl

        # 3. GMGN 深度扫描
        analytics = await safe_call(get_gmgn_analytics(ca), 45, "GMGN")
        screenshot = None
        
        if analytics:
            token_data["gmgn_tags"] = analytics.get("tags", [])
            token_data["top10_ratio"] = analytics.get("top10")
            token_data["avg_hold"] = analytics.get("avg_hold")
            token_data["gmgn_smart"] = analytics.get("raw_data", {}).get("smart", 0)
            token_data["gmgn_rat"] = analytics.get("raw_data", {}).get("rat", 0)
            token_data["gmgn_sniper"] = analytics.get("raw_data", {}).get("sniper", 0)
            token_data["gmgn_bundle"] = analytics.get("raw_data", {}).get("bundle", 0)
            screenshot = analytics.get("screenshot")
        
        # 4. 策略识别与配置 (✅✅✅ 关键修复点 ✅✅✅)
        strat_res = detect_strategy(token_data)
        
        # 自动识别返回类型（兼容 Tuple 和 String）
        if isinstance(strat_res, tuple):
            strategy_id, strategy_cfg = strat_res
        else:
            strategy_id = str(strat_res)
            strategy_cfg = {} # 空配置兜底
            
        token_data["strategy_id"] = strategy_id
        
        # 5. 仓位建议 (基于历史胜率)
        # 现在传入的 strategy_id 绝对是字符串，不会再报错 unhashable
        pos_info = calc_position_size(strategy_id)
        token_data["pos_info"] = pos_info

        # 6. 初始化追踪
        curr_price = float(token_data.get("price_usd") or 0)
        if curr_price > 0:
            await tp_tracker.init_position(ca, curr_price, strategy_id, strategy_cfg)

        # 7. AI 分析
        decision = await safe_call(brain.analyze_token(token_data), 30, "Brain")
        
        # 8. 发送通知
        await notify_user(
            ca=ca,
            token_data=token_data,
            visual_score=screenshot,
            decision=decision
        )
        logger.info(f"✅ 信号处理完成: {ca} ({strategy_id})")

# =============================
# 核心流程 2: 后台监控轮询
# =============================
async def auto_monitor_loop():
    """后台监控止盈止损"""
    logger.info("🕵️‍♂️ 价格监控服务已启动...")
    while True:
        try:
            active_cas = list(tp_tracker.data.keys())
            if not active_cas:
                await asyncio.sleep(5)
                continue

            for ca in active_cas:
                market = await get_market_data(ca)
                if not market: continue
                
                curr_price = float(market.get("priceUsd") or market.get("price_usd") or 0)
                if curr_price <= 0: continue

                result = await tp_tracker.update(ca, curr_price)
                
                if result:
                    event = result["event"]
                    strat = result["strategy"]
                    pnl = result["pnl"]
                    
                    logger.info(f"🔔 触发: {ca} -> {event} ({pnl:.2f}%)")
                    
                    # 记账
                    res_type = "WIN" if "TP" in event else "LOSS"
                    await stats_engine.record_trade(strat, res_type, pnl)
                    
                    # 推送通知
                    try:
                        from modules.commander import bot
                        from config.settings import REPORT_GROUP_ID
                        emoji = "🚀" if pnl > 0 else "🛑"
                        msg = (
                            f"{emoji} <b>策略执行报告: {strat}</b>\n"
                            f"<code>{ca}</code>\n"
                            f"━━━━━━━━━━━━━━\n"
                            f"触发: <b>{event}</b>\n"
                            f"盈亏: <b>{pnl:.2f}%</b>\n"
                            f"当前价: ${curr_price:.6f}"
                        )
                        await bot.send_message(
                            chat_id=REPORT_GROUP_ID, 
                            text=msg, 
                            parse_mode="HTML"
                        )
                    except Exception as e:
                        logger.error(f"推送告警失败: {e}")

            await asyncio.sleep(10) 

        except Exception as e:
            logger.error(f"监控循环异常: {e}")
            await asyncio.sleep(5)

# =============================
# 启动入口
# =============================
async def main():
    logger.info("🚀 SolanaHunter 全自动系统启动")
    await asyncio.gather(
        start_listener(process_new_signal),
        auto_monitor_loop()
    )

if __name__ == "__main__":
    try:
        if sys.platform == 'win32':
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 程序手动停止")
    except Exception as e:
        logger.critical(f"🔥 程序崩溃: {e}", exc_info=True)