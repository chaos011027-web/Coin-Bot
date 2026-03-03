import os
import logging
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger("ImageGen")

# ✅ 请在这里替换成你的专属账号
TG_BOT_ID = "@Hunter9527_bot"
X_HANDLE = "@OnchainJaeger"

def generate_milestone_image(symbol: str, mcap: float, multiplier: int, ca: str) -> str:
    """生成带专属背景的里程碑替换图"""
    try:
        os.makedirs("data/milestones", exist_ok=True)
        output_path = os.path.join("data/milestones", f"{symbol}_{multiplier}X.jpg")
        
        # 你的专属背景图路径
        bg_path = "data/my_bg.jpg" 

        # 1. 加载背景图，如果没有就用深灰色兜底
        if os.path.exists(bg_path):
            base_img = Image.open(bg_path).convert("RGBA")
            base_img = base_img.resize((1024, 768), Image.LANCZOS)
            # 加一层黑灰色半透明遮罩，保证文字能看清
            overlay = Image.new('RGBA', base_img.size, (0, 0, 0, 140))
            base_img = Image.alpha_composite(base_img, overlay)
        else:
            base_img = Image.new('RGBA', (1024, 768), (25, 25, 30, 255))

        draw = ImageDraw.Draw(base_img)
        width, height = base_img.size

        # 2. 加载字体 (系统兜底字体，建议去下载个粗体 arialbd.ttf 放到项目根目录效果最好)
        try:
            font_huge = ImageFont.truetype("arialbd.ttf", 220)
            font_large = ImageFont.truetype("arialbd.ttf", 100)
            font_small = ImageFont.truetype("arial.ttf", 36)
        except:
            font_huge = font_large = font_small = ImageFont.load_default()

        def draw_centered(text, font, y_pos, fill):
            bbox = draw.textbbox((0, 0), text, font=font)
            x_pos = (width - (bbox[2] - bbox[0])) / 2
            draw.text((x_pos, y_pos), text, font=font, fill=fill)

        # 3. 绘制元素 (排版完全仿照你提供的图片风格)
        draw_centered(f"${symbol.upper()}", font_large, 120, fill=(255, 255, 255))
        
        # 巨大的倍数，绿色
        draw_centered(f"{multiplier}X", font_huge, 260, fill=(0, 255, 100))
        
        mcap_str = f"${mcap/1000:.1f}K" if mcap < 1000000 else f"${mcap/1000000:.2f}M"
        draw_centered(f"Current Mcap: {mcap_str}", font_small, 540, fill=(220, 220, 220))

        # 底部联系方式
        footer_text = f"TG: {TG_BOT_ID}   |   X: {X_HANDLE}"
        draw_centered(footer_text, font_small, height - 80, fill=(150, 150, 150))

        final_img = base_img.convert("RGB")
        final_img.save(output_path, quality=95)
        logger.info(f"🎨 {multiplier}X 战报图已生成: {output_path}")
        
        return output_path

    except Exception as e:
        logger.error(f"❌ 制图失败: {e}")
        return ""