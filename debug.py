import os
import asyncio
from telethon import TelegramClient, events
from dotenv import load_dotenv

# 1. 加载配置
load_dotenv()
api_id = int(os.getenv("TELEGRAM_API_ID"))
# ↓↓↓ 之前这里多了一个括号，现在修好了 ↓↓↓
api_hash = os.getenv("TELEGRAM_API_HASH")

print("🔍 全频道听诊器启动中... (按 Ctrl+C 停止)")

client = TelegramClient('sessions/hunter_session', api_id, api_hash)

# 监听【所有】消息 (incoming=True: 别人发的, outgoing=True: 自己发的)
@client.on(events.NewMessage)
async def debug_handler(event):
    chat = await event.get_chat()
    sender = await event.get_sender()
    
    # 尝试获取名称
    chat_title = getattr(chat, 'title', getattr(chat, 'username', 'Unknown Chat'))
    sender_name = getattr(sender, 'username', getattr(sender, 'first_name', 'Unknown User'))
    
    print("\n" + "="*40)
    print(f"📨 【收到消息】")
    print(f"📍 来源群组/频道: {chat_title}")
    # ↓↓↓ 这个就是你要复制到 .env 的 ID ↓↓↓
    print(f"🆔 来源 ID (Target ID): {event.chat_id}")
    print(f"👤 发送者: {sender_name} (ID: {event.sender_id})")
    print(f"📄 内容: {event.text}")
    print("="*40)

client.start()
client.run_until_disconnected()