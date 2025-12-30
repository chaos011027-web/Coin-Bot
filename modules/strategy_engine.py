from typing import Dict, Any, Tuple

# 策略配置中心
STRATEGY_CONFIGS = {
    "BUNDLE_CTRL": {
        "name": "控盘博弈",
        "emoji": "🎭",
        "tp_targets": [1.20],      # +20%
        "sl_threshold": 0.90,      # -10%
        "pos_size": "3%"
    },
    "SNIPER_PLAY": {
        "name": "狙击盘",
        "emoji": "🎯",
        "tp_targets": [1.25, 1.50], # +25%, +50%
        "sl_threshold": 0.88,       # -12%
        "pos_size": "5%"
    },
    "SMART_TREND": {
        "name": "聪明钱趋势",
        "emoji": "🚀",
        "tp_targets": [1.30, 1.80], # +30%, +80%
        "sl_threshold": 0.85,       # -15%
        "pos_size": "8%"
    },
    "MIXED": {
        "name": "混合博弈",
        "emoji": "⚖️",
        "tp_targets": [1.30],      # +30%
        "sl_threshold": 0.85,      # -15%
        "pos_size": "5%"
    }
}

def _safe_int(val) -> int:
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return 0

def detect_strategy(td: dict) -> Tuple[str, Dict[str, Any]]:
    """
    返回: (策略ID, 策略配置字典)
    """
    # 提取并清洗数据
    bundle = _safe_int(td.get("gmgn_bundle") or 0)
    sniper = _safe_int(td.get("gmgn_sniper") or 0)
    
    # 解析 gmgn_tags 列表中的数值 (如果数据源是列表)
    smart = 0
    tags = td.get("gmgn_tags", [])
    if isinstance(tags, list):
        import re
        tags_str = " ".join(tags)
        match = re.search(r"(?:Smart|聪明钱).*?(\d+)", tags_str)
        if match:
            smart = int(match.group(1))
    
    # 判定逻辑
    strategy_id = "MIXED"
    if bundle >= 150:
        strategy_id = "BUNDLE_CTRL"
    elif sniper >= 60:
        strategy_id = "SNIPER_PLAY"
    elif smart >= 15: # 稍微降低门槛
        strategy_id = "SMART_TREND"

    return strategy_id, STRATEGY_CONFIGS[strategy_id]

def render_strategy_plan(strategy_id: str) -> str:
    cfg = STRATEGY_CONFIGS.get(strategy_id, STRATEGY_CONFIGS["MIXED"])
    
    tps = cfg["tp_targets"]
    tp_text = "\n".join([f"- TP{i+1}: +{int((tp-1)*100)}%" for i, tp in enumerate(tps)])
    sl_text = f"- SL：-{int((1-cfg['sl_threshold'])*100)}%"
    
    return (
        f"{cfg['emoji']} <b>策略类型：{cfg['name']}</b>\n"
        f"- 建议仓位: ≤ {cfg['pos_size']}\n"
        f"{tp_text}\n"
        f"{sl_text}\n"
    )