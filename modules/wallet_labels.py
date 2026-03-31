from __future__ import annotations

from typing import Any, Dict, List, Tuple


MIN_EVIDENCE_COUNT = 2
MIN_CONFIDENCE_SCORE = 0.7
DEFAULT_RULE_VERSION = "wallet_labels_v1"


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


def _normalize_row(row: Any) -> Dict[str, Any]:
    if isinstance(row, dict):
        return dict(row)
    try:
        return dict(row)
    except Exception:
        pass
    if hasattr(row, "keys"):
        return {key: row[key] for key in row.keys()}
    raise TypeError(f"unsupported wallet label row type: {type(row)!r}")


def _is_legacy_row(row: Dict[str, Any]) -> bool:
    if bool(row.get("legacy_path")):
        return True
    return _safe_text(row.get("path_kind")).upper() == "LEGACY_DIRECT_ENTER"


def build_wallet_label_snapshots(
    evidence_rows,
    *,
    snapshot_at: str = "",
    rule_version: str = DEFAULT_RULE_VERSION,
) -> List[Dict[str, Any]]:
    grouped: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for raw in list(evidence_rows or []):
        row = _normalize_row(raw)
        if _is_legacy_row(row):
            continue
        wallet_address = _safe_text(row.get("wallet_address"))
        label_candidate = _safe_text(row.get("label_candidate"))
        if not wallet_address or not label_candidate:
            continue
        key = (wallet_address, label_candidate)
        target = grouped.setdefault(
            key,
            {
                "wallet_address": wallet_address,
                "label_name": label_candidate,
                "confidence_values": [],
                "evidence_count": 0,
                "snapshot_at": "",
            },
        )
        target["confidence_values"].append(_safe_float(row.get("confidence_hint"), 0.0))
        target["evidence_count"] += 1
        observed_at = _safe_text(row.get("observed_at"))
        if observed_at and observed_at > target["snapshot_at"]:
            target["snapshot_at"] = observed_at

    rows: List[Dict[str, Any]] = []
    for key in sorted(grouped):
        target = grouped[key]
        evidence_count = int(target["evidence_count"])
        if evidence_count < MIN_EVIDENCE_COUNT:
            continue
        confidence_score = round(sum(target["confidence_values"]) / evidence_count, 6)
        if confidence_score < MIN_CONFIDENCE_SCORE:
            continue
        rows.append(
            {
                "wallet_address": target["wallet_address"],
                "label_name": target["label_name"],
                "confidence": confidence_score,
                "confidence_score": confidence_score,
                "evidence_count": evidence_count,
                "snapshot_at": _safe_text(snapshot_at) or target["snapshot_at"],
                "rule_version": _safe_text(rule_version) or DEFAULT_RULE_VERSION,
            }
        )
    return rows
