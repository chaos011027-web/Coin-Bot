from modules.attribution_feedback_sidecar import build_attribution_feedback_rows


def test_attribution_feedback_sidecar_builds_sample_rooted_feedback_objects_and_excludes_legacy():
    rows = build_attribution_feedback_rows(
        sample_rows=[
            {
                "sample_id": "sample_attr_trade_1",
                "analysis_run_id": 1341,
                "ca": "CA_ATTR_TRADE",
                "trace_link": "CA_ATTR_TRADE:11:22",
                "final_action": "ENTER",
                "strategy_id": "SMART_TREND",
                "path_kind": "MAIN_STATE_MACHINE",
                "legacy_path": False,
            },
            {
                "sample_id": "sample_attr_no_fill_1",
                "analysis_run_id": 1342,
                "ca": "CA_ATTR_NO_FILL",
                "trace_link": "CA_ATTR_NO_FILL:11:22",
                "final_action": "ENTER",
                "strategy_id": "SMART_TREND",
                "path_kind": "MAIN_STATE_MACHINE",
                "legacy_path": False,
            },
            {
                "sample_id": "sample_attr_legacy_1",
                "analysis_run_id": 1399,
                "ca": "CA_ATTR_LEGACY",
                "trace_link": "CA_ATTR_LEGACY:11:22",
                "final_action": "ENTER",
                "strategy_id": "MIXED",
                "path_kind": "LEGACY_DIRECT_ENTER",
                "legacy_path": True,
            },
        ],
        label_rows=[
            {
                "sample_id": "sample_attr_trade_1",
                "analysis_run_id": 1341,
                "ca": "CA_ATTR_TRADE",
                "label_kind": "trade_closed",
                "label_source": "paper_trade_closes",
                "position_ids": ["pos_attr_trade_1"],
                "close_legs": 2,
                "close_reasons": ["TP1", "CLOSED_TP"],
                "realized_pnl_sol": 0.52,
                "realized_return_pct": 52.0,
            },
            {
                "sample_id": "sample_attr_no_fill_1",
                "analysis_run_id": 1342,
                "ca": "CA_ATTR_NO_FILL",
                "label_kind": "no_fill",
                "label_source": "paper_ledger",
                "position_ids": [],
                "close_legs": 0,
                "close_reasons": [],
                "realized_pnl_sol": 0.0,
                "realized_return_pct": 0.0,
            },
            {
                "sample_id": "sample_attr_legacy_1",
                "analysis_run_id": 1399,
                "ca": "CA_ATTR_LEGACY",
                "label_kind": "trade_closed",
                "label_source": "paper_trade_closes",
                "position_ids": ["pos_attr_legacy_1"],
                "close_legs": 1,
                "close_reasons": ["CLOSED_TP"],
                "realized_pnl_sol": 0.30,
                "realized_return_pct": 30.0,
            },
        ],
        decision_event_rows=[],
        execution_event_rows=[
            {
                "analysis_run_id": 1341,
                "ca": "CA_ATTR_TRADE",
                "event_type": "PAPER_OPEN",
                "action": "ENTER",
                "signal_state": "ENTERED",
                "metadata": {"allocated_sol": 0.10},
            }
        ],
        state_transition_rows=[
            {
                "analysis_run_id": 1342,
                "ca": "CA_ATTR_NO_FILL",
                "from_state": "OBSERVING",
                "to_state": "ARMED",
            },
            {
                "analysis_run_id": 1341,
                "ca": "CA_ATTR_TRADE",
                "from_state": "MANAGING",
                "to_state": "EXITED",
            },
        ],
        trade_close_rows=[
            {
                "trade_close_id": "close_attr_trade_1",
                "analysis_run_id": 1341,
                "ca": "CA_ATTR_TRADE",
                "position_id": "pos_attr_trade_1",
                "partial": True,
            },
            {
                "trade_close_id": "close_attr_trade_2",
                "analysis_run_id": 1341,
                "ca": "CA_ATTR_TRADE",
                "position_id": "pos_attr_trade_1",
                "partial": False,
            },
        ],
        sizing_decision_rows=[
            {
                "sample_id": "sample_attr_trade_1",
                "analysis_run_id": 1341,
                "ca": "CA_ATTR_TRADE",
                "state": "ARMED",
                "new_entry_size": 0.12,
                "max_add_size": 0.0,
                "budget_reason": "armed_new_entry_size",
                "size_clamp_reason": "no_clamp",
                "hard_veto_risk_flags": [],
                "clamp_risk_flags": [],
            }
        ],
    )

    assert {row["sample_id"] for row in rows} == {"sample_attr_trade_1", "sample_attr_no_fill_1"}
    by_sample = {row["sample_id"]: row for row in rows}

    trade_row = by_sample["sample_attr_trade_1"]
    assert trade_row["analysis_run_id"] == 1341
    assert trade_row["trace_link"] == "CA_ATTR_TRADE:11:22"
    assert trade_row["position_ids"] == ["pos_attr_trade_1"]
    assert trade_row["trade_close_ids"] == ["close_attr_trade_1", "close_attr_trade_2"]
    assert trade_row["feedback_class"] == "entered_partial_win"

    no_fill_row = by_sample["sample_attr_no_fill_1"]
    assert no_fill_row["analysis_run_id"] == 1342
    assert no_fill_row["position_ids"] == []
    assert no_fill_row["trade_close_ids"] == []
    assert no_fill_row["feedback_class"] == "armed_no_fill"
