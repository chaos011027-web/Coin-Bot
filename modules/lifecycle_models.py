from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class LifecycleContext:
    path_kind: str = ""
    source: str = ""
    analysis_run_id: Optional[int] = None
    chat_id: Optional[int] = None
    message_id: Optional[int] = None
    legacy_path: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DecisionChain:
    candidate_action: str
    ai_verdict: str
    risk_adjusted_action: str
    final_action: str
    strategy_id: str = ""
    score: Optional[float] = None
    reason: str = ""
    risk_flags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TransitionRecord:
    ca: str
    from_state: str
    to_state: str
    action: str = ""
    source: str = ""
    path_kind: str = ""
    analysis_run_id: Optional[int] = None
    legacy_path: bool = False
    transition_reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionEventRecord:
    ca: str
    event_type: str
    action: str = ""
    signal_state: str = ""
    status: str = ""
    source: str = ""
    path_kind: str = ""
    analysis_run_id: Optional[int] = None
    legacy_path: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AnalysisRunRecord:
    ca: str
    source: str
    path_kind: str
    status: str = "STARTED"
    chat_id: Optional[int] = None
    message_id: Optional[int] = None
    analysis_run_id: Optional[int] = None
    legacy_path: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
