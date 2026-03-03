# config/settings.py
import os
import sys
from dotenv import load_dotenv

load_dotenv()

# ==========================================
# 1. 基础调试与网络配置
# ==========================================
DEBUG = True

PROXY_URL = None
# PROXY_URL = "http://127.0.0.1:7890"

ROUTER_BLACKLIST = {
    "So11111111111111111111111111111111111111112",  # WSOL
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",  # USDT
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
    "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",  # Raydium Authority
}

# ==========================================
# 2. 身份与权限
# ==========================================
SESSION_NAME = "solana_hunter"
BOT_SESSION_NAME = "solana_hunter_bot"

api_id_env = os.getenv("TELEGRAM_API_ID")
TELEGRAM_API_ID = int(api_id_env) if api_id_env else 6

api_hash_env = os.getenv("TELEGRAM_API_HASH")
TELEGRAM_API_HASH = api_hash_env if api_hash_env else "eb06d4abfb49dc3eeb1aeb98ae0f581e"

admin_id_str = os.getenv("ADMIN_CHAT_ID")
ADMIN_CHAT_ID = int(admin_id_str) if admin_id_str else 7230042939

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    print("\n" + "!" * 50)
    print("❌ 严重错误：无法从 .env 读取 TELEGRAM_BOT_TOKEN")
    sys.exit(1)

# ==========================================
# 3. 模式开关：仅私聊（✅ 你的需求）
# ==========================================
# True：只接受用户私聊机器人发CA；不再监听群
PRIVATE_ONLY_MODE = False

# 白名单（逗号分隔），不填则默认只有管理员
# 例：WHITELIST_USER_IDS=7230042939,11111111
_whitelist_env = os.getenv("WHITELIST_USER_IDS", "").strip()
if _whitelist_env:
    WHITELIST_USER_IDS = set(int(x.strip()) for x in _whitelist_env.split(",") if x.strip().isdigit())
else:
    WHITELIST_USER_IDS = {int(ADMIN_CHAT_ID)}

# （可选兼容字段）如果未来你要保留群推送，可以在 .env 里配置
# 但本阶段你要的是私聊，所以默认 None
REPORT_GROUP_ID = os.getenv("REPORT_GROUP_ID")
REPORT_GROUP_ID = int(REPORT_GROUP_ID) if REPORT_GROUP_ID and str(REPORT_GROUP_ID).lstrip("-").isdigit() else None

# ==========================================
# 4. 旧群配置（保留但在 PRIVATE_ONLY_MODE=True 下不会使用）
# ==========================================
SOURCE_GROUP_ID = int(os.getenv("SOURCE_GROUP_ID", "-1002809834135"))
VIP_SOURCES = {SOURCE_GROUP_ID: "🔥 核心监听群(A)"}
TARGET_CHANNELS = list(VIP_SOURCES.keys())

# ==========================================
# 5. 阈值与风控配置
# ==========================================
THRESHOLDS = {
    "MAX_RISK_SCORE": 5000,
    "REQUIRE_LP_LOCKED": False,
}
