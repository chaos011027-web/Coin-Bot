import os
import sys
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()

# --- 1. 基础调试配置 ---
DEBUG = True

# 路由黑名单
ROUTER_BLACKLIST = {
    "So11111111111111111111111111111111111111112", # WSOL
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB", # USDT
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", # USDC
    "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1", # Raydium Authority
} 

# --- 2. 身份与权限 (自动读取 .env) ---

# [API ID]
# 优先读 .env，读不到则用默认安卓 Key (6)
api_id_env = os.getenv("TELEGRAM_API_ID")
TELEGRAM_API_ID = int(api_id_env) if api_id_env else 6

api_hash_env = os.getenv("TELEGRAM_API_HASH")
TELEGRAM_API_HASH = api_hash_env if api_hash_env else "eb06d4abfb49dc3eeb1aeb98ae0f581e"

# [ADMIN ID]
admin_id_str = os.getenv("ADMIN_CHAT_ID")
# 这里的 7230042939 是为了防止 .env 读取失败时的备用方案
ADMIN_CHAT_ID = int(admin_id_str) if admin_id_str else 7230042939

# [BOT TOKEN]
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# 🚨【启动前自检】
# 如果 .env 读取失败，这里会直接拦截，防止后面报 "NoneType" 错误
if not TELEGRAM_BOT_TOKEN:
    print("\n" + "!"*50)
    print("❌ 严重错误：无法从 .env 读取 TELEGRAM_BOT_TOKEN")
    print("请检查：")
    print("1. 项目根目录下是否有 .env 文件？")
    print("2. .env 文件名是否正确 (不是 .env.txt)？")
    print("3. 内容格式是否为 TELEGRAM_BOT_TOKEN=xxxx:xxxx")
    print("!"*50 + "\n")
    # 强制停止，让你修好 .env
    sys.exit(1)

# --- 3. 监听目标配置 ---

# 🌟 金狗信号源 (AureHoundAI)
VIP_SOURCES = {
    7870541017: "AureHoundAI", 
}

# 普通监听频道
RAW_CHANNELS = []

# 合并监听列表
TARGET_CHANNELS = RAW_CHANNELS + list(VIP_SOURCES.keys())

# --- 4. 阈值配置 ---
THRESHOLDS = {
    "MAX_RISK_SCORE": 5000,      
    "REQUIRE_LP_LOCKED": False,  
}