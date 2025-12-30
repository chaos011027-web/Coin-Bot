import os
import sys
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()

# ==========================================
# 1. 基础调试与网络配置
# ==========================================
DEBUG = True

# 🌐 代理配置 (如果你之前的 WinError 网络错误频发，请取消注释并修改端口)
# 常见的本地代理端口: Clash 7890, v2rayN 10809
# PROXY_URL = "http://127.0.0.1:7890" 
PROXY_URL = None 

# 路由/代币黑名单 (过滤掉 WSOL, USDT, USDC 等非目标代币)
ROUTER_BLACKLIST = {
    "So11111111111111111111111111111111111111112", # WSOL
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB", # USDT
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", # USDC
    "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1", # Raydium Authority
}

# ==========================================
# 2. 身份与权限 (自动读取 .env)
# ==========================================

# [API ID / HASH]
# 优先读 .env，读不到则用 Telegram 安卓端默认 Key (方便测试)
api_id_env = os.getenv("TELEGRAM_API_ID")
TELEGRAM_API_ID = int(api_id_env) if api_id_env else 6

api_hash_env = os.getenv("TELEGRAM_API_HASH")
TELEGRAM_API_HASH = api_hash_env if api_hash_env else "eb06d4abfb49dc3eeb1aeb98ae0f581e"

# [ADMIN ID] - 机器人的超级管理员 (通常是你个人的 ID)
admin_id_str = os.getenv("ADMIN_CHAT_ID")
ADMIN_CHAT_ID = int(admin_id_str) if admin_id_str else 7230042939

# [BOT TOKEN]
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# 🚨【启动前自检】
if not TELEGRAM_BOT_TOKEN:
    print("\n" + "!"*50)
    print("❌ 严重错误：无法从 .env 读取 TELEGRAM_BOT_TOKEN")
    print("请检查：")
    print("1. 项目根目录下是否有 .env 文件？")
    print("2. 内容格式是否为 TELEGRAM_BOT_TOKEN=xxxx:xxxx")
    print("!"*50 + "\n")
    sys.exit(1)

# ==========================================
# 3. 关键群组配置 (核心逻辑)
# ==========================================

# ✅ [报告群 ID] 
# 机器人会将所有分析结果发到这个群。
# 如果是你自己发的消息，它会在这里回复；如果是监控到的，它会转发到这里。
REPORT_GROUP_ID = -5108950686  # 你的大群 ID

# ✅ [信号源配置] (格式: ID: "自定义名称")
# 只有在这里列出的群，机器人(Userbot)才会监听并抓取 CA。
VIP_SOURCES = {
    # 刚才识别到的信号群
    -1002809834135: "PUMP_Signal_Group", 
    
    # 你之前代码里保留的 (如果是无效的可以注释掉)
    7870541017: "AureHoundAI", 
}

# 自动生成监听列表
# 逻辑：监听所有 VIP 信号源 + 监听报告群本身(为了支持手动发 CA)
TARGET_CHANNELS = list(VIP_SOURCES.keys()) + [REPORT_GROUP_ID]

# ==========================================
# 4. 阈值与风控配置
# ==========================================
THRESHOLDS = {
    "MAX_RISK_SCORE": 5000,      
    "REQUIRE_LP_LOCKED": False,  
}