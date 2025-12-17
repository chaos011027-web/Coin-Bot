import logging
import html
from datetime import datetime
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from modules.commander import bot, ADMIN_CHAT_ID
from modules.browser import open_gmgn_link  # 自动打开 GMGN 页面

logger = logging.getLogger("Notifier")

def format_number(num):
    try:
        n = float(num)
        if n >= 1_000_000:
            return f"${n / 1_000_000:.2f}M"
        elif n >= 1_000:
            return f"${n / 1_000:.1f}K"
        else:
            return f"${n:.2f}"
    except Exception:
        return "N/A"

async def notify_user(ca: str, token_data: dict, visual_score: str, decision: dict):
    token_data = token_data or {}
    decision = decision or {}

    # 安全转义
    symbol = html.escape(token_data.get("symbol", "UNK"))
    token_name = html.escape(token_data.get("name", "Unknown"))
    reason_text = html.escape(decision.get("reason") or "-")
    visual_text = html.escape(visual_score or "无")
    if len(visual_text) > 100:
        visual_text = visual_text[:97] + "..."

    # 数据字段
    smart_money = token_data.get("smart_money_holders", 0)
    mcap_str = format_number(token_data.get("mcap", 0))
    score = decision.get("score", 0)
    action = decision.get("action", "PASS")
    risk_level = decision.get("risk_level", "Unknown")

    # 状态映射
    action_map = {
        "BUY": "🟢 <b>BUY (买入)</b>",
        "WATCH": "👀 <b>WATCH (观察)</b>",
        "PASS": "🔴 <b>PASS (放弃)</b>"
    }
    risk_map = {
        "Low": "🟢 低风险",
        "Medium": "🟡 中风险",
        "High": "🔴 高风险",
        "Critical": "☠️ 极度危险"
    }

    action_display = action_map.get(action, action)
    risk_display = risk_map.get(risk_level, f"❓ {risk_level}")
    time_str = datetime.now().strftime('%H:%M:%S')

    # 消息体
    text = (
        f"🎯 <b>SolanaHunter 捕获信号</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"💊 <b>Token:</b> <a href='https://gmgn.ai/sol/token/{ca}'>{symbol}</a> ({token_name})\n"
        f"📝 <b>CA:</b> <code>{ca}</code>\n"
        f"⏰ <b>时间:</b> {time_str}\n\n"
        f"📊 <b>市场数据:</b>\n"
        f"• 市值: <b>{mcap_str}</b>\n"
        f"• 聪钱: {smart_money} 地址\n\n"
        f"🧠 <b>AI 决策:</b>\n"
        f"• 评分: <b>{score} / 100</b>\n"
        f"• 建议: {action_display}\n"
        f"• 风险: {risk_display}\n\n"
        f"💡 <b>核心理由:</b>\n"
        f"<i>{reason_text}</i>\n\n"
        f"🎨 <b>视觉简评:</b> {visual_text}\n\n"
        f"🔗 <a href='https://dexscreener.com/solana/{ca}'>DexScreener</a> | "
        f"<a href='https://gmgn.ai/sol/token/{ca}'>GMGN</a>"
    )

    # 推送 Telegram 消息
    try:
        await bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )
        logger.info(f"✅ 通知发送成功: {symbol} | Score: {score}")
    except TelegramAPIError as e:
        logger.error(f"❌ Telegram API 错误 [CA:{ca}]: {e}")
    except Exception as e:
        logger.error(f"❌ 消息推送异常 [CA:{ca}]: {e}")

    # 自动打开浏览器
    try:
        if action in ["BUY", "WATCH"]:  # 避免垃圾币打开太多标签页
            open_gmgn_link(ca)
            logger.info(f"🌐 已打开 GMGN 页面: {symbol}")
    except Exception as e:
        logger.warning(f"⚠️ 浏览器跳转失败 [CA:{ca}]: {e}")

