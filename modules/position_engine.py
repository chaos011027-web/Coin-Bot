from modules.stats_engine import stats_engine

# 最小有效样本量 (少于这个数，胜率再高也不信)
MIN_SAMPLE_SIZE = 5 

def calc_position_size(strategy: str) -> dict:
    """
    智能仓位建议系统 V2
    逻辑：基础仓位 + 胜率加成 + 样本置信度校正
    """
    # 1. 获取原始数据 (不再解析字符串)
    stats = stats_engine.get_raw_stats(strategy)
    win_rate = stats["win_rate"]
    total_trades = stats["total"]
    is_new = stats["is_new"]

    # ==========================
    # 场景 A: 新策略 / 冷启动
    # ==========================
    if is_new or total_trades < MIN_SAMPLE_SIZE:
        return {
            "size": "1%", 
            "level": "🧪 测试",
            "reason": f"样本不足({total_trades}单)，强制小仓验证"
        }

    # ==========================
    # 场景 B: 胜率阶梯 (已有足够样本)
    # ==========================
    
    # 1. 王牌策略 (胜率 > 70% 且 样本 > 10)
    # 只有样本量足够大，才允许重仓
    if win_rate >= 70:
        if total_trades >= 10:
            return {
                "size": "8-10%",
                "level": "🔥 主攻",
                "reason": f"胜率{win_rate}%且样本充足，允许重拳出击"
            }
        else:
            # 胜率虽高但样本只有 5-9 个，稍微降一点
            return {
                "size": "5%",
                "level": "⭐ 激进",
                "reason": f"胜率{win_rate}%但样本较少，标准仓位"
            }

    # 2. 稳健策略 (55% - 70%)
    if win_rate >= 55:
        return {
            "size": "3-5%",
            "level": "⚖️ 标准",
            "reason": f"胜率{win_rate}%表现稳定，常规参与"
        }

    # 3. 鸡肋策略 (40% - 55%)
    if win_rate >= 40:
        return {
            "size": "1-2%",
            "level": "🛡 防守",
            "reason": f"胜率{win_rate}%偏低，仅博取高盈亏比"
        }

    # 4. 垃圾策略 (< 40%)
    return {
        "size": "0%",
        "level": "❌ 熔断",
        "reason": f"胜率{win_rate}%过低，触发策略熔断"
    }