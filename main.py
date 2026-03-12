import asyncio
import logging
import sys
import time
import re
import os
import json
from pathlib import Path
from typing import Any, Optional

from aiogram import Router, F
from aiogram.types import CallbackQuery

from modules.listener import start as start_listener
from modules.data_fetcher import (
    get_market_data,
    get_gmgn_analytics,
    get_helius_security,
    get_rugcheck_data,
    get_goplus_security,
    fetcher,
)
from modules.brain import brain
from modules.notifier import (
    notify_user_fast,
    update_user_message,
    send_thread_reply,
    build_ai_report_text,
    build_milestone_text,
)
from modules.database import db
from modules.bitquery_client import bitquery
from modules.insightx import insightx_agent
from modules.strategy_engine import detect_strategy
from modules.tp_tracker import tp_tracker
from modules.stats_engine import stats_engine
from modules.risk_engine import apply_final_gate
from modules.image_generator import generate_milestone_image
from modules.paper_portfolio_engine import paper_portfolio_engine
from config.settings import ADMIN_CHAT_ID

logger = logging.getLogger("Main")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)


def spawn_task(coro, name: str) -> asyncio.Task:
    task = asyncio.create_task(coro, name=name)

    def _handle_task_result(t: asyncio.Task):
        try:
            t.result()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"💥 后台任务 [{name}] 发生致命崩溃: {e}", exc_info=True)

    task.add_done_callback(_handle_task_result)
    return task


def _load_json_file(path: str) -> Optional[dict]:
    try:
        p = Path(path)
        if not p.exists():
            return None
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _paper_portfolio_call(method_name: str, *args, **kwargs) -> dict:
    """
    兼容不同版本的 PaperPortfolioEngine。
    即使缺少 on_final_close / on_tp_event，也不要把主循环打崩。
    """
    try:
        fn = getattr(paper_portfolio_engine, method_name, None)
        if callable(fn):
            ret = fn(*args, **kwargs)
            return ret if isinstance(ret, dict) else {"ok": bool(ret), "raw": ret}

        alt_names = {
            "on_final_close": ["close_position", "final_close", "close_trade", "close"],
            "on_tp_event": ["take_profit", "partial_take_profit", "tp_event", "reduce_position"],
        }.get(method_name, [])

        for alt in alt_names:
            alt_fn = getattr(paper_portfolio_engine, alt, None)
            if not callable(alt_fn):
                continue
            try:
                ret = alt_fn(*args, **kwargs)
            except TypeError:
                ret = alt_fn(*args)
            return ret if isinstance(ret, dict) else {"ok": bool(ret), "raw": ret, "fallback_method": alt}

        logger.warning(f"⚠️ PaperPortfolioEngine 缺少方法: {method_name}，本次仅跳过纸面账户记账，不影响主流程。")
        return {"ok": False, "reason": f"missing_method:{method_name}"}
    except Exception as e:
        logger.warning(f"⚠️ PaperPortfolio 调用失败 [{method_name}]: {e}", exc_info=True)
        return {"ok": False, "reason": f"error:{method_name}:{e}"}


# === LightGBM 预测模型全局加载 ===
try:
    import numpy as np
    import lightgbm as lgb
    from modules.feature_engine import calculate_ml_features

    LGB_AVAILABLE = True
    MODEL_PATH = "models/meme_strategy_v1.txt"
    MODEL_METRICS_PATH = "models/meme_strategy_v1_metrics.json"
    MODEL_FEATURES_PATH = "models/meme_strategy_v1_features.json"

    if os.path.exists(MODEL_PATH):
        lgb_model = lgb.Booster(model_file=MODEL_PATH)
        model_metrics = _load_json_file(MODEL_METRICS_PATH) or {}
        model_features = _load_json_file(MODEL_FEATURES_PATH) or {}

        logger.info("🧠 LightGBM 本地模型文件已加载入内存。")
        if model_metrics:
            logger.info(
                "📊 LightGBM 训练指标: "
                f"acc={model_metrics.get('accuracy')} | "
                f"precision={model_metrics.get('precision')} | "
                f"recall={model_metrics.get('recall')} | "
                f"f1={model_metrics.get('f1')} | "
                f"auc={model_metrics.get('roc_auc')}"
            )
        if model_features:
            logger.info(f"🧩 LightGBM 特征顺序: {model_features.get('feature_columns', [])}")
    else:
        lgb_model = None
        logger.info("⏳ 未检测到 LightGBM 模型文件，当前不启用机器学习预测。")
except ImportError as e:
    LGB_AVAILABLE = False
    lgb_model = None
    logger.warning(f"⚠️ 缺少机器学习依赖 ({e})，AI 预测辅助将处于离线状态。")
# ==================================

main_router = Router()
_in_flight_signals = {}
_in_flight_lock = asyncio.Lock()


def _is_missing(v: Any) -> bool:
    return v is None or v == ""


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        if isinstance(v, (int, float)):
            return float(v)
        s = str(v).strip().replace(",", "")
        if s.endswith("%"):
            s = s[:-1].strip()
        if not s:
            return default
        return float(s)
    except Exception:
        return default


def _safe_pct_text(v: Any) -> str:
    if v is None or v == "":
        return ""
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return ""
        if s.endswith("%"):
            return s
        try:
            return f"{float(s):.2f}%"
        except Exception:
            return s
    try:
        return f"{float(v):.2f}%"
    except Exception:
        return ""


TRUSTED_TOP10_SOURCES = {"BITQUERY", "GMGN"}


def _is_trusted_top10_source(src: Any) -> bool:
    return str(src or "").upper() in TRUSTED_TOP10_SOURCES


def _merge_existing_terminal(token_data: dict, terminal: Optional[dict]) -> dict:
    terminal = terminal or {}
    stable = terminal.get("stable_snapshot") or {}

    for src in (stable, terminal):
        if not src:
            continue

        if token_data.get("symbol") == "UNK" and src.get("symbol"):
            token_data["symbol"] = src.get("symbol")

        base_price = src.get("price_usd") or src.get("entry_price")
        if _safe_float(token_data.get("price_usd"), 0.0) <= 0 and _safe_float(base_price, 0.0) > 0:
            token_data["price_usd"] = _safe_float(base_price)

        for k in ["cap_usd", "liquidity_usd", "volume_h24", "buy_sell_ratio", "token_age_min"]:
            if _safe_float(token_data.get(k), 0.0) <= 0 and _safe_float(src.get(k), 0.0) > 0:
                token_data[k] = src.get(k)

        for k in ["token_image_url", "token_image_path", "chart_screenshot"]:
            if _is_missing(token_data.get(k)) and not _is_missing(src.get(k)):
                token_data[k] = src.get(k)

        trusted_src = str(src.get("top10_ratio_source") or "").upper()
        if _is_trusted_top10_source(trusted_src):
            for k in ["top10_ratio", "top10_ratio_source", "top10_ratio_bitquery", "top10_ratio_gmgn"]:
                if _is_missing(token_data.get(k)) and not _is_missing(src.get(k)):
                    token_data[k] = src.get(k)

        if _is_missing(token_data.get("top10_ratio_helius")) and not _is_missing(src.get("top10_ratio_helius")):
            token_data["top10_ratio_helius"] = src.get("top10_ratio_helius")

        for k in ["chg_1m", "chg_5m", "chg_15m", "chg_30m", "chg_1h", "chg_3h", "chg_6h", "chg_24h"]:
            if token_data.get(k) is None and src.get(k) is not None:
                token_data[k] = src.get(k)

        for k in [
            "gmgn_smart",
            "gmgn_kol",
            "gmgn_blue_chip",
            "gmgn_sniper",
            "gmgn_phishing_wallets",
            "gmgn_rat",
            "gmgn_dev",
            "gmgn_bundle",
        ]:
            if token_data.get(k) is None and src.get(k) is not None:
                token_data[k] = src.get(k)

        for k in ["is_burned", "is_locked", "dex_paid", "mint_authority_present", "freeze_authority_present"]:
            if token_data.get(k) is None and src.get(k) is not None:
                token_data[k] = src.get(k)

    return token_data



def _apply_helius_security(token_data: dict, helius_sec: Optional[dict]) -> dict:
    if not helius_sec:
        return token_data

    hs = dict(helius_sec)
    helius_top10 = hs.pop("top10_ratio", None)
    token_data.update(hs)

    if not _is_missing(helius_top10):
        token_data["top10_ratio_helius"] = _safe_pct_text(helius_top10)

    return token_data



def _resolve_top10_ratio(token_data: dict, analytics: Optional[dict], bq_data: Optional[dict]) -> dict:
    current_text = _safe_pct_text(token_data.get("top10_ratio"))
    current_source = str(token_data.get("top10_ratio_source") or "").upper()

    bq_text = _safe_pct_text((bq_data or {}).get("bitquery_top10_ratio"))
    gmgn_text = _safe_pct_text((analytics or {}).get("top10_ratio"))
    helius_text = _safe_pct_text(token_data.get("top10_ratio_helius"))

    if bq_text:
        token_data["top10_ratio_bitquery"] = bq_text

    if gmgn_text:
        token_data["top10_ratio_gmgn"] = gmgn_text

    if helius_text:
        token_data["top10_ratio_helius"] = helius_text

    gmgn_val = _safe_float(gmgn_text, -1.0) if gmgn_text else -1.0
    gmgn_looks_bad = bool(gmgn_text) and gmgn_val >= 85.0 and not bq_text
    if gmgn_looks_bad:
        logger.warning(f"⚠️ GMGN Top10 疑似误抓高值，暂不采用: {gmgn_text}")

    if bq_text:
        token_data["top10_ratio"] = bq_text
        token_data["top10_ratio_source"] = "BITQUERY"
        return token_data

    if gmgn_text and not gmgn_looks_bad:
        token_data["top10_ratio"] = gmgn_text
        token_data["top10_ratio_source"] = "GMGN"
        return token_data

    if current_text and _is_trusted_top10_source(current_source):
        token_data["top10_ratio"] = current_text
        token_data["top10_ratio_source"] = current_source
        return token_data

    token_data["top10_ratio"] = None
    token_data["top10_ratio_source"] = ""
    return token_data



def _build_stable_snapshot(token_data: dict, analytics: Optional[dict] = None) -> dict:
    analytics = analytics or {}
    keys = [
        "symbol", "name", "price_usd", "cap_usd", "liquidity_usd", "volume_h24", "buy_sell_ratio",
        "chg_1m", "chg_5m", "chg_15m", "chg_30m", "chg_1h", "chg_3h", "chg_6h", "chg_24h",
        "token_image_url", "token_image_path", "is_burned", "is_locked", "token_age_min",
        "gmgn_smart", "gmgn_kol", "gmgn_blue_chip", "gmgn_sniper", "gmgn_phishing_wallets",
        "gmgn_rat", "gmgn_dev", "gmgn_bundle", "mint_authority_present", "freeze_authority_present",
        "dex_paid",
    ]
    snap = {k: token_data.get(k) for k in keys if token_data.get(k) is not None}

    trusted_src = str(token_data.get("top10_ratio_source") or "").upper()
    if _is_trusted_top10_source(trusted_src) and not _is_missing(token_data.get("top10_ratio")):
        snap["top10_ratio"] = token_data.get("top10_ratio")
        snap["top10_ratio_source"] = trusted_src

    if not _is_missing(token_data.get("top10_ratio_bitquery")):
        snap["top10_ratio_bitquery"] = token_data.get("top10_ratio_bitquery")
    if not _is_missing(token_data.get("top10_ratio_gmgn")):
        snap["top10_ratio_gmgn"] = token_data.get("top10_ratio_gmgn")
    if not _is_missing(token_data.get("top10_ratio_helius")):
        snap["top10_ratio_helius"] = token_data.get("top10_ratio_helius")

    screenshot = analytics.get("screenshot") or token_data.get("chart_screenshot")
    if screenshot:
        snap["chart_screenshot"] = screenshot

    return snap



def _build_analytics_for_ai(analytics: Optional[dict], terminal_states: Optional[dict]) -> dict:
    out = dict(analytics or {})
    terminal_states = terminal_states or {}
    stable = terminal_states.get("stable_snapshot") or {}
    screenshot = out.get("screenshot") or stable.get("chart_screenshot") or terminal_states.get("chart_screenshot")
    if screenshot and os.path.exists(screenshot):
        out["screenshot"] = screenshot
    return out


def _apply_gmgn_analytics(token_data: dict, analytics: Optional[dict], *, patch_timeframes_only_when_missing: bool = True) -> dict:
    if not analytics:
        return token_data

    if token_data.get("symbol") == "UNK" and analytics.get("symbol"):
        token_data["symbol"] = analytics.get("symbol")

    logo = analytics.get("logo") or analytics.get("token_image_url")
    if logo and not token_data.get("token_image_url"):
        token_data["token_image_url"] = logo

    if analytics.get("token_image_path") and not token_data.get("token_image_path"):
        token_data["token_image_path"] = analytics.get("token_image_path")

    if analytics.get("price") and _safe_float(token_data.get("price_usd"), 0.0) <= 0:
        token_data["price_usd"] = _safe_float(analytics.get("price"))

    mcap_val = analytics.get("fdv") or analytics.get("market_cap") or analytics.get("mcap")
    if _safe_float(token_data.get("cap_usd"), 0.0) <= 0 and _safe_float(mcap_val, 0.0) > 0:
        token_data["cap_usd"] = _safe_float(mcap_val)

    liq_val = analytics.get("header_liq_usd") or analytics.get("liquidity_usd") or analytics.get("liquidity")
    if _safe_float(token_data.get("liquidity_usd"), 0.0) <= 0 and _safe_float(liq_val, 0.0) > 0:
        token_data["liquidity_usd"] = _safe_float(liq_val)

    creation_time = (
        analytics.get("pool_creation_timestamp")
        or analytics.get("open_timestamp")
        or analytics.get("creation_timestamp")
    )
    if creation_time and _safe_float(token_data.get("token_age_min")) <= 0:
        token_data["token_age_min"] = int(max(0, (time.time() - float(creation_time)) / 60))

    time_keys = [
        ("1m", "m1"), ("5m", "m5"), ("15m", "m15"), ("30m", "m30"),
        ("1h", "h1"), ("3h", "h3"), ("6h", "h6"), ("24h", "h24"),
    ]
    raw_data = analytics.get("raw_data") or {}
    for src_key, alt_key in time_keys:
        dst = f"chg_{src_key}"
        new_v = analytics.get(dst)
        if new_v is None:
            new_v = analytics.get(f"price_change_{alt_key}")
        if new_v is None:
            new_v = raw_data.get(dst)
        if new_v is None:
            continue
        if patch_timeframes_only_when_missing and token_data.get(dst) is not None:
            continue
        token_data[dst] = new_v

    if analytics.get("is_burned") is not None and token_data.get("is_burned") is None:
        token_data["is_burned"] = analytics.get("is_burned")

    if analytics.get("dex_paid") is not None and token_data.get("dex_paid") is None:
        token_data["dex_paid"] = analytics.get("dex_paid")

    if analytics.get("screenshot"):
        token_data["chart_screenshot"] = analytics.get("screenshot")

    raw = raw_data if isinstance(raw_data, dict) else {}
    tag_map = {
        "gmgn_smart": raw.get("smart"),
        "gmgn_kol": raw.get("kol"),
        "gmgn_blue_chip": raw.get("blue_chip"),
        "gmgn_sniper": raw.get("sniper"),
        "gmgn_phishing_wallets": raw.get("phishing_wallets"),
        "gmgn_rat": raw.get("rat"),
        "gmgn_dev": raw.get("dev"),
        "gmgn_bundle": raw.get("bundle"),
    }
    for key, new_v in tag_map.items():
        if new_v is None:
            continue
        try:
            iv = int(float(new_v))
        except Exception:
            continue
        if iv > 0:
            token_data[key] = iv

    gmgn_top10 = _safe_pct_text(analytics.get("top10_ratio"))
    if gmgn_top10:
        token_data["top10_ratio_gmgn"] = gmgn_top10

    return token_data


async def _return_none() -> None:
    return None


@main_router.callback_query(F.data.startswith("deep_ai:"))
async def process_deep_ai_callback(cq: CallbackQuery):
    ca = cq.data.split(":")[1]
    await cq.answer("🧠 正在调取大模型矩阵进行深度分析...", show_alert=False)
    spawn_task(trigger_deep_ai_report(ca, cq.message.chat.id, cq.message.message_id), f"DeepAI_{ca[:6]}")


async def trigger_deep_ai_report(ca: str, chat_id: int, msg_id: int):
    try:
        record = await db.get_signal_snapshot(ca)
        terminal_states = record.get("terminal_states", {}) if record else {}

        raw_market, helius_sec, analytics, bq_data = await asyncio.gather(
            safe_call(get_market_data(ca), 12, "DeepAI_Market"),
            safe_call(get_helius_security(ca), 8, "DeepAI_Helius"),
            safe_call(get_gmgn_analytics(ca), 30, "DeepAI_GMGN"),
            safe_call(bitquery.fetch_comprehensive_data(ca), 20, "DeepAI_Bitquery"),
        )

        token_data = normalize_token_data(
            ca,
            raw_market or {"symbol": terminal_states.get("symbol", "TOKEN")},
            "DEEP_AI",
            chat_id,
            msg_id,
        )
        token_data = _merge_existing_terminal(token_data, terminal_states)
        token_data = _apply_helius_security(token_data, helius_sec)
        token_data = _apply_gmgn_analytics(token_data, analytics, patch_timeframes_only_when_missing=True)
        token_data = _resolve_top10_ratio(token_data, analytics, bq_data)

        avatar_path = await safe_call(fetcher.ensure_token_avatar(ca, token_data.get("token_image_url", "")), 10, "DeepAI_Avatar")
        if avatar_path:
            token_data["token_image_path"] = avatar_path

        analytics_for_ai = _build_analytics_for_ai(analytics, terminal_states)
        decision = await brain.analyze_dynamic_strategy(token_data, terminal_states, analytics_for_ai)

        initial_msg_id = record.get("initial_msg_id") if record and record.get("initial_msg_id") else msg_id
        report_text = build_ai_report_text(ca, token_data, decision)
        await send_thread_reply(chat_id, initial_msg_id, report_text)
        await update_user_message(chat_id=chat_id, message_id=initial_msg_id, ca=ca, token_data=token_data, decision=decision)
    except Exception as e:
        logger.error(f"❌ 深度报告生成失败: {e}", exc_info=True)


async def trigger_milestone_update(ca: str, chat_id: int, record: dict, current_price: float, current_mcap: float, delta: float, trigger_gate: Optional[int] = None):
    try:
        terminal_states = record.get("terminal_states", {}) or {}
        token_data = {
            "symbol": terminal_states.get("symbol", "TOKEN"),
            "price_usd": current_price,
            "cap_usd": current_mcap,
            "ca": ca,
        }
        token_data = _merge_existing_terminal(token_data, terminal_states)
        analytics_for_ai = _build_analytics_for_ai(None, terminal_states)

        decision = await brain.analyze_dynamic_strategy(token_data, terminal_states, analytics_for_ai)

        initial_msg_id = record.get("initial_msg_id")
        text = build_milestone_text(ca, token_data, decision, delta)

        if initial_msg_id:
            await send_thread_reply(chat_id, initial_msg_id, text)

        await db.update_milestone(ca, current_price)
    except Exception as e:
        logger.error(f"❌ 战报更新失败: {e}", exc_info=True)


async def safe_call(coro, timeout_s: int, name: str):
    try:
        return await asyncio.wait_for(coro, timeout=timeout_s)
    except asyncio.TimeoutError:
        logger.warning(f"⏳ {name} 超时({timeout_s}s)")
        return None
    except Exception as e:
        logger.exception(f"💥 {name} 异常: {e}")
        return None


async def get_market_data_force(ca: str):
    try:
        return await fetcher.get_market_data(ca, force=True)
    except TypeError:
        return await get_market_data(ca)
    except Exception:
        return await get_market_data(ca)


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
        "reply_chat_id": chat_id,
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
        "token_image_url": raw_market.get("token_image_url") or raw_market.get("logo"),
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
    ca = (ca or "").strip()
    if not ca:
        return

    now = time.time()
    async with _in_flight_lock:
        for k, ts in list(_in_flight_signals.items()):
            if now - ts > 600:
                _in_flight_signals.pop(k, None)
        last_ts = _in_flight_signals.get(ca)
        if last_ts and (now - last_ts < 30):
            logger.info(f"🛡️ 防暴盾生效: {ca[:6]}... 已静默拦截并发！")
            return
        _in_flight_signals[ca] = now

    logger.info(f"⚡ 开始处理信号: CA={ca} | 来源={source}")

    try:
        is_dm = ("DM_USER" in str(source) or source == "MANUAL_QUERY")

        if not is_dm:
            try:
                record = await asyncio.wait_for(db.get_signal_snapshot(ca), timeout=3.0)
                if record:
                    try:
                        price_res = await fetcher.get_price_only(ca)
                        price = price_res[0] if isinstance(price_res, tuple) else float(price_res)
                        mcap = price_res[1] if isinstance(price_res, tuple) else 0.0

                        logger.info(f"🔎 [价格嗅探] CA: {ca[:6]}... | 最新现价: ${price:.6f}")

                        initial_price = float(record.get("entry_price") or 0)
                        last_notified_price = float(record.get("last_notified_price") or initial_price)

                        if initial_price <= 0 or price <= 0:
                            logger.info(f"♻️ {ca} 价格异常(初始:{initial_price}, 现价:{price})，静默拦截。")
                            return

                        if initial_price <= 0:
                            terminal_states["milestone_anchor_price"] = price
                            terminal_states.setdefault("entry_price", price)
                            stable = terminal_states.get("stable_snapshot") or {}
                            if _safe_float(stable.get("price_usd"), 0.0) <= 0:
                                stable["price_usd"] = price
                            terminal_states["stable_snapshot"] = stable
                            await safe_call(
                                db.save_initial_signal(ca, "SYSTEM", price, record.get("initial_msg_id") or msg_id, terminal_states),
                                2,
                                "DB_AnchorHeal",
                            )
                            logger.info(f"🩹 {ca} 里程碑锚点缺失，已用现价自愈为 1.00x 基准。")
                            return

                        current_multiplier = price / initial_price
                        peak_multiplier = max(1.0, last_notified_price / initial_price if initial_price > 0 else 1.0)
                        next_gate = max(2, int(peak_multiplier) + 1)
                        gate_tolerance = 0.10
                        gate_hit = current_multiplier >= max(1.0, next_gate - gate_tolerance)

                        if gate_hit:
                            logger.info(
                                f"🎉 [里程碑突破] {ca[:8]} 从 {peak_multiplier:.2f}x 飙升至 {current_multiplier:.2f}x！(突破 {next_gate}x 大关)"
                            )
                            spawn_task(
                                trigger_milestone_update(ca, chat_id, record, price, mcap, current_multiplier, next_gate),
                                f"Milestone_{ca[:6]}",
                            )
                            return
                        else:
                            logger.info(f"♻️ {ca} 已存在，当前 {current_multiplier:.2f}x，未突破 {next_gate}x 整数关口，静默拦截。")
                            return

                    except Exception as e:
                        logger.error(f"❌ 战报验价及整数倍计算失败: {e}")
                        return
            except Exception as e:
                logger.warning(f"⚠️ 数据库查重超时跳过: {e}")

        logger.info(f"⏳ 开始抓取 ({ca[:4]}...) 核心数据...")

        early_anchor_price = 0.0
        early_anchor_res = await safe_call(fetcher.get_price_only(ca), 3, "PriceOnly")
        if isinstance(early_anchor_res, tuple) and len(early_anchor_res) >= 1:
            early_anchor_price = _safe_float(early_anchor_res[0], 0.0)
        else:
            early_anchor_price = _safe_float(early_anchor_res, 0.0)

        raw_market, helius_sec = await asyncio.gather(
            safe_call(get_market_data(ca), 10, "Market"),
            safe_call(get_helius_security(ca), 5, "Helius"),
        )

        if not raw_market:
            raw_market = {"symbol": "UNK"}

        token_data = normalize_token_data(ca, raw_market, source, chat_id, msg_id)
        token_data = _apply_helius_security(token_data, helius_sec)

        # 首卡阶段不等待 GMGN / Bitquery / 头像落盘。
        # Top10 若没有可信来源，直接留空，等待深度链回写。
        token_data = _resolve_top10_ratio(token_data, None, None)

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
            await asyncio.wait_for(
                db.execute(
                    "INSERT INTO tokens_meta (ca, symbol, name) VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
                    ca,
                    token_data.get("symbol"),
                    token_data.get("name"),
                ),
                timeout=2.0,
            )
        except Exception:
            pass

        strat_res = detect_strategy(token_data)
        if isinstance(strat_res, tuple):
            token_data["strategy_id"] = str(strat_res[0])
        else:
            token_data["strategy_id"] = str(strat_res)

        logger.info("🚀 准备下发初期战报卡片...")
        fast_msg_id = await notify_user_fast(ca=ca, token_data=token_data)
        if not fast_msg_id:
            logger.error("❌ notify_user_fast 未返回 msg_id，发卡片失败！")
            return

        try:
            entry_price = early_anchor_price if early_anchor_price > 0 else _safe_float(token_data.get("price_usd"), 0.0)
            if entry_price <= 0:
                pr = await safe_call(fetcher.get_price_only(ca), 3, "AnchorRetry")
                if isinstance(pr, tuple) and len(pr) >= 1:
                    entry_price = _safe_float(pr[0], entry_price)
                else:
                    entry_price = _safe_float(pr, entry_price)

            terminal_states_fast = {
                "symbol": token_data.get("symbol", "UNK"),
                "entry_price": entry_price,
                "milestone_anchor_price": entry_price,
                "cap_usd": _safe_float(token_data.get("cap_usd"), 0.0),
                "liquidity_usd": _safe_float(token_data.get("liquidity_usd"), 0.0),
                "token_image_url": token_data.get("token_image_url", ""),
                "token_image_path": token_data.get("token_image_path", ""),
                "is_burned": bool(token_data.get("is_burned")) if token_data.get("is_burned") is not None else False,
                "reply_chat_id": chat_id,
                "stable_snapshot": _build_stable_snapshot(token_data),
            }
            await safe_call(db.save_initial_signal(ca, "SYSTEM", entry_price, fast_msg_id, terminal_states_fast), 2, "DB_FastSave")
        except Exception:
            pass

        spawn_task(
            run_deep_analysis(ca, token_data, fast_msg_id, chat_id, use_insightx=(not is_dm)),
            f"DeepAnalysis_{ca[:6]}",
        )

    except Exception as e:
        logger.exception(f"💥 process_new_signal 核心处理崩溃: {e}")


async def run_deep_analysis(ca: str, token_data: dict, message_id: int, chat_id: int, use_insightx: bool = False):
    try:
        existing_record = await db.get_signal_snapshot(ca)
        existing_terminal = existing_record.get("terminal_states", {}) if existing_record else {}
        token_data = _merge_existing_terminal(token_data or {}, existing_terminal)

        rug_task = safe_call(get_rugcheck_data(ca), 8, "RugCheck")
        bq_task = safe_call(bitquery.fetch_comprehensive_data(ca), 20, "Bitquery")
        goplus_task = safe_call(get_goplus_security(ca), 10, "GoPlus")
        gmgn_task = safe_call(get_gmgn_analytics(ca), 45, "GMGN")
        ix_task = safe_call(insightx_agent.fetch_deep_analysis(ca), 15, "InsightX") if use_insightx else _return_none()

        rug_data, bq_data, goplus_data, analytics, ix_data = await asyncio.gather(
            rug_task,
            bq_task,
            goplus_task,
            gmgn_task,
            ix_task,
        )

        if not token_data.get("cap_usd") or _safe_float(token_data.get("cap_usd")) == 0:
            logger.info("🔄 启动二次挽救机制: 重试 DexScreener 以修复0值...")
            retry_market = await safe_call(get_market_data_force(ca), 5, "MarketRetry")
            if retry_market:
                if retry_market.get("priceUsd"):
                    token_data["price_usd"] = _safe_float(retry_market.get("priceUsd"))
                if retry_market.get("fdv"):
                    token_data["cap_usd"] = _safe_float(retry_market.get("fdv"))

                liq = retry_market.get("liquidity_usd")
                if not liq and isinstance(retry_market.get("liquidity"), dict):
                    liq = retry_market.get("liquidity", {}).get("usd")
                if liq:
                    token_data["liquidity_usd"] = _safe_float(liq)

                created_at = retry_market.get("pairCreatedAt")
                if created_at:
                    token_data["token_age_min"] = int(max(0, (time.time() - float(created_at) / 1000) / 60))

                if retry_market.get("info", {}).get("imageUrl"):
                    token_data["token_image_url"] = retry_market.get("info", {}).get("imageUrl")

                if retry_market.get("baseToken", {}).get("symbol"):
                    token_data["symbol"] = retry_market.get("baseToken").get("symbol")

        if rug_data:
            token_data["is_burned"] = (_safe_float(rug_data.get("lp_burned_pct"), 0) > 95)
            token_data["is_locked"] = (_safe_float(rug_data.get("lp_locked_pct"), 0) > 95)

        if goplus_data and goplus_data.get("is_honeypot"):
            token_data["risk_flags"] = token_data.get("risk_flags", []) + ["🚨 貔貅盘(GoPlus)"]

        token_data = _apply_gmgn_analytics(token_data, analytics, patch_timeframes_only_when_missing=True)
        token_data = _resolve_top10_ratio(token_data, analytics, bq_data)

        avatar_path = await safe_call(fetcher.ensure_token_avatar(ca, token_data.get("token_image_url", "")), 10, "AvatarCache")
        if avatar_path:
            token_data["token_image_path"] = avatar_path

        analytics_for_ai = _build_analytics_for_ai(analytics, existing_terminal)
        if token_data.get("chart_screenshot") and not analytics_for_ai.get("screenshot"):
            analytics_for_ai["screenshot"] = token_data.get("chart_screenshot")

        curr_price = _safe_float(token_data.get("price_usd"), 0.0)
        curr_mcap = _safe_float(token_data.get("cap_usd"), 0.0)

        if curr_price > 0:
            strat_res = detect_strategy(token_data)
            strategy_id = str(strat_res[0]) if isinstance(strat_res, tuple) else str(strat_res)
            config = strat_res[1] if isinstance(strat_res, tuple) else {}
            token_data["strategy_id"] = strategy_id

            await tp_tracker.init_position(
                ca=ca,
                entry_price=curr_price,
                strategy_id=strategy_id,
                config=config,
                initial_mcap=curr_mcap,
                reply_chat_id=chat_id,
                reply_msg_id=message_id,
            )
            await tp_tracker.observe_price(ca, curr_price)
            token_data["baseline"] = await tp_tracker.get_baseline_metrics(ca, current_price=curr_price)

            existing_open = getattr(paper_portfolio_engine, "open_positions", {}) or {}
            if ca not in existing_open:
                paper_ret = paper_portfolio_engine.open_position(
                    ca=ca,
                    symbol=str(token_data.get("symbol") or "UNK"),
                    strategy=str(strategy_id or "MIXED"),
                    entry_price=curr_price,
                    entry_mcap=curr_mcap,
                    opened_at=time.time(),
                )
                if paper_ret.get("ok"):
                    logger.info(
                        f"📒 PaperPortfolio 开仓成功: {ca[:6]}... | strategy={strategy_id} | "
                        f"alloc={paper_ret.get('allocated_sol')} SOL | cash_left={paper_ret.get('cash_left_sol')} SOL"
                    )
                else:
                    logger.info(f"📒 PaperPortfolio 未开仓: {ca[:6]}... | reason={paper_ret.get('reason')}")
            else:
                logger.info(f"📒 PaperPortfolio 已存在持仓，跳过重复开仓: {ca[:6]}...")

        if ix_data:
            token_data["insightx"] = {
                "gini": ix_data.get("gini_coefficient"),
                "smart_money": ix_data.get("smart_money_count"),
                "is_bundled": ix_data.get("bundled_sniper"),
                "partial": ix_data.get("insightx_partial"),
                "rate_limited": ix_data.get("insightx_rate_limited"),
            }
            if ix_data.get("bundled_sniper"):
                token_data["risk_flags"] = token_data.get("risk_flags", []) + ["🚨 疑似老鼠仓(InsightX)"]

        if LGB_AVAILABLE and lgb_model:
            try:
                features = calculate_ml_features(token_data, analytics_for_ai or {}, {})
                ml_features_array = np.array([[
                    _safe_float(token_data.get("cap_usd"), 0),
                    _safe_float(token_data.get("liquidity_usd"), 0),
                    _safe_float(features.get("smart_money_delta"), 0),
                    _safe_float(features.get("maker_vol_ratio"), 0),
                    _safe_float(features.get("overhang_ratio"), 0),
                    _safe_float(features.get("breakout_vol_ratio"), 0),
                ]])

                win_prob = lgb_model.predict(ml_features_array)[0]
                token_data["lgb_win_prob"] = win_prob

                if win_prob > 0.85:
                    token_data["risk_flags"] = token_data.get("risk_flags", []) + [f"🎯 AI预测极高胜率 ({win_prob:.1%})"]
                elif win_prob < 0.20:
                    token_data["risk_flags"] = token_data.get("risk_flags", []) + [f"🗑️ AI预测极低胜率 ({win_prob:.1%})"]
            except Exception as e:
                logger.error(f"⚠️ LightGBM 预测执行失败: {e}")

        temp_decision = {"verdict": "WAIT", "reason": "🧠 核心数据已就绪，AI 正在进行深度模型推演，请稍候..."}
        await update_user_message(chat_id=chat_id, message_id=message_id, ca=ca, token_data=token_data, decision=temp_decision)

        static_res = await safe_call(brain.analyze_static_narrative(token_data, analytics_for_ai), 90, "AI_Static") or {}

        stable_snapshot = _build_stable_snapshot(token_data, analytics_for_ai)
        terminal_states = {
            "ai_narrative": static_res.get("ai_narrative") or "静态脑样本不足，暂以盘面与筹码为主。",
            "ai_image_read": static_res.get("ai_image_read") or "头像/社交样本不足，暂不下视觉结论。",
            "entry_price": curr_price,
            "milestone_anchor_price": _safe_float((existing_terminal or {}).get("milestone_anchor_price"), _safe_float((existing_terminal or {}).get("entry_price"), curr_price)) or curr_price,
            "is_burned": token_data.get("is_burned", False),
            "symbol": token_data.get("symbol", "UNK"),
            "token_image_url": token_data.get("token_image_url", ""),
            "token_image_path": token_data.get("token_image_path", ""),
            "cap_usd": token_data.get("cap_usd", 0),
            "liquidity_usd": token_data.get("liquidity_usd", 0),
            "reply_chat_id": chat_id,
            "chart_screenshot": analytics_for_ai.get("screenshot", ""),
            "stable_snapshot": stable_snapshot,
        }

        decision = await safe_call(brain.analyze_dynamic_strategy(token_data, terminal_states, analytics_for_ai), 90, "AI_Dynamic") or {}
        decision, pos_info, _ = apply_final_gate(token_data, decision, None)
        token_data["pos_info"] = pos_info

        try:
            await db.save_initial_signal(ca, "SYSTEM", terminal_states["milestone_anchor_price"], message_id, terminal_states)
            await asyncio.wait_for(
                db.execute(
                    "UPDATE signals_snapshot SET rank_score = $1, ai_narrative = $2, status = 'analyzed' WHERE ca = $3",
                    float(decision.get("score", 0)),
                    decision.get("reason", ""),
                    ca,
                ),
                timeout=2.0,
            )
        except Exception as e:
            logger.error(f"⚠️ 保存初始状态失败: {e}")

        await update_user_message(chat_id=chat_id, message_id=message_id, ca=ca, token_data=token_data, decision=decision)
        spawn_task(evolve_database(ca, token_data, analytics or {}, ix_data or {}), f"EvolveDB_{ca[:6]}")

    except Exception as e:
        logger.exception(f"💥 run_deep_analysis 异常: {e}")


async def evolve_database(ca: str, token_data: dict, gmgn_data: dict, ix_data: dict):
    try:
        mcap = token_data.get("cap_usd", 0)
        liq = token_data.get("liquidity_usd", 0)
        age = token_data.get("token_age_min", 0)
        holders = token_data.get("top10_ratio") or (gmgn_data.get("top10_ratio") if gmgn_data else "N/A")

        await db.execute("""
            INSERT INTO golden_dog_morphology 
            (ca, snapshot_time, token_age_mins_at_snap, market_cap_at_snap, liquidity_at_snap, holder_distribution, social_signal)
            VALUES ($1, NOW(), $2, $3, $4, $5, $6)
            ON CONFLICT (ca, snapshot_time) DO NOTHING
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

    except Exception as e:
        logger.error(f"🧬 数据库进化失败: {e}")


async def price_monitor_loop():
    logger.info("🕵️‍♂️ 价格及里程碑监控服务已启动... (Jupiter 主查价 + Dex 兜底)")
    while True:
        try:
            await asyncio.sleep(1.5)
            for ca, pos in list(tp_tracker.data.items()):
                if str(pos.get("status", "")).upper() != "ACTIVE":
                    continue

                try:
                    price_res = await fetcher.get_price_only(ca)
                    price_f = price_res[0] if isinstance(price_res, tuple) else float(price_res)
                    mcap_f = price_res[1] if isinstance(price_res, tuple) else 0.0
                except Exception:
                    continue

                if price_f <= 0:
                    continue

                await tp_tracker.observe_price(ca, price_f)
                paper_portfolio_engine.mark_price(ca, price_f, mcap_f)

                event_dict = await tp_tracker.update(ca, price_f, curr_mcap=mcap_f)
                if event_dict and isinstance(event_dict, dict):
                    event_type = event_dict.get("event")
                    t_chat_id = pos.get("reply_chat_id")
                    t_msg_id = pos.get("reply_msg_id")

                    if event_type == "MILESTONE":
                        if t_chat_id and t_msg_id:
                            mult = event_dict.get("multiplier")
                            pnl = event_dict.get("pnl", 0.0)

                            img_path = await asyncio.to_thread(
                                generate_milestone_image,
                                symbol="TOKEN",
                                mcap=mcap_f,
                                multiplier=mult,
                                ca=ca,
                            )
                            if img_path:
                                if hasattr(tp_tracker, "update_custom_image"):
                                    await tp_tracker.update_custom_image(ca, img_path)
                                else:
                                    tp_tracker.data[ca]["custom_image"] = img_path
                                    await tp_tracker._save()

                            report_text = (
                                f"🚀 <b>里程碑突破战报</b>\n\n"
                                f"🎉 代币: <code>{ca}</code>\n"
                                f"📈 当前倍数: <b>{mult}x</b>\n"
                                f"💰 实时收益: <b>{pnl:+.1f}%</b>\n\n"
                                f"AI 持续监控中，利润正在奔跑。"
                            )
                            await send_thread_reply(t_chat_id, t_msg_id, report_text)
                            await refresh_token_panel(ca, t_chat_id, t_msg_id, force_deep=False)

                    elif event_type in ["CLOSED_TP", "CLOSED_SL"]:
                        strategy_id = pos.get("strategy_id", "DEFAULT")
                        pnl_pct = event_dict.get("pnl_percentage", 0.0)

                        stats_engine.record(
                            strategy=strategy_id,
                            result_type=event_type,
                            pnl_percent=pnl_pct,
                            ca=ca,
                        )

                        paper_ret = _paper_portfolio_call("on_final_close", ca, price_f, mcap_f, reason=event_type)
                        if paper_ret.get("ok"):
                            logger.info(
                                f"📒 PaperPortfolio 平仓成功: {ca[:6]}... | reason={event_type} | "
                                f"net_pnl={paper_ret.get('net_pnl_sol')} SOL | cash={paper_ret.get('cash_sol')} SOL"
                            )

                        if t_chat_id and t_msg_id:
                            if event_type == "CLOSED_SL":
                                report_text = (
                                    f"🛑 <b>铁血止损触发</b>\n\n"
                                    f"代币: <code>{ca}</code>\n"
                                    f"操作: <b>市价清仓</b>\n"
                                    f"最终盈亏: <b>{pnl_pct:+.2f}%</b>\n"
                                    f"说明: 留得青山在，不怕没柴烧。"
                                )
                            else:
                                report_text = (
                                    f"🎯 <b>完美止盈落袋</b>\n\n"
                                    f"代币: <code>{ca}</code>\n"
                                    f"操作: <b>全量获利了结</b>\n"
                                    f"最终盈亏: <b>{pnl_pct:+.2f}%</b>\n"
                                    f"说明: 恭喜猎手，利润已安全入库。"
                                )

                            await send_thread_reply(t_chat_id, t_msg_id, report_text)

                    elif str(event_type).startswith("止盈"):
                        pnl_pct = event_dict.get("pnl", 0.0)
                        paper_ret = _paper_portfolio_call("on_tp_event", ca, price_f, mcap_f, str(event_type))
                        if paper_ret.get("ok"):
                            logger.info(
                                f"📒 PaperPortfolio 部分止盈: {ca[:6]}... | {event_type} | "
                                f"net_pnl={paper_ret.get('net_pnl_sol')} SOL | cash={paper_ret.get('cash_sol')} SOL"
                            )

                        if t_chat_id and t_msg_id:
                            report_text = (
                                f"💸 <b>阶段止盈触发</b>\n\n"
                                f"代币: <code>{ca}</code>\n"
                                f"进度: <b>{event_type}</b>\n"
                                f"当前收益: <b>{pnl_pct:+.2f}%</b>\n"
                                f"说明: 已抛售部分仓位锁定利润，剩余仓位继续博取更高倍数。"
                            )
                            await send_thread_reply(t_chat_id, t_msg_id, report_text)

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"💥 价格监控主循环发生系统级异常: {e}", exc_info=True)
            await asyncio.sleep(2.0)


async def refresh_token_panel(ca: str, chat_id: int, message_id: int, force_deep: bool = True):
    raw_market, helius_sec = await asyncio.gather(
        safe_call(get_market_data(ca), 12, "Market"),
        safe_call(get_helius_security(ca), 12, "Helius"),
    )

    existing_record = await db.get_signal_snapshot(ca)
    existing_terminal = existing_record.get("terminal_states", {}) if existing_record else {}

    token_data = normalize_token_data(ca, raw_market or {}, "REFRESH", chat_id, message_id)
    token_data = _merge_existing_terminal(token_data, existing_terminal)
    token_data = _apply_helius_security(token_data, helius_sec)
    token_data = _resolve_top10_ratio(token_data, None, None)

    pos = tp_tracker.data.get(ca, {})
    if pos.get("custom_image") and os.path.exists(pos.get("custom_image")):
        token_data["token_image_path"] = pos.get("custom_image")
        token_data["token_image_url"] = ""

    curr_price = _safe_float(token_data.get("price_usd"), 0.0)

    if curr_price > 0 and pos and not (
        _safe_float(pos.get("entry"), 0.0) == 0.0
        and str(pos.get("strategy_id", "")).upper() in {"", "UNKNOWN", "UNK"}
        and str(pos.get("status", "")).upper() == "OBSERVE"
    ):
        await tp_tracker.observe_price(ca, curr_price)
        token_data["baseline"] = await tp_tracker.get_baseline_metrics(ca, current_price=curr_price)

    await update_user_message(chat_id, message_id, ca, token_data, {"verdict": "REFRESH", "reason": "刷新中..."})
    if force_deep:
        spawn_task(run_deep_analysis(ca, token_data, message_id, chat_id, use_insightx=False), f"RefreshDeep_{ca[:6]}")


async def main():
    logger.info("🚀 SolanaHunter V3.6 核心引擎与安全网启动...")

    try:
        pp_summary = paper_portfolio_engine.summary()
        logger.info(
            "📒 PaperPortfolio 已加载: "
            f"cash={pp_summary.get('cash_sol')} SOL | "
            f"equity={pp_summary.get('equity_sol')} SOL | "
            f"open={pp_summary.get('open_positions')} | "
            f"closed={pp_summary.get('closed_trades')} | "
            f"roi={pp_summary.get('roi_pct')}%"
        )
    except Exception as e:
        logger.warning(f"⚠️ PaperPortfolio 启动摘要读取失败: {e}")

    try:
        from modules.commander import dp
        from modules.notifier import refresh_router
        dp.include_router(refresh_router)
        dp.include_router(main_router)
    except Exception as e:
        logger.error(f"路由注册异常: {e}")

    await fetcher.prepare_browser_profile()
    await db.init_pool()

    try:
        try:
            from modules.watchdog import time_series_patrol_loop
            spawn_task(time_series_patrol_loop(), "WatchdogPatrol")
        except ImportError:
            pass

        spawn_task(price_monitor_loop(), "PriceMonitorLoop")

        try:
            await start_listener(process_new_signal, refresh_token_panel, trigger_deep_ai_report)
        except TypeError:
            await start_listener(process_new_signal, refresh_token_panel)

    except asyncio.CancelledError:
        logger.info("🛑 收到内部取消信号...")
    except Exception as e:
        logger.exception(f"💥 主程序运行时发生致命错误: {e}")
    finally:
        logger.info("🧹 正在执行全局优雅停机 (Graceful Shutdown)...")
        if fetcher:
            try:
                await fetcher.close()
                logger.info("✅ 爬虫与无头浏览器已安全关闭。")
            except Exception as e:
                logger.error(f"关闭爬虫资源时出错: {e}")

        try:
            closer = getattr(insightx_agent, "close", None) or getattr(insightx_agent, "aclose", None)
            if closer:
                r = closer()
                if asyncio.iscoroutine(r):
                    await r
                logger.info("✅ InsightX 客户端已安全关闭。")
        except Exception as e:
            logger.error(f"关闭 InsightX 资源时出错: {e}")

        try:
            paper_portfolio_engine.save()
            logger.info("✅ PaperPortfolio 状态已安全保存。")
        except Exception as e:
            logger.error(f"关闭 PaperPortfolio 资源时出错: {e}")

        if db:
            try:
                await db.close_pool()
                logger.info("✅ 数据库连接池已安全释放。")
            except Exception as e:
                logger.error(f"关闭数据库资源时出错: {e}")

        logger.info("👋 资源清理完成，主程序安全退出。")


if __name__ == "__main__":
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 已收到终止命令(Ctrl+C)，开始断开系统连接...")