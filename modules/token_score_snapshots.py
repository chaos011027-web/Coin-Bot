from __future__ import annotations

import json
from typing import Any, Dict, List


DEFAULT_SCORE_VERSION = "token_score_snapshots_v1"


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


def _normalize_row(row: Any) -> Dict[str, Any]:
    if isinstance(row, dict):
        return dict(row)
    try:
        return dict(row)
    except Exception:
        pass
    if hasattr(row, "keys"):
        return {key: row[key] for key in row.keys()}
    raise TypeError(f"unsupported token score row type: {type(row)!r}")


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


def _metric_confidence_score(metric_confidence: Dict[str, Any]) -> float:
    values = []
    for value in metric_confidence.values():
        number = _safe_float(value, None)
        if number is None:
            continue
        values.append(max(0.0, min(1.0, number)))
    if not values:
        return 0.5
    return round(sum(values) / len(values), 6)


def build_token_score_snapshots(
    *,
    signal_rows=None,
    morphology_rows=None,
    risk_flag_rows=None,
    analysis_run_rows=None,
    snapshot_at: str = "",
    score_version: str = DEFAULT_SCORE_VERSION,
) -> List[Dict[str, Any]]:
    analysis_runs_by_ca = _analysis_run_map(list(analysis_run_rows or []))
    signal_map: Dict[str, Dict[str, Any]] = {}
    morphology_map: Dict[str, Dict[str, Any]] = {}
    risk_flags_by_ca: Dict[str, set[str]] = {}

    for raw in list(signal_rows or []):
        row = _normalize_row(raw)
        if _is_legacy_row(row):
            continue
        ca = _safe_text(row.get("ca"))
        if not ca:
            continue
        signal_map[ca] = row

    for raw in list(morphology_rows or []):
        row = _normalize_row(raw)
        if _is_legacy_row(row):
            continue
        ca = _safe_text(row.get("ca"))
        if not ca:
            continue
        morphology_map[ca] = row

    for raw in list(risk_flag_rows or []):
        row = _normalize_row(raw)
        if _is_legacy_row(row):
            continue
        ca = _safe_text(row.get("ca"))
        risk_flag = _safe_text(row.get("risk_flag"))
        if not ca or not risk_flag:
            continue
        risk_flags_by_ca.setdefault(ca, set()).add(risk_flag)

    rows: List[Dict[str, Any]] = []
    for ca in sorted(set(signal_map) | set(morphology_map)):
        signal_row = signal_map.get(ca, {})
        morphology_row = morphology_map.get(ca, {})
        risk_flags = risk_flags_by_ca.get(ca, set())

        pair_liquidity_usd = _safe_float(signal_row.get("pair_liquidity_usd"), 0.0)
        liquidity_structure_score = round(max(0.0, min(1.0, pair_liquidity_usd / 50000.0)), 6)

        top10_adjusted_pct = _safe_float(
            signal_row.get("top10_adjusted_pct") or signal_row.get("top10_raw_pct"),
            0.0,
        )
        top10_concentration_score = round(max(0.0, 1.0 - min(100.0, top10_adjusted_pct) / 100.0), 6)

        gmgn_behavior_score = 0.2 if "GMGN_BEHAVIOR_RISK" in risk_flags else 0.8

        metric_confidence = _safe_json_obj(signal_row.get("metric_confidence"))
        source_confidence_score = _metric_confidence_score(metric_confidence)
        if "SOURCE_CONFLICT" in risk_flags:
            source_confidence_score = max(0.0, source_confidence_score - 0.25)
        if "TOP10_SEMANTIC_CONFLICT" in risk_flags:
            source_confidence_score = max(0.0, source_confidence_score - 0.25)
        source_confidence_score = round(source_confidence_score, 6)

        total_score = round(
            (
                liquidity_structure_score
                + top10_concentration_score
                + gmgn_behavior_score
                + source_confidence_score
            )
            / 4.0,
            6,
        )

        resolved_snapshot_at = _safe_text(snapshot_at)
        resolved_snapshot_at = _max_timestamp(
            resolved_snapshot_at,
            _safe_text(signal_row.get("snapshot_time") or signal_row.get("updated_at") or signal_row.get("created_at")),
        )
        resolved_snapshot_at = _max_timestamp(
            resolved_snapshot_at,
            _safe_text(morphology_row.get("snapshot_time")),
        )

        analysis_run_id = signal_row.get("analysis_run_id")
        if analysis_run_id is None:
            analysis_run_id = analysis_runs_by_ca.get(ca)

        rows.append(
            {
                "ca": ca,
                "snapshot_at": resolved_snapshot_at,
                "analysis_run_id": analysis_run_id,
                "score_version": _safe_text(score_version) or DEFAULT_SCORE_VERSION,
                "liquidity_structure_score": liquidity_structure_score,
                "top10_concentration_score": top10_concentration_score,
                "gmgn_behavior_score": gmgn_behavior_score,
                "source_confidence_score": source_confidence_score,
                "total_score": total_score,
                "summary": f"liq={liquidity_structure_score:.4f}; top10={top10_concentration_score:.4f}; gmgn={gmgn_behavior_score:.4f}; source={source_confidence_score:.4f}",
            }
        )
    return rows
