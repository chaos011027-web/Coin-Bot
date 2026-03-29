import inspect

import pytest

import main
from modules.execution_event_logger import log_execution_event, log_state_transition
from modules.lifecycle_repository import InMemoryLifecycleRepository
from modules.strategy_state import (
    AnalysisPathKind,
    ExecutionEventType,
    StrategyAction,
    StrategySignalState,
    lifecycle_context_scope,
)


def test_main_paths_define_stage_key_and_shared_trace_link():
    process_source = inspect.getsource(main.process_new_signal)
    deep_source = inspect.getsource(main.run_deep_analysis)
    monitor_source = inspect.getsource(main.price_monitor_loop)

    assert '"trace_link": f"{ca}:{int(chat_id or 0)}:{int(fast_msg_id or 0)}"' in process_source
    assert '"lifecycle_key": f"fast_init:{ca}:{int(chat_id or 0)}:{int(fast_msg_id or 0)}"' in process_source
    assert '"trace_link": f"{ca}:{int(chat_id or 0)}:{int(message_id or 0)}"' in deep_source
    assert '"lifecycle_key": f"deep_analysis:{ca}:{int(chat_id or 0)}:{int(message_id or 0)}"' in deep_source
    assert 'trace_link = f"{ca}:{int(pos.get(\'reply_chat_id\') or 0)}:{int(pos.get(\'reply_msg_id\') or 0)}"' in monitor_source
    assert '"trace_link": trace_link' in monitor_source
    assert 'f"price_monitor:{ca}:{int(pos.get(\'reply_chat_id\') or 0)}:{int(pos.get(\'reply_msg_id\') or 0)}"' in monitor_source


@pytest.mark.asyncio
async def test_ambient_context_metadata_is_passthrough_for_transition_and_execution(monkeypatch):
    monkeypatch.setenv("SHADOW_LIFECYCLE_ENABLED", "1")

    repo = InMemoryLifecycleRepository()
    trace_link = "CA_LINK:1:101"
    lifecycle_key = "fast_init:CA_LINK:1:101"

    with lifecycle_context_scope(
        path_kind=AnalysisPathKind.FAST_SIGNAL_INIT.value,
        source="process_new_signal",
        chat_id=1,
        message_id=101,
        metadata={"trace_link": trace_link, "lifecycle_key": lifecycle_key},
    ):
        await log_state_transition(
            "CA_LINK",
            StrategySignalState.NEW_SIGNAL.value,
            StrategySignalState.OBSERVING.value,
            action=StrategyAction.WATCH.value,
            repository=repo,
        )
        await log_execution_event(
            "CA_LINK",
            ExecutionEventType.TP_TRACKER_OBSERVE.value,
            action=StrategyAction.WATCH.value,
            signal_state=StrategySignalState.OBSERVING.value,
            repository=repo,
        )

    assert repo.strategy_state_transitions[0]["metadata"]["trace_link"] == trace_link
    assert repo.strategy_state_transitions[0]["metadata"]["lifecycle_key"] == lifecycle_key
    assert repo.execution_events[0]["metadata"]["trace_link"] == trace_link
    assert repo.execution_events[0]["metadata"]["lifecycle_key"] == lifecycle_key
