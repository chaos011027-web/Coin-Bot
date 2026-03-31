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


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
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
    raise TypeError(f"unsupported wallet behavior row type: {type(row)!r}")


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


def _contains_wallet_in_social_signal(wallet_address: str, social_signal: Dict[str, Any]) -> bool:
    ix_data = _safe_json_obj(social_signal.get("ix_data"))
    candidates = _safe_list(ix_data.get("wallets")) + _safe_list(ix_data.get("smart_wallets"))
    wallet_norm = _safe_text(wallet_address)
    for item in candidates:
        if _safe_text(item) == wallet_norm:
            return True
        if isinstance(item, dict):
            candidate_wallet = _safe_text(item.get("wallet_address") or item.get("owner") or item.get("address"))
            if candidate_wallet == wallet_norm:
                return True
    return False


def _contains_wallet_in_holder_distribution(wallet_address: str, holder_distribution: Dict[str, Any]) -> bool:
    wallet_norm = _safe_text(wallet_address)
    candidates = _safe_list(holder_distribution.get("top_wallets")) + _safe_list(holder_distribution.get("holders"))
    for item in candidates:
        if _safe_text(item) == wallet_norm:
            return True
        if isinstance(item, dict):
            candidate_wallet = _safe_text(item.get("wallet_address") or item.get("owner") or item.get("address"))
            if candidate_wallet == wallet_norm:
                return True
    return False


def _empty_feature_row(wallet_address: str) -> Dict[str, Any]:
    return {
        "wallet_address": wallet_address,
        "snapshot_at": "",
        "tag_count": 0,
        "smart_money_tag_hits": 0,
        "suspicious_cluster_hits": 0,
        "cluster_risk_level_max": 0.0,
        "cluster_wallets_total_max": 0,
        "total_trades": 0,
        "avg_entry_mcap": 0.0,
        "observed_token_count": 0,
        "social_signal_token_count": 0,
        "holder_token_count": 0,
        "last_seen_ca": "",
        "last_seen_analysis_run_id": None,
        "_observed_tokens": set(),
    }


def build_wallet_behavior_feature_snapshots(
    *,
    smart_wallet_rows=None,
    wallet_cluster_rows=None,
    morphology_rows=None,
    analysis_run_rows=None,
) -> List[Dict[str, Any]]:
    analysis_runs_by_ca = _analysis_run_map(list(analysis_run_rows or []))
    feature_map: Dict[str, Dict[str, Any]] = {}

    for raw in list(smart_wallet_rows or []):
        row = _normalize_row(raw)
        if _is_legacy_row(row):
            continue
        wallet_address = _safe_text(row.get("wallet_address"))
        if not wallet_address:
            continue
        target = feature_map.setdefault(wallet_address, _empty_feature_row(wallet_address))
        tags = [_safe_text(tag).upper() for tag in _safe_list(row.get("tags")) if _safe_text(tag)]
        target["snapshot_at"] = _max_timestamp(target["snapshot_at"], _safe_text(row.get("last_active")))
        target["tag_count"] = max(target["tag_count"], len(tags))
        target["smart_money_tag_hits"] = max(
            target["smart_money_tag_hits"],
            sum(1 for tag in tags if tag == "SMART MONEY"),
        )
        target["total_trades"] = max(target["total_trades"], _safe_int(row.get("total_trades"), 0))
        target["avg_entry_mcap"] = max(target["avg_entry_mcap"], _safe_float(row.get("avg_entry_mcap"), 0.0))
        last_seen_ca = _safe_text(row.get("last_seen_ca"))
        if last_seen_ca:
            target["last_seen_ca"] = last_seen_ca
            target["_observed_tokens"].add(last_seen_ca)

    for raw in list(wallet_cluster_rows or []):
        row = _normalize_row(raw)
        if _is_legacy_row(row):
            continue
        wallet_address = _safe_text(row.get("wallet_address"))
        if not wallet_address:
            continue
        target = feature_map.setdefault(wallet_address, _empty_feature_row(wallet_address))
        if _safe_text(row.get("behavior_tag")).upper() == "SUSPICIOUS_CLUSTER":
            target["suspicious_cluster_hits"] += 1
        target["cluster_risk_level_max"] = max(
            target["cluster_risk_level_max"],
            _safe_float(row.get("risk_level"), 0.0),
        )
        target["cluster_wallets_total_max"] = max(
            target["cluster_wallets_total_max"],
            _safe_int(row.get("total_wallets_in_cluster"), 0),
        )
        target["snapshot_at"] = _max_timestamp(target["snapshot_at"], _safe_text(row.get("created_at")))
        discovered_in_token = _safe_text(row.get("discovered_in_token"))
        if discovered_in_token:
            target["last_seen_ca"] = discovered_in_token
            target["_observed_tokens"].add(discovered_in_token)

    for raw in list(morphology_rows or []):
        row = _normalize_row(raw)
        if _is_legacy_row(row):
            continue
        ca = _safe_text(row.get("ca"))
        if not ca:
            continue
        social_signal = _safe_json_obj(row.get("social_signal"))
        holder_distribution = _safe_json_obj(row.get("holder_distribution"))
        snapshot_at = _safe_text(row.get("snapshot_time"))
        for wallet_address, target in feature_map.items():
            saw_social_signal = _contains_wallet_in_social_signal(wallet_address, social_signal)
            saw_holder_distribution = _contains_wallet_in_holder_distribution(wallet_address, holder_distribution)
            if not saw_social_signal and not saw_holder_distribution:
                continue
            target["snapshot_at"] = _max_timestamp(target["snapshot_at"], snapshot_at)
            target["_observed_tokens"].add(ca)
            if saw_social_signal:
                target["social_signal_token_count"] += 1
            if saw_holder_distribution:
                target["holder_token_count"] += 1

    rows: List[Dict[str, Any]] = []
    for wallet_address in sorted(feature_map):
        row = dict(feature_map[wallet_address])
        observed_tokens = set(row.pop("_observed_tokens", set()))
        row["observed_token_count"] = len(observed_tokens)
        if row["last_seen_ca"]:
            row["last_seen_analysis_run_id"] = analysis_runs_by_ca.get(row["last_seen_ca"])
        rows.append(row)
    return rows
