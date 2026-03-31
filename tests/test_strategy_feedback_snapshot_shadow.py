from modules.execution_outcome_bridge import build_execution_outcome_bucket
from modules.strategy_feedback_snapshot import build_strategy_feedback_snapshot
from modules.strategy_state import StrategySignalState


def test_strategy_feedback_snapshot_builds_sample_rooted_feedback_object():
    sample_row = {
        "sample_id": "sample_strategy_feedback_1",
        "analysis_run_id": 1311,
        "ca": "CA_STRATEGY_FEEDBACK",
        "trace_link": "CA_STRATEGY_FEEDBACK:11:22",
        "final_action": "ENTER",
        "strategy_id": "SMART_TREND",
        "path_kind": "MAIN_STATE_MACHINE",
        "legacy_path": False,
    }
    label_row = {
        "sample_id": "sample_strategy_feedback_1",
        "analysis_run_id": 1311,
        "ca": "CA_STRATEGY_FEEDBACK",
        "label_kind": "trade_closed",
        "label_source": "paper_trade_closes",
        "position_ids": ["pos_strategy_feedback_1"],
        "close_legs": 1,
        "close_reasons": ["CLOSED_TP"],
        "realized_pnl_sol": 0.56,
        "realized_return_pct": 56.0,
    }
    state_rows = [
        {
            "analysis_run_id": 1311,
            "ca": "CA_STRATEGY_FEEDBACK",
            "from_state": StrategySignalState.NEW_SIGNAL.value,
            "to_state": StrategySignalState.OBSERVING.value,
            "created_at": "2026-03-31T12:00:00Z",
        },
        {
            "analysis_run_id": 1311,
            "ca": "CA_STRATEGY_FEEDBACK",
            "from_state": StrategySignalState.OBSERVING.value,
            "to_state": StrategySignalState.ARMED.value,
            "created_at": "2026-03-31T12:01:00Z",
        },
        {
            "analysis_run_id": 1311,
            "ca": "CA_STRATEGY_FEEDBACK",
            "from_state": StrategySignalState.ARMED.value,
            "to_state": StrategySignalState.ENTERED.value,
            "created_at": "2026-03-31T12:02:00Z",
        },
        {
            "analysis_run_id": 1311,
            "ca": "CA_STRATEGY_FEEDBACK",
            "from_state": StrategySignalState.ENTERED.value,
            "to_state": StrategySignalState.MANAGING.value,
            "created_at": "2026-03-31T12:03:00Z",
        },
        {
            "analysis_run_id": 1311,
            "ca": "CA_STRATEGY_FEEDBACK",
            "from_state": StrategySignalState.MANAGING.value,
            "to_state": StrategySignalState.EXITED.value,
            "transition_reason": "ledger_position_closed",
            "created_at": "2026-03-31T12:04:00Z",
        },
    ]
    decision_rows = [
        {
            "analysis_run_id": 1311,
            "ca": "CA_STRATEGY_FEEDBACK",
            "candidate_action": "WATCH",
            "ai_verdict": "ENTER",
            "risk_adjusted_action": "ENTER",
            "final_action": "ENTER",
            "strategy_id": "SMART_TREND",
            "score": 84.0,
            "reason": "score gate passed",
            "risk_flags": ["LOW_LIQUIDITY"],
            "created_at": "2026-03-31T12:00:30Z",
        }
    ]
    outcome = build_execution_outcome_bucket(
        sample_row=sample_row,
        label_row=label_row,
        state_transition_rows=state_rows,
        decision_event_rows=decision_rows,
        execution_event_rows=[],
        trade_close_rows=[
            {
                "trade_close_id": "close_strategy_feedback_1",
                "analysis_run_id": 1311,
                "ca": "CA_STRATEGY_FEEDBACK",
                "position_id": "pos_strategy_feedback_1",
                "partial": False,
            }
        ],
    )

    snapshot = build_strategy_feedback_snapshot(
        sample_row=sample_row,
        label_row=label_row,
        execution_outcome_row=outcome,
        decision_event_rows=decision_rows,
        state_transition_rows=state_rows,
    )

    assert snapshot["sample_id"] == "sample_strategy_feedback_1"
    assert snapshot["analysis_run_id"] == 1311
    assert snapshot["ca"] == "CA_STRATEGY_FEEDBACK"
    assert snapshot["trace_link"] == "CA_STRATEGY_FEEDBACK:11:22"
    assert snapshot["position_ids"] == ["pos_strategy_feedback_1"]
    assert snapshot["trade_close_ids"] == ["close_strategy_feedback_1"]
    assert snapshot["label_kind"] == "trade_closed"
    assert snapshot["feedback_class"] == "entered_profit"
    assert snapshot["final_action"] == "ENTER"
    assert snapshot["strategy_id"] == "SMART_TREND"
    assert snapshot["state_path"] == [
        StrategySignalState.NEW_SIGNAL.value,
        StrategySignalState.OBSERVING.value,
        StrategySignalState.ARMED.value,
        StrategySignalState.ENTERED.value,
        StrategySignalState.MANAGING.value,
        StrategySignalState.EXITED.value,
    ]
    assert snapshot["final_state"] == StrategySignalState.EXITED.value
    assert snapshot["candidate_action"] == "WATCH"
    assert snapshot["ai_verdict"] == "ENTER"
    assert snapshot["risk_adjusted_action"] == "ENTER"
    assert snapshot["decision_reason"] == "score gate passed"


def test_strategy_feedback_snapshot_supports_no_trade_without_position_or_trade_close_refs():
    sample_row = {
        "sample_id": "sample_strategy_feedback_no_trade_1",
        "analysis_run_id": 1312,
        "ca": "CA_STRATEGY_FEEDBACK_NO_TRADE",
        "trace_link": "CA_STRATEGY_FEEDBACK_NO_TRADE:11:22",
        "final_action": "WATCH",
        "strategy_id": "SMART_TREND",
        "path_kind": "MAIN_STATE_MACHINE",
        "legacy_path": False,
    }
    label_row = {
        "sample_id": "sample_strategy_feedback_no_trade_1",
        "analysis_run_id": 1312,
        "ca": "CA_STRATEGY_FEEDBACK_NO_TRADE",
        "label_kind": "no_trade",
        "label_source": "paper_ledger",
        "position_ids": [],
        "close_legs": 0,
        "close_reasons": [],
        "realized_pnl_sol": 0.0,
        "realized_return_pct": 0.0,
    }
    outcome = build_execution_outcome_bucket(
        sample_row=sample_row,
        label_row=label_row,
        state_transition_rows=[
            {
                "analysis_run_id": 1312,
                "ca": "CA_STRATEGY_FEEDBACK_NO_TRADE",
                "from_state": StrategySignalState.OBSERVING.value,
                "to_state": StrategySignalState.REJECTED.value,
            }
        ],
        decision_event_rows=[],
        execution_event_rows=[],
        trade_close_rows=[],
    )

    snapshot = build_strategy_feedback_snapshot(
        sample_row=sample_row,
        label_row=label_row,
        execution_outcome_row=outcome,
        decision_event_rows=[],
        state_transition_rows=[],
    )

    assert snapshot["label_kind"] == "no_trade"
    assert snapshot["feedback_class"] == "observe_reject"
    assert snapshot["position_ids"] == []
    assert snapshot["trade_close_ids"] == []
