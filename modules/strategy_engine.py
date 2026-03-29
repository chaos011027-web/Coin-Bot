import os
import json
import logging
from copy import deepcopy
from typing import Any, Dict, List, Tuple

from config.metric_settings import CANONICAL_METRIC_THRESHOLDS
from modules.canonical_metrics import get_canonical_top10_pct, get_decision_liquidity_usd

try:
    from modules.score_engine import calc_score_breakdown
except Exception:
    from score_engine import calc_score_breakdown

logger = logging.getLogger("StrategyEngine")

DEFAULT_STRATEGY_PARAMS: Dict[str, Any] = {
    "gates": {
        # 0~100 分制（与 score_engine 对齐）
        "smart_trend_min_score": 78,
        "sniper_play_min_score": 66,
        "mixed_min_score": 48,
        # 结构阈值
        "healthy_top10_max": float(CANONICAL_METRIC_THRESHOLDS.get("top10_green_max_pct", 15.0)),
        "warn_top10_max": float(CANONICAL_METRIC_THRESHOLDS.get("top10_warn_pct", 30.0)),
        "danger_top10_max": float(CANONICAL_METRIC_THRESHOLDS.get("top10_danger_pct", 50.0)),
        "fatal_top10_min": float(CANONICAL_METRIC_THRESHOLDS.get("top10_fatal_pct", 60.0)),
        "bundle_warn_min": 35.0,
        "bundle_danger_min": 70.0,
        "bundle_fatal_min": 120.0,
        "sniper_warn_min": 40.0,
        "sniper_danger_min": 90.0,
        "rat_fatal_min": 1.0,
        "dev_warn_min": 8.0,
        # 流动性 / 年龄 / 动能
        "min_liq_for_trend": float(CANONICAL_METRIC_THRESHOLDS.get("liquidity_low_usd", 10000.0)),
        "min_liq_for_sniper": 8000.0,
        "low_liq_warn": float(CANONICAL_METRIC_THRESHOLDS.get("liquidity_warn_usd", 5000.0)),
        "fatal_liq_below": float(CANONICAL_METRIC_THRESHOLDS.get("liquidity_fatal_usd", 800.0)),
        "early_age_max_min": 180.0,
        "fresh_age_max_min": 45.0,
        "momentum_5m_for_trend": 8.0,
        "momentum_1h_for_trend": 12.0,
        "momentum_5m_for_sniper": 5.0,
        "dynamic_boost_min_score": 88.0,
        "dynamic_clean_top10_max": 18.0,
        "dynamic_clean_bundle_max": 20.0,
        "dynamic_fresh_age_max_min": 15.0,
        "dynamic_dirty_top10_min": 45.0,
        "dynamic_low_liq_threshold": 12000.0,
        "dump_24h_fatal": -65.0,
        "smart_min_for_trend": 2.0,
        "smart_min_for_sniper": 1.0,
        "kol_min_for_trend": 1.0,
    },
    "strategy_configs": {
        "SMART_TREND": {
            "tp_targets": [1.30, 1.60, 2.00],
            "sl_pct": 0.12,
            "alloc_pct": 0.18,
            "paper_alloc_sol": 0.18,
        },
        "SNIPER_PLAY": {
            "tp_targets": [1.20, 1.45, 1.80],
            "sl_pct": 0.10,
            "alloc_pct": 0.12,
            "paper_alloc_sol": 0.12,
        },
        "BUNDLE_CTRL": {
            "tp_targets": [1.18, 1.35, 1.60],
            "sl_pct": 0.09,
            "alloc_pct": 0.06,
            "paper_alloc_sol": 0.06,
        },
        "MIXED": {
            "tp_targets": [1.22, 1.45, 1.75],
            "sl_pct": 0.10,
            "alloc_pct": 0.08,
            "paper_alloc_sol": 0.08,
        },
    },
}


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        if isinstance(v, (int, float)):
            return float(v)
        s = str(v).strip().replace(",", "")
        if s.endswith("%"):
            s = s[:-1].strip()
        if not s:
            return default
        return float(s)
    except Exception:
        return default


def _safe_pct(v: Any, default: float = 0.0, ratio_if_le_one: bool = False) -> float:
    x = _safe_float(v, default)
    if ratio_if_le_one and 0 < x <= 1:
        return x * 100.0
    return x


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = deepcopy(v)
    return out


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _strategy_alias(label: str) -> str:
    label = str(label or "").strip().upper()
    alias = {
        "STRONG_BULL": "SMART_TREND",
        "BULL": "SNIPER_PLAY",
        "WATCH": "MIXED",
        "PASS": "BUNDLE_CTRL",
        "AVOID": "BUNDLE_CTRL",
        "DEFAULT": "MIXED",
    }
    return alias.get(label, label)


def _normalize_external_params(raw: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}

    norm: Dict[str, Any] = {}

    if "gates" in raw and isinstance(raw["gates"], dict):
        norm["gates"] = raw["gates"]

    if "strategy_configs" in raw and isinstance(raw["strategy_configs"], dict):
        norm["strategy_configs"] = {
            _strategy_alias(k): v for k, v in raw["strategy_configs"].items() if isinstance(v, dict)
        }

    # 兼容把策略直接放在顶层的情况
    direct_cfg = {}
    for key in ["SMART_TREND", "SNIPER_PLAY", "BUNDLE_CTRL", "MIXED", "STRONG_BULL", "BULL", "AVOID"]:
        if isinstance(raw.get(key), dict):
            direct_cfg[_strategy_alias(key)] = raw[key]
    if direct_cfg:
        norm.setdefault("strategy_configs", {})
        norm["strategy_configs"].update(direct_cfg)

    # 兼容 strategy_best_params.json 结构
    score_thresholds = raw.get("score_thresholds") or {}
    if isinstance(score_thresholds, dict):
        gates = norm.setdefault("gates", {})
        strong = score_thresholds.get("strong_bull_min")
        bull = score_thresholds.get("bull_min")
        mixed = score_thresholds.get("mixed_min")
        # 既兼容 0~10，也兼容 0~100
        if strong is not None:
            strong_v = _safe_float(strong, 78.0)
            gates["smart_trend_min_score"] = strong_v * 10 if 0 < strong_v <= 10 else strong_v
        if bull is not None:
            bull_v = _safe_float(bull, 66.0)
            gates["sniper_play_min_score"] = bull_v * 10 if 0 < bull_v <= 10 else bull_v
        if mixed is not None:
            mixed_v = _safe_float(mixed, 48.0)
            gates["mixed_min_score"] = mixed_v * 10 if 0 < mixed_v <= 10 else mixed_v

    filters = raw.get("filters") or {}
    if isinstance(filters, dict):
        gates = norm.setdefault("gates", {})
        if "min_liquidity_usd" in filters:
            gates["min_liq_for_trend"] = _safe_float(filters.get("min_liquidity_usd"), 12000.0)
            gates["min_liq_for_sniper"] = max(3000.0, gates["min_liq_for_trend"] * 0.66)
        if "max_top10_pct" in filters:
            max_top = _safe_pct(filters.get("max_top10_pct"), 35.0, ratio_if_le_one=True)
            gates["warn_top10_max"] = max_top
            gates["danger_top10_max"] = max(max_top, 50.0)
        if "max_deployer_pct" in filters:
            gates["dev_warn_min"] = _safe_pct(filters.get("max_deployer_pct"), 8.0, ratio_if_le_one=True)

    trade_plan = raw.get("trade_plan") or {}
    if isinstance(trade_plan, dict):
        alloc_map = trade_plan.get("alloc_map") or {}
        sl_map = trade_plan.get("sl_map") or {}
        tp_map = trade_plan.get("tp_map") or {}
        if any(isinstance(x, dict) for x in [alloc_map, sl_map, tp_map]):
            norm.setdefault("strategy_configs", {})
            for src_key in set(list(alloc_map.keys()) + list(sl_map.keys()) + list(tp_map.keys())):
                sid = _strategy_alias(src_key)
                cfg = norm["strategy_configs"].setdefault(sid, {})
                if src_key in alloc_map:
                    cfg["alloc_pct"] = _safe_float(alloc_map.get(src_key), cfg.get("alloc_pct", 0.08))
                    cfg["paper_alloc_sol"] = cfg["alloc_pct"]
                if src_key in sl_map:
                    cfg["sl_pct"] = _safe_float(sl_map.get(src_key), cfg.get("sl_pct", 0.10))
                if src_key in tp_map and isinstance(tp_map.get(src_key), list):
                    cfg["tp_targets"] = [_safe_float(x, 0.0) for x in tp_map.get(src_key) if _safe_float(x, 0.0) > 1.0]
                    if not cfg["tp_targets"]:
                        raw_tp = [_safe_float(x, 0.0) for x in tp_map.get(src_key) if _safe_float(x, 0.0) > 0]
                        cfg["tp_targets"] = [round(1.0 + x, 4) for x in raw_tp]

    return norm


def load_strategy_params(path: str = "models/strategy_best_params.json") -> Dict[str, Any]:
    params = deepcopy(DEFAULT_STRATEGY_PARAMS)
    if not os.path.exists(path):
        logger.info("ℹ️ 未检测到 strategy_best_params.json，策略引擎使用默认参数。")
        return params

    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f) or {}
        normalized = _normalize_external_params(raw)
        params = _deep_merge(params, normalized)
        logger.info("✅ 已加载策略参数文件: %s", path)
        return params
    except Exception as e:
        logger.exception("❌ 加载 strategy_best_params.json 失败，回退默认参数: %s", e)
        return params


PARAMS = load_strategy_params()


def reload_strategy_params(path: str = "models/strategy_best_params.json") -> Dict[str, Any]:
    global PARAMS
    PARAMS = load_strategy_params(path)
    return PARAMS


def _build_gmgn_tags_from_flat(token_data: Dict[str, Any]) -> List[str]:
    tags: List[str] = []
    mapping = [
        ("gmgn_smart", "🧠 聪明钱"),
        ("gmgn_kol", "📣 KOL"),
        ("gmgn_rat", "🐀 老鼠仓"),
        ("gmgn_sniper", "🔫 狙击手"),
        ("gmgn_bundle", "📦 捆绑"),
        ("gmgn_dev", "👨‍💻 Dev"),
    ]
    for key, label in mapping:
        val = _safe_float(token_data.get(key), 0.0)
        if val > 0:
            if abs(val - int(val)) < 1e-9:
                tags.append(f"{label}({int(val)})")
            else:
                tags.append(f"{label}({val:.2f})")
    return tags


def _prepare_for_score(token_data: Dict[str, Any]) -> Dict[str, Any]:
    td = deepcopy(token_data or {})
    if not td.get("gmgn_tags"):
        td["gmgn_tags"] = _build_gmgn_tags_from_flat(td)

    if not td.get("mcap"):
        td["mcap"] = td.get("cap_usd") or td.get("fdv") or 0
    if not td.get("fdv"):
        td["fdv"] = td.get("cap_usd") or td.get("mcap") or 0

    if td.get("price_change_24h") in (None, ""):
        td["price_change_24h"] = td.get("chg_24h", td.get("h24", 0))
    if td.get("volume_h24") in (None, ""):
        td["volume_h24"] = td.get("volume_24h", td.get("vol_24h", 0))
    return td


def _extract_metrics(token_data: Dict[str, Any]) -> Dict[str, float]:
    return {
        "mcap": _safe_float(token_data.get("cap_usd") or token_data.get("mcap") or token_data.get("fdv"), 0.0),
        "liq": _safe_float(get_decision_liquidity_usd(token_data), 0.0),
        "top10": _safe_pct(get_canonical_top10_pct(token_data), 0.0, ratio_if_le_one=True),
        "age_min": _safe_float(token_data.get("token_age_min"), 0.0),
        "smart": _safe_float(token_data.get("gmgn_smart"), 0.0),
        "kol": _safe_float(token_data.get("gmgn_kol"), 0.0),
        "rat": _safe_float(token_data.get("gmgn_rat"), 0.0),
        "sniper": _safe_float(token_data.get("gmgn_sniper"), 0.0),
        "bundle": _safe_float(token_data.get("gmgn_bundle"), 0.0),
        "dev": _safe_float(token_data.get("gmgn_dev"), 0.0),
        "chg_5m": _safe_float(token_data.get("chg_5m") or token_data.get("price_change_m5") or token_data.get("m5"), 0.0),
        "chg_1h": _safe_float(token_data.get("chg_1h") or token_data.get("price_change_h1") or token_data.get("h1"), 0.0),
        "chg_24h": _safe_float(token_data.get("chg_24h") or token_data.get("price_change_24h") or token_data.get("h24"), 0.0),
        "vol_24h": _safe_float(token_data.get("volume_h24") or token_data.get("volume_24h") or token_data.get("vol_24h"), 0.0),
    }


def _dynamic_adjust_config(
    strategy_id: str,
    base_cfg: Dict[str, Any],
    metrics: Dict[str, float],
    score: float,
    reasons: List[str],
    gates: Dict[str, Any],
) -> Dict[str, Any]:
    cfg = deepcopy(base_cfg)
    alloc = _safe_float(cfg.get("alloc_pct"), 0.08)
    sl_pct = _safe_float(cfg.get("sl_pct"), 0.10)
    tp_targets = [_safe_float(x, 0.0) for x in cfg.get("tp_targets", []) if _safe_float(x, 0.0) > 1.0]
    if not tp_targets:
        tp_targets = [1.20, 1.50, 2.00]

    dynamic_boost_min_score = _safe_float(gates.get("dynamic_boost_min_score", 88.0), 88.0)
    dynamic_clean_top10_max = _safe_pct(gates.get("dynamic_clean_top10_max", 18.0), 18.0, ratio_if_le_one=True)
    dynamic_clean_bundle_max = _safe_float(gates.get("dynamic_clean_bundle_max", 20.0), 20.0)
    dynamic_fresh_age_max_min = _safe_float(gates.get("dynamic_fresh_age_max_min", 15.0), 15.0)
    dynamic_dirty_top10_min = _safe_pct(gates.get("dynamic_dirty_top10_min", 45.0), 45.0, ratio_if_le_one=True)
    dynamic_low_liq_threshold = _safe_float(gates.get("dynamic_low_liq_threshold", 12000.0), 12000.0)

    # 高分但结构干净：略微放大利润空间
    if (
        strategy_id == "SMART_TREND"
        and score >= dynamic_boost_min_score
        and metrics["top10"] <= dynamic_clean_top10_max
        and metrics["bundle"] < dynamic_clean_bundle_max
    ):
        tp_targets = [round(x + 0.05, 2) for x in tp_targets]
        alloc *= 1.08
        reasons.append("高分+结构干净，适度放大利润目标")

    # 新币波动大：同策略下略缩仓
    if 0 < metrics["age_min"] <= dynamic_fresh_age_max_min:
        alloc *= 0.90
        reasons.append("币龄极短，缩小初始仓位")

    # 结构偏脏：缩仓并略收紧止盈
    if (
        metrics["bundle"] >= _safe_float(gates.get("bundle_danger_min", 70.0), 70.0)
        or metrics["top10"] >= dynamic_dirty_top10_min
        or metrics["dev"] >= _safe_float(gates.get("dev_warn_min", 8.0), 8.0)
    ):
        alloc *= 0.75
        tp_targets = [round(max(1.12, x - 0.05), 2) for x in tp_targets]
        reasons.append("结构偏脏，缩仓并下调TP")

    # 流动性一般：再保守一点
    if 0 < metrics["liq"] < dynamic_low_liq_threshold:
        alloc *= 0.85
        reasons.append("流动性一般，进一步缩仓")

    cfg["alloc_pct"] = round(_clamp(alloc, 0.03, 0.25), 4)
    cfg["paper_alloc_sol"] = round(cfg["alloc_pct"], 4)
    cfg["sl_pct"] = round(_clamp(sl_pct, 0.06, 0.15), 4)
    cfg["tp_targets"] = [round(x, 2) for x in tp_targets]
    return cfg


def detect_strategy(token_data: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    params = PARAMS or DEFAULT_STRATEGY_PARAMS
    gates = params.get("gates", {})
    strategy_configs = params.get("strategy_configs", {})

    prepared = _prepare_for_score(token_data)
    score_data = calc_score_breakdown(prepared)
    score = _safe_float(score_data.get("total"), 0.0)
    metrics = _extract_metrics(prepared)

    reasons: List[str] = []

    healthy_structure = (
        metrics["top10"] <= _safe_pct(gates.get("healthy_top10_max", 18.0), 18.0, ratio_if_le_one=True)
        and metrics["bundle"] < _safe_float(gates.get("bundle_warn_min", 35.0), 35.0)
        and metrics["liq"] >= _safe_float(gates.get("min_liq_for_trend", 12000.0), 12000.0)
    )

    fatal = False
    if metrics["rat"] >= _safe_float(gates.get("rat_fatal_min", 1.0), 1.0):
        fatal = True
        reasons.append(f"老鼠仓>{int(metrics['rat'])}")
    if metrics["top10"] >= _safe_pct(gates.get("fatal_top10_min", 60.0), 60.0, ratio_if_le_one=True):
        fatal = True
        reasons.append(f"Top10过高({metrics['top10']:.1f}%)")
    if 0 < metrics["liq"] < _safe_float(gates.get("fatal_liq_below", 800.0), 800.0):
        fatal = True
        reasons.append(f"流动性过低(${int(metrics['liq'])})")
    if metrics["bundle"] >= _safe_float(gates.get("bundle_fatal_min", 120.0), 120.0):
        fatal = True
        reasons.append(f"极端Bundle({int(metrics['bundle'])})")
    if metrics["chg_24h"] <= _safe_float(gates.get("dump_24h_fatal", -65.0), -65.0):
        fatal = True
        reasons.append(f"24h跌幅过大({metrics['chg_24h']:.1f}%)")

    if fatal:
        strategy_id = "BUNDLE_CTRL"
        reasons.append("触发保守风控策略")
    else:
        trend_score_ok = score >= _safe_float(gates.get("smart_trend_min_score", 78.0), 78.0)
        trend_momentum_ok = (
            metrics["chg_1h"] >= _safe_float(gates.get("momentum_1h_for_trend", 12.0), 12.0)
            or metrics["chg_5m"] >= _safe_float(gates.get("momentum_5m_for_trend", 8.0), 8.0)
            or (metrics["liq"] > 0 and metrics["vol_24h"] > metrics["liq"] * 1.5)
        )
        trend_flow_ok = (
            metrics["smart"] >= _safe_float(gates.get("smart_min_for_trend", 2.0), 2.0)
            or (metrics["smart"] >= 1 and metrics["kol"] >= _safe_float(gates.get("kol_min_for_trend", 1.0), 1.0))
        )

        sniper_score_ok = score >= _safe_float(gates.get("sniper_play_min_score", 66.0), 66.0)
        sniper_age_ok = 0 < metrics["age_min"] <= _safe_float(gates.get("early_age_max_min", 180.0), 180.0)
        sniper_momentum_ok = metrics["chg_5m"] >= _safe_float(gates.get("momentum_5m_for_sniper", 5.0), 5.0)
        sniper_flow_ok = (
            metrics["smart"] >= _safe_float(gates.get("smart_min_for_sniper", 1.0), 1.0)
            or metrics["sniper"] >= _safe_float(gates.get("sniper_warn_min", 40.0), 40.0)
        )
        sniper_structure_ok = (
            metrics["top10"] <= _safe_pct(gates.get("warn_top10_max", 35.0), 35.0, ratio_if_le_one=True)
            and metrics["bundle"] < _safe_float(gates.get("bundle_danger_min", 70.0), 70.0)
            and metrics["liq"] >= _safe_float(gates.get("min_liq_for_sniper", 8000.0), 8000.0)
        )

        dirty_structure = (
            metrics["top10"] >= _safe_pct(gates.get("danger_top10_max", 50.0), 50.0, ratio_if_le_one=True)
            or metrics["bundle"] >= _safe_float(gates.get("bundle_danger_min", 70.0), 70.0)
            or metrics["dev"] >= _safe_float(gates.get("dev_warn_min", 8.0), 8.0)
            or (0 < metrics["liq"] < _safe_float(gates.get("min_liq_for_sniper", 8000.0), 8000.0))
        )

        if trend_score_ok and trend_momentum_ok and trend_flow_ok and healthy_structure:
            strategy_id = "SMART_TREND"
            reasons.append("高分+聪明钱/动能/结构同时满足")
        elif sniper_score_ok and sniper_age_ok and sniper_momentum_ok and sniper_flow_ok and sniper_structure_ok:
            strategy_id = "SNIPER_PLAY"
            reasons.append("早期动能型机会，适合快进快出")
        elif dirty_structure or score < _safe_float(gates.get("mixed_min_score", 48.0), 48.0):
            strategy_id = "BUNDLE_CTRL"
            reasons.append("结构偏脏或分数偏低，切保守剧本")
        else:
            strategy_id = "MIXED"
            reasons.append("多空因子混合，按中性剧本处理")

    base_cfg = deepcopy(strategy_configs.get(strategy_id, strategy_configs.get("MIXED", {})))
    config = _dynamic_adjust_config(strategy_id, base_cfg, metrics, score, reasons, gates)

    config.update({
        "score": round(score, 2),
        "summary": score_data.get("summary", ""),
        "breakdown": score_data.get("breakdown", {}),
        "reason": "；".join(reasons),
        "params_source": "models/strategy_best_params.json" if os.path.exists("models/strategy_best_params.json") else "defaults",
        "metrics": {
            "mcap": round(metrics["mcap"], 4),
            "liq": round(metrics["liq"], 4),
            "top10": round(metrics["top10"], 4),
            "smart": round(metrics["smart"], 4),
            "bundle": round(metrics["bundle"], 4),
            "sniper": round(metrics["sniper"], 4),
            "dev": round(metrics["dev"], 4),
            "age_min": round(metrics["age_min"], 4),
            "chg_5m": round(metrics["chg_5m"], 4),
            "chg_1h": round(metrics["chg_1h"], 4),
            "chg_24h": round(metrics["chg_24h"], 4),
        },
    })

    return strategy_id, config


__all__ = ["detect_strategy", "load_strategy_params", "reload_strategy_params", "DEFAULT_STRATEGY_PARAMS"]
