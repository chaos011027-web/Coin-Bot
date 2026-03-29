from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any, Dict, Optional, Tuple

from modules.lifecycle_models import AnalysisRunRecord, DecisionChain, LifecycleContext
from modules.lifecycle_repository import lifecycle_repository
from modules.strategy_state import (
    AnalysisPathKind,
    DecisionEventType,
    get_lifecycle_flags,
    reset_current_lifecycle_context,
    set_current_lifecycle_context,
)

logger = logging.getLogger("DecisionEventLogger")


def _default_repository(repository):
    return repository or lifecycle_repository


def _safe_source(value: str) -> str:
    return str(value or "").strip()


async def start_analysis_run(
    ca: str,
    *,
    source: str,
    path_kind: str,
    chat_id: Optional[int] = None,
    message_id: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None,
    legacy_path: bool = False,
    repository=None,
) -> Tuple[LifecycleContext, Optional[object]]:
    repo = _default_repository(repository)
    flags = get_lifecycle_flags()
    context = LifecycleContext(
        path_kind=path_kind or AnalysisPathKind.MAIN_STATE_MACHINE.value,
        source=_safe_source(source),
        chat_id=chat_id,
        message_id=message_id,
        legacy_path=bool(legacy_path),
        metadata=dict(metadata or {}),
    )
    run_id = None

    if flags.enabled and flags.db_writes_enabled:
        try:
            run_id = await repo.create_analysis_run(
                AnalysisRunRecord(
                    ca=str(ca or "").strip(),
                    source=context.source,
                    path_kind=context.path_kind,
                    chat_id=chat_id,
                    message_id=message_id,
                    legacy_path=context.legacy_path,
                    metadata=context.metadata,
                )
            )
        except Exception as exc:
            logger.warning("analysis run start failed | ca=%s | err=%s", ca, exc, exc_info=True)

    if run_id is not None:
        context = replace(context, analysis_run_id=int(run_id))
    token = set_current_lifecycle_context(context)
    return context, token


async def finish_analysis_run(
    context: Optional[LifecycleContext],
    *,
    status: str,
    metadata: Optional[Dict[str, Any]] = None,
    repository=None,
) -> None:
    flags = get_lifecycle_flags()
    if not flags.enabled or not flags.db_writes_enabled:
        return
    if not context or context.analysis_run_id is None:
        return

    repo = _default_repository(repository)
    try:
        await repo.finish_analysis_run(
            int(context.analysis_run_id),
            status=str(status or "COMPLETED"),
            metadata=dict(metadata or {}),
        )
    except Exception as exc:
        logger.warning(
            "analysis run finish failed | run_id=%s | err=%s",
            context.analysis_run_id,
            exc,
            exc_info=True,
        )


def end_analysis_context(token: Optional[object]) -> None:
    if token is not None:
        reset_current_lifecycle_context(token)


async def log_decision_chain(
    ca: str,
    chain: DecisionChain,
    *,
    event_type: str = DecisionEventType.FINAL_ACTION.value,
    repository=None,
    context: Optional[LifecycleContext] = None,
) -> bool:
    flags = get_lifecycle_flags()
    if not flags.enabled or not flags.db_writes_enabled:
        return False

    ctx = context or LifecycleContext()
    if ctx.path_kind == "" or ctx.source == "":
        from modules.strategy_state import get_current_lifecycle_context

        ctx = get_current_lifecycle_context() or ctx

    repo = _default_repository(repository)
    try:
        await repo.append_decision_event(
            ca=str(ca or "").strip(),
            event_type=str(event_type or DecisionEventType.FINAL_ACTION.value),
            chain=chain,
            analysis_run_id=ctx.analysis_run_id,
            source=_safe_source(ctx.source),
            path_kind=_safe_source(ctx.path_kind),
            legacy_path=bool(ctx.legacy_path),
        )
        return True
    except Exception as exc:
        logger.warning("decision event append failed | ca=%s | err=%s", ca, exc, exc_info=True)
        return False
