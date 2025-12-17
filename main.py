import asyncio
import logging
import sys
import signal
from modules import (
    listener, 
    commander, 
    gatekeeper, 
    data_fetcher, 
    insightx, 
    vision, 
    brain,
    notifier  # ✅ [新增] 导入通知模块
)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("hunter.log", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("MAIN")

# --- 辅助流水线 ---

async def vision_pipeline(ca: str):
    """子任务：截图 -> 视觉分析"""
    img_path = await data_fetcher.get_chart_screenshot(ca)
    if not img_path:
        return "截图失败，跳过视觉分析"
    
    analysis = await vision.analyze_chart(img_path)
    return analysis

async def process_new_token(ca: str):
    """【核心流水线】处理单个代币"""
    
    # 1. 全局开关检查
    if commander.state.is_paused:
        logger.info(f"⏸ 系统暂停中，忽略: {ca}")
        return

    # 2. 快速安检
    is_safe, reason = await gatekeeper.check_safety(ca)
    if not is_safe:
        logger.info(f"🛡 熔断拦截 [{ca}]: {reason}")
        return

    logger.info(f"⚔️ 开始分析: {ca} [模式: {commander.state.current_mode.value}]")

    # 3. 并行数据采集
    try:
        results = await asyncio.gather(
            data_fetcher.get_market_data(ca),
            insightx.fetch_data(ca),
            vision_pipeline(ca),
            return_exceptions=True
        )
        market_data, insight_data, vision_analysis = results

        # 容错处理
        if isinstance(market_data, Exception) or not market_data:
            market_data = {}
        if isinstance(insight_data, Exception): 
            insight_data = {}
        if isinstance(vision_analysis, Exception):
            vision_analysis = "视觉模块故障"

        if not market_data.get("symbol"):
            logger.warning(f"⚠️ 无效代币或数据缺失: {ca}")
            return

    except Exception as e:
        logger.error(f"❌ 数据流异常: {e}")
        return

    # 4. 大脑决策
    logger.info(f"🧠 DeepSeek 正在思考...")
    decision = await brain.analyze(
        market_data, 
        vision_analysis, 
        insight_data, 
        mode=commander.state.current_mode.value
    )

    # 5. 结果评估
    threshold_map = {"aggressive": 50, "balanced": 70, "conservative": 85}
    threshold = threshold_map.get(commander.state.current_mode.value, 70)
    score = decision.get("score", 0)

    logger.info(f"🎯 最终评分: {score}/{threshold} | 动作: {decision.get('action')}")

    # 6. 推送通知 (✅ 改为调用 notifier 模块)
    if score >= threshold:
        await notifier.notify_user(ca, market_data, vision_analysis, decision)

# --- 启动逻辑 ---

async def cleanup():
    """退出清理"""
    logger.info("🧹 正在清理资源...")
    try:
        if hasattr(data_fetcher.fetcher, 'page') and data_fetcher.fetcher.page:
            data_fetcher.fetcher.page.quit()
    except:
        pass

async def main():
    print(r"""
   _____       __                  __  __            __           
  / ___/____  / /___ _____  ____ _/ / / /_  ______  / /____  _____
  \__ \/ __ \/ / __ `/ __ \/ __ `/ /_/ / / / / __ \/ __/ _ \/ ___/
 ___/ / /_/ / / /_/ / / / / /_/ / __  / /_/ / / / / /_/  __/ /    
/____/\____/_/\__,_/_/ /_/\__,_/_/ /_/\__,_/_/ /_/\__/\___/_/     
                                                      V3.0 Online
    """)
    logger.info("🚀 系统初始化中...")

    # 启动后台任务
    commander_task = asyncio.create_task(commander.start_commander())

    logger.info("👂 启动监听进程...")
    try:
        await listener.start(callback_func=process_new_token)
    except asyncio.CancelledError:
        logger.info("🛑 任务取消")
    except Exception as e:
        logger.error(f"🛑 严重错误: {e}")
    finally:
        await cleanup()

if __name__ == "__main__":
    try:
        if sys.platform.startswith('win'):
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 强制退出")