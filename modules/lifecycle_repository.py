from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from modules.database import db
from modules.lifecycle_models import AnalysisRunRecord, DecisionChain, ExecutionEventRecord, TransitionRecord

logger = logging.getLogger("LifecycleRepository")


def _json_payload(value: Any) -> Optional[str]:
    if value is None:
        return None
    return json.dumps(value)


class DatabaseLifecycleRepository:
    async def create_analysis_run(self, record: AnalysisRunRecord) -> Optional[int]:
        row = await db.fetchrow(
            """
            INSERT INTO analysis_runs
            (
                ca, source, path_kind, status, chat_id, message_id,
                legacy_path, metadata
            )
            VALUES
            (
                $1, $2, $3, $4, $5, $6, $7, $8::jsonb
            )
            RETURNING id
            """,
            record.ca,
            record.source,
            record.path_kind,
            record.status,
            record.chat_id,
            record.message_id,
            bool(record.legacy_path),
            _json_payload(record.metadata),
        )
        if isinstance(row, dict):
            return int(row.get("id")) if row.get("id") is not None else None
        return int(row["id"]) if row and row.get("id") is not None else None

    async def finish_analysis_run(
        self,
        analysis_run_id: int,
        *,
        status: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        await db.execute(
            """
            UPDATE analysis_runs
            SET status = $2,
                metadata = COALESCE(metadata, '{}'::jsonb) || COALESCE($3::jsonb, '{}'::jsonb),
                finished_at = NOW()
            WHERE id = $1
            """,
            int(analysis_run_id),
            str(status or "COMPLETED"),
            _json_payload(metadata or {}),
        )

    async def append_state_transition(self, record: TransitionRecord) -> None:
        await db.execute(
            """
            INSERT INTO strategy_state_transitions
            (
                analysis_run_id, ca, from_state, to_state, action,
                source, path_kind, legacy_path, transition_reason, metadata
            )
            VALUES
            (
                $1, $2, $3, $4, $5,
                $6, $7, $8, $9, $10::jsonb
            )
            """,
            record.analysis_run_id,
            record.ca,
            record.from_state,
            record.to_state,
            record.action or "",
            record.source or "",
            record.path_kind or "",
            bool(record.legacy_path),
            record.transition_reason or "",
            _json_payload(record.metadata or {}),
        )

    async def append_decision_event(
        self,
        *,
        ca: str,
        event_type: str,
        chain: DecisionChain,
        analysis_run_id: Optional[int],
        source: str,
        path_kind: str,
        legacy_path: bool,
    ) -> None:
        await db.execute(
            """
            INSERT INTO decision_events
            (
                analysis_run_id, ca, event_type, candidate_action, ai_verdict,
                risk_adjusted_action, final_action, strategy_id, score, reason,
                risk_flags, source, path_kind, legacy_path, metadata
            )
            VALUES
            (
                $1, $2, $3, $4, $5,
                $6, $7, $8, $9, $10,
                $11::jsonb, $12, $13, $14, $15::jsonb
            )
            """,
            analysis_run_id,
            ca,
            event_type,
            chain.candidate_action,
            chain.ai_verdict,
            chain.risk_adjusted_action,
            chain.final_action,
            chain.strategy_id or "",
            chain.score,
            chain.reason or "",
            _json_payload(chain.risk_flags or []),
            source or "",
            path_kind or "",
            bool(legacy_path),
            _json_payload(chain.metadata or {}),
        )

    async def append_execution_event(self, record: ExecutionEventRecord) -> None:
        await db.execute(
            """
            INSERT INTO execution_events
            (
                analysis_run_id, ca, event_type, action, signal_state, status,
                source, path_kind, legacy_path, metadata
            )
            VALUES
            (
                $1, $2, $3, $4, $5, $6,
                $7, $8, $9, $10::jsonb
            )
            """,
            record.analysis_run_id,
            record.ca,
            record.event_type,
            record.action or "",
            record.signal_state or "",
            record.status or "",
            record.source or "",
            record.path_kind or "",
            bool(record.legacy_path),
            _json_payload(record.metadata or {}),
        )


class InMemoryLifecycleRepository:
    def __init__(self):
        self.analysis_runs: List[Dict[str, Any]] = []
        self.strategy_state_transitions: List[Dict[str, Any]] = []
        self.decision_events: List[Dict[str, Any]] = []
        self.execution_events: List[Dict[str, Any]] = []
        self._next_analysis_run_id = 1

    async def create_analysis_run(self, record: AnalysisRunRecord) -> Optional[int]:
        run_id = self._next_analysis_run_id
        self._next_analysis_run_id += 1
        row = {
            "id": run_id,
            "ca": record.ca,
            "source": record.source,
            "path_kind": record.path_kind,
            "status": record.status,
            "chat_id": record.chat_id,
            "message_id": record.message_id,
            "legacy_path": record.legacy_path,
            "metadata": dict(record.metadata or {}),
        }
        self.analysis_runs.append(row)
        return run_id

    async def finish_analysis_run(
        self,
        analysis_run_id: int,
        *,
        status: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        for row in self.analysis_runs:
            if row.get("id") == analysis_run_id:
                row["status"] = status
                merged = dict(row.get("metadata") or {})
                if metadata:
                    merged.update(metadata)
                row["metadata"] = merged
                return

    async def append_state_transition(self, record: TransitionRecord) -> None:
        self.strategy_state_transitions.append(
            {
                "analysis_run_id": record.analysis_run_id,
                "ca": record.ca,
                "from_state": record.from_state,
                "to_state": record.to_state,
                "action": record.action,
                "source": record.source,
                "path_kind": record.path_kind,
                "legacy_path": record.legacy_path,
                "transition_reason": record.transition_reason,
                "metadata": dict(record.metadata or {}),
            }
        )

    async def append_decision_event(
        self,
        *,
        ca: str,
        event_type: str,
        chain: DecisionChain,
        analysis_run_id: Optional[int],
        source: str,
        path_kind: str,
        legacy_path: bool,
    ) -> None:
        self.decision_events.append(
            {
                "analysis_run_id": analysis_run_id,
                "ca": ca,
                "event_type": event_type,
                "candidate_action": chain.candidate_action,
                "ai_verdict": chain.ai_verdict,
                "risk_adjusted_action": chain.risk_adjusted_action,
                "final_action": chain.final_action,
                "strategy_id": chain.strategy_id,
                "score": chain.score,
                "reason": chain.reason,
                "risk_flags": list(chain.risk_flags or []),
                "source": source,
                "path_kind": path_kind,
                "legacy_path": legacy_path,
                "metadata": dict(chain.metadata or {}),
            }
        )

    async def append_execution_event(self, record: ExecutionEventRecord) -> None:
        self.execution_events.append(
            {
                "analysis_run_id": record.analysis_run_id,
                "ca": record.ca,
                "event_type": record.event_type,
                "action": record.action,
                "signal_state": record.signal_state,
                "status": record.status,
                "source": record.source,
                "path_kind": record.path_kind,
                "legacy_path": record.legacy_path,
                "metadata": dict(record.metadata or {}),
            }
        )


lifecycle_repository = DatabaseLifecycleRepository()
