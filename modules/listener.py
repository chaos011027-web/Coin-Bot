# modules/listener.py
import re
import asyncio
import logging
import os
import time
import inspect
from typing import Callable, Any, Dict, Optional, List

from telethon import TelegramClient, events
from telethon.tl.types import MessageEntityTextUrl, MessageEntityUrl

from config.settings import TELEGRAM_API_ID, TELEGRAM_API_HASH, TARGET_CHANNELS, VIP_SOURCES

logger = logging.getLogger("Hunter")

# Solana Base58 32~44
SOL_PATTERN = re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{32,44}\b")

DEFAULT_BLACKLIST = {
    "So11111111111111111111111111111111111111112",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",
}


class AlphaListener:
    def __init__(self):
        os.makedirs("sessions", exist_ok=True)
        session_path = "sessions/hunter_session"

        self.client = TelegramClient(
            session_path,
            TELEGRAM_API_ID,
            TELEGRAM_API_HASH,
            connection_retries=None,
            auto_reconnect=True,
            base_logger=logging.getLogger("telethon"),
        )

        self.seen_cache: Dict[str, float] = {}
        self.ttl = 600
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
                    url = text[ent.offset : ent.offset + ent.length]
                except Exception:
                    url = None

            if not url:
                continue

            ca = self._find_ca_in_text(url)
            if ca:
                return ca

        return None

    def _extract_from_buttons(self, message) -> Optional[str]:
        """
        Telethon: message.reply_markup 里可能包含按钮URL
        """
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
        except Exception:
            return None

        return None

    def extract_ca(self, event) -> Optional[str]:
        msg = getattr(event, "message", None)
        text = (event.raw_text or "")

        # 1) 隐藏链接实体
        ca = self._extract_from_entities(msg, text)
        if ca:
            return ca

        # 2) 按钮 URL
        ca = self._extract_from_buttons(msg)
        if ca:
            return ca

        # 3) 纯文本
        ca = self._find_ca_in_text(text)
        return ca

    # --------------------------
    # dedup/filters
    # --------------------------
    def _should_process(self, ca: str, source_name: str) -> bool:
        now = time.time()

        if ca in self.blacklist:
            logger.info(f"🚫 黑名单跳过: {ca} | src={source_name}")
            return False

        last = self.seen_cache.get(ca)
        if last and (now - last) < self.ttl:
            logger.info(f"♻️ 去重跳过: {ca} | {int(now-last)}s | src={source_name}")
            return False

        self.seen_cache[ca] = now
        # 清理
        if len(self.seen_cache) > 5000:
            cutoff = now - self.ttl
            for k, t in list(self.seen_cache.items()):
                if t < cutoff:
                    self.seen_cache.pop(k, None)
        return True

    # --------------------------
    # callback runner
    # --------------------------
    async def _run_callback(self, callback_func: Callable[..., Any], args4, args7):
        async with self._sem:
            argc = None
            try:
                sig = inspect.signature(callback_func)
                argc = len([
                    p for p in sig.parameters.values()
                    if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
                ])
            except Exception:
                argc = None

            try:
                if asyncio.iscoroutinefunction(callback_func):
                    if argc is None or argc >= 7:
                        await callback_func(*args7)
                    else:
                        await callback_func(*args4)
                else:
                    if argc is None or argc >= 7:
                        callback_func(*args7)
                    else:
                        callback_func(*args4)
            except Exception as e:
                logger.error(f"❌ 回调执行失败（分析未触发）: {e}", exc_info=True)

    def _create_task_with_log(self, coro):
        t = asyncio.create_task(coro)
        def _done(task: asyncio.Task):
            try:
                task.result()
            except Exception as e:
                logger.error(f"❌ 后台任务异常（分析未触发）: {e}", exc_info=True)
        t.add_done_callback(_done)
        return t

    # --------------------------
    # start
    # --------------------------
    async def start(self, callback_func: Callable[..., Any]):
        valid_channels = [ch for ch in TARGET_CHANNELS if ch]
        logger.info(f"🎯 锁定目标源数量: {len(valid_channels)}")
        logger.info(f"🎯 TARGET_CHANNELS = {valid_channels}")

        await self.client.start()
        me = await self.client.get_me()
        logger.info(f"✅ Telegram 登录成功: @{me.username or me.first_name} (ID:{me.id})")

        @self.client.on(events.NewMessage(chats=valid_channels))
        async def handler(event):
            chat_id = event.chat_id
            msg = getattr(event, "message", None)
            msg_id = getattr(msg, "id", None)
            text = (event.raw_text or "").strip()

            source_name = VIP_SOURCES.get(chat_id, f"Source_{chat_id}")

            # 你现在的 debug 日志
            logger.debug(f"DEBUG: 收到消息 | ChatID: {chat_id} | 内容: {text[:80]}...")

            ca = self.extract_ca(event)
            if not ca:
                # ✅ 关键诊断：告诉你为什么没触发分析
                # 同时打印一下是否有按钮/实体，确认 CA 是否藏在那
                ent_cnt = len(getattr(msg, "entities", []) or [])
                has_btn = bool(getattr(getattr(msg, "reply_markup", None), "rows", None))
                logger.info(
                    f"🟡 未发现CA，跳过分析 | chat={chat_id} msg={msg_id} src={source_name} "
                    f"| entities={ent_cnt} buttons={has_btn}"
                )
                return

            logger.info(f"📌 命中CA: {ca} | chat={chat_id} msg={msg_id} src={source_name}")

            if not self._should_process(ca, source_name):
                return

            raw_message = text
            trigger_mode = "auto"
            is_vip = chat_id in VIP_SOURCES

            args4 = (ca, source_name, chat_id, msg_id)
            args7 = (ca, source_name, chat_id, msg_id, raw_message, trigger_mode, is_vip)

            logger.info(f"🚀 触发分析回调: {ca}")
            self._create_task_with_log(self._run_callback(callback_func, args4, args7))

        logger.info("🚀 猎人已就位，等待目标群消息...")
        await self.client.run_until_disconnected()


_listener_instance = AlphaListener()

async def start(callback_func):
    await _listener_instance.start(callback_func)

