from __future__ import annotations

from typing import Any, Dict, Optional, Set

from modules.lifecycle_models import DecisionChain
from modules.strategy_state import StrategyAction, StrategySignalState, normalize_shadow_action, normalize_strategy_state


ALLOWED_TRANSITIONS: Dict[str, Set[str]] = {
    StrategySignalState.NEW_SIGNAL.value: {
        StrategySignalState.OBSERVING.value,
        StrategySignalState.REJECTED.value,
        StrategySignalState.BLOCKED.value,
        StrategySignalState.INVALIDATED.value,
    },
    StrategySignalState.OBSERVING.value: {
        StrategySignalState.OBSERVING.value,
        StrategySignalState.WATCH.value,
        StrategySignalState.ARMED.value,
        StrategySignalState.ENTER_PENDING.value,
        StrategySignalState.REJECTED.value,
        StrategySignalState.BLOCKED.value,
        StrategySignalState.INVALIDATED.value,
    },
    StrategySignalState.WATCH.value: {
        StrategySignalState.WATCH.value,
        StrategySignalState.OBSERVING.value,
        StrategySignalState.ARMED.value,
        StrategySignalState.ENTER_PENDING.value,
        StrategySignalState.REJECTED.value,
        StrategySignalState.BLOCKED.value,
        StrategySignalState.INVALIDATED.value,
    },
    StrategySignalState.ARMED.value: {
        StrategySignalState.ARMED.value,
        StrategySignalState.OBSERVING.value,
        StrategySignalState.ENTER_PENDING.value,
        StrategySignalState.REJECTED.value,
        StrategySignalState.BLOCKED.value,
        StrategySignalState.INVALIDATED.value,
    },
    StrategySignalState.ENTER_PENDING.value: {
        StrategySignalState.ENTERED.value,
        StrategySignalState.BLOCKED.value,
        StrategySignalState.REJECTED.value,
        StrategySignalState.INVALIDATED.value,
    },
    StrategySignalState.ENTERED.value: {
        StrategySignalState.ENTERED.value,
        StrategySignalState.MANAGING.value,
        StrategySignalState.EXIT_PENDING.value,
        StrategySignalState.EXITED.value,
        StrategySignalState.INVALIDATED.value,
    },
    StrategySignalState.MANAGING.value: {
        StrategySignalState.MANAGING.value,
        StrategySignalState.EXIT_PENDING.value,
        StrategySignalState.EXITED.value,
        StrategySignalState.INVALIDATED.value,
    },
    StrategySignalState.EXIT_PENDING.value: {
        StrategySignalState.EXITED.value,
        StrategySignalState.OBSERVING.value,
        StrategySignalState.INVALIDATED.value,
    },
    StrategySignalState.EXITED.value: {
        StrategySignalState.OBSERVING.value,
        StrategySignalState.INVALIDATED.value,
        StrategySignalState.EXITED.value,
    },
    StrategySignalState.REJECTED.value: {
        StrategySignalState.REJECTED.value,
        StrategySignalState.OBSERVING.value,
        StrategySignalState.INVALIDATED.value,
    },
    StrategySignalState.BLOCKED.value: {
        StrategySignalState.BLOCKED.value,
        StrategySignalState.OBSERVING.value,
        StrategySignalState.INVALIDATED.value,
    },
    StrategySignalState.INVALIDATED.value: {
        StrategySignalState.INVALIDATED.value,
    },
}


def is_transition_allowed(from_state: Any, to_state: Any) -> bool:
    src = normalize_strategy_state(from_state)
    dst = normalize_strategy_state(to_state)
    allowed = ALLOWED_TRANSITIONS.get(src, set())
    return dst in allowed


def assert_transition_allowed(from_state: Any, to_state: Any) -> None:
    if not is_transition_allowed(from_state, to_state):
        raise ValueError(
            f"Illegal strategy state transition: {from_state!r} -> {to_state!r}"
        )


def derive_candidate_action(
    score: Optional[float],
    current_state: Any,
    *,
    enter_min: float = 80.0,
    probe_min: float = 65.0,
    watch_min: float = 50.0,
    exit_max: float = 35.0,
) -> str:
    try:
        value = float(score if score is not None else 0.0)
    except Exception:
        value = 0.0

    state = normalize_strategy_state(current_state)
    if state == StrategySignalState.ENTERED.value and value <= exit_max:
        return StrategyAction.EXIT.value
    if value >= enter_min:
        return StrategyAction.ENTER.value
    if value >= probe_min:
        return StrategyAction.PROBE.value
    if value >= watch_min:
        return StrategyAction.WATCH.value
    return StrategyAction.PASS.value


def build_decision_chain(
    *,
    candidate_action: Any,
    ai_verdict: Any,
    risk_adjusted_action: Any,
    final_action: Any,
    strategy_id: str = "",
    score: Optional[float] = None,
    reason: str = "",
    risk_flags: Optional[list[str]] = None,
    metadata: Optional[dict] = None,
) -> DecisionChain:
    return DecisionChain(
        candidate_action=normalize_shadow_action(candidate_action, StrategyAction.WATCH.value),
        ai_verdict=normalize_shadow_action(ai_verdict, StrategyAction.WATCH.value),
        risk_adjusted_action=normalize_shadow_action(risk_adjusted_action, StrategyAction.WATCH.value),
        final_action=normalize_shadow_action(final_action, StrategyAction.WATCH.value),
        strategy_id=str(strategy_id or ""),
        score=score,
        reason=str(reason or ""),
        risk_flags=list(risk_flags or []),
        metadata=dict(metadata or {}),
    )
