import webbrowser
import logging

logger = logging.getLogger("BrowserOpener")

def open_gmgn_link(ca: str):
    """
    使用系统默认浏览器打开 GMGN 页面 (非阻塞，跨平台)
    """
    if not ca or len(ca) < 20:
        logger.warning("⚠️ CA 地址无效，跳过浏览器打开")
        return

    url = f"https://gmgn.ai/sol/token/{ca}"
    try:
        webbrowser.open(url)
        logger.info(f"🌐 已请求打开默认浏览器: {url}")
    except Exception as e:
        logger.error(f"❌ 打开浏览器失败: {e}")

# 可选：用于手动测试
if __name__ == "__main__":
    open_gmgn_link("DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263")
