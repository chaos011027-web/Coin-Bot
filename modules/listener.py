# modules/listener.py
import re
import asyncio
import logging
import os
from typing import Callable, Any, Optional

from telethon import TelegramClient, events
from telethon.tl.types import MessageEntityTextUrl, MessageEntityUrl

from config.settings import (
    TELEGRAM_API_ID,
    TELEGRAM_API_HASH,
    BOT_SESSION_NAME,
    TELEGRAM_BOT_TOKEN,
    ADMIN_CHAT_ID,
    PRIVATE_ONLY_MODE,
    WHITELIST_USER_IDS,
    TARGET_CHANNELS,
    VIP_SOURCES,
)

logger = logging.getLogger("Hunter")

SOL_PATTERN = re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{32,44}\b")

DEFAULT_BLACKLIST = {
    "So11111111111111111111111111111111111111112",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",
}


class AlphaListener:
    """
    ✅ 目标：
    - 群监听：用 USER session（能看到“信号机器人”发的消息）
    - 私聊入口：用 BOT session（用户私聊 bot 触发）
    - 输出：仍走 _resolve_reply_chat_id（PRIVATE_ONLY_MODE 行为不变）
    """

    def __init__(self):
        os.makedirs("sessions", exist_ok=True)

        # 1) BOT 客户端：用于私聊入口（bot_token 登录）
        bot_session_path = f"sessions/{BOT_SESSION_NAME}"
        self.bot_client = TelegramClient(
            bot_session_path,
            TELEGRAM_API_ID,
            TELEGRAM_API_HASH,
            connection_retries=None,
            auto_reconnect=True,
            base_logger=logging.getLogger("telethon"),
        )

        # 2) USER 客户端：用于群监听入口（用户号登录）
        user_session_path = "sessions/user_listener"
        self.user_client = TelegramClient(
            user_session_path,
            TELEGRAM_API_ID,
            TELEGRAM_API_HASH,
            connection_retries=None,
            auto_reconnect=True,
            base_logger=logging.getLogger("telethon"),
        )

        self.blacklist = set(DEFAULT_BLACKLIST)
        self._sem = asyncio.Semaphore(6)

    # --------------------------
    # CA extract helpers
    # --------------------------
    def _find_ca_in_text(self, text: str) -> Optional[str]:
        if not text:
            return None
        text = text.replace("\u200b", " ").strip()
        m = SOL_PATTERN.search(text)
        return m.group(0) if m else None

    def _extract_from_entities(self, message, text: str) -> Optional[str]:
        if not message or not getattr(message, "entities", None):
            return None

        for ent in message.entities:
            url = None
            if isinstance(ent, MessageEntityTextUrl):
                url = ent.url
            elif isinstance(ent, MessageEntityUrl):
                try:
                    url = text[ent.offset: ent.offset + ent.length]
                except Exception:
                    url = None

            if not url:
                continue

            ca = self._find_ca_in_text(url)
            if ca:
                return ca
        return None

    def _extract_from_buttons(self, message) -> Optional[str]:
        rm = getattr(message, "reply_markup", None)
        if not rm or not getattr(rm, "rows", None):
            return None

        try:
            for row in rm.rows:
                for btn in row.buttons:
                    url = getattr(btn, "url", None)
                    if not url:
                        continue
                    ca = self._find_ca_in_text(url)
                    if ca:
                        return ca
        except Exception as e:
            logger.debug(f"按钮解析异常（忽略）: {e}", exc_info=True)

        return None

    def extract_ca(self, event) -> Optional[str]:
        msg = getattr(event, "message", None)
        text = (event.raw_text or "")

        ca = self._extract_from_entities(msg, text)
        if ca:
            return ca

        ca = self._extract_from_buttons(msg)
        if ca:
            return ca

        return self._find_ca_in_text(text)

    # --------------------------
    # 过滤逻辑
    # --------------------------
    def _should_process(self, ca: str, source_name: str) -> bool:
        if ca in self.blacklist:
            logger.info(f"🚫 黑名单跳过: {ca} | src={source_name}")
            return False
        return True

    def _is_whitelisted(self, sender_id: int) -> bool:
        try:
            return int(sender_id) in set(int(x) for x in WHITELIST_USER_IDS)
        except Exception:
            return sender_id == int(ADMIN_CHAT_ID)

    def _resolve_reply_chat_id(self, preferred_chat_id: int) -> int:
        """
        私聊模式下：不在群里回复，统一回 ADMIN（或白名单第一人）
        非私聊模式：保持原来的 chat_id
        """
        if not PRIVATE_ONLY_MODE:
            return preferred_chat_id

        if ADMIN_CHAT_ID:
            return int(ADMIN_CHAT_ID)

        try:
            wl = list(int(x) for x in WHITELIST_USER_IDS)
            if wl:
                return int(wl[0])
        except Exception:
            pass

        return preferred_chat_id

    # --------------------------
    # 回调执行（固定 5 参数）
    # --------------------------
    async def _run_callback(self, callback_func: Callable[..., Any], args5):
        async with self._sem:
            try:
                if asyncio.iscoroutinefunction(callback_func):
                    await callback_func(*args5)
                else:
                    callback_func(*args5)
            except Exception as e:
                logger.error(f"❌ 回调执行失败: {e}", exc_info=True)

    def _create_task_with_log(self, coro):
        t = asyncio.create_task(coro)

        def _done(task: asyncio.Task):
            try:
                task.result()
            except Exception as e:
                logger.error(f"❌ 后台任务异常: {e}", exc_info=True)

        t.add_done_callback(_done)
        return t

    def _normalize_channels(self):
        valid = []
        for ch in (TARGET_CHANNELS or []):
            try:
                valid.append(int(ch))
            except Exception:
                continue
        return valid

    # --------------------------
    # start
    # --------------------------
    async def start(
        self,
        callback_func: Callable[..., Any],
        refresh_callback: Optional[Callable[..., Any]] = None,
    ):
        # ✅ 关键补丁：把 refresh_callback 注入 Commander（不影响旧逻辑）
        if refresh_callback is not None:
            try:
                # 延迟导入避免循环依赖
                from modules.commander import set_refresh_callback
                set_refresh_callback(refresh_callback)
                logger.info("✅ listener 已注入 refresh_callback 到 Commander")
            except Exception as e:
                logger.warning(f"⚠️ 注入 refresh_callback 失败（不影响监听）：{e}")

        # ---------- 1) 启动 BOT 客户端（私聊入口） ----------
        await self.bot_client.start(bot_token=TELEGRAM_BOT_TOKEN)
        bot_me = await self.bot_client.get_me()
        bot_username = f"@{bot_me.username}" if getattr(bot_me, "username", None) else f"ID:{bot_me.id}"
        logger.info(f"🤖 BOT 客户端已启动: {bot_username}（私聊入口）")

        # ---------- 2) 启动 USER 客户端（群监听入口） ----------
        # 注意：首次运行可能需要你在终端输入手机号+验证码（只做一次）
        await self.user_client.start()
        user_me = await self.user_client.get_me()
        user_username = f"@{user_me.username}" if getattr(user_me, "username", None) else f"ID:{user_me.id}"
        logger.info(f"👤 USER 客户端已启动: {user_username}（群监听入口）")

        valid_channels = self._normalize_channels()
        if valid_channels:
            logger.info(f"🎯 群监听启用（输入源）：{valid_channels}")
        else:
            logger.warning("⚠️ TARGET_CHANNELS 为空，群监听不会触发（只剩私聊入口）")

        # --------------------------
        # ✅ 群监听（用 USER client）
        # --------------------------
        if valid_channels:

            @self.user_client.on(events.NewMessage(chats=valid_channels, incoming=True))
            async def group_debug(event):
                try:
                    chat_id = int(event.chat_id or 0)
                    msg = getattr(event, "message", None)
                    msg_id = int(getattr(msg, "id", 0) or 0)
                    text = (event.raw_text or "").strip()
                    if text:
                        logger.info(f"🛰️ [GROUP_RX] chat={chat_id} msg={msg_id} text={text[:80]!r}")
                except Exception:
                    pass

            @self.user_client.on(events.NewMessage(chats=valid_channels, incoming=True))
            async def group_handler(event):
                try:
                    chat_id = int(event.chat_id or 0)
                    msg = getattr(event, "message", None)
                    msg_id = int(getattr(msg, "id", 0) or 0)
                    text = (event.raw_text or "").strip()

                    ca = self.extract_ca(event)
                    if not ca:
                        return

                    sender = await event.get_sender()
                    sender_str = "未知用户"
                    if sender:
                        uname = getattr(sender, "username", None)
                        fname = getattr(sender, "first_name", None)
                        if uname:
                            sender_str = f"@{uname}"
                        elif fname:
                            sender_str = fname

                    channel_name = VIP_SOURCES.get(chat_id, f"Group_{chat_id}")
                    readable_source = f"{channel_name} | {sender_str}"

                    if not self._should_process(ca, readable_source):
                        return

                    # 输出目标：PRIVATE_ONLY_MODE=True 时会回到管理员私聊
                    reply_chat_id = self._resolve_reply_chat_id(chat_id)

                    logger.info(
                        f"📌 群命中CA: {ca} | chat={chat_id} msg={msg_id} src={readable_source} -> reply_to={reply_chat_id}"
                    )

                    args5 = (ca, readable_source, reply_chat_id, msg_id, text)
                    self._create_task_with_log(self._run_callback(callback_func, args5))

                except Exception as e:
                    logger.error(f"❌ 群消息处理异常: {e}", exc_info=True)

        # --------------------------
        # ✅ 私聊入口（用 BOT client），继续做白名单限制
        # --------------------------
        @self.bot_client.on(events.NewMessage(incoming=True))
        async def dm_handler(event):
            try:
                if not event.is_private:
                    return

                sender_id = int(getattr(event, "sender_id", 0) or 0)
                if not self._is_whitelisted(sender_id):
                    return

                chat_id = int(event.chat_id or 0)
                msg = getattr(event, "message", None)
                msg_id = int(getattr(msg, "id", 0) or 0)
                text = (event.raw_text or "").strip()

                ca = self.extract_ca(event)
                if not ca:
                    logger.info(f"📩 白名单私聊无CA: from={sender_id} msg={msg_id}")
                    return

                readable_source = f"DM_USER | {sender_id}"

                if not self._should_process(ca, readable_source):
                    return

                logger.info(f"📩 私聊命中CA: {ca} | from={sender_id} chat={chat_id} msg={msg_id}")

                args5 = (ca, readable_source, chat_id, msg_id, text)
                self._create_task_with_log(self._run_callback(callback_func, args5))

            except Exception as e:
                logger.error(f"❌ 私聊消息处理异常: {e}", exc_info=True)

        # --------------------------
        # 🟢 新增修复：接管 Bot 的透明按钮点击事件 (CallbackQuery)
        # --------------------------
        @self.bot_client.on(events.CallbackQuery())
        async def btn_handler(event):
            try:
                data = event.data
                if not data: 
                    return
                data_str = data.decode('utf-8')
                
                if data_str.startswith("refresh:"):
                    ca = data_str.split("refresh:", 1)[-1].strip()
                    chat_id = int(event.chat_id)
                    msg_id = int(event.message_id)
                    
                    if refresh_callback:
                        await event.answer("🔄 刷新中...")
                        self._create_task_with_log(refresh_callback(ca, chat_id, msg_id))
                    else:
                        await event.answer("⚠️ 未绑定刷新回调", alert=True)
            except Exception as e:
                logger.error(f"❌ 按钮回调处理异常: {e}")

        logger.info("🚀 猎人已就位：群输入(用户号) + 私聊输入(BOT) + 私聊输出(按 PRIVATE_ONLY_MODE) + 按钮响应(已接管)")

        # 两个客户端都跑起来
        await asyncio.gather(
            self.user_client.run_until_disconnected(),
            self.bot_client.run_until_disconnected(),
        )


_listener_instance = AlphaListener()


# ✅ 关键补丁：对外 start 增加 refresh_callback 第二参数（兼容 main.py 新调用）
async def start(callback_func, refresh_callback=None):
    await _listener_instance.start(callback_func, refresh_callback)