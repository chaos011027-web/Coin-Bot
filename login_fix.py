import os
import asyncio
from telethon import TelegramClient
from dotenv import load_dotenv

# 1. 加载 .env 中的配置 (确保用的是你刚申请的私有 ID)
load_dotenv()

api_id = os.getenv("TELEGRAM_API_ID")
api_hash = os.getenv("TELEGRAM_API_HASH")

# 检查是否读到了配置
if not api_id or not api_hash:
    print("❌ 错误: 无法读取 .env 文件中的 API_ID 或 API_HASH")
    print("👉 请检查 .env 文件是否保存，变量名是否正确。")
    exit(1)

# 确保 ID 是整数
try:
    api_id = int(api_id)
except ValueError:
    print(f"❌ 错误: API_ID 必须是数字，当前获取到: {api_id}")
    exit(1)

# 2. 准备 Session 文件夹
if not os.path.exists("sessions"):
    os.makedirs("sessions")

# 指定 Session 文件名
session_name = "sessions/hunter_session"

print(f"🚀 正在启动登录程序...")
print(f"🆔 使用 API ID: {api_id}")
print(f"📂 目标文件: {session_name}.session")
print("-" * 40)

client = TelegramClient(session_name, api_id, api_hash)

async def main():
    # client.start() 是 Telethon 的标准登录流程
    # 它会自动检测：
    # 1. 如果没有登录 -> 提示输入手机号
    # 2. 输入验证码
    # 3. 如果有两步验证 (2FA) -> 提示输入密码
    await client.start()

    print("\n" + "="*40)
    print("✅ 登录成功！(Login Success)")
    print("🤖 猎人账号已就位。")
    print("👉 为了安全，建议今天不要运行 main.py，明天再开始抓取。")
    print("="*40 + "\n")

if __name__ == "__main__":
    try:
        client.loop.run_until_complete(main())
    except KeyboardInterrupt:
        print("\n🚫 用户取消操作")
    except Exception as e:
        print(f"\n❌ 发生错误: {e}")