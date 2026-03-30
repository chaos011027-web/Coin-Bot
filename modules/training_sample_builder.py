from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, Dict, List, Optional
from uuid import uuid4

from modules.database import db
from modules.db_schema import TRAINING_SAMPLES_TABLE
from modules.lifecycle_models import LifecycleContext
from modules.strategy_state import get_current_lifecycle_context


def _json_payload(value: Any) -> Optional[str]:
    if value is None:
        return None
    return json.dumps(value)


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
    raise TypeError(f"unsupported training sample row type: {type(row)!r}")


def _normalize_rows(rows: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in list(rows or []):
        normalized = _normalize_row(row)
        if normalized is not None:
            out.append(normalized)
    return out


def _freeze_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _freeze_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_freeze_value(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return deepcopy(value)
    return str(value)


def _current_context(context: Optional[LifecycleContext] = None) -> LifecycleContext:
    return context or get_current_lifecycle_context() or LifecycleContext()


def _merged_metadata(ctx: LifecycleContext, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload = dict(ctx.metadata or {})
    payload.update(dict(metadata or {}))
    return payload


def _skip_sample(ctx: LifecycleContext) -> bool:
    return bool(ctx.legacy_path)


class DatabaseTrainingSampleRepository:
    async def append_sample(self, record: Dict[str, Any]) -> None:
        await db.execute(
            f"""
            INSERT INTO {TRAINING_SAMPLES_TABLE}
            (
                sample_id, analysis_run_id, ca, final_action, strategy_id, trace_link,
                path_kind, source, legacy_path, frozen_features, feature_sources, metadata
            )
            VALUES
            (
                $1, $2, $3, $4, $5, $6,
                $7, $8, $9, $10::jsonb, $11::jsonb, $12::jsonb
            )
            ON CONFLICT (sample_id) DO NOTHING
            """,
            record.get("sample_id"),
            record.get("analysis_run_id"),
            record.get("ca"),
            record.get("final_action"),
            record.get("strategy_id"),
            record.get("trace_link"),
            record.get("path_kind"),
            record.get("source"),
            bool(record.get("legacy_path")),
            _json_payload(record.get("frozen_features") or {}),
            _json_payload(record.get("feature_sources") or {}),
            _json_payload(record.get("metadata") or {}),
        )

    async def get_sample(self, sample_id: str) -> Optional[Dict[str, Any]]:
        row = await db.fetchrow(
            f"""
            SELECT
                sample_id, analysis_run_id, ca, final_action, strategy_id, trace_link,
                path_kind, source, legacy_path, frozen_features, feature_sources, metadata
            FROM {TRAINING_SAMPLES_TABLE}
            WHERE sample_id = $1
            """,
            str(sample_id or "").strip(),
        )
        return _normalize_row(row)

    async def list_samples(self) -> List[Dict[str, Any]]:
        rows = await db.fetch(
            f"""
            SELECT
                sample_id, analysis_run_id, ca, final_action, strategy_id, trace_link,
                path_kind, source, legacy_path, frozen_features, feature_sources, metadata
            FROM {TRAINING_SAMPLES_TABLE}
            WHERE COALESCE(legacy_path, FALSE) = FALSE
            ORDER BY created_at ASC
            """
        )
        return _normalize_rows(rows)


class InMemoryTrainingSampleRepository:
    def __init__(self):
        self.samples: List[Dict[str, Any]] = []

    async def append_sample(self, record: Dict[str, Any]) -> None:
        self.samples.append(
            {
                "sample_id": record.get("sample_id"),
                "analysis_run_id": record.get("analysis_run_id"),
                "ca": record.get("ca"),
                "final_action": record.get("final_action"),
                "strategy_id": record.get("strategy_id"),
                "trace_link": record.get("trace_link"),
                "path_kind": record.get("path_kind"),
                "source": record.get("source"),
                "legacy_path": bool(record.get("legacy_path")),
                "frozen_features": _freeze_value(record.get("frozen_features") or {}),
                "feature_sources": _freeze_value(record.get("feature_sources") or {}),
                "metadata": _freeze_value(record.get("metadata") or {}),
            }
        )

    async def get_sample(self, sample_id: str) -> Optional[Dict[str, Any]]:
        for row in self.samples:
            if row.get("sample_id") == sample_id:
                return dict(row)
        return None

    async def list_samples(self) -> List[Dict[str, Any]]:
        return [dict(row) for row in self.samples if not bool(row.get("legacy_path"))]


training_sample_repository = DatabaseTrainingSampleRepository()


async def create_training_sample(
    *,
    ca: str,
    final_action: str,
    strategy_id: str,
    frozen_features: Optional[Dict[str, Any]],
    feature_sources: Optional[Dict[str, Any]],
    metadata: Optional[Dict[str, Any]] = None,
    repository=None,
    context: Optional[LifecycleContext] = None,
) -> Optional[str]:
    ctx = _current_context(context)
    if _skip_sample(ctx):
        return None

    sample_id = f"sample_{uuid4().hex}"
    record = {
        "sample_id": sample_id,
        "analysis_run_id": ctx.analysis_run_id,
        "ca": _safe_text(ca),
        "final_action": _safe_text(final_action),
        "strategy_id": _safe_text(strategy_id),
        "trace_link": _safe_text((ctx.metadata or {}).get("trace_link")),
        "path_kind": _safe_text(ctx.path_kind),
        "source": _safe_text(ctx.source),
        "legacy_path": bool(ctx.legacy_path),
        "frozen_features": _freeze_value(frozen_features or {}),
        "feature_sources": _freeze_value(feature_sources or {}),
        "metadata": _freeze_value(_merged_metadata(ctx, metadata)),
    }
    repo = repository or training_sample_repository
    await repo.append_sample(record)
    return sample_id
