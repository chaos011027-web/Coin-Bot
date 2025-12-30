import os
import asyncio
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from pathlib import Path

# ✅ 强制加载当前文件所在目录的 .env
BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
load_dotenv(ENV_PATH)

TOKEN = os.getenv("BOT_TOKEN")

dp = Dispatcher()

@dp.message(F.text)
async def echo(m: Message):
    await m.answer("✅ bot is alive: " + (m.text or ""))

async def main():
    if not TOKEN:
        print("❌ BOT_TOKEN 为空，未能从 .env 读取")
        print("👉 请确认 .env 路径:", ENV_PATH)
        return

    print("✅ BOT_TOKEN 已读取，启动 polling...")
    bot = Bot(TOKEN)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
