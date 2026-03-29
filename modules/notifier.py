import logging
import html
import asyncio
import os
import math
import json
from typing import Optional, Any, Callable, Dict, List

from aiogram.enums import ParseMode
from aiogram.types import FSInputFile, InputMediaPhoto
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramRetryAfter
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram import Router

refresh_router = Router()

from modules.commander import bot
from modules.tp_tracker import tp_tracker
from modules.canonical_metrics import (
    get_canonical_stage,
    get_confirmed_top10_pct,
    get_decision_liquidity_context,
    get_decision_liquidity_usd,
    get_source_conflict,
)

logger = logging.getLogger("Notifier")

MAX_TEXT_LEN = 3800
MAX_CAPTION_LEN = 950
TRUSTED_TOP10_SOURCES = {"BITQUERY", "GMGN"}
VERDICT_LABELS = {
    "PASS": "放弃",
    "WATCH": "观察",
    "PROBE": "试探",
    "ENTER": "进场",
    "EXIT": "离场",
}


def _clip(s: str, max_len: int) -> str:
    s = s or ""
    if len(s) <= max_len:
        return s
    return s[: max_len - 12] + "\n...(truncated)"


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None or x == "":
            return default
        if isinstance(x, str):
            x = x.replace(",", "").strip()
            if x.endswith("%"):
                x = x[:-1].strip()
        v = float(x)
        if math.isnan(v) or math.isinf(v):
            return default
        return v
    except Exception:
        return default


def _fmt_num_compact(num):
    try:
        if num is None:
            return "0"
        num = float(num)
        if num >= 1_000_000_000:
            return f"{num/1_000_000_000:.2f}B"
        if num >= 1_000_000:
            return f"{num/1_000_000:.1f}M"
        if num >= 1_000:
            return f"{num/1_000:.1f}K"
        return f"{num:.1f}"
    except Exception:
        return "0"


def _fmt_price_raw(v):
    try:
        if v is None:
            return "0"
        x = float(v)
        if x < 0.0001:
            return f"{x:.8f}".rstrip("0")
        return f"{x:.5f}"
    except Exception:
        return "0"


def _fmt_price_usd(v):
    try:
        if v is None:
            return "$0"
        x = float(v)
        if x < 0.0001:
            return f"${x:.8f}".rstrip("0")
        return f"${x:.5f}"
    except Exception:
        return "$0"


def _fmt_mcap_usd(v):
    try:
        if v is None:
            return "$0"
        x = float(v)
        if x >= 1_000_000_000:
            return f"${x/1_000_000_000:.2f}B"
        if x >= 1_000_000:
            return f"${x/1_000_000:.2f}M"
        if x >= 1_000:
            return f"${x/1_000:.2f}K"
        return f"${x:.0f}"
    except Exception:
        return "$0"


def _int0(v: Any) -> int:
    try:
        return int(float(v))
    except Exception:
        return 0


def _parse_pct(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        if isinstance(v, str):
            s = v.replace(",", "").strip()
            if s.endswith("%"):
                s = s[:-1].strip()
            if not s:
                return None
            return float(s)
        return float(v)
    except Exception:
        return None


def _is_trusted_top10_source(src: Any) -> bool:
    return str(src or "").upper() in TRUSTED_TOP10_SOURCES


def _get_trusted_top10_pct(token_data: dict) -> Optional[float]:
    return _parse_pct(get_confirmed_top10_pct(token_data or {}))


def _verdict_label(verdict: Any) -> str:
    key = str(verdict or "WATCH").upper().strip()
    return VERDICT_LABELS.get(key, key or "观察")


def _has_conflict(token_data: dict, key: Optional[str] = None) -> bool:
    raw = get_source_conflict(token_data or {}, key)
    if isinstance(raw, dict):
        marker = raw.get("has_conflict")
        if marker is not None:
            return bool(marker)
        return any(bool(v) for v in raw.values() if isinstance(v, bool))
    return bool(raw)


def _top10_status_hint(token_data: dict) -> Optional[str]:
    td = token_data or {}
    stage = str(get_canonical_stage(td) or "").strip().lower()
    if _has_conflict(td, "top10") or stage == "conflict":
        return "Top10 存在冲突"
    if td.get("top10_entity_adjusted") is False or stage in {
        "unresolved",
        "source_conflict_adjusted",
        "source_conflict_adjusted_not_entity_adjusted",
    }:
        return "Top10 待校正"
    return None


def _format_top10_display(token_data: dict) -> str:
    td = token_data or {}
    if bool(td.get("top10_pending_gmgn_review")):
        return "待校正"

    top10 = _get_trusted_top10_pct(td)
    hint = _top10_status_hint(td)

    if top10 is None:
        return hint or "❓"

    if hint:
        suffix = hint.replace("Top10 ", "", 1).strip()
        return f"{top10:.1f}%（{suffix}）" if suffix else f"{top10:.1f}%"

    return f"{top10:.1f}%"


def _format_liquidity_display(token_data: dict) -> str:
    td = token_data or {}
    if bool(td.get("suspicious_low_pair_fallback")):
        return "待确认"
    liquidity = _safe_float(get_decision_liquidity_usd(td), 0.0)
    if liquidity > 0:
        return _fmt_num_compact(liquidity)

    liq_ctx = get_decision_liquidity_context(td)
    if _has_conflict(td, "liquidity") or str(liq_ctx.get("liquidity_source_error") or "").upper().find("CONFLICT") >= 0:
        return "数据冲突"
    return "待确认"


def _format_change_cell(label: str, value: Any) -> Optional[str]:
    val = _parse_pct(value)
    if val is None:
        return None
    sign = "+" if val > 0 else ""
    return f"{label}:<b>{sign}{val:.0f}%</b>"


def _build_timeframe_lines(td: dict) -> List[str]:
    row1 = []
    row2 = []

    for label, key in [("1m", "chg_1m"), ("5m", "chg_5m"), ("15m", "chg_15m"), ("30m", "chg_30m")]:
        value = td.get(key)
        if value is None:
            value = td.get(f"price_change_{label}")
        cell = _format_change_cell(label, value)
        if cell:
            row1.append(cell)

    for label, key in [("1H", "chg_1h"), ("3H", "chg_3h"), ("6H", "chg_6h"), ("24H", "chg_24h")]:
        value = td.get(key)
        if value is None:
            value = td.get(f"price_change_{label.lower()}")
        cell = _format_change_cell(label, value)
        if cell:
            row2.append(cell)

    lines: List[str] = []
    if row1:
        lines.append("⏱️ " + " | ".join(row1))
    if row2:
        lines.append("📈 " + " | ".join(row2))
    return lines


def _get_token_avatar_payload(token_data: dict):
    token_data = token_data or {}
    url = (token_data.get("token_image_url") or "").strip()
    if url.startswith("ipfs://"):
        url = "https://ipfs.io/ipfs/" + url.replace("ipfs://", "").lstrip("/")

    def _path_source_url(path: str) -> str:
        try:
            base, _ = os.path.splitext(path)
            meta_path = f"{base}.json"
            if os.path.exists(meta_path):
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                    if isinstance(meta, dict):
                        return str(meta.get("source_url") or "").strip()
        except Exception:
            pass
        return ""

    p = (token_data.get("token_image_path") or "").strip()
    if p and os.path.exists(p):
        source_url = _path_source_url(p)
        suspicious_cache_path = "token_avatars" in os.path.normpath(p).lower()
        if url:
            if source_url and source_url == url:
                try:
                    return FSInputFile(p)
                except Exception:
                    pass
            elif source_url and source_url != url:
                return url
            elif suspicious_cache_path:
                return url
        else:
            try:
                return FSInputFile(p)
            except Exception:
                pass
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return None


def _build_keyboard(ca: str):
    try:
        kb = InlineKeyboardBuilder()
        ca_esc = html.escape(ca or "")
        kb.button(text="🤖 深度 AI 矩阵分析", callback_data=f"deep_ai:{ca_esc}")
        kb.button(text="🤖 Debot", url=f"https://debot.ai/token/{ca_esc}")
        kb.button(text="🔍 GMGN", url=f"https://gmgn.ai/sol/token/{ca_esc}")
        kb.button(text="🔄 极速刷新", callback_data=f"refresh:{ca_esc}")
        kb.adjust(1, 2, 1)
        return kb
    except Exception:
        return None


def _gmgn_grid_layout(token_data: dict) -> str:
    tags_present = token_data.get("gmgn_tags_present")

    def _cell(key: str) -> str:
        raw = token_data.get(f"gmgn_{key}")
        if raw in (None, ""):
            return "—"
        try:
            return f"x{int(float(raw))}"
        except Exception:
            return "—" if tags_present is False else "—"

    smart = _cell("smart")
    kol = _cell("kol")
    blue = _cell("blue_chip")
    sniper = _cell("sniper")
    fish = _cell("phishing_wallets")
    rat = _cell("rat")
    dev = _cell("dev")
    bundle = _cell("bundle")

    line1 = f"🧠 {smart} | 💎 {blue} | 👨‍💻 {kol}"
    line2 = f"🎣 {fish} | 🐀 {rat} | 🔫 {sniper}"
    line3 = f"📦 <b>Bundler: {bundle}</b> | 👨‍🔧 <b>Dev: {dev}</b>"
    return f"{line1}\n{line2}\n{line3}"


def _safety_verdict_block(token_data: dict) -> str:
    td = token_data or {}
    pending = bool(td.get("gmgn_render_pending"))
    mint = td.get("mint_authority_present")
    freeze = td.get("freeze_authority_present")
    dex_paid = td.get("dex_paid")
    burned = td.get("is_burned")
    locked = td.get("is_locked")

    if pending and not bool(td.get("gmgn_dex_paid_confirmed")) and dex_paid is False:
        dex_paid = None
    if pending and not bool(td.get("gmgn_burned_confirmed")) and burned is False:
        burned = None
    if pending and not bool(td.get("gmgn_locked_confirmed")) and locked is False:
        locked = None
    if pending and not bool(td.get("gmgn_mint_confirmed")) and mint is True:
        mint = None
    if pending and not bool(td.get("gmgn_freeze_confirmed")) and freeze is True:
        freeze = None

    top10_hint = _top10_status_hint(td)
    top10_pending = bool(td.get("top10_pending_gmgn_review"))
    top10 = None if top10_pending else _get_trusted_top10_pct(td)

    risks = []
    unknowns = []

    if mint is None:
        unknowns.append("Mint")
    elif mint:
        risks.append("Mint未丢")

    if freeze is None:
        unknowns.append("Freeze")
    elif freeze:
        risks.append("可冻结")

    if top10_pending:
        unknowns.append("Top10 待校正")
    elif top10_hint and top10 is None:
        unknowns.append(top10_hint)
    elif top10 is None:
        unknowns.append("Top10")
    elif top10 > 50:
        risks.append(f"Top10高({top10:.0f}%)")

    if (not top10_pending) and top10_hint is None and top10 is not None and top10 > 70:
        verdict = f"🔴 <b>危险</b> ({','.join(risks)})"
    elif len(risks) >= 2:
        verdict = f"🔴 <b>危险</b> ({','.join(risks)})"
    elif len(risks) == 1:
        verdict = f"🟡 <b>警告</b> ({','.join(risks)})"
    else:
        verdict = f"🟡 <b>待确认</b> ({','.join(unknowns)})" if unknowns else "🟢 <b>安全</b>"

    def _yn(val, good_is_true=True):
        if val is None:
            return "❓"
        if good_is_true:
            return "✅" if val else "❌"
        return "❌" if val else "✅"

    top10_txt = _format_top10_display(td)
    logger.info(
        "UIRenderSafetyTrace | mint=%s | freeze=%s | dex_paid=%s | burned=%s | locked=%s | top10=%s",
        mint,
        freeze,
        dex_paid,
        burned,
        locked,
        top10_txt,
    )

    return (
        f"🛡️ <b>基本面</b>: {verdict}\n"
        f"• Mint: {_yn(mint, False)}  • Freeze: {_yn(freeze, False)}  • Top10: {top10_txt}\n"
        f"• Dex付费: {_yn(dex_paid, True)}  • 烧池: {_yn(burned, True)}  • 锁定: {_yn(locked, True)}"
    )


def _pnl_tracking_block(token_data: dict) -> str:
    baseline = token_data.get("baseline")
    if not baseline or not isinstance(baseline, dict):
        return ""

    cur = baseline.get("rel_change_pct", 0)
    peak = baseline.get("peak_change_pct", 0)

    def _clr(v):
        return f"+{v:.1f}%" if v >= 0 else f"{v:.1f}%"

    return (
        "📉 <b>信号追踪</b> (自发现)\n"
        f"• 当前: <b>{_clr(cur)}</b>  • 最高: <b>{_clr(peak)}</b>\n"
    )


def _tp_sl_block(ca: str, token_data: dict) -> str:
    """
    主显示市值，不再强行展示价格行，减少占位。
    """
    ca = (ca or "").strip()
    td = token_data or {}

    try:
        pos = tp_tracker.data.get(ca)
    except Exception:
        pos = None

    if not pos:
        return ""

    try:
        entry_price = float(pos.get("entry") or pos.get("entry_price") or 0)
    except Exception:
        entry_price = 0.0

    try:
        sl_price = float(pos.get("sl_price") or 0)
    except Exception:
        sl_price = 0.0

    tp_targets = pos.get("tp_targets") or []
    try:
        tp_hit = int(pos.get("tp_hit_index") or -1)
    except Exception:
        tp_hit = -1

    status = str(pos.get("status") or "ACTIVE").upper()
    strat = str(pos.get("strategy") or pos.get("strategy_id") or "UNKNOWN")

    if (
        entry_price <= 0
        and sl_price <= 0
        and status == "OBSERVE"
        and strat.upper() in {"UNKNOWN", "UNK", ""}
    ):
        return ""

    try:
        curr_price = float(td.get("price_usd") or td.get("priceUsd") or 0)
    except Exception:
        curr_price = 0.0

    try:
        entry_mcap = float(pos.get("initial_mcap") or 0)
    except Exception:
        entry_mcap = 0.0

    try:
        curr_mcap = float(pos.get("current_mcap") or td.get("cap_usd") or td.get("mcap") or 0)
    except Exception:
        curr_mcap = 0.0

    pnl_txt = "—"
    if entry_price > 0 and curr_price > 0:
        pnl = (curr_price - entry_price) / entry_price * 100.0
        pnl_txt = f"{'+' if pnl > 0 else ''}{pnl:.2f}%"

    tp_lines = []
    for i, m in enumerate(tp_targets):
        try:
            mult = float(m)
            if mult <= 0:
                continue
            tag = "✅" if i <= tp_hit else "▫️"
            if entry_mcap > 0:
                tp_lines.append(f"{tag}TP{i + 1}:{_fmt_mcap_usd(entry_mcap * mult)}")
        except Exception:
            continue

    sl_text = ""
    if sl_price > 0 and entry_mcap > 0 and entry_price > 0:
        sl_mult = sl_price / entry_price
        sl_mcap = entry_mcap * sl_mult
        sl_text = _fmt_mcap_usd(sl_mcap)

    st_icon = "🟢" if status == "ACTIVE" else ("✅" if status == "WIN" else "🔴")
    sl_tag = "🛡️SL(保本)" if bool(pos.get("sl_moved_to_entry")) else "🛡️SL"

    lines = [f"🎯 <b>追踪</b>：{st_icon} {status} | 策略: {html.escape(strat)}"]

    if entry_mcap > 0 or curr_mcap > 0:
        lines.append(
            f"• 成本市值: <b>{_fmt_mcap_usd(entry_mcap)}</b>  • 当前市值: <b>{_fmt_mcap_usd(curr_mcap)}</b>  • PnL: <b>{pnl_txt}</b>"
        )
    else:
        lines.append(f"• PnL: <b>{pnl_txt}</b>")

    if sl_text:
        lines.append(f"• {sl_tag}: <b>{sl_text}</b>")

    if tp_lines:
        lines.append(f"• {'  '.join(tp_lines[:3])}")

    return "\n".join(lines)


def _build_message_text(ca: str, token_data: dict, decision: dict, stage: str = "FAST") -> str:
    td = token_data or {}
    mcap = _fmt_num_compact(td.get("cap_usd", 0))
    liq = _format_liquidity_display(td)
    vol = _fmt_num_compact(td.get("volume_h24", 0))

    age = _int0(td.get("token_age_min", 0))
    age_str = f"{age}m" if age < 60 else f"{age/60:.1f}h"

    header_lines = [f"⏳ 龄: <b>{age_str}</b> | 📊 {mcap} | 💧 {html.escape(liq)}"]
    header_lines.extend(_build_timeframe_lines(td))
    header_line = "\n".join(header_lines)

    symbol = html.escape(td.get("symbol", "UNK"))
    name = html.escape(td.get("name", ""))

    try:
        bs_val = float(td.get("buy_sell_ratio", 0))
    except Exception:
        bs_val = 0
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
        "",
    ]

    tp_block = _tp_sl_block(ca, td)
    if tp_block:
        lines.extend([tp_block, ""])
    else:
        pnl = _pnl_tracking_block(td)
        if pnl:
            lines.extend([pnl, ""])

    tag_count = td.get("gmgn_tag_non_null_count")
    try:
        tag_count = max(0, int(float(tag_count))) if tag_count is not None else None
    except Exception:
        tag_count = None
    if tag_count is None:
        tag_count = sum(
            1
            for key in [
                "gmgn_smart",
                "gmgn_kol",
                "gmgn_blue_chip",
                "gmgn_sniper",
                "gmgn_phishing_wallets",
                "gmgn_rat",
                "gmgn_dev",
                "gmgn_bundle",
            ]
            if td.get(key) is not None
        )

    if stage == "FAST":
        if tag_count >= 4:
            lines.append("🧷 <b>地址标签深度扫描</b>")
            lines.append(_gmgn_grid_layout(td))
        else:
            lines.append("⏳ <b>正在进行深度扫描 (底层节点获取中)...</b>")
    else:
        if bool(td.get("gmgn_render_pending")) or tag_count < 4:
            lines.append("⏳ <b>正在进行深度扫描 (底层节点获取中)...</b>")
        else:
            lines.append("🧷 <b>地址标签深度扫描</b>")
            lines.append(_gmgn_grid_layout(td))
        lines.append("")

        ai_reason = decision.get("reason", "")
        if not ai_reason or len(ai_reason) < 3:
            ai_reason = "数据不足或正在监控中，请留意价格异动。"

        lines.append("🤖 <b>闪电 AI 评测</b>")
        lines.append(f"• <b>结论</b>: {html.escape(_verdict_label(decision.get('verdict', 'WATCH')))} ({html.escape(ai_reason)})")
        terminal_visual = ""
        if isinstance(td.get("terminal_states"), dict):
            terminal_visual = (td.get("terminal_states") or {}).get("ai_image_read") or ""
        visual_read = decision.get("ai_image_read") or td.get("ai_image_read") or terminal_visual
        visual_read = str(visual_read or "").strip() or "头像/视觉样本不足"
        lines.append(f"• 视觉: {html.escape(visual_read)}")

    return "\n".join(lines)


def build_ai_report_text(ca: str, token_data: dict, decision: dict) -> str:
    td = token_data or {}
    symbol = html.escape(td.get("symbol", "UNK"))
    mcap = _fmt_mcap_usd(td.get("cap_usd", 0))

    ai_narrative = html.escape(str(decision.get("ai_narrative", "暂无")))
    ai_image_read = html.escape(str(decision.get("ai_image_read", "暂无")))
    ai_chart_read = html.escape(str(decision.get("ai_chart_read", "暂无")))
    ai_reason = html.escape(str(decision.get("reason", "")))
    ai_entry = html.escape(str(decision.get("ai_entry", "")))
    ai_exit = html.escape(str(decision.get("ai_exit", "")))
    verdict = html.escape(_verdict_label(decision.get("verdict", "WATCH")))

    lines = [
        f"🧠 <b>【{symbol}】深度 AI 矩阵分析报告</b>",
        f"<code>{ca}</code>",
        f"📊 当前市值: <b>{mcap}</b>",
        "",
        f"📜 <b>静态叙事基础</b>:\n{ai_narrative}",
        "",
        f"🎨 <b>视觉基因诊断</b>:\n{ai_image_read}",
        "",
        f"📉 <b>K线视觉诊断</b>:\n{ai_chart_read}",
        "",
        f"🎯 <b>即时操盘策略 ({verdict})</b>:\n{ai_reason}",
        f"🟢 <b>入场纪律</b>: {ai_entry}",
        f"🔴 <b>防守退场</b>: {ai_exit}",
    ]
    return "\n".join(lines)


def build_milestone_text(ca: str, token_data: dict, decision: dict, multiplier: float) -> str:
    td = token_data or {}
    symbol = html.escape(td.get("symbol", "UNK"))
    mcap = _fmt_mcap_usd(td.get("cap_usd", 0))
    reason = html.escape(str(decision.get("reason", "")))
    ai_exit = html.escape(str(decision.get("ai_exit", "")))
    verdict = html.escape(_verdict_label(decision.get("verdict", "WATCH")))
    gate = int(td.get("milestone_gate") or max(2, int(multiplier)))

    lines = [
        f"🚨 <b>【{symbol}】突破 {gate}X｜当前 {multiplier:.2f}X</b>",
        f"📊 当前市值: <b>{mcap}</b>",
        "",
        f"🤖 <b>操盘手即时决断 ({verdict})</b>:",
        f"• {reason}",
        f"• 建议: {ai_exit}",
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
        "reason": "⏳ 深度分析进行中...",
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
                reply_markup=kb_markup,
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
            reply_markup=kb_markup,
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
                    media=InputMediaPhoto(
                        media=avatar_payload,
                        caption=_clip(text, MAX_CAPTION_LEN),
                        parse_mode=ParseMode.HTML,
                    ),
                    chat_id=int(chat_id),
                    message_id=int(message_id),
                    reply_markup=kb_markup,
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
                reply_markup=kb_markup,
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
                reply_markup=kb_markup,
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


async def send_thread_reply(chat_id: int, reply_to_msg_id: int, text: str) -> Optional[int]:
    try:
        msg = await bot.send_message(
            chat_id=int(chat_id),
            text=_clip(text, MAX_TEXT_LEN),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_to_message_id=int(reply_to_msg_id),
        )
        return int(getattr(msg, "message_id"))
    except Exception as e:
        logger.error(f"❌ 盖楼回复发送失败: {e}")
        return None


async def notify_user(ca: str, token_data: dict, visual_score: Optional[str], decision: dict):
    # 兼容旧调用接口，本轮不主动扩展
    pass
