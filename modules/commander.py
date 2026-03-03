import asyncio
import logging
from enum import Enum
from typing import Awaitable, Callable, Optional

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, Filter
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config.settings import TELEGRAM_BOT_TOKEN, ADMIN_CHAT_ID

logger = logging.getLogger("Commander")


class BotMode(str, Enum):
    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    AGGRESSIVE = "aggressive"


class BotState:
    def __init__(self):
        self.is_paused = False
        self.current_mode = BotMode.BALANCED


state = BotState()

bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

# ✅ 阶段6：绑定刷新回调（由 main.py 注入）
_refresh_callback: Optional[Callable[[str, int, int], Awaitable[None]]] = None


def set_refresh_callback(cb: Callable[[str, int, int], Awaitable[None]]):
    """
    main.py 启动时注入：refresh_token_panel(ca, chat_id, message_id)
    """
    global _refresh_callback
    _refresh_callback = cb
    logger.info("✅ refresh callback 已绑定到 Commander")


class AdminFilter(Filter):
    async def __call__(self, message: Message) -> bool:
        return str(message.chat.id) == str(ADMIN_CHAT_ID)


def get_mode_name(mode: str) -> str:
    mapping = {
        BotMode.CONSERVATIVE: "🛡 稳健",
        BotMode.AGGRESSIVE: "🚀 激进",
        BotMode.BALANCED: "⚖️ 均衡"
    }
    return mapping.get(mode, "⚖️ 均衡")


def get_dashboard_text() -> str:
    status = "🔴 *已暂停*" if state.is_paused else "🟢 *运行中* (监听中...)"
    mode_display = get_mode_name(state.current_mode)

    return (
        f"🎛 *SolanaHunter V3 控制台*\n"
        f"━━━━━━━━━━━━━━\n"
        f"📡 状态: {status}\n"
        f"🕹 模式: {mode_display}\n\n"
        f"_👇 点击下方按钮实时调整策略_"
    )


def get_dashboard_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    curr = state.current_mode
    builder.row(
        InlineKeyboardButton(
            text=("✅ 稳健" if curr == BotMode.CONSERVATIVE else "🛡 稳健"),
            callback_data=f"set_mode_{BotMode.CONSERVATIVE}"
        ),
        InlineKeyboardButton(
            text=("✅ 均衡" if curr == BotMode.BALANCED else "⚖️ 均衡"),
            callback_data=f"set_mode_{BotMode.BALANCED}"
        ),
        InlineKeyboardButton(
            text=("✅ 激进" if curr == BotMode.AGGRESSIVE else "🚀 激进"),
            callback_data=f"set_mode_{BotMode.AGGRESSIVE}"
        )
    )

    pause_text = "▶️ 恢复监听" if state.is_paused else "⏸ 暂停系统"
    pause_data = "cmd_resume" if state.is_paused else "cmd_pause"

    builder.row(
        InlineKeyboardButton(text=pause_text, callback_data=pause_data),
        InlineKeyboardButton(text="🔄 刷新面板", callback_data="cmd_refresh_panel")
    )

    return builder.as_markup()


@dp.message(Command("start", "menu"), AdminFilter())
async def cmd_start(message: types.Message):
    await message.answer(
        get_dashboard_text(),
        reply_markup=get_dashboard_keyboard(),
        parse_mode="Markdown"
    )


@dp.message(Command("pause"), AdminFilter())
async def cmd_pause(message: types.Message):
    state.is_paused = True
    logger.info("⏸ 系统已通过指令暂停")
    await message.answer("⏸ *系统已暂停监听*", parse_mode="Markdown")


@dp.message(Command("resume"), AdminFilter())
async def cmd_resume(message: types.Message):
    state.is_paused = False
    logger.info("▶️ 系统已通过指令恢复")
    await message.answer("▶️ *系统已恢复监听*", parse_mode="Markdown")


@dp.message(Command("status"), AdminFilter())
async def cmd_status(message: types.Message):
    await message.answer(get_dashboard_text(), parse_mode="Markdown")


@dp.callback_query(F.data.startswith("set_mode_"))
async def on_mode_change(callback: types.CallbackQuery):
    if str(callback.message.chat.id) != str(ADMIN_CHAT_ID):
        await callback.answer("🚫 无权操作", show_alert=True)
        return

    new_mode = callback.data.replace("set_mode_", "")
    if new_mode in [m.value for m in BotMode]:
        state.current_mode = BotMode(new_mode)
        logger.info(f"🧭 模式切换为: {state.current_mode}")

        try:
            await callback.message.edit_text(
                get_dashboard_text(),
                reply_markup=get_dashboard_keyboard(),
                parse_mode="Markdown"
            )
        except Exception:
            pass

        await callback.answer(f"✅ 已切换为: {get_mode_name(new_mode)}")
    else:
        await callback.answer("⚠️ 无效模式")


@dp.callback_query(F.data.in_({"cmd_pause", "cmd_resume", "cmd_refresh_panel"}))
async def on_control_cmd(callback: types.CallbackQuery):
    if str(callback.message.chat.id) != str(ADMIN_CHAT_ID):
        await callback.answer("🚫 无权操作", show_alert=True)
        return

    if callback.data == "cmd_pause":
        state.is_paused = True
        logger.info("⏸ 通过面板暂停")
    elif callback.data == "cmd_resume":
        state.is_paused = False
        logger.info("▶️ 通过面板恢复")

    try:
        await callback.message.edit_text(
            get_dashboard_text(),
            reply_markup=get_dashboard_keyboard(),
            parse_mode="Markdown"
        )
    except Exception:
        pass

    await callback.answer("🔄 状态已更新")


# ✅ 阶段6：真正处理 token 面板的 refresh:<ca>
@dp.callback_query(F.data.startswith("refresh:"))
async def on_refresh_token_panel(callback: types.CallbackQuery):
    try:
        if not callback.message:
            await callback.answer("⚠️ 无消息上下文", show_alert=True)
            return

        ca = callback.data.split("refresh:", 1)[-1].strip()
        chat_id = int(callback.message.chat.id)
        message_id = int(callback.message.message_id)

        if not ca:
            await callback.answer("⚠️ CA 为空", show_alert=True)
            return

        if _refresh_callback is None:
            await callback.answer("⚠️ 刷新回调未绑定", show_alert=True)
            logger.warning("refresh:<ca> 被触发，但 _refresh_callback 未绑定")
            return

        await callback.answer("🔄 刷新中...")
        await _refresh_callback(ca, chat_id, message_id)

    except Exception as e:
        logger.exception(f"refresh:<ca> 处理异常: {e}")
        try:
            await callback.answer("❌ 刷新失败", show_alert=True)
        except Exception:
            pass


async def send_alert(text, markup=None):
    if not ADMIN_CHAT_ID:
        logger.warning("⚠️ 未配置 ADMIN_CHAT_ID，无法发送通知")
        return

    try:
        await bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=text,
            parse_mode="Markdown",
            reply_markup=markup,
            disable_web_page_preview=True
        )
    except Exception as e:
        logger.error(f"❌ 发送消息失败: {e}")


async def start_commander():
    if not TELEGRAM_BOT_TOKEN:
        logger.critical("❌ 未配置 TELEGRAM_BOT_TOKEN，Commander 无法启动")
        return

    logger.info(f"🤖 Commander 已启动 (Admin ID: {ADMIN_CHAT_ID})")

    await bot.delete_webhook(drop_pending_updates=True)

    await dp.start_polling(
        bot,
        allowed_updates=["message", "callback_query"]
    )
