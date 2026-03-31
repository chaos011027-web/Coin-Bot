import pytest

from modules.sizing_feedback_snapshot import build_sizing_feedback_snapshot


def test_sizing_feedback_snapshot_links_requested_and_effective_sizes():
    snapshot = build_sizing_feedback_snapshot(
        sample_row={
            "sample_id": "sample_sizing_feedback_1",
            "analysis_run_id": 1321,
            "ca": "CA_SIZING_FEEDBACK",
            "trace_link": "CA_SIZING_FEEDBACK:11:22",
            "legacy_path": False,
        },
        execution_outcome_row={
            "feedback_class": "entered_partial_win",
            "position_ids": ["pos_sizing_feedback_1"],
            "trade_close_ids": ["close_sizing_feedback_1", "close_sizing_feedback_2"],
            "realized_pnl_sol": 0.44,
            "realized_return_pct": 44.0,
        },
        sizing_decision_rows=[
            {
                "sample_id": "sample_sizing_feedback_1",
                "analysis_run_id": 1321,
                "ca": "CA_SIZING_FEEDBACK",
                "state": "ARMED",
                "new_entry_size": 0.12,
                "max_add_size": 0.0,
                "budget_reason": "armed_new_entry_size",
                "size_clamp_reason": "risk_clamp:LOW_LIQUIDITY",
                "hard_veto_risk_flags": [],
                "clamp_risk_flags": ["LOW_LIQUIDITY"],
                "created_at": "2026-03-31T12:00:00Z",
            },
            {
                "sample_id": "sample_sizing_feedback_1",
                "analysis_run_id": 1321,
                "ca": "CA_SIZING_FEEDBACK",
                "state": "MANAGING",
                "new_entry_size": 0.0,
                "max_add_size": 0.04,
                "budget_reason": "managing_max_add_size",
                "size_clamp_reason": "risk_clamp:LOW_LIQUIDITY",
                "hard_veto_risk_flags": [],
                "clamp_risk_flags": ["LOW_LIQUIDITY"],
                "created_at": "2026-03-31T12:10:00Z",
            },
        ],
        execution_event_rows=[
            {
                "analysis_run_id": 1321,
                "ca": "CA_SIZING_FEEDBACK",
                "event_type": "PAPER_OPEN",
                "action": "ENTER",
                "signal_state": "ENTERED",
                "metadata": {
                    "allocated_sol": 0.10,
                    "budget_reason": "armed_new_entry_size",
                    "size_clamp_reason": "risk_clamp:LOW_LIQUIDITY",
                },
                "created_at": "2026-03-31T12:01:00Z",
            },
            {
                "analysis_run_id": 1321,
                "ca": "CA_SIZING_FEEDBACK",
                "event_type": "PAPER_ADD",
                "action": "ADD",
                "signal_state": "MANAGING",
                "metadata": {
                    "effective_add_size": 0.02,
                },
                "created_at": "2026-03-31T12:11:00Z",
            },
        ],
    )

    assert snapshot["sample_id"] == "sample_sizing_feedback_1"
    assert snapshot["analysis_run_id"] == 1321
    assert snapshot["ca"] == "CA_SIZING_FEEDBACK"
    assert snapshot["requested_entry_size"] == pytest.approx(0.12)
    assert snapshot["effective_allocated_size"] == pytest.approx(0.10)
    assert snapshot["requested_max_add_size"] == pytest.approx(0.04)
    assert snapshot["effective_add_size"] == pytest.approx(0.02)
    assert snapshot["budget_reason"] == "armed_new_entry_size"
    assert snapshot["size_clamp_reason"] == "risk_clamp:LOW_LIQUIDITY"
    assert snapshot["hard_veto_risk_flags"] == []
    assert snapshot["clamp_risk_flags"] == ["LOW_LIQUIDITY"]


def test_sizing_feedback_snapshot_records_hard_veto_zero_sizes():
    snapshot = build_sizing_feedback_snapshot(
        sample_row={
            "sample_id": "sample_sizing_feedback_veto_1",
            "analysis_run_id": 1322,
            "ca": "CA_SIZING_FEEDBACK_VETO",
            "trace_link": "CA_SIZING_FEEDBACK_VETO:11:22",
            "legacy_path": False,
        },
        execution_outcome_row={
            "feedback_class": "armed_no_fill",
            "position_ids": [],
            "trade_close_ids": [],
            "realized_pnl_sol": 0.0,
            "realized_return_pct": 0.0,
        },
        sizing_decision_rows=[
            {
                "sample_id": "sample_sizing_feedback_veto_1",
                "analysis_run_id": 1322,
                "ca": "CA_SIZING_FEEDBACK_VETO",
                "state": "ARMED",
                "new_entry_size": 0.0,
                "max_add_size": 0.0,
                "budget_reason": "hard_veto_budget_zero",
                "size_clamp_reason": "hard_veto:AUTHORITY_RISK",
                "hard_veto_risk_flags": ["AUTHORITY_RISK"],
                "clamp_risk_flags": [],
            }
        ],
        execution_event_rows=[],
    )

    assert snapshot["requested_entry_size"] == pytest.approx(0.0)
    assert snapshot["effective_allocated_size"] == pytest.approx(0.0)
    assert snapshot["requested_max_add_size"] == pytest.approx(0.0)
    assert snapshot["effective_add_size"] == pytest.approx(0.0)
    assert snapshot["hard_veto_risk_flags"] == ["AUTHORITY_RISK"]
    assert snapshot["budget_reason"] == "hard_veto_budget_zero"
