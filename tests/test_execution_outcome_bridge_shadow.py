import pytest

from modules.execution_outcome_bridge import build_execution_outcome_bucket
from modules.strategy_state import StrategySignalState


@pytest.mark.parametrize(
    ("sample_row", "label_row", "state_rows", "trade_close_rows", "expected_feedback_class", "expected_final_state"),
    [
        (
            {
                "sample_id": "sample_observe_reject_1",
                "analysis_run_id": 1301,
                "ca": "CA_OBSERVE_REJECT",
                "trace_link": "CA_OBSERVE_REJECT:11:22",
                "final_action": "WATCH",
                "strategy_id": "SMART_TREND",
                "path_kind": "MAIN_STATE_MACHINE",
                "legacy_path": False,
            },
            {
                "sample_id": "sample_observe_reject_1",
                "analysis_run_id": 1301,
                "ca": "CA_OBSERVE_REJECT",
                "label_kind": "no_trade",
                "label_source": "paper_ledger",
                "position_ids": [],
                "close_legs": 0,
                "close_reasons": [],
                "realized_pnl_sol": 0.0,
                "realized_return_pct": 0.0,
            },
            [
                {
                    "analysis_run_id": 1301,
                    "ca": "CA_OBSERVE_REJECT",
                    "from_state": StrategySignalState.NEW_SIGNAL.value,
                    "to_state": StrategySignalState.OBSERVING.value,
                    "created_at": "2026-03-31T12:00:00Z",
                },
                {
                    "analysis_run_id": 1301,
                    "ca": "CA_OBSERVE_REJECT",
                    "from_state": StrategySignalState.OBSERVING.value,
                    "to_state": StrategySignalState.REJECTED.value,
                    "transition_reason": "reject_blocking_risk_flags",
                    "created_at": "2026-03-31T12:01:00Z",
                },
            ],
            [],
            "observe_reject",
            StrategySignalState.REJECTED.value,
        ),
        (
            {
                "sample_id": "sample_armed_no_fill_1",
                "analysis_run_id": 1302,
                "ca": "CA_ARMED_NO_FILL",
                "trace_link": "CA_ARMED_NO_FILL:11:22",
                "final_action": "ENTER",
                "strategy_id": "SMART_TREND",
                "path_kind": "MAIN_STATE_MACHINE",
                "legacy_path": False,
            },
            {
                "sample_id": "sample_armed_no_fill_1",
                "analysis_run_id": 1302,
                "ca": "CA_ARMED_NO_FILL",
                "label_kind": "no_fill",
                "label_source": "paper_ledger",
                "position_ids": [],
                "close_legs": 0,
                "close_reasons": [],
                "realized_pnl_sol": 0.0,
                "realized_return_pct": 0.0,
            },
            [
                {
                    "analysis_run_id": 1302,
                    "ca": "CA_ARMED_NO_FILL",
                    "from_state": StrategySignalState.NEW_SIGNAL.value,
                    "to_state": StrategySignalState.OBSERVING.value,
                    "created_at": "2026-03-31T12:00:00Z",
                },
                {
                    "analysis_run_id": 1302,
                    "ca": "CA_ARMED_NO_FILL",
                    "from_state": StrategySignalState.OBSERVING.value,
                    "to_state": StrategySignalState.ARMED.value,
                    "created_at": "2026-03-31T12:01:00Z",
                },
            ],
            [],
            "armed_no_fill",
            StrategySignalState.ARMED.value,
        ),
        (
            {
                "sample_id": "sample_partial_win_1",
                "analysis_run_id": 1303,
                "ca": "CA_PARTIAL_WIN",
                "trace_link": "CA_PARTIAL_WIN:11:22",
                "final_action": "ENTER",
                "strategy_id": "SMART_TREND",
                "path_kind": "MAIN_STATE_MACHINE",
                "legacy_path": False,
            },
            {
                "sample_id": "sample_partial_win_1",
                "analysis_run_id": 1303,
                "ca": "CA_PARTIAL_WIN",
                "label_kind": "trade_closed",
                "label_source": "paper_trade_closes",
                "position_ids": ["pos_partial_win_1"],
                "close_legs": 2,
                "close_reasons": ["TP1", "CLOSED_TP"],
                "realized_pnl_sol": 0.62,
                "realized_return_pct": 62.0,
            },
            [
                {
                    "analysis_run_id": 1303,
                    "ca": "CA_PARTIAL_WIN",
                    "from_state": StrategySignalState.NEW_SIGNAL.value,
                    "to_state": StrategySignalState.OBSERVING.value,
                    "created_at": "2026-03-31T12:00:00Z",
                },
                {
                    "analysis_run_id": 1303,
                    "ca": "CA_PARTIAL_WIN",
                    "from_state": StrategySignalState.OBSERVING.value,
                    "to_state": StrategySignalState.ARMED.value,
                    "created_at": "2026-03-31T12:01:00Z",
                },
                {
                    "analysis_run_id": 1303,
                    "ca": "CA_PARTIAL_WIN",
                    "from_state": StrategySignalState.ARMED.value,
                    "to_state": StrategySignalState.ENTERED.value,
                    "created_at": "2026-03-31T12:02:00Z",
                },
                {
                    "analysis_run_id": 1303,
                    "ca": "CA_PARTIAL_WIN",
                    "from_state": StrategySignalState.ENTERED.value,
                    "to_state": StrategySignalState.MANAGING.value,
                    "created_at": "2026-03-31T12:03:00Z",
                },
                {
                    "analysis_run_id": 1303,
                    "ca": "CA_PARTIAL_WIN",
                    "from_state": StrategySignalState.MANAGING.value,
                    "to_state": StrategySignalState.EXITED.value,
                    "created_at": "2026-03-31T12:04:00Z",
                },
            ],
            [
                {
                    "trade_close_id": "close_partial_1",
                    "analysis_run_id": 1303,
                    "ca": "CA_PARTIAL_WIN",
                    "position_id": "pos_partial_win_1",
                    "partial": True,
                },
                {
                    "trade_close_id": "close_partial_2",
                    "analysis_run_id": 1303,
                    "ca": "CA_PARTIAL_WIN",
                    "position_id": "pos_partial_win_1",
                    "partial": False,
                },
            ],
            "entered_partial_win",
            StrategySignalState.EXITED.value,
        ),
        (
            {
                "sample_id": "sample_profit_1",
                "analysis_run_id": 1304,
                "ca": "CA_PROFIT",
                "trace_link": "CA_PROFIT:11:22",
                "final_action": "ENTER",
                "strategy_id": "SMART_TREND",
                "path_kind": "MAIN_STATE_MACHINE",
                "legacy_path": False,
            },
            {
                "sample_id": "sample_profit_1",
                "analysis_run_id": 1304,
                "ca": "CA_PROFIT",
                "label_kind": "trade_closed",
                "label_source": "paper_trade_closes",
                "position_ids": ["pos_profit_1"],
                "close_legs": 1,
                "close_reasons": ["CLOSED_TP"],
                "realized_pnl_sol": 0.45,
                "realized_return_pct": 45.0,
            },
            [],
            [
                {
                    "trade_close_id": "close_profit_1",
                    "analysis_run_id": 1304,
                    "ca": "CA_PROFIT",
                    "position_id": "pos_profit_1",
                    "partial": False,
                }
            ],
            "entered_profit",
            StrategySignalState.EXITED.value,
        ),
        (
            {
                "sample_id": "sample_loss_1",
                "analysis_run_id": 1305,
                "ca": "CA_LOSS",
                "trace_link": "CA_LOSS:11:22",
                "final_action": "ENTER",
                "strategy_id": "SMART_TREND",
                "path_kind": "MAIN_STATE_MACHINE",
                "legacy_path": False,
            },
            {
                "sample_id": "sample_loss_1",
                "analysis_run_id": 1305,
                "ca": "CA_LOSS",
                "label_kind": "trade_closed",
                "label_source": "paper_trade_closes",
                "position_ids": ["pos_loss_1"],
                "close_legs": 1,
                "close_reasons": ["CLOSED_SL"],
                "realized_pnl_sol": -0.21,
                "realized_return_pct": -21.0,
            },
            [],
            [
                {
                    "trade_close_id": "close_loss_1",
                    "analysis_run_id": 1305,
                    "ca": "CA_LOSS",
                    "position_id": "pos_loss_1",
                    "partial": False,
                }
            ],
            "entered_loss",
            StrategySignalState.EXITED.value,
        ),
    ],
)
def test_execution_outcome_bridge_maps_fixed_feedback_classes(
    sample_row,
    label_row,
    state_rows,
    trade_close_rows,
    expected_feedback_class,
    expected_final_state,
):
    result = build_execution_outcome_bucket(
        sample_row=sample_row,
        label_row=label_row,
        state_transition_rows=state_rows,
        decision_event_rows=[],
        execution_event_rows=[],
        trade_close_rows=trade_close_rows,
    )

    assert result["sample_id"] == sample_row["sample_id"]
    assert result["analysis_run_id"] == sample_row["analysis_run_id"]
    assert result["ca"] == sample_row["ca"]
    assert result["trace_link"] == sample_row["trace_link"]
    assert result["label_kind"] == label_row["label_kind"]
    assert result["feedback_class"] == expected_feedback_class
    assert result["final_state"] == expected_final_state
    assert result["position_ids"] == list(label_row.get("position_ids") or [])


def test_execution_outcome_bridge_keeps_rejected_and_exited_in_distinct_feedback_classes():
    rejected = build_execution_outcome_bucket(
        sample_row={
            "sample_id": "sample_reject_distinct",
            "analysis_run_id": 1306,
            "ca": "CA_REJECT_DISTINCT",
            "trace_link": "CA_REJECT_DISTINCT:11:22",
            "final_action": "WATCH",
            "strategy_id": "SMART_TREND",
            "path_kind": "MAIN_STATE_MACHINE",
            "legacy_path": False,
        },
        label_row={
            "sample_id": "sample_reject_distinct",
            "analysis_run_id": 1306,
            "ca": "CA_REJECT_DISTINCT",
            "label_kind": "no_trade",
            "label_source": "paper_ledger",
            "position_ids": [],
            "close_legs": 0,
            "close_reasons": [],
            "realized_pnl_sol": 0.0,
            "realized_return_pct": 0.0,
        },
        state_transition_rows=[
            {
                "analysis_run_id": 1306,
                "ca": "CA_REJECT_DISTINCT",
                "from_state": StrategySignalState.OBSERVING.value,
                "to_state": StrategySignalState.REJECTED.value,
            }
        ],
        execution_event_rows=[],
        decision_event_rows=[],
        trade_close_rows=[],
    )
    exited = build_execution_outcome_bucket(
        sample_row={
            "sample_id": "sample_exit_distinct",
            "analysis_run_id": 1307,
            "ca": "CA_EXIT_DISTINCT",
            "trace_link": "CA_EXIT_DISTINCT:11:22",
            "final_action": "ENTER",
            "strategy_id": "SMART_TREND",
            "path_kind": "MAIN_STATE_MACHINE",
            "legacy_path": False,
        },
        label_row={
            "sample_id": "sample_exit_distinct",
            "analysis_run_id": 1307,
            "ca": "CA_EXIT_DISTINCT",
            "label_kind": "trade_closed",
            "label_source": "paper_trade_closes",
            "position_ids": ["pos_exit_distinct_1"],
            "close_legs": 1,
            "close_reasons": ["CLOSED_TP"],
            "realized_pnl_sol": 0.31,
            "realized_return_pct": 31.0,
        },
        state_transition_rows=[
            {
                "analysis_run_id": 1307,
                "ca": "CA_EXIT_DISTINCT",
                "from_state": StrategySignalState.MANAGING.value,
                "to_state": StrategySignalState.EXITED.value,
            }
        ],
        execution_event_rows=[],
        decision_event_rows=[],
        trade_close_rows=[
            {
                "trade_close_id": "close_exit_distinct_1",
                "analysis_run_id": 1307,
                "ca": "CA_EXIT_DISTINCT",
                "position_id": "pos_exit_distinct_1",
                "partial": False,
            }
        ],
    )

    assert rejected["feedback_class"] == "observe_reject"
    assert exited["feedback_class"] == "entered_profit"
    assert rejected["feedback_class"] != exited["feedback_class"]
