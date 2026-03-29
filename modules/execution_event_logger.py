from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from modules.lifecycle_models import ExecutionEventRecord, LifecycleContext, TransitionRecord
from modules.lifecycle_repository import lifecycle_repository
from modules.strategy_state import (
    get_current_lifecycle_context,
    get_lifecycle_flags,
    normalize_shadow_action,
    normalize_strategy_state,
)
from modules.strategy_state_machine import assert_transition_allowed

logger = logging.getLogger("ExecutionEventLogger")


def _default_repository(repository):
    return repository or lifecycle_repository


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


async def log_state_transition(
    ca: str,
    from_state: Any,
    to_state: Any,
    *,
    action: Any = "",
    source: str = "",
    reason: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    repository=None,
    context: Optional[LifecycleContext] = None,
) -> bool:
    flags = get_lifecycle_flags()
    if not flags.enabled or not flags.db_writes_enabled:
        return False

    ctx = context or get_current_lifecycle_context() or LifecycleContext()
    normalized_from = normalize_strategy_state(from_state)
    normalized_to = normalize_strategy_state(to_state)
    normalized_action = normalize_shadow_action(action, "")
    payload = dict(ctx.metadata or {})
    payload.update(dict(metadata or {}))

    try:
        assert_transition_allowed(normalized_from, normalized_to)
    except ValueError:
        if flags.strict_transitions:
            raise
        payload.setdefault("invalid_transition", True)

    repo = _default_repository(repository)
    try:
        await repo.append_state_transition(
            TransitionRecord(
                ca=str(ca or "").strip(),
                from_state=normalized_from,
                to_state=normalized_to,
                action=normalized_action,
                source=_safe_text(source) or _safe_text(ctx.source),
                path_kind=_safe_text(ctx.path_kind),
                analysis_run_id=ctx.analysis_run_id,
                legacy_path=bool(ctx.legacy_path),
                transition_reason=_safe_text(reason),
                metadata=payload,
            )
        )
        return True
    except Exception as exc:
        logger.warning("state transition append failed | ca=%s | err=%s", ca, exc, exc_info=True)
        return False


async def log_execution_event(
    ca: str,
    event_type: Any,
    *,
    action: Any = "",
    signal_state: Any = "",
    status: str = "",
    source: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    repository=None,
    context: Optional[LifecycleContext] = None,
) -> bool:
    flags = get_lifecycle_flags()
    if not flags.enabled or not flags.db_writes_enabled:
        return False

    ctx = context or get_current_lifecycle_context() or LifecycleContext()
    payload = dict(ctx.metadata or {})
    payload.update(dict(metadata or {}))
    repo = _default_repository(repository)
    try:
        await repo.append_execution_event(
            ExecutionEventRecord(
                ca=str(ca or "").strip(),
                event_type=_safe_text(event_type),
                action=normalize_shadow_action(action, ""),
                signal_state=normalize_strategy_state(signal_state, "") if signal_state else "",
                status=_safe_text(status),
                source=_safe_text(source) or _safe_text(ctx.source),
                path_kind=_safe_text(ctx.path_kind),
                analysis_run_id=ctx.analysis_run_id,
                legacy_path=bool(ctx.legacy_path),
                metadata=payload,
            )
        )
        return True
    except Exception as exc:
        logger.warning("execution event append failed | ca=%s | err=%s", ca, exc, exc_info=True)
        return False


def log_execution_event_sync(
    ca: str,
    event_type: Any,
    *,
    action: Any = "",
    signal_state: Any = "",
    status: str = "",
    source: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    repository=None,
    context: Optional[LifecycleContext] = None,
) -> None:
    flags = get_lifecycle_flags()
    if not flags.enabled or not flags.db_writes_enabled:
        return

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    loop.create_task(
        log_execution_event(
            ca,
            event_type,
            action=action,
            signal_state=signal_state,
            status=status,
            source=source,
            metadata=metadata,
            repository=repository,
            context=context,
        )
    )
