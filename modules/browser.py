import os
import webbrowser
import logging

logger = logging.getLogger("Browser")

# 可通过 .env 控制：ENABLE_BROWSER_POPUP=true/false
ENABLE_BROWSER_POPUP = os.getenv("ENABLE_BROWSER_POPUP", "true").lower() == "true"

def _has_gui() -> bool:
    """
    判断当前环境是否可能有图形界面：
    - Windows / macOS 基本都有
    - Linux 需检查 DISPLAY / WAYLAND_DISPLAY
    """
    if os.name == "nt":   # Windows
        return True
    if os.name == "posix":
        # Linux/Unix: 没有显示环境就别打开
        return bool(os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY"))
    return False

def open_gmgn_link(ca: str):
    """
    自动打开 GMGN 页面（不会影响主程序）
    """
    if not ENABLE_BROWSER_POPUP or not ca:
        return

    if not _has_gui():
        # 服务器无 GUI：静默跳过
        return

    try:
        # 建议用更常见的路径；如你确认 /sol/token 更快，也可改成 env 可配置
        url = f"https://gmgn.ai/sol/token/{ca}"
        webbrowser.open(url, new=2)
        logger.info(f"🌍 [浏览器] 已打开 GMGN: {url}")
    except Exception as e:
        logger.warning(f"⚠️ 无法打开浏览器 (不影响主程序运行): {e}")

if __name__ == "__main__":
    # 测试：随便填一个 CA
    open_gmgn_link("So11111111111111111111111111111111111111112")
