from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from modules.database import db
from modules.db_schema import PAPER_FILLS_TABLE, PAPER_ORDERS_TABLE, PAPER_TRADE_CLOSES_TABLE


DEFAULT_INPUT = Path("data/training_replay_records.json")
DEFAULT_OUTPUT = Path("data/replay_dataset_bridge.json")
LEGACY_OUTPUT_NAMES = {"strategy_backtest_records.json"}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _safe_json_obj(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
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
    raise TypeError(f"unsupported replay bridge row type: {type(row)!r}")


def _normalize_reason(reasons: List[str]) -> str:
    uniq: List[str] = []
    seen = set()
    for reason in reasons or []:
        value = _safe_text(reason)
        if not value or value in seen:
            continue
        seen.add(value)
        uniq.append(value)
    if not uniq:
        return "BACKTEST_EXIT"
    if len(uniq) == 1:
        return uniq[0]
    return " | ".join(uniq)


def _load_phase3_records(input_path: str = "") -> List[Dict[str, Any]]:
    source = Path(input_path) if input_path else DEFAULT_INPUT
    raw = json.loads(source.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        records = raw.get("records", []) or []
    elif isinstance(raw, list):
        records = raw
    else:
        raise ValueError("training replay export must be a list or {'records': [...]}")
    return [_normalize_row(row) for row in records]


def _is_legacy_record(record: Dict[str, Any]) -> bool:
    return _safe_text(record.get("path_kind")).upper() == "LEGACY_DIRECT_ENTER"


async def _load_position_bundle_from_db(position_ids: List[str]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    orders_rows = await db.fetch(
        f"""
        SELECT order_id, analysis_run_id, ca, position_id, side, intent, requested_price, strategy_id, legacy_path, metadata
        FROM {PAPER_ORDERS_TABLE}
        WHERE position_id = ANY($1::text[])
          AND COALESCE(legacy_path, FALSE) = FALSE
        ORDER BY created_at ASC
        """,
        position_ids,
    )
    fills_rows = await db.fetch(
        f"""
        SELECT fill_id, order_id, analysis_run_id, ca, position_id, side, fill_qty, fill_price, legacy_path, metadata
        FROM {PAPER_FILLS_TABLE}
        WHERE position_id = ANY($1::text[])
          AND COALESCE(legacy_path, FALSE) = FALSE
        ORDER BY filled_at ASC
        """,
        position_ids,
    )
    closes_rows = await db.fetch(
        f"""
        SELECT trade_close_id, position_id, order_id, fill_id, analysis_run_id, ca, strategy,
               opened_at, closed_at, close_reason, partial, close_ratio,
               entry_notional_sol, exit_notional_sol, total_fee_sol,
               realized_pnl_sol, realized_return_pct, legacy_path
        FROM {PAPER_TRADE_CLOSES_TABLE}
        WHERE position_id = ANY($1::text[])
          AND COALESCE(legacy_path, FALSE) = FALSE
        ORDER BY closed_at ASC, recorded_at ASC
        """,
        position_ids,
    )
    return (
        [_normalize_row(row) for row in orders_rows],
        [_normalize_row(row) for row in fills_rows],
        [_normalize_row(row) for row in closes_rows],
    )


def _load_position_bundle_from_repo(position_ids: List[str], repository) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    keep = set(position_ids)
    orders = [
        dict(row)
        for row in list(getattr(repository, "orders", []) or [])
        if _safe_text(row.get("position_id")) in keep and not bool(row.get("legacy_path"))
    ]
    fills = [
        dict(row)
        for row in list(getattr(repository, "fills", []) or [])
        if _safe_text(row.get("position_id")) in keep and not bool(row.get("legacy_path"))
    ]
    closes = [
        dict(row)
        for row in list(getattr(repository, "trade_closes", []) or [])
        if _safe_text(row.get("position_id")) in keep and not bool(row.get("legacy_path"))
    ]
    return orders, fills, closes


def _load_position_bundle(position_ids: List[str], paper_ledger_repository=None) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    if paper_ledger_repository is not None and hasattr(paper_ledger_repository, "fills"):
        return _load_position_bundle_from_repo(position_ids, paper_ledger_repository)
    return asyncio.run(_load_position_bundle_from_db(position_ids))


def _resolve_symbol(orders: List[Dict[str, Any]], fills: List[Dict[str, Any]]) -> str:
    for row in fills:
        metadata = _safe_json_obj(row.get("metadata"))
        symbol = _safe_text(metadata.get("symbol"))
        if symbol:
            return symbol
    for row in orders:
        metadata = _safe_json_obj(row.get("metadata"))
        symbol = _safe_text(metadata.get("symbol"))
        if symbol:
            return symbol
    return "UNK"


def build_replay_dataset_records(
    records: List[Dict[str, Any]],
    *,
    paper_ledger_repository=None,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for raw in records or []:
        record = _normalize_row(raw)
        if _is_legacy_record(record):
            continue

        label = _normalize_row(record.get("label") or {})
        if _safe_text(label.get("label_kind")) != "trade_closed":
            continue

        position_ids = [_safe_text(value) for value in list(label.get("position_ids") or []) if _safe_text(value)]
        if not position_ids:
            continue

        orders, fills, closes = _load_position_bundle(position_ids, paper_ledger_repository=paper_ledger_repository)
        if not closes:
            continue

        buy_fills = [
            row for row in fills
            if _safe_text(row.get("side")).upper() == "BUY"
            and _safe_float(row.get("fill_price"), 0.0) > 0
        ]
        sell_fills = [
            row for row in fills
            if _safe_text(row.get("side")).upper() == "SELL"
            and _safe_float(row.get("fill_qty"), 0.0) > 0
            and _safe_float(row.get("fill_price"), 0.0) > 0
        ]
        if not buy_fills or not sell_fills:
            continue

        features = _normalize_row(record.get("frozen_features") or {})
        entry_mcap = _safe_float(features.get("cap_usd"), 0.0)
        entry_price = _safe_float(buy_fills[0].get("fill_price"), 0.0)
        if entry_mcap <= 0 or entry_price <= 0:
            continue

        total_sell_qty = sum(_safe_float(row.get("fill_qty"), 0.0) for row in sell_fills)
        if total_sell_qty <= 0:
            continue
        weighted_exit_notional = sum(
            _safe_float(row.get("fill_qty"), 0.0) * _safe_float(row.get("fill_price"), 0.0)
            for row in sell_fills
        )
        exit_price = weighted_exit_notional / total_sell_qty
        if exit_price <= 0:
            continue

        exit_mcap = entry_mcap * (exit_price / entry_price)
        if exit_mcap <= 0:
            continue

        opened_at = min(_safe_float(row.get("opened_at"), 0.0) for row in closes)
        closed_at = max(_safe_float(row.get("closed_at"), 0.0) for row in closes)
        if opened_at <= 0 or closed_at <= 0:
            continue

        out.append(
            {
                "sample_id": _safe_text(record.get("sample_id")),
                "analysis_run_id": record.get("analysis_run_id"),
                "ca": _safe_text(record.get("ca")),
                "symbol": _resolve_symbol(orders, fills),
                "strategy": _safe_text(record.get("strategy_id")) or _safe_text(record.get("final_action")) or "MIXED",
                "opened_at": round(opened_at, 6),
                "closed_at": round(closed_at, 6),
                "entry_price": round(entry_price, 12),
                "exit_price": round(exit_price, 12),
                "entry_mcap": round(entry_mcap, 6),
                "exit_mcap": round(exit_mcap, 6),
                "exit_reason": _normalize_reason(list(label.get("close_reasons") or [])),
            }
        )
    out.sort(key=lambda row: (_safe_float(row.get("opened_at"), 0.0), _safe_text(row.get("sample_id"))))
    return out


def export_replay_dataset_bridge(
    *,
    input_path: str = "",
    output_path: str = "",
    paper_ledger_repository=None,
) -> Path:
    target = Path(output_path) if output_path else DEFAULT_OUTPUT
    if target.name in LEGACY_OUTPUT_NAMES:
        raise ValueError("replay bridge output must not overwrite legacy strategy_backtest_records.json")

    rows = build_replay_dataset_records(
        _load_phase3_records(input_path),
        paper_ledger_repository=paper_ledger_repository,
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "records": rows,
        "records_count": len(rows),
        "generated_from": "training_replay_records+paper_ledger",
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export replay/backtest JSON from phase-3 training replay records.")
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="Input training_replay_records JSON path.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output replay bridge JSON path.")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    path = export_replay_dataset_bridge(input_path=str(args.input), output_path=str(args.output))
    print(str(path))
