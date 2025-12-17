# get_id.py (终极方案: QR 扫码登录)
import asyncio
import os
import qrcode
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

# 使用 Telegram Android 官方 ID (最稳定)
api_id = 6
api_hash = "eb06d4abfb49dc3eeb1aeb98ae0f581e"

# 自动创建 session 文件夹
if not os.path.exists("sessions"):
    os.makedirs("sessions")

# 使用一个新的 session 文件名，避免旧缓存干扰
client = TelegramClient("sessions/qr_login_session", api_id, api_hash)

async def main():
    print("🚀 正在初始化...")
    await client.connect()

    # 检查是否已经登录
    if not await client.is_user_authorized():
        print("📲 正在生成二维码，请准备好手机 Telegram...")
        
        # 请求二维码登录
        qr_login = await client.qr_login()
        
        # 打印二维码到终端
        qr = qrcode.QRCode()
        qr.add_data(qr_login.url)
        qr.make()
        print("\n请使用手机 Telegram -> 设置 -> 设备 -> 连接桌面设备 扫描下方二维码：\n")
        qr.print_ascii(invert=True)
        
        # 等待扫描
        print("⏳ 等待扫描中...")
        try:
            # 等待登录完成
            await qr_login.wait()
        except SessionPasswordNeededError:
            # 如果开启了二次验证密码
            pw = input("🔐 检测到两步验证，请输入你的 2FA 密码: ")
            await client.sign_in(password=pw)
    
    print("\n✅ 登录成功！")
    print("👀 监听已启动...")
    print("👉 请静静等待 **AureHoundAI 群组** 出现一条新消息...")

    @client.on(events.NewMessage)
    async def handler(event):
        # 这一部分和之前一样，用于捕获 ID
        from telethon import events # 重新导入以防作用域问题
        
        msg_text = (event.raw_text or "").replace("\n", " ")[:50]
        chat_title = "未知会话"
        try:
            chat = await event.get_chat()
            chat_title = getattr(chat, 'title', '私聊')
        except:
            pass

        print("\n" + "="*30)
        print(f"📌 捕获到新消息！来源: {chat_title}")
        print(f"📝 内容: {msg_text}...")
        print("-" * 30)
        print(f"🔑 CHAT ID: {event.chat_id}")
        print("-" * 30)
        
        if str(event.chat_id).startswith("-100"):
            print(f"👉 请复制这个 ID: {event.chat_id}")
            print("👉 填入 config/settings.py 的 VIP_SOURCES 中")
        else:
            print(f"⚠️ 这是私聊 ID ({event.chat_id})，请确认是群组消息。")

        print("="*30 + "\n")
        await client.disconnect()

    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
