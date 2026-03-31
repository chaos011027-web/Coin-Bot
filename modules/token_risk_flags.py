from __future__ import annotations

import json
from typing import Any, Dict, List


DEFAULT_RULE_VERSION = "token_risk_flags_v1"
ALLOWED_RISK_FLAGS = {
    "TOP10_CONCENTRATION",
    "LOW_LIQUIDITY",
    "AUTHORITY_RISK",
    "GMGN_BEHAVIOR_RISK",
    "SOURCE_CONFLICT",
    "TOP10_SEMANTIC_CONFLICT",
}


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def _safe_json_obj(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return dict(parsed) if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _safe_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return list(parsed)
        except Exception:
            return []
    return []


def _normalize_row(row: Any) -> Dict[str, Any]:
    if isinstance(row, dict):
        return dict(row)
    try:
        return dict(row)
    except Exception:
        pass
    if hasattr(row, "keys"):
        return {key: row[key] for key in row.keys()}
    raise TypeError(f"unsupported token risk row type: {type(row)!r}")


def _is_legacy_row(row: Dict[str, Any]) -> bool:
    if bool(row.get("legacy_path")):
        return True
    return _safe_text(row.get("path_kind")).upper() == "LEGACY_DIRECT_ENTER"


def _max_timestamp(current: str, candidate: str) -> str:
    current_value = _safe_text(current)
    candidate_value = _safe_text(candidate)
    if not candidate_value:
        return current_value
    if not current_value:
        return candidate_value
    return candidate_value if candidate_value > current_value else current_value


def _analysis_run_map(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for raw in rows or []:
        row = _normalize_row(raw)
        if _is_legacy_row(row):
            continue
        ca = _safe_text(row.get("ca"))
        if not ca:
            continue
        run_id = row.get("id")
        if run_id is None:
            run_id = row.get("analysis_run_id")
        if run_id is not None:
            out[ca] = run_id
    return out


def _token_bucket(ca: str) -> Dict[str, Any]:
    return {
        "ca": ca,
        "analysis_run_id": None,
        "snapshot_at": "",
        "top10_adjusted_pct": 0.0,
        "pair_liquidity_usd": 0.0,
        "source_conflict": {},
        "security_flags": {},
        "social_signal": {},
        "holder_distribution": {},
    }


def build_token_risk_flag_snapshots(
    *,
    signal_rows=None,
    morphology_rows=None,
    token_meta_rows=None,
    analysis_run_rows=None,
    snapshot_at: str = "",
    rule_version: str = DEFAULT_RULE_VERSION,
) -> List[Dict[str, Any]]:
    analysis_runs_by_ca = _analysis_run_map(list(analysis_run_rows or []))
    token_map: Dict[str, Dict[str, Any]] = {}

    for raw in list(signal_rows or []):
        row = _normalize_row(raw)
        if _is_legacy_row(row):
            continue
        ca = _safe_text(row.get("ca"))
        if not ca:
            continue
        target = token_map.setdefault(ca, _token_bucket(ca))
        target["analysis_run_id"] = row.get("analysis_run_id") if row.get("analysis_run_id") is not None else target["analysis_run_id"]
        target["snapshot_at"] = _max_timestamp(
            target["snapshot_at"],
            _safe_text(row.get("snapshot_time") or row.get("updated_at") or row.get("created_at")),
        )
        target["top10_adjusted_pct"] = max(
            target["top10_adjusted_pct"],
            _safe_float(row.get("top10_adjusted_pct") or row.get("top10_raw_pct"), 0.0),
        )
        liquidity = _safe_float(row.get("pair_liquidity_usd"), 0.0)
        if liquidity > 0:
            current_liquidity = _safe_float(target.get("pair_liquidity_usd"), 0.0)
            if current_liquidity <= 0 or liquidity < current_liquidity:
                target["pair_liquidity_usd"] = liquidity
        source_conflict = _safe_json_obj(row.get("source_conflict"))
        if source_conflict:
            target["source_conflict"] = source_conflict

    for raw in list(morphology_rows or []):
        row = _normalize_row(raw)
        if _is_legacy_row(row):
            continue
        ca = _safe_text(row.get("ca"))
        if not ca:
            continue
        target = token_map.setdefault(ca, _token_bucket(ca))
        target["snapshot_at"] = _max_timestamp(target["snapshot_at"], _safe_text(row.get("snapshot_time")))
        social_signal = _safe_json_obj(row.get("social_signal"))
        if social_signal:
            target["social_signal"] = social_signal
        holder_distribution = _safe_json_obj(row.get("holder_distribution"))
        if holder_distribution:
            target["holder_distribution"] = holder_distribution

    for raw in list(token_meta_rows or []):
        row = _normalize_row(raw)
        if _is_legacy_row(row):
            continue
        ca = _safe_text(row.get("ca"))
        if not ca:
            continue
        target = token_map.setdefault(ca, _token_bucket(ca))
        target["security_flags"] = _safe_json_obj(row.get("security_flags"))

    rows: List[Dict[str, Any]] = []
    for ca in sorted(token_map):
        target = token_map[ca]
        analysis_run_id = target["analysis_run_id"]
        if analysis_run_id is None:
            analysis_run_id = analysis_runs_by_ca.get(ca)
        effective_snapshot_at = _safe_text(snapshot_at) or target["snapshot_at"]

        def append_flag(flag: str, risk_value: float, risk_score: float) -> None:
            if flag not in ALLOWED_RISK_FLAGS:
                raise RuntimeError(f"unsupported risk flag: {flag}")
            rows.append(
                {
                    "ca": ca,
                    "risk_flag": flag,
                    "risk_value": round(risk_value, 6),
                    "risk_score": round(risk_score, 6),
                    "snapshot_at": effective_snapshot_at,
                    "analysis_run_id": analysis_run_id,
                    "rule_version": _safe_text(rule_version) or DEFAULT_RULE_VERSION,
                }
            )

        top10_adjusted_pct = _safe_float(target["top10_adjusted_pct"], 0.0)
        if top10_adjusted_pct >= 50.0:
            append_flag("TOP10_CONCENTRATION", top10_adjusted_pct, min(1.0, top10_adjusted_pct / 100.0))

        pair_liquidity_usd = _safe_float(target["pair_liquidity_usd"], 0.0)
        if 0.0 < pair_liquidity_usd < 20000.0:
            append_flag("LOW_LIQUIDITY", pair_liquidity_usd, round(1.0 - (pair_liquidity_usd / 20000.0), 6))

        security_flags = _safe_json_obj(target["security_flags"])
        if any(
            bool(security_flags.get(key))
            for key in (
                "mint_authority_not_renounced",
                "freeze_authority_present",
                "has_mint_authority",
                "has_freeze_authority",
                "authority_risk",
            )
        ):
            append_flag("AUTHORITY_RISK", 1.0, 1.0)

        social_signal = _safe_json_obj(target["social_signal"])
        ix_data = _safe_json_obj(social_signal.get("ix_data"))
        clusters = _safe_list(ix_data.get("clusters"))
        if clusters:
            append_flag("GMGN_BEHAVIOR_RISK", float(len(clusters)), min(1.0, len(clusters) / 5.0))

        source_conflict = _safe_json_obj(target["source_conflict"])
        if source_conflict:
            append_flag("SOURCE_CONFLICT", 1.0, 1.0)

        holder_distribution = _safe_json_obj(target["holder_distribution"])
        top10_semantic_conflict = bool(holder_distribution.get("top10_semantic_conflict")) or any(
            "top10" in _safe_text(key).lower()
            for key in source_conflict.keys()
        )
        if top10_semantic_conflict:
            append_flag("TOP10_SEMANTIC_CONFLICT", 1.0, 1.0)

    rows.sort(key=lambda item: (_safe_text(item.get("ca")), _safe_text(item.get("risk_flag"))))
    return rows
