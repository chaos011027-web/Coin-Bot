import aiohttp
import logging
from config.settings import THRESHOLDS

logger = logging.getLogger("Gatekeeper")

# RugCheck API 地址
RUGCHECK_API = "https://api.rugcheck.xyz/v1/tokens/{mint}/report"

async def check_safety(ca: str):
    """
    第一道防线：快速检测合约安全性
    返回: (is_safe: bool, reason: str)
    """
    # 1. 如果配置了跳过安检 (调试用)
    # if THRESHOLDS.get('SKIP_GATEKEEPER', False):
    #     return True, "Debug Mode Skipped"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(RUGCHECK_API.format(mint=ca), timeout=5) as response:
                
                # 如果 RugCheck 还没收录这个币 (太新了)，通常意味着它可能刚出炉
                # 策略：可以选择“放行”让 AI 进一步看，或者“拦截”求稳。
                # 这里我们选择：如果 404，暂时放行 (Trust but Verify)
                if response.status == 404:
                    return True, "Too new (No Report)"
                
                if response.status != 200:
                    logger.warning(f"RugCheck API 异常: {response.status}")
                    return True, "API Error (Fail Open)"

                data = await response.json()
                
                # === 核心硬指标检查 ===
                
                # 1. 检查 Mint Authority (铸币权)
                # 如果铸币权还在，Dev 可以随时印钞砸盘 -> 极度危险
                token_meta = data.get('tokenMeta', {})
                if token_meta.get('mutable', False): 
                    # Mutable metadata 还可以接受，但 Mint Authority 必须丢弃
                    pass 

                # RugCheck 的风险打分 (Score 越高越危险)
                # 这里的 score 通常是 0-10000 还是类似机制，我们需要看 dangerous 列表
                risks = data.get('risks', [])
                score = data.get('score', 0)
                
                # 2. 致命风险清单 (一票否决)
                fatal_risks = [
                    "Mint Authority is enabled",  # 能无限印钞
                    "Freeze Authority is enabled", # 能冻结你的币
                    "Top 10 holders own more than", # 筹码过于集中
                    "Liquidity is not locked", # 池子没锁 (虽然很多新盘刚开始都没锁)
                ]

                detected_fatal = []
                for risk in risks:
                    risk_name = risk.get('name', '')
                    # 检查是否包含致命关键词
                    if "Mint Authority" in risk_name:
                        return False, f"❌ 铸币权未丢弃 ({risk_name})"
                    if "Freeze Authority" in risk_name:
                        return False, f"❌ 存在冻结权限 ({risk_name})"
                
                # 3. 评分拦截 (阈值可在 settings.py 调整)
                # RugCheck 评分 > 5000 通常被认为是 "Danger"
                MAX_RISK_SCORE = THRESHOLDS.get('MAX_RISK_SCORE', 5000) 
                if score > MAX_RISK_SCORE:
                    return False, f"❌ 风险评分过高: {score}"

                # 4. 流动性检查 (可选)
                # 有些盘子刚开没有流动性，这步看情况开启
                # markets = data.get('markets', [])
                # if not markets:
                #    return False, "❌ 无流动性池"

                logger.info(f"✅ {ca} 通过安检 (Score: {score})")
                return True, "Pass"

    except Exception as e:
        logger.error(f"Gatekeeper 检测失败: {e}")
        # 出错时是放行还是拦截？建议放行，让后面更强的 AI 去判断
        return True, "Check Failed (Fail Open)"