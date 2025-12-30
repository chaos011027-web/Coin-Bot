import logging
import html
import asyncio
import os
import math
from typing import Optional, Any, Dict, Callable

from aiogram.enums import ParseMode
from aiogram.types import FSInputFile
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramRetryAfter
from aiogram.utils.keyboard import InlineKeyboardBuilder

from modules.commander import bot
from config.settings import REPORT_GROUP_ID

from modules.score_engine import calc_score_breakdown
from modules.strategy_engine import detect_strategy, render_strategy_plan
from modules.stats_engine import stats_engine
from modules.tp_tracker import tp_tracker
from modules.performance_engine import performance_engine
from modules.risk_engine import get_risk_level

# position_engine / position_manager 兼容
try:
    from modules.position_engine import calc_position_size
except Exception:
    from modules.position_manager import calc_position_size  # type: ignore

logger = logging.getLogger("Notifier")

# Telegram 限制常数
MAX_TEXT_LEN = 3800
MAX_CAPTION_LEN = 950


# ===========================
# 🛠️ 格式化工具
# ===========================
def _clip(s: str, max_len: int) -> str:
    if not s:
        return ""
    return s if len(s) <= max_len else (s[: max_len - 3] + "...")

def _safe_float(x: Any) -> Optional[float]:
    try:
        if x is None or x == "":
            return None
        if isinstance(x, str):
            x = x.replace(",", "").strip()
        v = float(x)
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    except Exception:
        return None

def format_number(num: Any) -> str:
    n = _safe_float(num)
    if n is None:
        return "N/A"
    if n == 0:
        return "0"
    abs_n = abs(n)
    if abs_n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.2f}B"
    if abs_n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if abs_n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return f"{n:,.0f}"

def format_price(price: Any) -> str:
    p = _safe_float(price)
    if p is None:
        return "-"
    if p == 0:
        return "$0"
    if p < 0.000001:
        return f"${p:.10f}".rstrip("0")
    if p < 0.001:
        return f"${p:.8f}".rstrip("0")
    if p < 1.0:
        return f"${p:.5f}"
    return f"${p:,.2f}"

def _get_verdict_emoji(action: str, score: int, is_auto_push: bool) -> str:
    if is_auto_push:
        return "🚀"
    action = (action or "").upper()
    if action == "BUY":
        return "🟢"
    if action == "WATCH":
        return "👀"
    if score < 30:
        return "🔴"
    return "🟡"


# ===========================
# 🔘 Keyboard（按你的要求：去掉 Dex / Pump，只留 GMGN；也可直接 return None）
# ===========================
def _build_keyboard(ca: str):
    if not ca:
        return None
    kb = InlineKeyboardBuilder()
    kb.button(text="⚡ GMGN", url=f"https://gmgn.ai/sol/token/{ca}")
    kb.adjust(1)
    return kb


# ===========================
# 🧩 渲染组件
# ===========================
def _render_gmgn_section(token_data: dict) -> str:
    """
    渲染 GMGN 链上结构（优先结构化字段；兼容旧 tags）
    """
    smart = int(token_data.get("gmgn_smart", 0) or 0)
    kol = int(token_data.get("gmgn_kol", 0) or 0)
    sniper = int(token_data.get("gmgn_sniper", 0) or 0)
    degen = int(token_data.get("gmgn_degen", 0) or 0)
    dev = int(token_data.get("gmgn_dev", 0) or 0)
    rat = int(token_data.get("gmgn_rat", 0) or 0)
    bundle = int(token_data.get("gmgn_bundle", 0) or 0)

    # 没结构化数据则尝试 tags
    if smart == 0 and kol == 0 and sniper == 0 and bundle == 0 and rat == 0 and degen == 0 and dev == 0:
        tags = token_data.get("gmgn_tags", []) or []
        if tags:
            return f"🕵️‍♂️ <b>GMGN 标签:</b>\n{' | '.join(map(html.escape, map(str, tags)))}\n"
        return ""

    warn = " ⚠️" if (bundle >= 100 or sniper >= 50) else ""
    return (
        "🕵️‍♂️ <b>GMGN 深度扫描</b>\n"
        f"Smart x{smart} | KOL x{kol} | Sniper x{sniper}\n"
        f"Degen x{degen} | Rat x{rat} | Dev x{dev}\n"
        f"Bundle x{bundle}{warn}\n"
    )

def _render_score_section(score_data: dict) -> str:
    lines = ["📊 <b>评分拆解</b>"]
    bd = score_data.get("breakdown", {}) or {}
    for k, v in bd.items():
        sign = "+" if v > 0 else ""
        lines.append(f"- {html.escape(str(k))}: {sign}{v}")
    lines.append(f"➡️ 综合得分: <b>{int(score_data.get('total', 0) or 0)} / 100</b>")
    return "\n".join(lines) + "\n"

def _render_strategy_section(strategy_id: str, pos_info: dict, strategy_tag: str) -> str:
    if not pos_info:
        return ""
    plan = render_strategy_plan(strategy_id).strip()
    return (
        f"🎯 <b>策略:</b> {html.escape(strategy_tag)}\n"
        f"{plan}\n"
        f"📦 <b>仓位:</b> <b>{html.escape(pos_info.get('size','0%'))}</b>（{html.escape(pos_info.get('level','未知'))}）\n"
        f"📝 逻辑: <i>{html.escape(pos_info.get('reason',''))}</i>\n"
    )

def _render_tracker_section(track_info: dict) -> str:
    """
    兼容：
    - {"event": "TP1", "pnl": 25.0}
    - {"should_push": True, ...}
    - {"cur_pnl":..., "max_pnl":...}
    """
    if not track_info:
        return ""

    # TP/SL 事件（dict形式）
    if isinstance(track_info, dict) and "event" in track_info:
        event = str(track_info.get("event"))
        pnl = _safe_float(track_info.get("pnl")) or 0.0
        emoji = "🚀" if pnl > 0 else "🛑"
        return f"{emoji} <b>触发 {html.escape(event)}:</b> PnL <b>{pnl:+.2f}%</b>\n"

    # 自动推送触发提示（翻倍推送）
    if track_info.get("should_push") is True:
        return "🚀 <b>翻倍推送触发:</b> 已满足自动推送条件\n"

    # 追踪浮盈
    if "cur_pnl" in track_info or "max_pnl" in track_info:
        cur = _safe_float(track_info.get("cur_pnl")) or 0.0
        ath = _safe_float(track_info.get("max_pnl")) or 0.0
        return f"📉 <b>当前浮盈:</b> {cur:+.1f}%（最高 {ath:+.1f}%）\n"

    return ""

def _render_performance_panel(strategy_id: str) -> str:
    rep = performance_engine.get_report(strategy_id)
    lines = ["📈 <b>策略回测面板</b>"]

    for window in ("7d", "30d"):
        r = rep.get(window)
        if not r:
            lines.append(f"- {window}: 无数据")
            continue
        risk = get_risk_level(r["win_rate"], r["r_ratio"])
        lines.append(
            f"- {window}: {risk['color']} {risk['level']} | 胜率 {r['win_rate']}% | R {r['r_ratio']} | 交易 {r['trades']}"
        )

    if performance_engine.should_eliminate(strategy_id):
        lines.append("🧨 <b>建议:</b> 该策略30d表现过差，建议淘汰/降权。")

    return "\n".join(lines) + "\n"


# ===========================
# 🧱 组装最终消息（不同模式不同 UI）
# ===========================
def _build_message_text(ca: str, token_data: dict, decision: dict) -> str:
    token_data = token_data or {}
    decision = decision or {}

    # 模式判断：翻倍推送优先看 track_info.should_push
    track_info = token_data.get("track_info", {}) or {}
    is_auto_push = bool(track_info.get("should_push"))

    score_data = calc_score_breakdown(token_data)
    score_total = int(score_data.get("total", 0) or 0)

    # 策略：若 main 没注入 strategy_id/pos_info，这里兜底自动计算
    strategy_id = token_data.get("strategy_id") or detect_strategy(token_data)
    strategy_tag = stats_engine.get_tag(strategy_id)
    pos_info = token_data.get("pos_info") or calc_position_size(strategy_id)

    # decision（AI 只作为补充）
    ai_score = int(_safe_float(decision.get("score")) or 0)
    action = (decision.get("action") or decision.get("verdict") or "PASS").upper()
    reason = _clip(html.escape(decision.get("reason") or "无"), 500)

    emoji = _get_verdict_emoji(action, score_total if score_total > 0 else ai_score, is_auto_push)

    # 市场数据（优先 cap_usd）
    price = format_price(token_data.get("price_usd"))
    mcap = format_number(token_data.get("cap_usd") or token_data.get("mcap") or token_data.get("fdv"))
    liq = format_number(token_data.get("liquidity_usd"))
    vol = format_number(token_data.get("volume_h24"))

    # 外部喊单（可选）
    ext_pnl = _safe_float(token_data.get("external_pnl"))
    pnl_line = f"📣 喊单涨幅: <b>+{ext_pnl:.1f}%</b>\n" if ext_pnl is not None else ""

    # 标题：首次发现 vs 翻倍推送
    if is_auto_push:
        header = f"🚀 <b>翻倍推送</b> | Score: <b>{score_total}</b>"
    else:
        header = f"{emoji} <b>{action}</b> | Score: <b>{score_total}</b>"

    gmgn_block = _render_gmgn_section(token_data)
    score_block = _render_score_section(score_data)
    strat_block = _render_strategy_section(strategy_id, pos_info, strategy_tag)
    tracker_block = _render_tracker_section(track_info)
    perf_block = _render_performance_panel(strategy_id)

    # 你的“AI观点”保留，但降级为“AI补充”
    return (
        f"{header}\n"
        f"<code>{html.escape(ca)}</code>\n"
        f"━━━━━━━━━━━━━━\n"
        f"💰 <b>{price}</b> | 📊 <b>{mcap}</b>\n"
        f"💧 池子: {liq} | 📈 24h: {vol}\n\n"
        f"{gmgn_block}"
        f"{score_block}"
        f"💡 <b>判断:</b> {html.escape(score_data.get('summary',''))}\n\n"
        f"{strat_block}"
        f"{pnl_line}"
        f"{tracker_block}"
        f"{perf_block}"
        f"🤖 <b>AI补充:</b>\n"
        f"<i>{reason}</i>\n"
    )


# ===========================
# 🚀 发送逻辑（带重试）
# ===========================
async def _send_with_retry(send_factory: Callable[[], Any], attempts: int = 3):
    for attempt in range(1, attempts + 1):
        try:
            return await send_factory()
        except TelegramRetryAfter as e:
            wait_s = int(getattr(e, "retry_after", 2) or 2)
            logger.warning(f"⏱️ 限流等待 {wait_s}s (attempt {attempt}/{attempts})")
            await asyncio.sleep(wait_s)
        except TelegramBadRequest as e:
            logger.error(f"❌ 请求格式错误: {e}")
            raise
        except TelegramAPIError as e:
            logger.error(f"❌ TelegramAPIError: {e}")
            await asyncio.sleep(1)
        except Exception as e:
            logger.exception(f"💥 发送异常: {e}")
            await asyncio.sleep(1)
    return None


async def notify_user(ca: str, token_data: dict, visual_score: str, decision: dict):
    token_data = token_data or {}
    decision = decision or {}
    target_chat_id = REPORT_GROUP_ID

    message_text = _clip(_build_message_text(ca, token_data, decision), MAX_TEXT_LEN)

    kb = _build_keyboard(ca)
    kb_markup = kb.as_markup() if kb else None

    # 图片处理
    photo_file = None
    if isinstance(visual_score, str) and visual_score and os.path.exists(visual_score):
        photo_file = FSInputFile(visual_score)

    # A: 发图（caption不够则拆分）
    if photo_file:
        if len(message_text) <= MAX_CAPTION_LEN:
            async def send_photo_direct():
                return await bot.send_photo(
                    chat_id=target_chat_id,
                    photo=photo_file,
                    caption=_clip(message_text, MAX_CAPTION_LEN),
                    parse_mode=ParseMode.HTML,
                    reply_markup=kb_markup
                )
            try:
                await _send_with_retry(send_photo_direct)
                return
            except TelegramBadRequest:
                photo_file = None

        short_caption = f"📊 <b>{html.escape(str(token_data.get('symbol','UNK')))}</b> 数据快照\n<code>{html.escape(ca)}</code>"

        async def send_split():
            await bot.send_photo(
                chat_id=target_chat_id,
                photo=photo_file,
                caption=_clip(short_caption, MAX_CAPTION_LEN),
                parse_mode=ParseMode.HTML
            )
            await bot.send_message(
                chat_id=target_chat_id,
                text=_clip(message_text, MAX_TEXT_LEN),
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                reply_markup=kb_markup
            )

        try:
            await _send_with_retry(send_split)
            return
        except TelegramBadRequest:
            photo_file = None

    # B: 纯文本
    async def send_text():
        return await bot.send_message(
            chat_id=target_chat_id,
            text=_clip(message_text, MAX_TEXT_LEN),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=kb_markup
        )

    await _send_with_retry(send_text)

