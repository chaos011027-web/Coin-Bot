import logging
from typing import Any, Dict

logger = logging.getLogger("FeatureEngine")


def _get_float(d: dict, key: str, default=0.0) -> float:
    try:
        if not isinstance(d, dict):
            return default
        v = d.get(key, default)
        if v is None or v == "":
            return default
        if isinstance(v, str):
            s = v.replace(",", "").strip()
            if s.endswith("%"):
                s = s[:-1].strip()
            if not s:
                return default
            return float(s)
        return float(v)
    except Exception:
        return default


def _extract_smart_count(analytics: dict) -> float:
    """
    兼容两种格式：
    1) analytics["gmgn_smart"]
    2) analytics["raw_data"]["smart"]
    """
    if not isinstance(analytics, dict):
        return 0.0

    direct = _get_float(analytics, "gmgn_smart", 0.0)
    if direct > 0:
        return direct

    raw = analytics.get("raw_data") or {}
    if isinstance(raw, dict):
        return _get_float(raw, "smart", 0.0)

    return 0.0


def _extract_top10_ratio(current_data: dict, analytics: dict) -> float:
    """
    优先级：
    1) analytics["top10_ratio"]
    2) current_data["top10_ratio"]
    3) analytics["gmgn_top10_ratio"]（兼容未来扩展）
    """
    for source in (analytics, current_data):
        if isinstance(source, dict):
            val = _get_float(source, "top10_ratio", None)
            if val is not None:
                return val

    if isinstance(analytics, dict):
        val = _get_float(analytics, "gmgn_top10_ratio", None)
        if val is not None:
            return val

    return 0.0


def _extract_volume_h24(current_data: dict) -> float:
    vol = _get_float(current_data, "volume_h24", 0.0)
    if vol > 0:
        return vol

    if isinstance(current_data, dict):
        volume = current_data.get("volume") or {}
        if isinstance(volume, dict):
            return _get_float(volume, "h24", 0.0)

    return 0.0


def _extract_liquidity(current_data: dict) -> float:
    liq = _get_float(current_data, "liquidity_usd", 0.0)
    if liq > 0:
        return liq

    if isinstance(current_data, dict):
        liquidity = current_data.get("liquidity") or {}
        if isinstance(liquidity, dict):
            return _get_float(liquidity, "usd", 0.0)

    return 0.0


def _extract_mcap(current_data: dict) -> float:
    for key in ("cap_usd", "mcap", "fdv", "marketCap"):
        val = _get_float(current_data, key, 0.0)
        if val > 0:
            return val
    return 0.0


def _extract_buys_24h(current_data: dict) -> float:
    buys = _get_float(current_data, "buys_24h", 0.0)
    if buys > 0:
        return buys

    if isinstance(current_data, dict):
        txns = current_data.get("txns") or {}
        if isinstance(txns, dict):
            h24 = txns.get("h24") or {}
            if isinstance(h24, dict):
                return _get_float(h24, "buys", 0.0)

    return 0.0


def _extract_chg_5m(current_data: dict) -> float:
    chg = _get_float(current_data, "chg_5m", None)
    if chg is not None:
        return chg

    if isinstance(current_data, dict):
        price_change = current_data.get("priceChange") or {}
        if isinstance(price_change, dict):
            chg2 = _get_float(price_change, "m5", None)
            if chg2 is not None:
                return chg2

    return 0.0


def calculate_ml_features(current_data: dict, analytics: dict, prev_snapshot: dict = None) -> dict:
    """
    计算高阶衍生特征（兼容 token_data / raw_market / GMGN raw_data）
    输出字段保持不变：
    - maker_vol_ratio
    - overhang_ratio
    - smart_money_delta
    - breakout_vol_ratio
    """
    features: Dict[str, Any] = {}
    current_data = current_data or {}
    analytics = analytics or {}
    prev_snapshot = prev_snapshot or {}

    liq = _extract_liquidity(current_data)
    if liq <= 0:
        liq = 1.0  # 防除0

    mcap = _extract_mcap(current_data)
    if mcap <= 0:
        mcap = 1.0  # 防除0

    vol_h24 = _extract_volume_h24(current_data)
    buys = _extract_buys_24h(current_data)

    current_smart = _extract_smart_count(analytics)
    top10_pct = _extract_top10_ratio(current_data, analytics)

    # 1. 真实交易者密度（防刷量）
    # 每千元成交额对应的买单数量，越低越可疑
    if vol_h24 > 0:
        features["maker_vol_ratio"] = buys / vol_h24 * 1000.0
    else:
        features["maker_vol_ratio"] = 0.0

    # 2. 悬空筹码比（Top10 持仓价值 / 资金池）
    top10_value = mcap * (top10_pct / 100.0)
    features["overhang_ratio"] = top10_value / liq if liq > 0 else 99.0

    # 3. 聪明钱 Delta（时间序列变化）
    prev_smart = _get_float(prev_snapshot, "smart_money", 0.0)
    features["smart_money_delta"] = int(current_smart - prev_smart)

    # 4. 突破量能比初筛（简化特征）
    chg_5m = _extract_chg_5m(current_data)
    if chg_5m > 15 and vol_h24 > 0:
        features["breakout_vol_ratio"] = 1.0
    else:
        features["breakout_vol_ratio"] = 0.0

    return features