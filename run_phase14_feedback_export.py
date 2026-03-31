from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List

from modules.database import db
from modules.db_schema import (
    DECISION_EVENTS_TABLE,
    EXECUTION_EVENTS_TABLE,
    PAPER_TRADE_CLOSES_TABLE,
    STATE_TRANSITIONS_TABLE,
)
from modules.feedback_export_bridge import export_feedback_export_records
from modules.phase14_feedback_manifest import build_phase14_feedback_manifest, write_phase14_feedback_manifest
from modules.lifecycle_repository import lifecycle_repository
from modules.paper_ledger_repository import paper_ledger_repository
from modules.training_label_builder import training_label_repository
from modules.training_sample_builder import training_sample_repository


DEFAULT_DATA_DIR = Path("data")
DEFAULT_RECORDS_OUTPUT_NAME = "feedback_export_records.json"
DEFAULT_MANIFEST_OUTPUT_NAME = "phase14_feedback_manifest.json"


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_row(row: Any) -> Dict[str, Any]:
    if isinstance(row, dict):
        return dict(row)
    try:
        return dict(row)
    except Exception:
        pass
    if hasattr(row, "keys"):
        return {key: row[key] for key in row.keys()}
    raise TypeError(f"unsupported phase14 export row type: {type(row)!r}")


def _normalize_rows(rows: Any) -> List[Dict[str, Any]]:
    return [_normalize_row(row) for row in list(rows or [])]


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def _resolve_data_dir(data_dir: str = "data") -> Path:
    return Path(_safe_text(data_dir) or str(DEFAULT_DATA_DIR)).resolve()


async def _load_sample_rows() -> List[Dict[str, Any]]:
    repo = training_sample_repository
    if hasattr(repo, "list_samples"):
        return _normalize_rows(await repo.list_samples())
    return _normalize_rows(getattr(repo, "samples", []) or [])


async def _load_label_rows() -> List[Dict[str, Any]]:
    repo = training_label_repository
    if hasattr(repo, "list_labels"):
        return _normalize_rows(await repo.list_labels())
    return _normalize_rows(getattr(repo, "labels", []) or [])


async def _load_decision_event_rows() -> List[Dict[str, Any]]:
    repo = lifecycle_repository
    if hasattr(repo, "decision_events"):
        return _normalize_rows(getattr(repo, "decision_events", []) or [])
    try:
        rows = await db.fetch(
            f"""
            SELECT
                analysis_run_id, ca, event_type, candidate_action, ai_verdict,
                risk_adjusted_action, final_action, strategy_id, score, reason,
                risk_flags, source, path_kind, legacy_path, metadata, created_at
            FROM {DECISION_EVENTS_TABLE}
            WHERE COALESCE(legacy_path, FALSE) = FALSE
            ORDER BY created_at ASC
            """
        )
    except Exception as exc:
        raise RuntimeError(f"decision events load failed: {exc}") from exc
    return _normalize_rows(rows)


async def _load_execution_event_rows() -> List[Dict[str, Any]]:
    repo = lifecycle_repository
    if hasattr(repo, "execution_events"):
        return _normalize_rows(getattr(repo, "execution_events", []) or [])
    try:
        rows = await db.fetch(
            f"""
            SELECT
                analysis_run_id, ca, event_type, action, signal_state, status,
                source, path_kind, legacy_path, metadata, created_at
            FROM {EXECUTION_EVENTS_TABLE}
            WHERE COALESCE(legacy_path, FALSE) = FALSE
            ORDER BY created_at ASC
            """
        )
    except Exception as exc:
        raise RuntimeError(f"execution events load failed: {exc}") from exc
    return _normalize_rows(rows)


async def _load_state_transition_rows() -> List[Dict[str, Any]]:
    repo = lifecycle_repository
    if hasattr(repo, "strategy_state_transitions"):
        return _normalize_rows(getattr(repo, "strategy_state_transitions", []) or [])
    try:
        rows = await db.fetch(
            f"""
            SELECT
                analysis_run_id, ca, from_state, to_state, action,
                source, path_kind, legacy_path, transition_reason, metadata, created_at
            FROM {STATE_TRANSITIONS_TABLE}
            WHERE COALESCE(legacy_path, FALSE) = FALSE
            ORDER BY created_at ASC
            """
        )
    except Exception as exc:
        raise RuntimeError(f"strategy state transitions load failed: {exc}") from exc
    return _normalize_rows(rows)


async def _load_trade_close_rows() -> List[Dict[str, Any]]:
    repo = paper_ledger_repository
    if hasattr(repo, "trade_closes"):
        return _normalize_rows(getattr(repo, "trade_closes", []) or [])
    try:
        rows = await db.fetch(
            f"""
            SELECT
                trade_close_id, position_id, order_id, fill_id, analysis_run_id, ca,
                strategy, opened_at, closed_at, close_reason, partial, close_ratio,
                entry_notional_sol, exit_notional_sol, total_fee_sol,
                realized_pnl_sol, realized_return_pct, source, path_kind,
                legacy_path, metadata, recorded_at
            FROM {PAPER_TRADE_CLOSES_TABLE}
            WHERE COALESCE(legacy_path, FALSE) = FALSE
            ORDER BY recorded_at ASC, closed_at ASC
            """
        )
    except Exception as exc:
        raise RuntimeError(f"paper trade closes load failed: {exc}") from exc
    return _normalize_rows(rows)


def _safe_json_obj(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def _derive_sizing_decision_rows(
    *,
    sample_rows: List[Dict[str, Any]],
    execution_event_rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    sample_identity_map: Dict[tuple[int, str], Dict[str, Any]] = {}
    for sample in sample_rows:
        analysis_run_id = sample.get("analysis_run_id")
        ca = _safe_text(sample.get("ca"))
        if analysis_run_id is None or not ca:
            continue
        sample_identity_map[(int(analysis_run_id), ca)] = sample

    rows: List[Dict[str, Any]] = []
    for raw in execution_event_rows:
        row = _normalize_row(raw)
        metadata = _safe_json_obj(row.get("metadata"))
        analysis_run_id = row.get("analysis_run_id")
        ca = _safe_text(row.get("ca"))
        if analysis_run_id is None or not ca:
            continue

        action = _safe_text(row.get("action")).upper()
        event_type = _safe_text(row.get("event_type")).upper()
        signal_state = _safe_text(row.get("signal_state")).upper()
        budget_reason = _safe_text(metadata.get("budget_reason"))
        size_clamp_reason = _safe_text(metadata.get("size_clamp_reason"))

        is_entry_like = action == "ENTER" or event_type == "PAPER_OPEN" or signal_state == "ENTERED"
        is_add_like = action == "ADD" or event_type == "PAPER_ADD"
        if not is_entry_like and not is_add_like:
            continue

        sample_row = sample_identity_map.get((int(analysis_run_id), ca), {})
        row_state = "ARMED" if is_entry_like else "MANAGING"
        requested_entry_size = 0.0
        requested_max_add_size = 0.0
        if is_entry_like:
            requested_entry_size = _safe_float(
                metadata.get("requested_entry_size")
                or metadata.get("allocated_sol")
                or 0.0
            )
        if is_add_like:
            requested_max_add_size = _safe_float(
                metadata.get("requested_max_add_size")
                or metadata.get("effective_add_size")
                or metadata.get("allocated_sol")
                or 0.0
            )

        rows.append(
            {
                "sample_id": _safe_text(sample_row.get("sample_id")),
                "analysis_run_id": int(analysis_run_id),
                "ca": ca,
                "state": row_state,
                "new_entry_size": requested_entry_size,
                "max_add_size": requested_max_add_size,
                "budget_reason": budget_reason,
                "size_clamp_reason": size_clamp_reason,
                "hard_veto_risk_flags": list(metadata.get("hard_veto_risk_flags") or []),
                "clamp_risk_flags": list(metadata.get("clamp_risk_flags") or []),
                "created_at": row.get("created_at") or row.get("recorded_at"),
            }
        )
    return rows


def _load_records_payload(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("feedback export records payload must be an object")
    if not isinstance(payload.get("records"), list):
        raise RuntimeError("feedback export records payload missing records")
    return payload


async def _async_collect_feedback_inputs() -> Dict[str, List[Dict[str, Any]]]:
    sample_rows = await _load_sample_rows()
    if not sample_rows:
        raise RuntimeError("training samples missing")

    label_rows = await _load_label_rows()
    if not label_rows:
        raise RuntimeError("training labels missing")

    decision_event_rows = await _load_decision_event_rows()
    execution_event_rows = await _load_execution_event_rows()
    state_transition_rows = await _load_state_transition_rows()
    trade_close_rows = await _load_trade_close_rows()
    sizing_decision_rows = _derive_sizing_decision_rows(
        sample_rows=sample_rows,
        execution_event_rows=execution_event_rows,
    )

    return {
        "sample_rows": sample_rows,
        "label_rows": label_rows,
        "decision_event_rows": decision_event_rows,
        "execution_event_rows": execution_event_rows,
        "state_transition_rows": state_transition_rows,
        "trade_close_rows": trade_close_rows,
        "sizing_decision_rows": sizing_decision_rows,
    }


def run_phase14_feedback_export(data_dir="data") -> dict:
    resolved_data_dir = _resolve_data_dir(str(data_dir))
    resolved_data_dir.mkdir(parents=True, exist_ok=True)
    inputs = asyncio.run(_async_collect_feedback_inputs())

    records_path = export_feedback_export_records(
        output_path=str((resolved_data_dir / DEFAULT_RECORDS_OUTPUT_NAME).resolve()),
        sample_rows=list(inputs.get("sample_rows") or []),
        label_rows=list(inputs.get("label_rows") or []),
        decision_event_rows=list(inputs.get("decision_event_rows") or []),
        execution_event_rows=list(inputs.get("execution_event_rows") or []),
        state_transition_rows=list(inputs.get("state_transition_rows") or []),
        trade_close_rows=list(inputs.get("trade_close_rows") or []),
        sizing_decision_rows=list(inputs.get("sizing_decision_rows") or []),
    ).resolve()

    records_payload = _load_records_payload(records_path)
    manifest = build_phase14_feedback_manifest(
        records=[_normalize_row(row) for row in list(records_payload.get("records") or [])],
        records_path=str(records_path),
    )
    manifest_path = write_phase14_feedback_manifest(
        manifest,
        output_path=str((resolved_data_dir / DEFAULT_MANIFEST_OUTPUT_NAME).resolve()),
    )

    return {
        "status": "success",
        "feedback_export_records_path": str(records_path),
        "feedback_manifest_path": str(manifest_path),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run phase14 feedback export over phase13 feedback sidecars.")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    result = run_phase14_feedback_export(data_dir=str(args.data_dir))
    print(json.dumps(result, ensure_ascii=False, indent=2))
