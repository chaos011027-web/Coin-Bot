import asyncio
import logging
import sys
import time
import re
import os
import json
from typing import Dict, Any, Optional

from aiogram import Router, F
from aiogram.types import CallbackQuery

from modules.listener import start as start_listener
from modules.data_fetcher import get_market_data, get_gmgn_analytics, get_helius_security, get_rugcheck_data, get_goplus_security, fetcher
from modules.brain import brain
from modules.notifier import notify_user_fast, update_user_message, send_thread_reply, build_ai_report_text, build_milestone_text
from modules.database import db

from modules.bitquery_client import bitquery 
from modules.insightx import insightx_agent
from modules.trench_client import trench_agent

from modules.strategy_engine import detect_strategy
from modules.tp_tracker import tp_tracker
from modules.stats_engine import stats_engine
from modules.risk_engine import apply_final_gate
from modules.image_generator import generate_milestone_image
from config.settings import ADMIN_CHAT_ID

logger = logging.getLogger("Main")
logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", 
    handlers=[logging.StreamHandler(sys.stdout)]
)

# 🟢 注册深度 AI 按键路由
main_router = Router()

@main_router.callback_query(F.data.startswith("deep_ai:"))
async def process_deep_ai_callback(cq: CallbackQuery):
    ca = cq.data.split(":")[1]
    await cq.answer("🧠 正在调取大模型矩阵进行深度分析...", show_alert=False)
    asyncio.create_task(trigger_deep_ai_report(ca, cq.message.chat.id, cq.message.message_id))

async def trigger_deep_ai_report(ca: str, chat_id: int, msg_id: int):
    """按钮触发：即时生成深度报告并盖楼，且刷新主卡"""
    try:
        record = await db.get_signal_snapshot(ca)
        terminal_states = record.get("terminal_states", {}) if record else {}
        
        # 🟢 核心修复：兼容 get_price_only 返回单浮点数的情况，防止 unpack 崩溃
        price_res = await fetcher.get_price_only(ca)
        price = price_res[0] if isinstance(price_res, tuple) else float(price_res)
        mcap = price_res[1] if isinstance(price_res, tuple) else 0.0
        
        token_data = {"symbol": "TOKEN", "price_usd": price, "cap_usd": mcap, "ca": ca}
        
        # 提取静态缓存，交由动态大脑极速生成策略
        decision = await brain.analyze_dynamic_strategy(token_data, terminal_states)
        
        # 发送深度长文盖楼报告
        initial_msg_id = record.get("initial_msg_id") if record and record.get("initial_msg_id") else msg_id
        report_text = build_ai_report_text(ca, token_data, decision)
        await send_thread_reply(chat_id, initial_msg_id, report_text)
        
        # 顺手把主卡片的实时价格和市值也刷新了
        await refresh_token_panel(ca, chat_id, initial_msg_id, force_deep=False)
    except Exception as e:
        logger.error(f"❌ 深度报告生成失败: {e}")

async def trigger_milestone_update(ca: str, chat_id: int, record: dict, current_price: float, current_mcap: float, delta: float):
    """自动触发：暴涨暴跌时生成极简战报并盖楼"""
    try:
        terminal_states = record.get("terminal_states", {})
        token_data = {"symbol": "TOKEN", "price_usd": current_price, "cap_usd": current_mcap, "ca": ca}
        
        # AI 右脑瞬间给出交易指令
        decision = await brain.analyze_dynamic_strategy(token_data, terminal_states)
        
        initial_msg_id = record.get("initial_msg_id")
        text = build_milestone_text(ca, token_data, decision, delta)
        
        if initial_msg_id:
            await send_thread_reply(chat_id, initial_msg_id, text)
            
        # 更新锚点价格，准备下一次里程碑
        await db.update_milestone(ca, current_price)
    except Exception as e:
        logger.error(f"❌ 战报更新失败: {e}")

async def safe_call(coro, timeout_s: int, name: str):
    try:
        return await asyncio.wait_for(coro, timeout=timeout_s)
    except asyncio.TimeoutError:
        logger.warning(f"⏳ {name} 超时({timeout_s}s)")
        return None
    except Exception as e:
        logger.exception(f"💥 {name} 异常: {e}")
        return None

def normalize_token_data(ca: str, raw_market: dict, source: str, chat_id: int, msg_id: int):
    raw_market = raw_market or {}
    
    symbol = raw_market.get("symbol", "UNK")
    name = raw_market.get("name", "")
    
    price_usd = raw_market.get("priceUsd") or raw_market.get("price_usd") or 0
    cap_usd = raw_market.get("fdv") or raw_market.get("cap_usd") or raw_market.get("mcap") or 0
    
    liq_usd = raw_market.get("liquidity_usd")
    if not liq_usd and isinstance(raw_market.get("liquidity"), dict):
        liq_usd = raw_market.get("liquidity", {}).get("usd")
    liq_usd = liq_usd or 0
        
    vol_h24 = raw_market.get("volume_h24")
    if not vol_h24 and isinstance(raw_market.get("volume"), dict):
        vol_h24 = raw_market.get("volume", {}).get("h24")
    vol_h24 = vol_h24 or 0

    chg_5m = raw_market.get("chg_5m")
    if chg_5m is None:
        pc = raw_market.get("priceChange") or {}
        chg_5m = pc.get("m5")
        chg_1h = pc.get("h1")
        chg_6h = pc.get("h6")
        chg_24h = pc.get("h24")
    else:
        chg_1h = raw_market.get("chg_1h")
        chg_6h = raw_market.get("chg_6h")
        chg_24h = raw_market.get("chg_24h")

    return {
        "ca": ca, 
        "symbol": symbol, 
        "name": name, 
        "chain": "SOL", 
        "source": source, 
        "chat_id": chat_id, 
        "msg_id": msg_id,
        "price_usd": price_usd, 
        "cap_usd": cap_usd, 
        "liquidity_usd": liq_usd, 
        "volume_h24": vol_h24,
        "dex_paid": raw_market.get("dex_paid", False), 
        "is_locked": None, 
        "is_burned": None,
        "token_age_min": raw_market.get("token_age_min", 0), 
        "buys_24h": raw_market.get("buys_24h", 0), 
        "sells_24h": raw_market.get("sells_24h", 0), 
        "buy_sell_ratio": raw_market.get("buy_sell_ratio", 0.0),
        "chg_1m": raw_market.get("chg_1m"), 
        "chg_5m": chg_5m, 
        "chg_15m": raw_market.get("chg_15m"), 
        "chg_30m": raw_market.get("chg_30m"), 
        "chg_1h": chg_1h, 
        "chg_3h": raw_market.get("chg_3h"), 
        "chg_6h": chg_6h, 
        "chg_24h": chg_24h,
        "token_image_url": raw_market.get("token_image_url"), 
        "token_image_path": raw_market.get("token_image_path"),
    }

def simple_gatekeeper(token_data: dict) -> bool:
    try:
        liq = float(token_data.get("liquidity_usd") or 0)
        mcap = float(token_data.get("cap_usd") or 0)
        
        if liq < 500:
            logger.info(f"⚠️ Gatekeeper: 池子极小 (${liq:.0f}) - ALLOWED")
        if mcap < 1000:
            logger.info(f"⚠️ Gatekeeper: 市值极小 (${mcap:.0f}) - ALLOWED")
            
        return True
    except Exception:
        return True

async def process_new_signal(ca: str, source: str, chat_id: int, msg_id: int, raw_message: str = ""):
    logger.info(f"⚡ 开始处理信号: CA={ca} | 来源={source}")
    ca = (ca or "").strip()
    if not ca: return
        
    try:
        is_dm = ("DM_USER" in str(source) or source == "MANUAL_QUERY")
        
        # 🟢 核心重构：防抖拦截与整数倍战报触发
        if not is_dm:
            try:
                record = await asyncio.wait_for(db.get_signal_snapshot(ca), timeout=3.0)
                if record:
                    try:
                        # 兼容单值返回，修复 unpacking error
                        price_res = await fetcher.get_price_only(ca)
                        price = price_res[0] if isinstance(price_res, tuple) else float(price_res)
                        mcap = price_res[1] if isinstance(price_res, tuple) else 0.0
                        
                        logger.info(f"🔎 [价格嗅探] CA: {ca[:6]}... | 最新现价: ${price:.6f}")
                        
                        initial_price = float(record.get("entry_price") or 0)
                        last_notified_price = float(record.get("last_notified_price") or initial_price)
                        
                        # 数据保护墙：防止除以0或拿不到价格
                        if initial_price <= 0 or price <= 0:
                            logger.info(f"♻️ {ca} 价格异常(初始:{initial_price}, 现价:{price})，静默拦截。")
                            return
                            
                        # 计算精准倍数
                        current_multiplier = price / initial_price
                        # 获取历史曾到达过的最高倍数 (默认最小为 1)
                        peak_multiplier = max(1.0, last_notified_price / initial_price)
                        
                        # 🎯 终极整倍数跨越判定
                        # 只有当前整数倍 严格大于 历史记录的整数倍 时才触发！
                        if int(current_multiplier) > int(peak_multiplier):
                            logger.info(f"🎉 [里程碑突破] {ca[:8]} 从 {peak_multiplier:.2f}x 飙升至 {current_multiplier:.2f}x！(突破 {int(current_multiplier)}x 大关)")
                            asyncio.create_task(trigger_milestone_update(ca, chat_id, record, price, mcap, current_multiplier))
                            return
                        else:
                            logger.info(f"♻️ {ca} 已存在，当前 {current_multiplier:.2f}x，未突破 {int(peak_multiplier) + 1}x 整数关口，静默拦截。")
                            return
                            
                    except Exception as e:
                        logger.error(f"❌ 战报验价及整数倍计算失败: {e}")
                        return
            except Exception as e:
                logger.warning(f"⚠️ 数据库查重超时跳过: {e}")

        logger.info(f"⏳ 开始抓取 ({ca[:4]}...) 核心数据...")
        if not is_dm:
            await asyncio.sleep(2.5)

        raw_market, helius_sec = await asyncio.gather(
            safe_call(get_market_data(ca), 10, "Market"),
            safe_call(get_helius_security(ca), 5, "Helius")
        )
        
        if not raw_market:
            raw_market = {"symbol": "UNK"} 

        token_data = normalize_token_data(ca, raw_market, source, chat_id, msg_id)
        if helius_sec:
            token_data.update(helius_sec)
        
        simple_gatekeeper(token_data)

        ext_pnl = None
        if raw_message:
            m = re.search(r"(?:涨幅|Increase|Profit)[:：]?\s*([0-9\.,]+)%", raw_message, re.IGNORECASE)
            if not m:
                m = re.search(r"\+([0-9\.,]+)%", raw_message)
            if m:
                ext_pnl = m.group(1)
                
        token_data["external_pnl"] = ext_pnl

        try:
            await asyncio.wait_for(db.execute(
                "INSERT INTO tokens_meta (ca, symbol, name) VALUES ($1, $2, $3) ON CONFLICT DO NOTHING", 
                ca, 
                token_data.get("symbol"), 
                token_data.get("name")
            ), timeout=2.0)
        except Exception:
            pass
        
        strat_res = detect_strategy(token_data)
        if isinstance(strat_res, tuple):
            token_data["strategy_id"] = str(strat_res[0])
        else:
            token_data["strategy_id"] = str(strat_res)
        
        logger.info(f"🚀 准备下发初期战报卡片...")
        fast_msg_id = await notify_user_fast(ca=ca, token_data=token_data)
        if not fast_msg_id:
            logger.error("❌ notify_user_fast 未返回 msg_id，发卡片失败！")
            return
            
        asyncio.create_task(run_deep_analysis(ca, token_data, fast_msg_id, ADMIN_CHAT_ID))
        
    except Exception as e:
        logger.exception(f"💥 process_new_signal 核心处理崩溃: {e}")

async def run_deep_analysis(ca: str, token_data: dict, message_id: int, chat_id: int):
    try:
        curr_price = float(token_data.get("price_usd") or 0)
        curr_mcap = float(token_data.get("cap_usd") or 0)
        
        if curr_price > 0:
            await tp_tracker.observe_price(ca, curr_price)
            token_data["baseline"] = await tp_tracker.get_baseline_metrics(ca, current_price=curr_price)
            strat_res = detect_strategy(token_data)
            
            config = strat_res[1] if isinstance(strat_res, tuple) else {}
            await tp_tracker.init_position(
                ca=ca, 
                entry_price=curr_price, 
                strategy_id=token_data.get("strategy_id", "UNK"), 
                config=config, 
                initial_mcap=curr_mcap, 
                reply_chat_id=chat_id, 
                reply_msg_id=message_id
            )

        rug_data, bq_data, goplus_data, analytics = await asyncio.gather(
            safe_call(get_rugcheck_data(ca), 8, "RugCheck"), 
            safe_call(bitquery.fetch_comprehensive_data(ca), 20, "Bitquery"),
            safe_call(get_goplus_security(ca), 10, "GoPlus"), 
            safe_call(get_gmgn_analytics(ca), 45, "GMGN")
        )

        if rug_data:
            token_data["is_burned"] = ((rug_data.get("lp_burned_pct", 0) or 0) > 95)
            token_data["is_locked"] = ((rug_data.get("lp_locked_pct", 0) or 0) > 95)

        if goplus_data and goplus_data.get("is_honeypot"): 
            token_data["risk_flags"] = token_data.get("risk_flags", []) + ["🚨 貔貅盘(GoPlus)"]

        if bq_data:
            for k in ["chg_1m", "chg_15m", "chg_30m", "chg_3h"]:
                if bq_data.get(k):
                    token_data[k] = bq_data.get(k)
                    
            if bq_data.get("bitquery_top10_ratio") and not token_data.get("top10_ratio"):
                token_data["top10_ratio"] = f"{bq_data['bitquery_top10_ratio']:.2f}%"

        if analytics:
            if token_data.get("symbol") == "UNK" and analytics.get("symbol"):
                token_data["symbol"] = analytics.get("symbol")
            
            for k in ["chg_1m", "chg_5m", "chg_15m", "chg_30m", "chg_1h", "chg_6h", "chg_24h"]:
                if analytics.get(k) and not token_data.get(k):
                    token_data[k] = analytics.get(k)

            gmgn_burned = analytics.get("is_burned")
            if gmgn_burned is not None and token_data.get("is_burned") != gmgn_burned:
                token_data["is_burned"] = gmgn_burned

            gmgn_dex = analytics.get("dex_paid")
            if gmgn_dex is not None and token_data.get("dex_paid") != gmgn_dex:
                token_data["dex_paid"] = gmgn_dex

            if analytics.get("top10_ratio"):
                token_data["top10_ratio"] = analytics.get("top10_ratio")

            gmgn_liq = analytics.get("header_liq_usd", 0)
            api_liq = token_data.get("liquidity_usd", 0)
            
            if gmgn_liq > 0 and (api_liq == 0 or abs(api_liq - gmgn_liq) / max(api_liq, 1) > 0.15):
                token_data["liquidity_usd"] = gmgn_liq

            raw = analytics.get("raw_data", {}) or {}
            for k in ["rat", "sniper", "smart", "blue_chip", "phishing_wallets", "bundle", "dev", "kol"]:
                token_data[f"gmgn_{k}"] = raw.get(k, 0)

        # 🟢 核心重构：调用双脑并将不可逆状态存入数据库
        static_res = await safe_call(brain.analyze_static_narrative(token_data, analytics),60, "AI_Static") or {}
        terminal_states = {
            "ai_narrative": static_res.get("ai_narrative", "无"),
            "ai_image_read": static_res.get("ai_image_read", "无"),
            "entry_price": curr_price,
            "is_burned": token_data.get("is_burned", False)
        }
        
        decision = await safe_call(brain.analyze_dynamic_strategy(token_data, terminal_states, analytics), 60, "AI_Dynamic") or {}
        decision, pos_info, _ = apply_final_gate(token_data, decision, None)
        token_data["pos_info"] = pos_info

        try:
            # 永久封存该代币的静态报告，防失忆
            await db.save_initial_signal(ca, "SYSTEM", curr_price, message_id, terminal_states)
            
            await asyncio.wait_for(db.execute(
                "UPDATE signals_snapshot SET rank_score = $1, ai_narrative = $2, status = 'analyzed' WHERE ca = $3", 
                float(decision.get("score", 0)), 
                decision.get("reason", ""), 
                ca
            ), timeout=2.0)
        except Exception as e:
            logger.error(f"⚠️ 保存初始状态失败: {e}")
        
        await update_user_message(chat_id=chat_id, message_id=message_id, ca=ca, token_data=token_data, decision=decision)
        
        asyncio.create_task(evolve_database(ca, token_data, analytics, {}))

    except Exception as e:
        logger.exception(f"💥 run_deep_analysis 异常: {e}")

async def evolve_database(ca: str, token_data: dict, gmgn_data: dict, ix_data: dict):
    try:
        mcap = token_data.get("cap_usd", 0)
        liq = token_data.get("liquidity_usd", 0)
        age = token_data.get("token_age_min", 0)
        holders = gmgn_data.get("top10_ratio", "N/A") if gmgn_data else "N/A"
        
        await db.execute("""
            INSERT INTO golden_dog_morphology 
            (ca, snapshot_time, token_age_mins_at_snap, market_cap_at_snap, liquidity_at_snap, holder_distribution, social_signal)
            VALUES ($1, NOW(), $2, $3, $4, $5, $6)
            ON CONFLICT (ca) DO NOTHING
        """, ca, age, mcap, liq, json.dumps({"top10": holders}), json.dumps({"ix_data": ix_data}))

        top_holders = gmgn_data.get("top_holders_detail", []) if gmgn_data else []
        for holder in top_holders:
            addr = holder.get("address")
            tags = holder.get("tags", [])
            if addr and tags and any(t in tags for t in ["Smart Money", "KOL", "Sniper", "Dev"]):
                await db.execute("""
                    INSERT INTO smart_wallet_intel (wallet_address, tags, total_trades, avg_entry_mcap)
                    VALUES ($1, $2, 1, $3)
                    ON CONFLICT (wallet_address) DO UPDATE 
                    SET last_active = NOW(), total_trades = smart_wallet_intel.total_trades + 1
                """, addr, json.dumps(tags), mcap)

        clusters = ix_data.get("clusters", []) if ix_data else []
        for cluster in clusters:
            cluster_id = cluster.get("cluster_id", "UNK")
            wallets = cluster.get("wallets", [])
            for w in wallets:
                await db.execute("""
                    INSERT INTO wallet_clusters (cluster_id, wallet_address, discovered_in_token, behavior_tag, risk_level, total_wallets_in_cluster)
                    VALUES ($1, $2, $3, $4, 8, $5)
                    ON CONFLICT (cluster_id, wallet_address) DO NOTHING
                """, str(cluster_id), str(w), ca, "SUSPICIOUS_CLUSTER", len(wallets))

        logger.info(f"🧬 数据库切片记录完成 (CA: {ca})")
        
    except Exception as e:
        logger.error(f"🧬 数据库进化失败: {e}")

async def price_monitor_loop():
    logger.info("🕵️‍♂️ 价格及里程碑监控服务已启动... (搭载 Jupiter 极速零延迟查价引擎)")
    while True:
        try:
            await asyncio.sleep(1.5)
            for ca, pos in list(tp_tracker.data.items()):
                if str(pos.get("status", "")).upper() != "ACTIVE":
                    continue
                
                # 🟢 核心修复：兼容极速 API 返回的单值解包
                try: 
                    price_res = await fetcher.get_price_only(ca)
                    price_f = price_res[0] if isinstance(price_res, tuple) else float(price_res)
                    mcap_f = price_res[1] if isinstance(price_res, tuple) else 0.0
                except Exception:
                    continue
                    
                if price_f <= 0:
                    continue
                    
                await tp_tracker.observe_price(ca, price_f)
                
                event_dict = await tp_tracker.update(ca, price_f, curr_mcap=mcap_f)
                if event_dict and isinstance(event_dict, dict) and event_dict.get("event") == "MILESTONE":
                    t_chat_id = pos.get("reply_chat_id")
                    t_msg_id = pos.get("reply_msg_id")
                    
                    if t_chat_id and t_msg_id:
                        mult = event_dict.get("multiplier")
                        img_path = await asyncio.to_thread(
                            generate_milestone_image, 
                            symbol="TOKEN", 
                            mcap=mcap_f, 
                            multiplier=mult, 
                            ca=ca
                        )
                        if img_path:
                            tp_tracker.data[ca]["custom_image"] = img_path
                            tp_tracker._save()
                            await refresh_token_panel(ca, t_chat_id, t_msg_id, force_deep=False)
        except Exception:
            pass

async def refresh_token_panel(ca: str, chat_id: int, message_id: int, force_deep: bool = True):
    raw_market, helius_sec = await asyncio.gather(
        safe_call(get_market_data(ca), 12, "Market"), 
        safe_call(get_helius_security(ca), 12, "Helius")
    )
    
    token_data = normalize_token_data(ca, raw_market, "REFRESH", chat_id, message_id)
    if helius_sec:
        token_data.update(helius_sec)
    
    pos = tp_tracker.data.get(ca, {})
    if pos.get("custom_image") and os.path.exists(pos.get("custom_image")):
        token_data["token_image_path"] = pos.get("custom_image")
        token_data["token_image_url"] = "" 
        
    try:
        curr_price = float(token_data.get("price_usd") or 0)
    except Exception:
        curr_price = 0
        
    if curr_price > 0:
        await tp_tracker.observe_price(ca, curr_price)
        token_data["baseline"] = await tp_tracker.get_baseline_metrics(ca, current_price=curr_price)
        
    await update_user_message(chat_id, message_id, ca, token_data, {"verdict": "REFRESH", "reason": "刷新中..."})
    if force_deep:
        await run_deep_analysis(ca, token_data, message_id, chat_id)

async def main():
    logger.info("🚀 SolanaHunter V3.6 防CF拦截与增量状态引擎启动...")
    try:
        from modules.commander import dp
        from modules.notifier import refresh_router
        dp.include_router(refresh_router)
        dp.include_router(main_router)  # ✅ 注册深度 AI 分析的按键路由
    except Exception as e:
        logger.error(f"路由注册异常: {e}")

    await fetcher.prepare_browser_profile()
    
    # ✅ 恢复并启动数据库引擎 (支撑状态化记忆的核心)
    await db.init_pool()
    
    asyncio.create_task(price_monitor_loop())
    await start_listener(process_new_signal, refresh_token_panel)

if __name__ == "__main__":
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 已退出")