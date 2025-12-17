# login_fix.py (扫码版)
import os
import asyncio
import qrcode
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

# 1. 使用安卓官方 ID
api_id = 6
api_hash = "eb06d4abfb49dc3eeb1aeb98ae0f581e"

# 2. 确保文件夹存在
if not os.path.exists("sessions"):
    os.makedirs("sessions")

# 3. 指定 main.py 需要的那个确切的文件名！
session_name = "sessions/hunter_session"

print(f"🚀 正在为 {session_name} 创建登录凭证...")

client = TelegramClient(session_name, api_id, api_hash)

async def main():
    await client.connect()
    
    # 如果没登录，启动扫码流程
    if not await client.is_user_authorized():
        try:
            qr_login = await client.qr_login()
            
            # 生成二维码
            qr = qrcode.QRCode()
            qr.add_data(qr_login.url)
            qr.make()
            
            print("\n" + "="*40)
            print("📲 请拿出手机，打开 Telegram -> 设置 -> 设备 -> 连接桌面设备")
            print("👉 扫描下方的二维码 (有效期30秒)")
            print("="*40 + "\n")
            
            qr.print_ascii(invert=True)
            
            print("⏳ 等待扫描中...")
            await qr_login.wait()
            
        except SessionPasswordNeededError:
            pw = input("🔐 请输入两步验证密码: ")
            await client.sign_in(password=pw)
        except Exception as e:
            print(f"❌ 登录超时或失败: {e}")
            return

    print("\n" + "="*40)
    print("✅ 登录成功！")
    print(f"📂 凭证已保存: {session_name}.session")
    print("🎉 修复完成！请直接运行 python main.py")
    print("="*40 + "\n")

if __name__ == "__main__":
    asyncio.run(main())