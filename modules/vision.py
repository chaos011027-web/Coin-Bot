import os
import logging
import asyncio
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from PIL import Image

logger = logging.getLogger("VisionEye")

class VisionEye:
    def __init__(self):
        """
        初始化 Gemini Flash 模型，用于图像分析
        """
        self.api_key = os.getenv("GEMINI_API_KEY")
        
        # 并发控制：限制同时只能有 3 个请求正在处理，防止触发 API 频率限制
        self.semaphore = asyncio.Semaphore(3)

        if not self.api_key:
            logger.warning("⚠️ 未检测到 GEMINI_API_KEY，视觉模块将不可用！")
            self.model = None
        else:
            try:
                genai.configure(api_key=self.api_key)
                self.model = genai.GenerativeModel('gemini-1.5-flash')
                logger.info("✅ VisionEye (Gemini Flash) 初始化成功")
            except Exception as e:
                logger.error(f"Gemini 初始化失败: {e}")
                self.model = None

    async def analyze_chart(self, image_path: str):
        """
        异步分析本地截图的代币K线图
        """
        if not self.model:
            return "Vision Analysis Skipped (No Model)"
        
        if not image_path or not os.path.exists(image_path):
            return "Vision Analysis Skipped (No File)"

        # 使用信号量控制并发
        async with self.semaphore:
            try:
                # 将同步的图像处理和 API 请求放入线程池运行
                return await asyncio.to_thread(self._sync_analyze, image_path)
            except Exception as e:
                logger.error(f"视觉分析致命错误: {e}")
                return "Vision Analysis Failed"

    def _sync_analyze(self, image_path):
        """
        [同步内部函数] 图片压缩 + 调用 API
        """
        try:
            # 1. 安全地打开图片 (自动关闭文件句柄)
            with Image.open(image_path) as img:
                # 2. 图片预处理：压缩尺寸
                # 如果图片太大，Gemini 处理会慢。限制最大边长为 1024px
                img.thumbnail((1024, 1024))
                
                # 3. 构建 Prompt
                prompt = (
                    "Role: Professional Crypto Chart Pattern Analyst.\n"
                    "Task: Analyze this Solana memecoin chart (M1/M5).\n"
                    "Identify:\n"
                    "- Trend: Uptrend/Downtrend/Consolidation\n"
                    "- Volume: Any unusual buying spikes?\n"
                    "- Pattern: Sniper Loading (good), Rug Pull (bad), Parabolic (fomo)\n"
                    "- Risk: Organic or Bot manipulation?\n"
                    "\n"
                    "Constraint: Answer in 1 short sentence. Be decisive."
                    "Example: 'Bullish consolidation with organic buy volume, looks like accumulation.'"
                )

                # 4. 配置安全设置 (防止 AI 因为'金融建议'或'敏感内容'拒答)
                safety_settings = {
                    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
                }

                # 5. 发送请求
                response = self.model.generate_content(
                    [prompt, img],
                    safety_settings=safety_settings
                )
                
                return response.text.strip()

        except Exception as e:
            # 捕获具体的 API 错误信息
            error_msg = str(e)
            if "429" in error_msg:
                logger.warning("Gemini 限流 (429), 请稍后")
                return "API Rate Limit Hit"
            logger.error(f"Gemini API 请求异常: {e}")
            return "Error during analysis"

# 单例封装
eye = VisionEye()

async def analyze_chart(image_path):
    return await eye.analyze_chart(image_path)