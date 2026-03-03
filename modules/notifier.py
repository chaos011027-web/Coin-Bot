import logging
import html
import asyncio
import os
import math
from typing import Optional, Any, Callable, Dict, Tuple, List

from aiogram.enums import ParseMode
from aiogram.types import FSInputFile, InputMediaPhoto
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramRetryAfter
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram import Router
refresh_router = Router()

from modules.commander import bot

from modules.score_engine import calc_score_breakdown
from modules.strategy_engine import detect_strategy, render_strategy_plan
from modules.stats_engine import stats_engine
from modules.risk_engine import get_risk_level
from modules.tp_tracker import tp_tracker

from modules.position_engine import calc_position_size
logger = logging.getLogger("Notifier")

MAX_TEXT_LEN = 3800
MAX_CAPTION_LEN = 950

DEBOT_URL_TMPL = "https://debot.ai/sol/token/{ca}"


def _clip(s: str, max_len: int) -> str:
    s = s or ""
    if len(s) <= max_len:
        return s
    return s[: max_len - 12] + "\n...(truncated)"


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


def _fmt_num_compact(num):
    try:
        if num is None: return "0"
        num = float(num)
        if num >= 1_000_000_000:
            return f"{num/1_000_000_000:.2f}B"
        if num >= 1_000_000:
            return f"{num/1_000_000:.1f}M"
        if num >= 1_000:
            return f"{num/1_000:.1f}K"
        return f"{num:.1f}"
    except:
        return "0"


def _fmt_price_raw(v):
    try:
        if v is None: return "0"
        x = float(v)
        if x < 0.0001:
            return f"{x:.8f}".rstrip("0")
        return f"{x:.5f}"
    except:
        return "0"


def _fmt_price_usd(v):
    try:
        if v is None: return "$0"
        x = float(v)
        if x < 0.0001:
            return f"${x:.8f}".rstrip("0")
        return f"${x:.5f}"
    except:
        return "$0"


def _yn_icon(v: Any) -> str:
    if v is True: return "✅"
    if v is False: return "❌"
    return "❓"


def _int0(v: Any) -> int:
    try:
        return int(float(v))
    except Exception:
        return 0


def _get_token_avatar_payload(token_data: dict):
    token_data = token_data or {}
    p = (token_data.get("token_image_path") or "").strip()
    if p and os.path.exists(p):
        try:
            return FSInputFile(p)
        except Exception:
            pass
    url = (token_data.get("token_image_url") or "").strip()
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return None


def _build_keyboard(ca: str):
    try:
        kb = InlineKeyboardBuilder()
        ca_esc = html.escape(ca or "")
        # 第一排：极具商业价值的深度 AI 分析入口
        kb.button(text="🤖 深度 AI 矩阵分析", callback_data=f"deep_ai:{ca_esc}")
        # 第二排：常规工具
        kb.button(text="🤖 Debot", url=f"https://debot.ai/token/{ca_esc}")
        kb.button(text="🔍 GMGN", url=f"https://gmgn.ai/sol/token/{ca_esc}")
        # 第三排：刷新数据
        kb.button(text="🔄 极速刷新", callback_data=f"refresh:{ca_esc}")
        kb.adjust(1, 2, 1)
        return kb
    except Exception:
        return None


def _tp_sl_block(ca: str, token_data: dict) -> str:
    ca = (ca or "").strip()
    td = token_data or {}
    pos = None
    try:
        pos = tp_tracker.data.get(ca)
    except Exception:
        pos = None

    if not pos: return "" 

    try: entry = float(pos.get("entry") or 0)
    except: entry = 0.0
    try: sl_price = float(pos.get("sl_price") or 0)
    except: sl_price = 0.0

    tp_targets = pos.get("tp_targets") or []
    try: tp_hit = int(pos.get("tp_hit_index") or -1)
    except: tp_hit = -1

    status = str(pos.get("status") or "ACTIVE").upper()
    strat = str(pos.get("strategy") or "UNKNOWN")

    try: curr = float(td.get("price_usd") or td.get("priceUsd") or 0)
    except: curr = 0.0

    pnl_txt = "—"
    if entry > 0 and curr > 0:
        pnl = (curr - entry) / entry * 100.0
        sign = "+" if pnl > 0 else ""
        pnl_txt = f"{sign}{pnl:.2f}%"

    tp_prices = []
    for i, m in enumerate(tp_targets):
        try:
            mult = float(m)
            if mult > 0 and entry > 0:
                price_i = entry * mult
                tag = "✅" if i <= tp_hit else "▫️"
                tp_prices.append(f"{tag}TP{i+1}:{_fmt_price_usd(price_i)}")
        except Exception:
            continue

    st_icon = "🟢" if status == "ACTIVE" else ("✅" if status == "WIN" else "🔴")
    sl_tag = "🛡️SL"
    if bool(pos.get("sl_moved_to_entry")):
        sl_tag = "🛡️SL(保本)"

    lines = []
    lines.append(f"🎯 <b>追踪</b>：{st_icon} {status} | 策略: {strat}")
    lines.append(f"• 成本: <b>{_fmt_price_usd(entry)}</b>  • PnL: <b>{pnl_txt}</b>")
    lines.append(f"• {sl_tag}: <b>{_fmt_price_usd(sl_price)}</b>")
    if tp_prices:
        tp_line = "  ".join(tp_prices[:3]) 
        lines.append(f"• {tp_line}")
    return "\n".join(lines)


# 保持原始标签原汁原味
def _gmgn_grid_layout(token_data: dict) -> str:
    def _c(key): return int(float(token_data.get(f"gmgn_{key}", 0) or 0))
    smart = _c("smart")
    kol = _c("kol")
    blue = _c("blue_chip")
    sniper = _c("sniper")
    fish = _c("phishing_wallets")
    rat = _c("rat")
    dev = _c("dev")
    bundle = _c("bundle")
    
    line1 = f"🧠 x{smart} | 💎 x{blue} | 👨‍💻 x{kol}"
    line2 = f"🎣 x{fish} | 🐀 x{rat} | 🔫 x{sniper}"
    line3 = f"📦 <b>Bundler: x{bundle}</b> | 👨‍🔧 <b>Dev: x{dev}</b>"
    return f"{line1}\n{line2}\n{line3}"


def _safety_verdict_block(token_data: dict) -> str:
    mint = token_data.get("mint_authority_present") 
    freeze = token_data.get("freeze_authority_present")
    dex_paid = token_data.get("dex_paid")
    top10_str = str(token_data.get("top10_ratio", "0")).replace("%","")
    try: top10 = float(top10_str)
    except: top10 = 0
    risks = []
    if mint: risks.append("Mint未丢")
    if freeze: risks.append("可冻结")
    if top10 > 50: risks.append(f"Top10高({top10:.0f}%)")
    if not risks: verdict = "🟢 <b>安全</b>"
    elif len(risks) >= 2 or top10 > 70: verdict = f"🔴 <b>危险</b> ({','.join(risks)})"
    else: verdict = f"🟡 <b>警告</b> ({','.join(risks)})"

    def _yn(val, good_is_true=True):
        if val is None: return "❓"
        if good_is_true: return "✅" if val else "❌"
        else: return "❌" if val else "✅"

    burned = token_data.get("is_burned")
    locked = token_data.get("is_locked") 
    return (
        f"🛡️ <b>基本面</b>: {verdict}\n"
        f"• Mint: {_yn(mint, False)}  • Freeze: {_yn(freeze, False)}  • Top10: {top10:.1f}%\n"
        f"• Dex付费: {_yn(dex_paid, True)}  • 烧池: {_yn(burned, True)}  • 锁定: {_yn(locked, True)}"
    )


def _pnl_tracking_block(token_data: dict) -> str:
    baseline = token_data.get("baseline")
    if not baseline or not isinstance(baseline, dict): return ""
    cur = baseline.get("rel_change_pct", 0)
    peak = baseline.get("peak_change_pct", 0)
    def _clr(v): return f"+{v:.1f}%" if v >= 0 else f"{v:.1f}%"
    return f"📉 <b>信号追踪</b> (自发现)\n• 当前: <b>{_clr(cur)}</b>  • 最高: <b>{_clr(peak)}</b>\n"


# ==========================================
# 🟢 核心重构：主卡片排版调整 (去价格，移位币龄和成交量)
# ==========================================
def _build_message_text(ca: str, token_data: dict, decision: dict, stage: str = "FAST") -> str:
    td = token_data or {}
    mcap = _fmt_num_compact(td.get("cap_usd", 0))
    liq = _fmt_num_compact(td.get("liquidity_usd", 0))
    vol = _fmt_num_compact(td.get("volume_h24", 0))
    
    def _chg(k): 
        v = td.get(k)
        if v is None: return "—"
        try: 
            val = float(v)
            sign = "+" if val > 0 else ""
            return f"{sign}{val:.0f}%"
        except: return "—"

    # 1. 顶部数据行：将币龄放在原价格位置
    age = _int0(td.get("token_age_min", 0))
    age_str = f"{age}m" if age < 60 else f"{age/60:.1f}h"
    header_line = (
        f"⏳ 龄: <b>{age_str}</b> | 📊 {mcap} | 💧 {liq}\n"
        f"⏱️ 1m:<b>{_chg('chg_1m')}</b> | 5m:<b>{_chg('chg_5m')}</b> | 15m:<b>{_chg('chg_15m')}</b> | 30m:<b>{_chg('chg_30m')}</b>\n"
        f"📈 1H:<b>{_chg('chg_1h')}</b> | 3H:<b>{_chg('chg_3h')}</b> | 6H:<b>{_chg('chg_6h')}</b> | 24H:<b>{_chg('chg_24h')}</b>"
    )
    
    symbol = html.escape(td.get("symbol", "UNK"))
    name = html.escape(td.get("name", ""))
    
    # 2. 子标题行：将成交量放至原币龄位置
    bs_ratio = td.get("buy_sell_ratio", 0)
    try: bs_val = float(bs_ratio)
    except: bs_val = 0
    bs_str = f"{bs_val:.1f}" if bs_val < 999 else "∞"
    sub_header = f"💰 24H量: <b>{vol}</b>  •  ⚖️ 买卖比: <b>{bs_str}</b>"

    lines = [
        f"🪙 <b>{symbol}</b> ({name})",
        f"<code>{ca}</code>",
        "",
        header_line,
        sub_header, 
        "",
        _safety_verdict_block(td),
        ""
    ]
    
    tp_block = _tp_sl_block(ca, td)
    if tp_block: 
        lines.extend([tp_block, ""])
    else:
        pnl = _pnl_tracking_block(td)
        if pnl: lines.extend([pnl, ""])
    
    if stage == "FAST":
        lines.append("⏳ <b>正在进行深度扫描 (底层节点获取中)...</b>")
    else:
        lines.append("🧷 <b>地址标签深度扫描</b>")
        lines.append(_gmgn_grid_layout(td))
        lines.append("")
        
        # 主卡片保留一句极简 AI 建议
        ai_reason = decision.get("reason", "")
        if not ai_reason or len(ai_reason) < 3:
            ai_reason = "数据不足或正在监控中，请留意价格异动。"
        lines.append("🤖 <b>闪电 AI 评测</b>")
        lines.append(f"• <b>结论</b>: {decision.get('verdict', 'WATCH')} ({html.escape(ai_reason)})")

    return "\n".join(lines)


# ==========================================
# 🟢 专供盖楼使用的模版引擎
# ==========================================
def build_ai_report_text(ca: str, token_data: dict, decision: dict) -> str:
    """生成深度 AI 矩阵分析副卡片"""
    td = token_data or {}
    symbol = html.escape(td.get("symbol", "UNK"))
    lines = [
        f"🧠 <b>【{symbol}】深度 AI 矩阵分析报告</b>",
        f"<code>{ca}</code>",
        "",
        f"📜 <b>静态叙事基础</b>:\n{html.escape(decision.get('ai_narrative', '暂无'))}",
        "",
        f"🎨 <b>视觉基因诊断</b>:\n{html.escape(decision.get('ai_image_read', '暂无'))}",
        "",
        f"🎯 <b>即时操盘策略 ({decision.get('verdict', 'WATCH')})</b>:\n{html.escape(decision.get('reason', ''))}",
        f"🟢 <b>入场纪律</b>: {html.escape(decision.get('ai_entry', ''))}",
        f"🔴 <b>防守退场</b>: {html.escape(decision.get('ai_exit', ''))}"
    ]
    return "\n".join(lines)


def build_milestone_text(ca: str, token_data: dict, decision: dict, multiplier: float) -> str:
    """生成涨跌倍数战报副卡片"""
    td = token_data or {}
    symbol = html.escape(td.get("symbol", "UNK"))
    # 虽然去掉了具体价格，但在暴涨战报中附带一个现价也许是好的，如果不需要，后续可随时调整
    price = _fmt_price_raw(td.get("price_usd"))
    mcap = _fmt_num_compact(td.get("cap_usd", 0))
    lines = [
        f"🚨 <b>【{symbol}】链上异动战报: {multiplier:.2f}X !</b>",
        f"💰 极速现价: <b>${price}</b> | 📊 最新市值: <b>{mcap}</b>",
        "",
        f"🤖 <b>操盘手即时决断 ({decision.get('verdict', 'WATCH')})</b>:",
        f"• {html.escape(decision.get('reason', ''))}",
        f"• 建议: {html.escape(decision.get('ai_exit', ''))}"
    ]
    return "\n".join(lines)


async def _send_with_retry(send_func: Callable[[], Any], max_retry: int = 3):
    last_exc = None
    for _ in range(max_retry):
        try:
            return await send_func()
        except TelegramRetryAfter as e:
            await asyncio.sleep(float(getattr(e, "retry_after", 2.0)) + 0.5)
            last_exc = e
        except TelegramAPIError as e:
            last_exc = e
            await asyncio.sleep(0.8)
        except Exception as e:
            last_exc = e
            await asyncio.sleep(0.8)
    if last_exc:
        raise last_exc


def _resolve_target_chat_id(token_data: dict) -> int:
    rcid = token_data.get("reply_chat_id")
    try:
        if rcid is not None:
            return int(rcid)
    except Exception:
        pass
    from config.settings import ADMIN_CHAT_ID
    return int(ADMIN_CHAT_ID)


async def notify_user_fast(ca: str, token_data: dict) -> Optional[int]:
    token_data = token_data or {}
    target_chat_id = _resolve_target_chat_id(token_data)

    pending_decision = {
        "score": 0,
        "verdict": "WATCH",
        "risk_flags": ["PENDING"],
        "reason": "⏳ 深度分析进行中..."
    }

    text = _clip(_build_message_text(ca, token_data, pending_decision, stage="FAST"), MAX_TEXT_LEN)
    kb = _build_keyboard(ca)
    kb_markup = kb.as_markup() if kb else None

    avatar_payload = _get_token_avatar_payload(token_data)

    if avatar_payload is not None:
        async def send_photo():
            return await bot.send_photo(
                chat_id=target_chat_id,
                photo=avatar_payload,
                caption=_clip(text, MAX_CAPTION_LEN),
                parse_mode=ParseMode.HTML,
                reply_markup=kb_markup
            )
        msg = await _send_with_retry(send_photo)
        try:
            return int(getattr(msg, "message_id"))
        except Exception:
            return None

    async def send_text():
        return await bot.send_message(
            chat_id=target_chat_id,
            text=_clip(text, MAX_TEXT_LEN),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=kb_markup
        )

    msg = await _send_with_retry(send_text)
    try:
        return int(getattr(msg, "message_id"))
    except Exception:
        return None


async def update_user_message(chat_id: int, message_id: int, ca: str, token_data: dict, decision: dict) -> bool:
    token_data = token_data or {}
    decision = decision or {}
    text = _clip(_build_message_text(ca, token_data, decision, stage="DEEP"), MAX_TEXT_LEN)

    kb = _build_keyboard(ca)
    kb_markup = kb.as_markup() if kb else None

    avatar_payload = _get_token_avatar_payload(token_data)

    if avatar_payload and isinstance(avatar_payload, FSInputFile):
        for _ in range(2):
            try:
                await bot.edit_message_media(
                    media=InputMediaPhoto(media=avatar_payload, caption=_clip(text, MAX_CAPTION_LEN), parse_mode=ParseMode.HTML),
                    chat_id=int(chat_id),
                    message_id=int(message_id),
                    reply_markup=kb_markup
                )
                return True
            except TelegramBadRequest as e:
                msg_str = str(e).lower()
                if "message is not modified" in msg_str:
                    return True
                if "there is no media" in msg_str or "can't be edited" in msg_str:
                    break
                await asyncio.sleep(0.4)
            except TelegramRetryAfter as e:
                await asyncio.sleep(float(getattr(e, "retry_after", 2.0)) + 0.5)
            except Exception:
                await asyncio.sleep(0.4)

    for _ in range(3):
        try:
            await bot.edit_message_caption(
                chat_id=int(chat_id),
                message_id=int(message_id),
                caption=_clip(text, MAX_CAPTION_LEN),
                parse_mode=ParseMode.HTML,
                reply_markup=kb_markup
            )
            return True
        except TelegramBadRequest as e:
            msg = str(e).lower()
            if "message is not modified" in msg:
                return True
            if "there is no caption" in msg or "message can't be edited" in msg:
                break
            await asyncio.sleep(0.4)
        except TelegramRetryAfter as e:
            await asyncio.sleep(float(getattr(e, "retry_after", 2.0)) + 0.5)
        except Exception:
            await asyncio.sleep(0.4)

    for _ in range(3):
        try:
            await bot.edit_message_text(
                chat_id=int(chat_id),
                message_id=int(message_id),
                text=_clip(text, MAX_TEXT_LEN),
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                reply_markup=kb_markup
            )
            return True
        except TelegramBadRequest as e:
            msg = str(e).lower()
            if "message is not modified" in msg:
                return True
            await asyncio.sleep(0.4)
        except TelegramRetryAfter as e:
            await asyncio.sleep(float(getattr(e, "retry_after", 2.0)) + 0.5)
        except Exception:
            await asyncio.sleep(0.4)

    return False


# ==========================================
# 🟢 核心重构：发送纯文字“盖楼”回复消息
# ==========================================
async def send_thread_reply(chat_id: int, reply_to_msg_id: int, text: str) -> Optional[int]:
    """
    发送盖楼回复消息（用于发送 AI 深度报告或战报，挂在原始主卡片下方）
    """
    try:
        msg = await bot.send_message(
            chat_id=int(chat_id),
            text=_clip(text, MAX_TEXT_LEN),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_to_message_id=int(reply_to_msg_id)
        )
        return int(getattr(msg, "message_id"))
    except Exception as e:
        logger.error(f"❌ 盖楼回复发送失败: {e}")
        return None


async def notify_user(ca: str, token_data: dict, visual_score: Optional[str], decision: dict):
    pass