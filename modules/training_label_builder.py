from __future__ import annotations

import json
import argparse
import asyncio
from typing import Any, Dict, List, Optional

from modules.database import db
from modules.db_schema import PAPER_ORDERS_TABLE, PAPER_TRADE_CLOSES_TABLE, TRAINING_LABELS_TABLE
from modules.training_sample_builder import training_sample_repository


def _json_payload(value: Any) -> Optional[str]:
    if value is None:
        return None
    return json.dumps(value)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_row(row: Any) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)
    try:
        return dict(row)
    except Exception:
        pass
    if hasattr(row, "keys"):
        try:
            return {key: row[key] for key in row.keys()}
        except Exception:
            pass
    raise TypeError(f"unsupported training label row type: {type(row)!r}")


def _normalize_rows(rows: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in list(rows or []):
        normalized = _normalize_row(row)
        if normalized is not None:
            out.append(normalized)
    return out


class DatabaseTrainingLabelRepository:
    async def append_label(self, record: Dict[str, Any]) -> None:
        await db.execute(
            f"""
            INSERT INTO {TRAINING_LABELS_TABLE}
            (
                sample_id, analysis_run_id, ca, label_kind, label_source,
                position_ids, close_legs, close_reasons,
                realized_pnl_sol, realized_return_pct, metadata
            )
            VALUES
            (
                $1, $2, $3, $4, $5,
                $6::jsonb, $7, $8::jsonb,
                $9, $10, $11::jsonb
            )
            ON CONFLICT (sample_id) DO UPDATE
            SET analysis_run_id = EXCLUDED.analysis_run_id,
                ca = EXCLUDED.ca,
                label_kind = EXCLUDED.label_kind,
                label_source = EXCLUDED.label_source,
                position_ids = EXCLUDED.position_ids,
                close_legs = EXCLUDED.close_legs,
                close_reasons = EXCLUDED.close_reasons,
                realized_pnl_sol = EXCLUDED.realized_pnl_sol,
                realized_return_pct = EXCLUDED.realized_return_pct,
                metadata = EXCLUDED.metadata
            """,
            record.get("sample_id"),
            record.get("analysis_run_id"),
            record.get("ca"),
            record.get("label_kind"),
            record.get("label_source"),
            _json_payload(record.get("position_ids") or []),
            int(record.get("close_legs") or 0),
            _json_payload(record.get("close_reasons") or []),
            record.get("realized_pnl_sol"),
            record.get("realized_return_pct"),
            _json_payload(record.get("metadata") or {}),
        )

    async def get_label(self, sample_id: str) -> Optional[Dict[str, Any]]:
        row = await db.fetchrow(
            f"""
            SELECT
                sample_id, analysis_run_id, ca, label_kind, label_source,
                position_ids, close_legs, close_reasons,
                realized_pnl_sol, realized_return_pct, metadata
            FROM {TRAINING_LABELS_TABLE}
            WHERE sample_id = $1
            """,
            _safe_text(sample_id),
        )
        return _normalize_row(row)

    async def list_labels(self) -> List[Dict[str, Any]]:
        rows = await db.fetch(
            f"""
            SELECT
                sample_id, analysis_run_id, ca, label_kind, label_source,
                position_ids, close_legs, close_reasons,
                realized_pnl_sol, realized_return_pct, metadata
            FROM {TRAINING_LABELS_TABLE}
            ORDER BY created_at ASC
            """
        )
        return _normalize_rows(rows)


class InMemoryTrainingLabelRepository:
    def __init__(self):
        self.labels: List[Dict[str, Any]] = []

    async def append_label(self, record: Dict[str, Any]) -> None:
        stored = {
            "sample_id": record.get("sample_id"),
            "analysis_run_id": record.get("analysis_run_id"),
            "ca": record.get("ca"),
            "label_kind": record.get("label_kind"),
            "label_source": record.get("label_source"),
            "position_ids": list(record.get("position_ids") or []),
            "close_legs": int(record.get("close_legs") or 0),
            "close_reasons": list(record.get("close_reasons") or []),
            "realized_pnl_sol": _safe_float(record.get("realized_pnl_sol"), 0.0),
            "realized_return_pct": _safe_float(record.get("realized_return_pct"), 0.0),
            "metadata": dict(record.get("metadata") or {}),
        }
        for idx, row in enumerate(self.labels):
            if row.get("sample_id") == stored["sample_id"]:
                self.labels[idx] = stored
                return
        self.labels.append(stored)

    async def get_label(self, sample_id: str) -> Optional[Dict[str, Any]]:
        for row in self.labels:
            if row.get("sample_id") == sample_id:
                return dict(row)
        return None

    async def list_labels(self) -> List[Dict[str, Any]]:
        return [dict(row) for row in self.labels]


training_label_repository = DatabaseTrainingLabelRepository()


async def _get_sample(sample_id: str, sample_repository=None) -> Optional[Dict[str, Any]]:
    repo = sample_repository or training_sample_repository
    if hasattr(repo, "get_sample"):
        return _normalize_row(await repo.get_sample(sample_id))
    for row in list(getattr(repo, "samples", []) or []):
        if row.get("sample_id") == sample_id:
            return dict(row)
    return None


async def _get_orders_for_sample(sample: Dict[str, Any], paper_ledger_repository=None) -> List[Dict[str, Any]]:
    analysis_run_id = sample.get("analysis_run_id")
    if analysis_run_id is None:
        return []

    repo = paper_ledger_repository
    if repo is not None and hasattr(repo, "orders"):
        return [
            dict(row)
            for row in list(getattr(repo, "orders", []) or [])
            if row.get("analysis_run_id") == analysis_run_id
            and not bool(row.get("legacy_path"))
            and _safe_text(row.get("intent")) == "open"
        ]

    rows = await db.fetch(
        f"""
        SELECT
            order_id, analysis_run_id, ca, position_id, intent, side, legacy_path
        FROM {PAPER_ORDERS_TABLE}
        WHERE analysis_run_id = $1
          AND COALESCE(legacy_path, FALSE) = FALSE
          AND intent = 'open'
        ORDER BY created_at ASC
        """,
        int(analysis_run_id),
    )
    return _normalize_rows(rows)


async def _get_trade_closes(position_ids: List[str], paper_ledger_repository=None) -> List[Dict[str, Any]]:
    if not position_ids:
        return []

    repo = paper_ledger_repository
    if repo is not None and hasattr(repo, "trade_closes"):
        keep = set(position_ids)
        return [
            dict(row)
            for row in list(getattr(repo, "trade_closes", []) or [])
            if _safe_text(row.get("position_id")) in keep and not bool(row.get("legacy_path"))
        ]

    rows = await db.fetch(
        f"""
        SELECT
            trade_close_id, position_id, order_id, fill_id, analysis_run_id, ca,
            strategy, opened_at, closed_at, close_reason, partial, close_ratio,
            entry_notional_sol, exit_notional_sol, total_fee_sol,
            realized_pnl_sol, realized_return_pct, legacy_path
        FROM {PAPER_TRADE_CLOSES_TABLE}
        WHERE position_id = ANY($1::text[])
          AND COALESCE(legacy_path, FALSE) = FALSE
        ORDER BY closed_at ASC, recorded_at ASC
        """,
        position_ids,
    )
    return _normalize_rows(rows)


def _build_no_trade_label(sample: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "sample_id": sample.get("sample_id"),
        "analysis_run_id": sample.get("analysis_run_id"),
        "ca": sample.get("ca"),
        "label_kind": "no_trade",
        "label_source": "paper_ledger",
        "position_ids": [],
        "close_legs": 0,
        "close_reasons": [],
        "realized_pnl_sol": 0.0,
        "realized_return_pct": 0.0,
        "metadata": {},
    }


def _build_no_fill_label(sample: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "sample_id": sample.get("sample_id"),
        "analysis_run_id": sample.get("analysis_run_id"),
        "ca": sample.get("ca"),
        "label_kind": "no_fill",
        "label_source": "paper_ledger",
        "position_ids": [],
        "close_legs": 0,
        "close_reasons": [],
        "realized_pnl_sol": 0.0,
        "realized_return_pct": 0.0,
        "metadata": {},
    }


def _aggregate_trade_close_label(sample: Dict[str, Any], trade_closes: List[Dict[str, Any]]) -> Dict[str, Any]:
    ordered = sorted(
        trade_closes,
        key=lambda row: (_safe_float(row.get("closed_at"), 0.0), _safe_text(row.get("trade_close_id"))),
    )
    position_ids = sorted({_safe_text(row.get("position_id")) for row in ordered if _safe_text(row.get("position_id"))})
    close_reasons: List[str] = []
    for row in ordered:
        reason = _safe_text(row.get("close_reason"))
        if reason and reason not in close_reasons:
            close_reasons.append(reason)
    total_entry_notional = sum(_safe_float(row.get("entry_notional_sol"), 0.0) for row in ordered)
    total_realized_pnl = sum(_safe_float(row.get("realized_pnl_sol"), 0.0) for row in ordered)
    realized_return_pct = (total_realized_pnl / total_entry_notional * 100.0) if total_entry_notional > 0 else 0.0
    return {
        "sample_id": sample.get("sample_id"),
        "analysis_run_id": sample.get("analysis_run_id"),
        "ca": sample.get("ca"),
        "label_kind": "trade_closed",
        "label_source": "paper_trade_closes",
        "position_ids": position_ids,
        "close_legs": len(ordered),
        "close_reasons": close_reasons,
        "realized_pnl_sol": round(total_realized_pnl, 6),
        "realized_return_pct": round(realized_return_pct, 6),
        "metadata": {},
    }


async def build_training_label_for_sample(
    *,
    sample_id: str,
    sample_repository=None,
    paper_ledger_repository=None,
    repository=None,
) -> Dict[str, Any]:
    sample = await _get_sample(sample_id, sample_repository=sample_repository)
    if not sample:
        raise RuntimeError(f"sample not found: {sample_id}")

    final_action = _safe_text(sample.get("final_action")).upper()
    if final_action != "ENTER":
        label = _build_no_trade_label(sample)
    else:
        open_orders = await _get_orders_for_sample(sample, paper_ledger_repository=paper_ledger_repository)
        position_ids = [
            _safe_text(row.get("position_id"))
            for row in open_orders
            if _safe_text(row.get("position_id"))
        ]
        if not position_ids:
            label = _build_no_fill_label(sample)
        else:
            trade_closes = await _get_trade_closes(position_ids, paper_ledger_repository=paper_ledger_repository)
            if not trade_closes:
                label = _build_no_fill_label(sample)
            else:
                label = _aggregate_trade_close_label(sample, trade_closes)

    repo = repository or training_label_repository
    await repo.append_label(label)
    return label


async def _load_samples(sample_repository=None) -> List[Dict[str, Any]]:
    repo = sample_repository or training_sample_repository
    if hasattr(repo, "list_samples"):
        return _normalize_rows(await repo.list_samples())
    return _normalize_rows(getattr(repo, "samples", []) or [])


async def async_build_training_labels(
    *,
    sample_repository=None,
    paper_ledger_repository=None,
    repository=None,
) -> List[Dict[str, Any]]:
    samples = await _load_samples(sample_repository)
    results: List[Dict[str, Any]] = []
    for sample in samples:
        sample_id = _safe_text(sample.get("sample_id"))
        if not sample_id:
            raise RuntimeError("sample_id missing from training sample")
        results.append(
            await build_training_label_for_sample(
                sample_id=sample_id,
                sample_repository=sample_repository,
                paper_ledger_repository=paper_ledger_repository,
                repository=repository,
            )
        )
    return results


def build_training_labels(
    *,
    sample_repository=None,
    paper_ledger_repository=None,
    repository=None,
) -> List[Dict[str, Any]]:
    return asyncio.run(
        async_build_training_labels(
            sample_repository=sample_repository,
            paper_ledger_repository=paper_ledger_repository,
            repository=repository,
        )
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build phase-3 training labels from training samples and paper ledger truth.")
    return parser.parse_args()


if __name__ == "__main__":
    _parse_args()
    labels = build_training_labels()
    print(str(len(labels)))
