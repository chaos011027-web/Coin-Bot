from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Iterator, Optional

from modules.lifecycle_models import LifecycleContext


class _StrEnum(str, Enum):
    pass


class StrategySignalState(_StrEnum):
    NEW_SIGNAL = "NEW_SIGNAL"
    OBSERVING = "OBSERVING"
    WATCH = "WATCH"
    ARMED = "ARMED"
    PROBE = "PROBE"
    ENTER_PENDING = "ENTER_PENDING"
    ENTERED = "ENTERED"
    MANAGING = "MANAGING"
    EXIT_PENDING = "EXIT_PENDING"
    EXITED = "EXITED"
    REJECTED = "REJECTED"
    BLOCKED = "BLOCKED"
    INVALIDATED = "INVALIDATED"


class StrategyAction(_StrEnum):
    PASS = "PASS"
    WATCH = "WATCH"
    PROBE = "PROBE"
    ENTER = "ENTER"
    ADD = "ADD"
    REDUCE = "REDUCE"
    EXIT = "EXIT"
    HOLD = "HOLD"
    REJECT = "REJECT"


class DecisionEventType(_StrEnum):
    FINAL_ACTION = "FINAL_ACTION"
    LEGACY_PATH_MARK = "LEGACY_PATH_MARK"


class ExecutionEventType(_StrEnum):
    EXECUTION_TRANSITION = "EXECUTION_TRANSITION"
    TP_TRACKER_OBSERVE = "TP_TRACKER_OBSERVE"
    TP_TRACKER_ARM = "TP_TRACKER_ARM"
    TP_TRACKER_ENTER = "TP_TRACKER_ENTER"
    TP_TRACKER_RESET = "TP_TRACKER_RESET"
    TP_TRACKER_CLOSE = "TP_TRACKER_CLOSE"
    TP_TRACKER_TP = "TP_TRACKER_TP"
    PAPER_OPEN = "PAPER_OPEN"
    PAPER_CLOSE = "PAPER_CLOSE"
    PAPER_TP = "PAPER_TP"


class AnalysisPathKind(_StrEnum):
    FAST_SIGNAL_INIT = "fast_signal_init"
    MAIN_STATE_MACHINE = "main_state_machine"
    LEGACY_DIRECT_ENTER = "legacy_direct_enter"
    PRICE_MONITOR = "price_monitor"
    TP_TRACKER = "tp_tracker"
    PAPER_PORTFOLIO = "paper_portfolio"


@dataclass(frozen=True)
class LifecycleFlags:
    enabled: bool = False
    strict_transitions: bool = False
    db_writes_enabled: bool = True


_ACTION_ALIASES: Dict[str, str] = {
    "BUY": StrategyAction.ENTER.value,
    "SELL": StrategyAction.EXIT.value,
    "HOLD": StrategyAction.HOLD.value,
}

_RUNTIME_ACTION_FALLBACKS: Dict[str, str] = {
    StrategyAction.HOLD.value: StrategyAction.WATCH.value,
    StrategyAction.ADD.value: StrategyAction.ENTER.value,
    StrategyAction.REDUCE.value: StrategyAction.PROBE.value,
    StrategyAction.REJECT.value: StrategyAction.PASS.value,
}

_STATE_ALIASES: Dict[str, str] = {
    "NEW": StrategySignalState.NEW_SIGNAL.value,
    "ACTIVE": StrategySignalState.ENTERED.value,
    "WIN": StrategySignalState.EXITED.value,
    "LOSS": StrategySignalState.EXITED.value,
}

_STATE_VALUES = {item.value for item in StrategySignalState}
_ACTION_VALUES = {item.value for item in StrategyAction}
_RUNTIME_ACTION_VALUES = {
    StrategyAction.PASS.value,
    StrategyAction.WATCH.value,
    StrategyAction.PROBE.value,
    StrategyAction.ENTER.value,
    StrategyAction.EXIT.value,
}
PRIMARY_STRATEGY_STATES = (
    StrategySignalState.NEW_SIGNAL.value,
    StrategySignalState.OBSERVING.value,
    StrategySignalState.ARMED.value,
    StrategySignalState.ENTERED.value,
    StrategySignalState.MANAGING.value,
    StrategySignalState.EXITED.value,
    StrategySignalState.REJECTED.value,
)
PRIMARY_STRATEGY_STATE_VALUES = set(PRIMARY_STRATEGY_STATES)

_CURRENT_CONTEXT: ContextVar[Optional[LifecycleContext]] = ContextVar(
    "strategy_lifecycle_context",
    default=None,
)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def get_lifecycle_flags() -> LifecycleFlags:
    return LifecycleFlags(
        enabled=_env_bool("SHADOW_LIFECYCLE_ENABLED", False),
        strict_transitions=_env_bool("SHADOW_LIFECYCLE_STRICT_TRANSITIONS", False),
        db_writes_enabled=_env_bool("SHADOW_LIFECYCLE_DB_WRITES_ENABLED", True),
    )


def normalize_strategy_state(state: Any, default: str = StrategySignalState.NEW_SIGNAL.value) -> str:
    text = str(state or default).upper().strip()
    text = _STATE_ALIASES.get(text, text)
    return text if text in _STATE_VALUES else default


def normalize_primary_strategy_state(
    state: Any,
    default: str = StrategySignalState.NEW_SIGNAL.value,
) -> str:
    normalized = normalize_strategy_state(state, "")
    if normalized in PRIMARY_STRATEGY_STATE_VALUES:
        return normalized

    default_text = str(default or "").upper().strip()
    default_text = _STATE_ALIASES.get(default_text, default_text)
    if default_text in PRIMARY_STRATEGY_STATE_VALUES:
        return default_text
    return StrategySignalState.NEW_SIGNAL.value


def is_primary_strategy_state(state: Any) -> bool:
    return normalize_strategy_state(state, "") in PRIMARY_STRATEGY_STATE_VALUES


def normalize_shadow_action(action: Any, default: str = StrategyAction.WATCH.value) -> str:
    text = str(action or default).upper().strip()
    text = _ACTION_ALIASES.get(text, text)
    return text if text in _ACTION_VALUES else default


def normalize_runtime_action(action: Any, default: str = StrategyAction.WATCH.value) -> str:
    text = normalize_shadow_action(action, default)
    text = _RUNTIME_ACTION_FALLBACKS.get(text, text)
    return text if text in _RUNTIME_ACTION_VALUES else default


def get_current_lifecycle_context() -> Optional[LifecycleContext]:
    return _CURRENT_CONTEXT.get()


def set_current_lifecycle_context(context: LifecycleContext) -> Token:
    return _CURRENT_CONTEXT.set(context)


def reset_current_lifecycle_context(token: Token) -> None:
    _CURRENT_CONTEXT.reset(token)


def derive_lifecycle_context(
    *,
    path_kind: Optional[str] = None,
    source: Optional[str] = None,
    analysis_run_id: Optional[int] = None,
    chat_id: Optional[int] = None,
    message_id: Optional[int] = None,
    legacy_path: Optional[bool] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> LifecycleContext:
    base = get_current_lifecycle_context() or LifecycleContext()
    merged_metadata = dict(base.metadata or {})
    if metadata:
        merged_metadata.update(metadata)
    return LifecycleContext(
        path_kind=path_kind if path_kind is not None else base.path_kind,
        source=source if source is not None else base.source,
        analysis_run_id=analysis_run_id if analysis_run_id is not None else base.analysis_run_id,
        chat_id=chat_id if chat_id is not None else base.chat_id,
        message_id=message_id if message_id is not None else base.message_id,
        legacy_path=legacy_path if legacy_path is not None else base.legacy_path,
        metadata=merged_metadata,
    )


@contextmanager
def lifecycle_context_scope(
    *,
    path_kind: Optional[str] = None,
    source: Optional[str] = None,
    analysis_run_id: Optional[int] = None,
    chat_id: Optional[int] = None,
    message_id: Optional[int] = None,
    legacy_path: Optional[bool] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Iterator[LifecycleContext]:
    context = derive_lifecycle_context(
        path_kind=path_kind,
        source=source,
        analysis_run_id=analysis_run_id,
        chat_id=chat_id,
        message_id=message_id,
        legacy_path=legacy_path,
        metadata=metadata,
    )
    token = set_current_lifecycle_context(context)
    try:
        yield context
    finally:
        reset_current_lifecycle_context(token)
