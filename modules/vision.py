import os
import logging
import asyncio
import time
from typing import Optional

logger = logging.getLogger("Vision")

try:
    from google import genai
    from google.genai import types
except Exception:
    genai = None
    types = None


GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_VISION_MODEL", "gemini-2.0-flash")


class VisionAnalyzer:
    """
    仅负责：
    - 对 K 线截图做第二意见分析
    - 输出一句简短、可供 Brain 动态策略引用的结论

    不负责：
    - 头像分析
    - 静态叙事
    - 直接决策买卖
    """

    def __init__(self):
        self.enabled = False
        self.client = None

        if not genai or not types:
            logger.warning("⚠️ google-genai 未安装或导入失败，Vision 模块不可用。")
            return

        if not GEMINI_API_KEY:
            logger.warning("⚠️ 未配置 GEMINI_API_KEY，Vision 模块不可用。")
            return

        try:
            self.client = genai.Client(api_key=GEMINI_API_KEY)
            self.enabled = True
            logger.info(f"✅ Gemini Vision 已就位，模型: {GEMINI_MODEL}")
        except Exception as e:
            logger.error(f"❌ Gemini Vision 初始化失败: {e}")
            self.enabled = False
            self.client = None

    def _guess_mime_type(self, image_path: str) -> str:
        lower = (image_path or "").lower()
        if lower.endswith(".jpg") or lower.endswith(".jpeg"):
            return "image/jpeg"
        if lower.endswith(".webp"):
            return "image/webp"
        return "image/png"

    def _read_image_bytes_with_retry(self, image_path: str) -> bytes:
        image_bytes = b""
        last_err = None

        for _ in range(5):
            try:
                with open(image_path, "rb") as f:
                    image_bytes = f.read()
                if image_bytes:
                    return image_bytes
            except PermissionError as e:
                last_err = e
                time.sleep(0.25)
            except Exception as e:
                last_err = e
                break

        if not image_bytes:
            raise last_err or RuntimeError("K线截图读取失败")

        return image_bytes

    def _analyze_chart_sync(self, image_path: str) -> str:
        if not self.enabled or not self.client:
            return "Gemini Vision 未启用"

        if not image_path:
            return "无K线截图"
        if not os.path.exists(image_path):
            return "K线截图不存在"
        if os.path.getsize(image_path) < 500:
            return "K线截图无效"

        try:
            image_bytes = self._read_image_bytes_with_retry(image_path)
            mime_type = self._guess_mime_type(image_path)

            prompt = (
                "你是顶级链上短线交易员，请只基于这张 memecoin K 线截图做判断。\n"
                "目标：输出一句简短中文结论，判断当前更像：\n"
                "1. 拉升初盘\n"
                "2. 洗盘诱空\n"
                "3. 高位出货\n"
                "4. 暴跌画门\n"
                "5. 区间震荡等待选择方向\n\n"
                "必须同时考虑：\n"
                "- K线结构\n"
                "- 上下影线特征\n"
                "- 量能变化\n"
                "- 是否疑似控盘/诱多/诱空\n\n"
                "输出要求：\n"
                "- 只输出一句中文\n"
                "- 不要分点\n"
                "- 不要免责声明\n"
                "- 控制在60字以内"
            )

            response = self.client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[
                    prompt,
                    types.Part.from_bytes(
                        data=image_bytes,
                        mime_type=mime_type,
                    ),
                ],
            )

            text = getattr(response, "text", "") or ""
            text = str(text).strip().replace("\n", " ")
            if not text:
                return "Gemini K线分析为空"

            return text[:120]

        except Exception as e:
            logger.error(f"❌ Gemini K线分析失败: {e}")
            return "Gemini K线分析报错"

    async def analyze_chart(self, image_path: str) -> str:
        return await asyncio.to_thread(self._analyze_chart_sync, image_path)


vision_analyzer = VisionAnalyzer()


async def analyze_chart(image_path: str) -> str:
    """
    提供给 brain.py 直接调用的异步函数接口
    """
    return await vision_analyzer.analyze_chart(image_path)