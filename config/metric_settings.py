import os
from typing import Any


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw in (None, ""):
        return float(default)
    try:
        return float(str(raw).strip())
    except Exception:
        return float(default)


def _env_str(name: str, default: str) -> str:
    raw = os.getenv(name)
    return str(raw).strip() if raw not in (None, "") else default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw in (None, ""):
        return bool(default)
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}


CANONICAL_METRIC_PIPELINE = {
    "top10_conflict_abs_pct": _env_float("TOP10_CONFLICT_ABS_PCT", 8.0),
    "gmgn_unconfirmed_high_pct": _env_float("GMGN_UNCONFIRMED_HIGH_PCT", 85.0),
    "gmgn_confidence": _env_float("GMGN_TOP10_CONFIDENCE", 0.58),
    "bitquery_confidence": _env_float("BITQUERY_TOP10_CONFIDENCE", 0.92),
    "bitquery_fallback_confidence": _env_float("BITQUERY_FALLBACK_TOP10_CONFIDENCE", 0.62),
    "legacy_top10_confidence": _env_float("LEGACY_TOP10_CONFIDENCE", 0.40),
    "dex_pair_confidence": _env_float("DEX_PAIR_LIQ_CONFIDENCE", 0.90),
    "birdeye_exit_confidence": _env_float("BIRDEYE_EXIT_LIQ_CONFIDENCE", 0.82),
    "gmgn_liquidity_confidence": _env_float("GMGN_LIQ_CONFIDENCE", 0.46),
    "legacy_liquidity_confidence": _env_float("LEGACY_LIQ_CONFIDENCE", 0.40),
    "liquidity_conflict_ratio": _env_float("LIQUIDITY_CONFLICT_RATIO", 1.80),
    "top10_conflict_strategy": _env_str("TOP10_CONFLICT_STRATEGY", "conservative_max"),
    "decision_liquidity_field": _env_str("DECISION_LIQUIDITY_FIELD", "exit_liquidity_usd"),
    "decision_liquidity_strict": _env_bool("DECISION_LIQUIDITY_STRICT", True),
    "strict_enter_block_verdict": _env_str("STRICT_ENTER_BLOCK_VERDICT", "PROBE"),
    "bitquery_supply_fallback_multiplier": _env_float("BITQUERY_SUPPLY_FALLBACK_MULTIPLIER", 2.5),
    "action_enter_score_min": _env_float("ACTION_ENTER_SCORE_MIN", 80.0),
    "action_probe_score_min": _env_float("ACTION_PROBE_SCORE_MIN", 65.0),
    "action_watch_score_min": _env_float("ACTION_WATCH_SCORE_MIN", 50.0),
    "action_exit_score_max_when_entered": _env_float("ACTION_EXIT_SCORE_MAX_WHEN_ENTERED", 35.0),
}


CANONICAL_METRIC_THRESHOLDS = {
    "top10_green_max_pct": _env_float("TOP10_GREEN_MAX_PCT", 15.0),
    "top10_warn_pct": _env_float("TOP10_WARN_PCT", 30.0),
    "top10_danger_pct": _env_float("TOP10_DANGER_PCT", 50.0),
    "top10_fatal_pct": _env_float("TOP10_FATAL_PCT", 60.0),
    "liquidity_low_usd": _env_float("LIQUIDITY_LOW_USD", 10000.0),
    "liquidity_warn_usd": _env_float("LIQUIDITY_WARN_USD", 5000.0),
    "liquidity_danger_usd": _env_float("LIQUIDITY_DANGER_USD", 2000.0),
    "liquidity_fatal_usd": _env_float("LIQUIDITY_FATAL_USD", 800.0),
    "liquidity_ratio_good": _env_float("LIQUIDITY_RATIO_GOOD", 0.15),
    "liquidity_ratio_warn": _env_float("LIQUIDITY_RATIO_WARN", 0.05),
    "liquidity_ratio_fatal": _env_float("LIQUIDITY_RATIO_FATAL", 0.01),
}


def metric_setting(name: str, default: Any = None) -> Any:
    return CANONICAL_METRIC_PIPELINE.get(name, default)


def metric_threshold(name: str, default: Any = None) -> Any:
    return CANONICAL_METRIC_THRESHOLDS.get(name, default)
