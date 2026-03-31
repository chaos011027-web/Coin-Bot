from __future__ import annotations

import json
from typing import Any, Dict, List


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
            return [value]
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
    raise TypeError(f"unsupported wallet evidence row type: {type(row)!r}")


def _is_legacy_row(row: Dict[str, Any]) -> bool:
    if bool(row.get("legacy_path")):
        return True
    return _safe_text(row.get("path_kind")).upper() == "LEGACY_DIRECT_ENTER"


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


def _tag_candidate(tag: str) -> str:
    normalized = _safe_text(tag).upper().replace(" ", "_")
    if not normalized:
        return ""
    return f"{normalized}_WALLET"


def _tag_confidence(tag: str) -> float:
    normalized = _safe_text(tag).upper()
    if normalized == "SMART MONEY":
        return 0.8
    if normalized == "KOL":
        return 0.7
    if normalized == "SNIPER":
        return 0.65
    if normalized == "DEV":
        return 0.55
    return 0.5


def build_wallet_label_evidence_rows(
    *,
    smart_wallet_rows=None,
    wallet_cluster_rows=None,
    analysis_run_rows=None,
) -> List[Dict[str, Any]]:
    analysis_runs_by_ca = _analysis_run_map(list(analysis_run_rows or []))
    rows: List[Dict[str, Any]] = []

    for raw in list(smart_wallet_rows or []):
        row = _normalize_row(raw)
        if _is_legacy_row(row):
            continue
        wallet_address = _safe_text(row.get("wallet_address"))
        if not wallet_address:
            continue
        ca = _safe_text(row.get("last_seen_ca") or row.get("ca"))
        trace_link = _safe_text(row.get("trace_link"))
        sample_id = _safe_text(row.get("sample_id"))
        observed_at = _safe_text(row.get("last_active") or row.get("created_at"))
        for tag in _safe_list(row.get("tags")):
            label_candidate = _tag_candidate(_safe_text(tag))
            if not label_candidate:
                continue
            source_key = f"{wallet_address}:{label_candidate}"
            rows.append(
                {
                    "evidence_id": f"evidence_smart_wallet_intel_{wallet_address}_{label_candidate}",
                    "wallet_address": wallet_address,
                    "label_candidate": label_candidate,
                    "source": "smart_wallet_intel",
                    "source_key": source_key,
                    "ca": ca,
                    "analysis_run_id": analysis_runs_by_ca.get(ca),
                    "trace_link": trace_link,
                    "sample_id": sample_id,
                    "evidence_payload": dict(row),
                    "confidence_hint": round(_tag_confidence(_safe_text(tag)), 6),
                    "observed_at": observed_at,
                }
            )

    for raw in list(wallet_cluster_rows or []):
        row = _normalize_row(raw)
        if _is_legacy_row(row):
            continue
        if _safe_text(row.get("behavior_tag")).upper() != "SUSPICIOUS_CLUSTER":
            continue
        wallet_address = _safe_text(row.get("wallet_address"))
        ca = _safe_text(row.get("discovered_in_token"))
        if not wallet_address or not ca:
            continue
        cluster_id = _safe_text(row.get("cluster_id")) or f"{wallet_address}:{ca}"
        rows.append(
            {
                "evidence_id": f"evidence_wallet_clusters_{cluster_id}",
                "wallet_address": wallet_address,
                "label_candidate": "SUSPICIOUS_CLUSTER_WALLET",
                "source": "wallet_clusters",
                "source_key": cluster_id,
                "ca": ca,
                "analysis_run_id": analysis_runs_by_ca.get(ca),
                "trace_link": _safe_text(row.get("trace_link")),
                "sample_id": _safe_text(row.get("sample_id")),
                "evidence_payload": dict(row),
                "confidence_hint": round(max(0.5, min(1.0, 0.45 + _safe_float(row.get("risk_level"), 0.0) / 40.0)), 6),
                "observed_at": _safe_text(row.get("created_at") or row.get("observed_at")),
            }
        )

    rows.sort(
        key=lambda item: (
            _safe_text(item.get("wallet_address")),
            _safe_text(item.get("label_candidate")),
            _safe_text(item.get("source_key")),
        )
    )
    return rows
