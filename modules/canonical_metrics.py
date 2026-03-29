import logging
from copy import deepcopy
from typing import Any, Dict, List, Optional

from config.metric_settings import CANONICAL_METRIC_PIPELINE, CANONICAL_METRIC_THRESHOLDS

logger = logging.getLogger("CanonicalMetrics")

TOP10_CANONICAL_STAGE = "source_conflict_adjusted"
TOP10_ADJUSTMENT_SEMANTICS = "source_conflict_adjusted_not_entity_adjusted"
TOP10_UNRESOLVED_STAGE = "unresolved"


def _to_float(value: Any, default: Optional[float] = 0.0) -> Optional[float]:
    try:
        if value is None or value == "":
            return default
        if isinstance(value, str):
            text = value.replace(",", "").strip()
            if text.endswith("%"):
                text = text[:-1].strip()
            if not text:
                return default
            return float(text)
        return float(value)
    except Exception:
        return default


def _round_or_none(value: Optional[float], digits: int = 4) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), digits)


def _pct_text(value: Optional[float]) -> Optional[str]:
    if value is None:
        return None
    return f"{float(value):.2f}%"


def _dict_or_empty(value: Any) -> Dict[str, Any]:
    return deepcopy(value) if isinstance(value, dict) else {}


def _gmgn_top10_gate(token_data: Dict[str, Any], analytics: Dict[str, Any]) -> Dict[str, Any]:
    td = token_data or {}
    analytics = analytics or {}

    popup_reason = str(analytics.get("popup_reason") or td.get("gmgn_popup_reason") or "").strip()
    blocked_reason = str(
        analytics.get("blocked_reason")
        or analytics.get("gmgn_page_blocked_reason")
        or td.get("gmgn_blocked_reason")
        or ""
    ).strip()
    strength = str(analytics.get("gmgn_result_strength") or td.get("gmgn_result_strength") or "").strip().lower()

    target_ready = analytics.get("target_ready")
    if target_ready is None and "gmgn_target_ready" in td:
        target_ready = td.get("gmgn_target_ready")

    layout_ready = analytics.get("layout_ready")
    if layout_ready is None and "gmgn_layout_ready" in td:
        layout_ready = td.get("gmgn_layout_ready")

    reasons: List[str] = []
    if popup_reason == "overlay_mask":
        reasons.append("overlay_mask")
    if blocked_reason:
        reasons.append("blocked")
    if strength in {"weak", "thin"}:
        reasons.append(f"strength:{strength}")
    if target_ready is not None and target_ready is not True:
        reasons.append("target_not_ready")
    if layout_ready is not None and layout_ready is not True:
        reasons.append("layout_not_ready")

    return {
        "allowed": not reasons,
        "reason": ",".join(reasons),
    }


def canonical_thresholds() -> Dict[str, float]:
    return dict(CANONICAL_METRIC_THRESHOLDS)


def canonical_pipeline_settings() -> Dict[str, Any]:
    return dict(CANONICAL_METRIC_PIPELINE)


def decision_liquidity_is_strict() -> bool:
    return bool(CANONICAL_METRIC_PIPELINE.get("decision_liquidity_strict", True))


def get_canonical_stage(token_data: Dict[str, Any]) -> str:
    td = token_data or {}
    stage = td.get("canonical_stage")
    if stage not in (None, ""):
        return str(stage)
    meta = td.get("canonical_metadata")
    if isinstance(meta, dict) and meta.get("canonical_stage") not in (None, ""):
        return str(meta.get("canonical_stage"))
    return ""


def get_canonical_metadata(token_data: Dict[str, Any]) -> Dict[str, Any]:
    raw = (token_data or {}).get("canonical_metadata")
    return _dict_or_empty(raw)


def get_canonical_top10_pct(token_data: Dict[str, Any], *, adjusted: bool = True) -> Optional[float]:
    td = token_data or {}
    if adjusted:
        adjusted_val = _to_float(td.get("top10_adjusted_pct"), None)
        if adjusted_val is not None:
            return adjusted_val
    raw_val = _to_float(td.get("top10_raw_pct"), None)
    if raw_val is not None:
        return raw_val
    legacy_val = _to_float(td.get("top10_ratio"), None)
    return legacy_val


def get_confirmed_top10_pct(token_data: Dict[str, Any]) -> Optional[float]:
    return _to_float((token_data or {}).get("top10_adjusted_pct"), None)


def get_pair_liquidity_usd(token_data: Dict[str, Any]) -> float:
    td = token_data or {}
    return float(_to_float(td.get("pair_liquidity_usd"), _to_float(td.get("liquidity_usd"), 0.0)) or 0.0)


def get_decision_liquidity_context(
    token_data: Dict[str, Any],
    *,
    strict: Optional[bool] = None,
) -> Dict[str, Any]:
    td = token_data or {}
    exit_liq = _to_float(td.get("exit_liquidity_usd"), None)
    pair_liq = _to_float(td.get("pair_liquidity_usd"), None)
    legacy_liq = _to_float(td.get("liquidity_usd"), None)
    strict_mode = decision_liquidity_is_strict() if strict is None else bool(strict)

    display_value = 0.0
    display_source = ""
    fallback_source = ""
    used_pair_fallback = False
    used_legacy_fallback = False

    if exit_liq is not None and exit_liq > 0:
        display_value = float(exit_liq)
        display_source = "EXIT_CANONICAL"
    elif pair_liq is not None and pair_liq > 0:
        display_value = float(pair_liq)
        display_source = "PAIR_FALLBACK"
        fallback_source = "pair_liquidity_usd"
        used_pair_fallback = True
    elif legacy_liq is not None and legacy_liq > 0:
        display_value = float(legacy_liq)
        display_source = "LEGACY_FALLBACK"
        fallback_source = "liquidity_usd"
        used_legacy_fallback = True

    market_data_ready = token_data.get("market_data_ready")
    if market_data_ready is None:
        market_data_ready = bool(
            display_value > 0
            or exit_liq is not None
            or pair_liq is not None
            or legacy_liq is not None
        )
    liquidity_data_ready = token_data.get("liquidity_data_ready")
    if liquidity_data_ready is None:
        liquidity_data_ready = display_value > 0
    liquidity_source_error = str(token_data.get("liquidity_source_error") or "")

    formal_enter_liquidity = float(exit_liq) if exit_liq is not None and exit_liq > 0 else 0.0
    formal_enter_ready = formal_enter_liquidity > 0 if strict_mode else display_value > 0

    return {
        "value": display_value,
        "display_liquidity_usd": display_value,
        "display_source": display_source,
        "fallback_source": fallback_source,
        "used_fallback": bool(fallback_source),
        "used_pair_fallback": used_pair_fallback,
        "used_legacy_fallback": used_legacy_fallback,
        "strict_mode": strict_mode,
        "exit_liquidity_usd": float(exit_liq) if exit_liq is not None and exit_liq > 0 else 0.0,
        "pair_liquidity_usd": float(pair_liq) if pair_liq is not None and pair_liq > 0 else 0.0,
        "formal_enter_liquidity_usd": formal_enter_liquidity if strict_mode else display_value,
        "formal_enter_ready": formal_enter_ready,
        "strict_blocked_enter": bool(strict_mode and display_value > 0 and formal_enter_liquidity <= 0),
        "market_data_ready": bool(market_data_ready),
        "liquidity_data_ready": bool(liquidity_data_ready),
        "liquidity_source_error": liquidity_source_error,
    }


def get_exit_liquidity_usd(
    token_data: Dict[str, Any],
    *,
    strict: Optional[bool] = None,
    formal_enter: bool = False,
) -> float:
    context = get_decision_liquidity_context(token_data, strict=strict)
    if formal_enter:
        return float(context["formal_enter_liquidity_usd"])
    return float(context["value"])


def get_formal_enter_liquidity_usd(token_data: Dict[str, Any], *, strict: Optional[bool] = None) -> float:
    return get_exit_liquidity_usd(token_data, strict=strict, formal_enter=True)


def can_formal_enter(token_data: Dict[str, Any], *, strict: Optional[bool] = None) -> bool:
    return bool(get_decision_liquidity_context(token_data, strict=strict).get("formal_enter_ready"))


def get_decision_liquidity_usd(token_data: Dict[str, Any], *, strict: Optional[bool] = None) -> float:
    field = str(CANONICAL_METRIC_PIPELINE.get("decision_liquidity_field", "exit_liquidity_usd")).strip().lower()
    if field == "pair_liquidity_usd":
        return get_pair_liquidity_usd(token_data)
    return get_exit_liquidity_usd(token_data, strict=strict)


def get_metric_confidence(token_data: Dict[str, Any], key: str = "overall") -> Optional[float]:
    raw = (token_data or {}).get("metric_confidence")
    if isinstance(raw, dict):
        return _to_float(raw.get(key), None)
    if key == "overall":
        return _to_float(raw, None)
    return None


def get_source_conflict(token_data: Dict[str, Any], key: Optional[str] = None) -> Any:
    raw = (token_data or {}).get("source_conflict")
    if key is None:
        return _dict_or_empty(raw) if isinstance(raw, dict) else raw
    if isinstance(raw, dict):
        return raw.get(key)
    return None


def apply_canonical_metrics(
    token_data: Dict[str, Any],
    analytics: Optional[Dict[str, Any]] = None,
    bq_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    td = token_data or {}
    analytics = analytics or {}
    bq_data = bq_data or {}
    gmgn_gate = _gmgn_top10_gate(td, analytics)

    gmgn_observed_value = _to_float(analytics.get("top10_ratio"), None)
    if gmgn_observed_value is None:
        gmgn_observed_value = _to_float(td.get("top10_ratio_gmgn_observed"), None)
    if gmgn_observed_value is None:
        gmgn_observed_value = _to_float(td.get("top10_ratio_gmgn"), None)

    top10_candidates = _build_top10_candidates(td, analytics, bq_data)
    liquidity_candidates = _build_liquidity_candidates(td, analytics)

    top10_result = _resolve_top10_candidates(top10_candidates)
    if gmgn_observed_value is not None and not gmgn_gate["allowed"]:
        conflict = _dict_or_empty(top10_result.get("conflict"))
        conflict["blocked_gmgn_value"] = round(gmgn_observed_value, 4)
        conflict["blocked_gmgn_reason"] = str(gmgn_gate.get("reason") or "")
        top10_result["conflict"] = conflict
    liquidity_result = _resolve_liquidity_candidates(liquidity_candidates, td)
    logger.info(
        "Top10Trace | ca=%s | primary=%s | raw=%s | adjusted=%s | reason=%s | candidates=%s",
        str(td.get("ca") or "")[:8],
        top10_result.get("primary_source") or "NONE",
        _round_or_none(top10_result.get("raw_pct"), 4),
        _round_or_none(top10_result.get("adjusted_pct"), 4),
        ((top10_result.get("conflict") or {}).get("reason") or "none"),
        top10_result.get("source_values") or {},
    )

    confidence = _dict_or_empty(td.get("metric_confidence"))
    confidence["top10"] = _round_or_none(top10_result["confidence"], 4)
    confidence["liquidity"] = _round_or_none(liquidity_result["confidence"], 4)
    top10_conf = top10_result["confidence"] or 0.0
    liq_conf = liquidity_result["confidence"] or 0.0
    confidence["overall"] = round((top10_conf + liq_conf) / 2.0, 4)

    conflicts = _dict_or_empty(td.get("source_conflict"))
    conflicts["top10"] = top10_result["conflict"]
    conflicts["liquidity"] = liquidity_result["conflict"]

    top10_raw = top10_result["raw_pct"]
    top10_adjusted = top10_result["adjusted_pct"]
    pair_liq = liquidity_result["pair_liquidity_usd"]
    exit_liq = liquidity_result["exit_liquidity_usd"]

    td["top10_raw_pct"] = _round_or_none(top10_raw, 4)
    td["top10_adjusted_pct"] = _round_or_none(top10_adjusted, 4)
    td["pair_liquidity_usd"] = _round_or_none(pair_liq, 4) if pair_liq and pair_liq > 0 else None
    td["exit_liquidity_usd"] = _round_or_none(exit_liq, 4) if exit_liq and exit_liq > 0 else None
    td["metric_confidence"] = confidence
    td["source_conflict"] = conflicts
    if td.get("market_data_ready") is None:
        td["market_data_ready"] = bool(td["pair_liquidity_usd"] is not None or td["exit_liquidity_usd"] is not None)
    if td.get("liquidity_data_ready") is None:
        td["liquidity_data_ready"] = bool(td["pair_liquidity_usd"] is not None or td["exit_liquidity_usd"] is not None)
    td["liquidity_source_error"] = str(td.get("liquidity_source_error") or "")

    liquidity_context = get_decision_liquidity_context(td)
    canonical_metadata = _dict_or_empty(td.get("canonical_metadata"))
    canonical_metadata.update(
        {
            "canonical_stage": top10_result["canonical_stage"],
            "top10_adjustment_semantics": top10_result["adjustment_semantics"],
            "top10_entity_adjusted": top10_result["entity_adjusted"],
            "top10_primary_source": top10_result["primary_source"] or "",
            "gmgn_top10_blocked_reason": str(gmgn_gate.get("reason") or "")
            if gmgn_observed_value is not None and not gmgn_gate["allowed"]
            else "",
            "decision_liquidity_field": str(
                CANONICAL_METRIC_PIPELINE.get("decision_liquidity_field", "exit_liquidity_usd")
            ).strip(),
            "decision_liquidity_strict": liquidity_context["strict_mode"],
            "decision_liquidity_source": liquidity_context["display_source"],
            "decision_liquidity_used_fallback": liquidity_context["used_fallback"],
            "decision_liquidity_fallback_source": liquidity_context["fallback_source"],
            "formal_enter_ready": liquidity_context["formal_enter_ready"],
            "formal_enter_liquidity_usd": _round_or_none(liquidity_context["formal_enter_liquidity_usd"], 4),
            "market_data_ready": liquidity_context["market_data_ready"],
            "liquidity_data_ready": liquidity_context["liquidity_data_ready"],
            "liquidity_source_error": liquidity_context["liquidity_source_error"],
        }
    )
    td["canonical_stage"] = canonical_metadata["canonical_stage"]
    td["canonical_metadata"] = canonical_metadata
    td["top10_adjustment_semantics"] = canonical_metadata["top10_adjustment_semantics"]
    td["top10_entity_adjusted"] = canonical_metadata["top10_entity_adjusted"]
    td["decision_liquidity_strict"] = canonical_metadata["decision_liquidity_strict"]
    td["decision_liquidity_source"] = canonical_metadata["decision_liquidity_source"]
    td["decision_liquidity_used_fallback"] = canonical_metadata["decision_liquidity_used_fallback"]
    td["decision_liquidity_fallback_source"] = canonical_metadata["decision_liquidity_fallback_source"]
    td["decision_liquidity_enter_ready"] = canonical_metadata["formal_enter_ready"]
    td["formal_enter_liquidity_usd"] = canonical_metadata["formal_enter_liquidity_usd"]
    td["market_data_ready"] = canonical_metadata["market_data_ready"]
    td["liquidity_data_ready"] = canonical_metadata["liquidity_data_ready"]
    td["liquidity_source_error"] = canonical_metadata["liquidity_source_error"]

    td["top10_ratio_bitquery"] = _pct_text(top10_result["source_values"].get("BITQUERY"))
    td["top10_ratio_gmgn"] = _pct_text(top10_result["source_values"].get("GMGN"))
    td["top10_ratio_gmgn_observed"] = _pct_text(gmgn_observed_value)
    if "HELIUS" in top10_result["source_values"]:
        td["top10_ratio_helius"] = _pct_text(top10_result["source_values"].get("HELIUS"))

    legacy_top10 = top10_adjusted if top10_adjusted is not None else top10_raw
    td["top10_ratio"] = _pct_text(legacy_top10)
    td["top10_ratio_source"] = top10_result["primary_source"] or ""

    td["liquidity_usd"] = (
        _round_or_none(liquidity_context["display_liquidity_usd"], 4)
        if liquidity_context["display_liquidity_usd"] > 0
        else None
    )

    return td


def _build_top10_candidates(
    token_data: Dict[str, Any],
    analytics: Dict[str, Any],
    bq_data: Dict[str, Any],
) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    gmgn_gate = _gmgn_top10_gate(token_data, analytics)

    bitquery_val = _to_float(bq_data.get("bitquery_top10_ratio"), None)
    if bitquery_val is not None:
        used_fallback = bool(bq_data.get("bitquery_supply_used_fallback"))
        candidates.append(
            {
                "source": "BITQUERY",
                "value": bitquery_val,
                "confidence": CANONICAL_METRIC_PIPELINE["bitquery_fallback_confidence"]
                if used_fallback
                else CANONICAL_METRIC_PIPELINE["bitquery_confidence"],
                "note": "supply_fallback" if used_fallback else "",
            }
        )

    gmgn_val = _to_float(analytics.get("top10_ratio"), None)
    if gmgn_val is None:
        gmgn_val = _to_float(token_data.get("top10_ratio_gmgn"), None)
    if gmgn_val is not None and gmgn_gate["allowed"]:
        candidates.append(
            {
                "source": "GMGN",
                "value": gmgn_val,
                "confidence": CANONICAL_METRIC_PIPELINE["gmgn_confidence"],
                "note": "page_regex",
            }
        )

    helius_val = _to_float(token_data.get("top10_ratio_helius"), None)
    if helius_val is not None:
        candidates.append(
            {
                "source": "HELIUS",
                "value": helius_val,
                "confidence": 0.10,
                "note": "observed_only",
            }
        )

    legacy_val = _to_float(token_data.get("top10_ratio"), None)
    legacy_source = str(token_data.get("top10_ratio_source") or "").upper()
    if (
        legacy_val is not None
        and legacy_source in {"BITQUERY", "GMGN"}
        and (legacy_source != "GMGN" or gmgn_gate["allowed"])
        and not any(str(c.get("source") or "").upper() == legacy_source for c in candidates)
    ):
        candidates.append(
            {
                "source": legacy_source,
                "value": legacy_val,
                "confidence": CANONICAL_METRIC_PIPELINE["legacy_top10_confidence"],
                "note": "legacy_field",
            }
        )

    return candidates


def _resolve_top10_candidates(candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    valid = [c for c in candidates if _to_float(c.get("value"), None) is not None]
    source_values = {c["source"]: float(c["value"]) for c in valid}

    if not valid:
        return {
            "primary_source": "",
            "raw_pct": None,
            "adjusted_pct": None,
            "canonical_stage": TOP10_UNRESOLVED_STAGE,
            "adjustment_semantics": TOP10_ADJUSTMENT_SEMANTICS,
            "entity_adjusted": False,
            "confidence": 0.0,
            "conflict": {"has_conflict": False, "reason": "no_source", "candidates": {}},
            "source_values": source_values,
        }

    preferred_order = {"BITQUERY": 0, "GMGN": 1, "HELIUS": 2}
    primary = sorted(
        valid,
        key=lambda item: (
            -float(item.get("confidence") or 0.0),
            preferred_order.get(str(item.get("source") or "").upper(), 9),
        ),
    )[0]

    values = [float(c["value"]) for c in valid]
    spread = max(values) - min(values) if len(values) >= 2 else 0.0
    has_conflict = len(values) >= 2 and spread >= float(CANONICAL_METRIC_PIPELINE["top10_conflict_abs_pct"])

    primary_source = str(primary.get("source") or "")
    raw_pct = float(primary["value"])
    adjusted = raw_pct
    reason = ""
    gmgn_candidate = next((c for c in valid if str(c.get("source") or "").upper() == "GMGN"), None)
    bitquery_candidate = next((c for c in valid if str(c.get("source") or "").upper() == "BITQUERY"), None)
    gmgn_value = float(gmgn_candidate["value"]) if gmgn_candidate else None
    bitquery_value = float(bitquery_candidate["value"]) if bitquery_candidate else None

    if gmgn_value is not None:
        primary_source = "GMGN"
        raw_pct = gmgn_value
        adjusted = gmgn_value
        if bitquery_value is not None:
            reason = "gmgn_preferred_over_bitquery"
        else:
            reason = "gmgn_only"
    elif bitquery_value is not None:
        primary_source = "BITQUERY"
        raw_pct = bitquery_value
        adjusted = bitquery_value
        reason = "bitquery_only"

    gmgn_high_pct = float(CANONICAL_METRIC_PIPELINE["gmgn_unconfirmed_high_pct"])
    if gmgn_value is not None and gmgn_value >= gmgn_high_pct and "BITQUERY" not in source_values:
        adjusted = None
        reason = "gmgn_unconfirmed_high"

    confidence_source = gmgn_candidate if gmgn_candidate is not None else primary
    confidence = float((confidence_source or {}).get("confidence") or 0.0)
    if has_conflict:
        confidence = max(0.0, confidence - 0.15)
    if adjusted is None:
        confidence = min(confidence, 0.25)

    return {
        "primary_source": primary_source,
        "raw_pct": raw_pct,
        "adjusted_pct": adjusted,
        "canonical_stage": TOP10_CANONICAL_STAGE,
        "adjustment_semantics": TOP10_ADJUSTMENT_SEMANTICS,
        "entity_adjusted": False,
        "confidence": confidence,
        "conflict": {
            "has_conflict": has_conflict or adjusted is None,
            "reason": reason,
            "spread_pct": round(spread, 4),
            "candidates": {k: round(v, 4) for k, v in source_values.items()},
        },
        "source_values": source_values,
    }


def _build_liquidity_candidates(token_data: Dict[str, Any], analytics: Dict[str, Any]) -> Dict[str, Any]:
    pair_candidates: List[Dict[str, Any]] = []
    exit_candidates: List[Dict[str, Any]] = []

    dex_pair = _to_float(token_data.get("pair_liquidity_usd"), None)
    if dex_pair is None:
        dex_pair = _to_float(token_data.get("liquidity_usd"), None)
    if dex_pair is not None and dex_pair > 0:
        pair_candidates.append(
            {
                "source": "DEXSCREENER_PAIR",
                "value": dex_pair,
                "confidence": CANONICAL_METRIC_PIPELINE["dex_pair_confidence"],
            }
        )

    birdeye_exit = _to_float(token_data.get("birdeye_liquidity_usd"), None)
    if birdeye_exit is None:
        birdeye_exit = _to_float(token_data.get("exit_liquidity_usd"), None)
    if birdeye_exit is not None and birdeye_exit > 0:
        exit_candidates.append(
            {
                "source": "BIRDEYE_EXIT",
                "value": birdeye_exit,
                "confidence": CANONICAL_METRIC_PIPELINE["birdeye_exit_confidence"],
            }
        )

    gmgn_liq = _to_float(analytics.get("header_liq_usd"), None)
    if gmgn_liq is None:
        gmgn_liq = _to_float(token_data.get("gmgn_header_liquidity_usd"), None)
    if gmgn_liq is not None and gmgn_liq > 0:
        pair_candidates.append(
            {
                "source": "GMGN_HEADER",
                "value": gmgn_liq,
                "confidence": CANONICAL_METRIC_PIPELINE["gmgn_liquidity_confidence"],
            }
        )

    return {"pair": pair_candidates, "exit": exit_candidates}


def _resolve_liquidity_candidates(candidates: Dict[str, Any], token_data: Dict[str, Any]) -> Dict[str, Any]:
    pair_candidates = candidates.get("pair") or []
    exit_candidates = candidates.get("exit") or []

    pair_primary = _pick_liquidity_candidate(pair_candidates)
    exit_primary = _pick_liquidity_candidate(exit_candidates)

    pair_liq = float(pair_primary["value"]) if pair_primary else 0.0
    exit_liq = float(exit_primary["value"]) if exit_primary else 0.0

    dex_pair = _to_float(token_data.get("pair_liquidity_usd"), None)
    birdeye_exit = _to_float(token_data.get("birdeye_liquidity_usd"), None)
    conflict_ratio = 0.0
    has_conflict = False
    if dex_pair and birdeye_exit and min(dex_pair, birdeye_exit) > 0:
        conflict_ratio = max(dex_pair, birdeye_exit) / max(1.0, min(dex_pair, birdeye_exit))
        has_conflict = conflict_ratio >= float(CANONICAL_METRIC_PIPELINE["liquidity_conflict_ratio"])

    confidence = float(exit_primary.get("confidence") if exit_primary else pair_primary.get("confidence") if pair_primary else 0.0)
    if has_conflict:
        confidence = max(0.0, confidence - 0.10)

    pair_values = {c["source"]: round(float(c["value"]), 4) for c in pair_candidates}
    exit_values = {c["source"]: round(float(c["value"]), 4) for c in exit_candidates}

    return {
        "pair_liquidity_usd": pair_liq,
        "exit_liquidity_usd": exit_liq,
        "confidence": confidence,
        "conflict": {
            "has_conflict": has_conflict,
            "ratio": round(conflict_ratio, 4),
            "pair_candidates": pair_values,
            "exit_candidates": exit_values,
            "pair_source": pair_primary.get("source") if pair_primary else "",
            "exit_source": exit_primary.get("source") if exit_primary else "",
        },
    }


def _pick_liquidity_candidate(candidates: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not candidates:
        return None
    preferred_order = {
        "BIRDEYE_EXIT": 0,
        "DEXSCREENER_PAIR": 1,
        "GMGN_HEADER": 2,
        "LEGACY_LIQUIDITY": 3,
    }
    ranked = sorted(
        candidates,
        key=lambda item: (
            preferred_order.get(str(item.get("source") or "").upper(), 9),
            -float(item.get("confidence") or 0.0),
        ),
    )
    return ranked[0]
