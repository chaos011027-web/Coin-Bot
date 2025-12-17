import re
import asyncio
import logging
import os
import time
from telethon import TelegramClient, events
from config.settings import (
    TELEGRAM_API_ID,
    TELEGRAM_API_HASH,
    TARGET_CHANNELS,
    VIP_SOURCES,
    DEBUG,
    ROUTER_BLACKLIST,
)

logger = logging.getLogger("Listener")

# Solana CA 正则
SOL_PATTERN = re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{32,44}\b")


class AlphaListener:
    def __init__(self):
        os.makedirs("sessions", exist_ok=True)

        session_path = "sessions/hunter_session"
        if not os.path.exists(session_path + ".session"):
            logger.warning(f"⚠️ 未找到登录文件 {session_path}.session，可能需要重新登录。建议先运行 get_id.py 登录一次。")

        self.client = TelegramClient(
            session_path,
            TELEGRAM_API_ID,
            TELEGRAM_API_HASH,
            connection_retries=None,
            auto_reconnect=True,
        )

        # 缓存结构: { ca: {'time': timestamp, 'is_vip': bool} }
        self.seen_cache = {}
        self.ttl = 600

        # DEBUG 打印 chat_id 去重，避免刷屏
        self._printed_chat_ids = set()

    def _extract_cas(self, text: str) -> list[str]:
        """提取所有有效 CA（去重 + 黑名单过滤）"""
        if not text:
            return []
        clean_text = text.replace("\u200b", "").strip()
        matches = SOL_PATTERN.findall(clean_text)
        if not matches:
            return []

        out, seen = [], set()
        for ca in matches:
            if ca in ROUTER_BLACKLIST:
                continue
            if ca not in seen:
                seen.add(ca)
                out.append(ca)
        return out

    def _should_process(self, ca: str, is_vip_source: bool) -> bool:
        """智能去重逻辑（保留 VIP 穿透）"""
        now = time.time()

        # 清理过期
        expired = [k for k, v in self.seen_cache.items() if now - v["time"] > self.ttl]
        for k in expired:
            self.seen_cache.pop(k, None)

        if ca in self.seen_cache:
            last_record = self.seen_cache[ca]
            # VIP 穿透：旧消息不是VIP，新消息是VIP -> 允许通过
            if last_record["is_vip"] or not is_vip_source:
                return False
            logger.info(f"💎 触发 VIP 穿透机制: {ca}")

        self.seen_cache[ca] = {"time": now, "is_vip": is_vip_source}
        return True

    async def start(self, callback_func):
        valid_channels = [ch for ch in TARGET_CHANNELS if ch]

        logger.info(f"🎧 正在启动监听... 有效目标源: {len(valid_channels)} 个")

        try:
            await self.client.start()
            me = await self.client.get_me()
            logger.info(f"✅ Telegram 登录成功: @{me.username or me.first_name} (ID: {me.id})")
        except Exception as e:
            logger.error(f"❌ Telegram 登录失败: {e}")
            return

        if not valid_channels:
            logger.warning("⚠️ 监听列表为空！请在 settings.py 中配置 TARGET_CHANNELS")
            # 仍然允许运行（你可用于 DEBUG 打印 chat_id）
            valid_channels = None

        @self.client.on(events.NewMessage(chats=valid_channels))
        async def handler(event):
            try:
                chat_id = event.chat_id

                # ✅ 更稳：用 raw_text
                text = event.raw_text or ""

                # ✅ DEBUG：第一次看到某个 chat_id 就打印（帮你拿 Aure 群 -100...）
                if DEBUG and chat_id and chat_id not in self._printed_chat_ids:
                    self._printed_chat_ids.add(chat_id)
                    title = getattr(event.chat, "title", None)
                    logger.info(f"[DEBUG] 捕获 chat_id={chat_id} title={title}")

                cas = self._extract_cas(text)
                if not cas:
                    return

                source_name = VIP_SOURCES.get(chat_id, "Raw_Monitor")
                is_vip = chat_id in VIP_SOURCES

                # ✅ 支持一条消息多个 CA
                for ca in cas:
                    if self._should_process(ca, is_vip):
                        logger.info(f"🔔 捕获信号: {ca} | 来源: {source_name}{' (VIP)' if is_vip else ''}")
                        asyncio.create_task(self._safe_callback(callback_func, ca, source_name))
                    else:
                        logger.debug(f"♻️ 忽略重复信号: {ca}")

            except Exception as e:
                logger.error(f"⚠️ 消息处理出错: {e}")

        logger.info("🚀 监听器正在运行... (Ctrl+C 停止)")
        await self.client.run_until_disconnected()

    async def _safe_callback(self, func, ca, source):
        try:
            if asyncio.iscoroutinefunction(func):
                await func(ca, source)
            else:
                func(ca, source)
        except Exception as e:
            logger.error(f"❌ 回调执行失败: {e}")


# main.py 调用入口
_listener_instance = AlphaListener()

async def start(callback_func):
    await _listener_instance.start(callback_func)
