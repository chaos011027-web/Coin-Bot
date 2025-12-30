def get_risk_level(win_rate: float, r_ratio: float) -> dict:
    """
    返回风险等级 + 颜色
    """
    if win_rate >= 60 and r_ratio >= 0.5:
        return {"level": "低风险", "color": "🟢"}
    if win_rate >= 45:
        return {"level": "中风险", "color": "🟡"}
    return {"level": "高风险", "color": "🔴"}
