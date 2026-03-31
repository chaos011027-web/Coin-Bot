import inspect

import pytest

from modules.strategy_state import StrategySignalState
from modules.strategy_state_transition_bridge import (
    build_strategy_state_identity,
    bridge_ledger_primary_state,
    evaluate_observing_state_transition,
)


def test_state_transition_bridge_uses_analysis_run_id_and_ca_as_primary_identity():
    identity = build_strategy_state_identity(
        analysis_run_id=1101,
        ca="CA_PHASE11",
        position_id="position_alpha",
        trace_link="CA_PHASE11:11:22",
        sample_id="sample_phase11_alpha",
    )

    assert identity["analysis_run_id"] == 1101
    assert identity["ca"] == "CA_PHASE11"
    assert identity["identity_key"] == "1101:CA_PHASE11"
    assert identity["position_id"] == "position_alpha"
    assert identity["trace_link"] == "CA_PHASE11:11:22"
    assert identity["sample_id"] == "sample_phase11_alpha"
    assert "position_alpha" not in identity["identity_key"]
    assert "sample_phase11_alpha" not in identity["identity_key"]


def test_observing_bridge_signature_does_not_accept_runtime_patch_inputs():
    parameters = set(inspect.signature(evaluate_observing_state_transition).parameters)

    assert "token_data" not in parameters
    assert "terminal_states" not in parameters
    assert "runtime_patch" not in parameters


def test_observing_bridge_arms_only_from_stable_inputs():
    result = evaluate_observing_state_transition(
        analysis_run_id=1102,
        ca="CA_ARMED",
        token_risk_flag_rows=[],
        token_score_snapshot_rows=[
            {
                "analysis_run_id": 1102,
                "ca": "CA_ARMED",
                "total_score": 0.84,
                "snapshot_at": "2026-03-31T11:00:00Z",
            }
        ],
        wallet_label_rows=[
            {
                "wallet_address": "wallet_alpha",
                "label_name": "SMART_MONEY_WALLET",
                "confidence": 0.82,
                "snapshot_at": "2026-03-31T11:00:00Z",
            }
        ],
    )

    assert result["next_state"] == StrategySignalState.ARMED.value
    assert result["reason"] == "armed_by_stable_inputs"


def test_observing_bridge_rejects_blocking_risk_or_wallet_labels_and_excludes_legacy():
    risk_reject = evaluate_observing_state_transition(
        analysis_run_id=1103,
        ca="CA_RISK_REJECT",
        token_risk_flag_rows=[
            {
                "analysis_run_id": 1103,
                "ca": "CA_RISK_REJECT",
                "risk_flag": "AUTHORITY_RISK",
                "snapshot_at": "2026-03-31T11:01:00Z",
            },
            {
                "analysis_run_id": 1199,
                "ca": "CA_RISK_REJECT",
                "risk_flag": "SOURCE_CONFLICT",
                "legacy_path": True,
                "snapshot_at": "2026-03-31T09:00:00Z",
            },
        ],
        token_score_snapshot_rows=[
            {
                "analysis_run_id": 1103,
                "ca": "CA_RISK_REJECT",
                "total_score": 0.95,
                "snapshot_at": "2026-03-31T11:01:00Z",
            }
        ],
        wallet_label_rows=[],
    )

    label_reject = evaluate_observing_state_transition(
        analysis_run_id=1104,
        ca="CA_LABEL_REJECT",
        token_risk_flag_rows=[],
        token_score_snapshot_rows=[
            {
                "analysis_run_id": 1104,
                "ca": "CA_LABEL_REJECT",
                "total_score": 0.91,
                "snapshot_at": "2026-03-31T11:02:00Z",
            }
        ],
        wallet_label_rows=[
            {
                "wallet_address": "wallet_risky",
                "label_name": "SUSPICIOUS_CLUSTER_WALLET",
                "confidence": 0.91,
                "snapshot_at": "2026-03-31T11:02:00Z",
            }
        ],
    )

    assert risk_reject["next_state"] == StrategySignalState.REJECTED.value
    assert risk_reject["blocking_risk_flags"] == ["AUTHORITY_RISK"]
    assert label_reject["next_state"] == StrategySignalState.REJECTED.value
    assert label_reject["blocking_wallet_labels"] == ["SUSPICIOUS_CLUSTER_WALLET"]


def test_ledger_bridge_moves_armed_to_entered_on_first_effective_buy_fill():
    result = bridge_ledger_primary_state(
        analysis_run_id=1105,
        ca="CA_ENTERED",
        current_state=StrategySignalState.ARMED.value,
        paper_fill_rows=[
            {
                "analysis_run_id": 1105,
                "ca": "CA_ENTERED",
                "position_id": "position_entered",
                "side": "BUY",
                "filled_at": "2026-03-31T11:03:00Z",
            }
        ],
        paper_position_rows=[],
        paper_trade_close_rows=[],
    )

    assert result["next_state"] == StrategySignalState.ENTERED.value
    assert result["position_id"] == "position_entered"
    assert result["reason"] == "ledger_open_fill_or_position_opened"


def test_ledger_bridge_keeps_partial_close_in_managing_and_only_full_close_exits():
    partial_result = bridge_ledger_primary_state(
        analysis_run_id=1106,
        ca="CA_MANAGING",
        current_state=StrategySignalState.MANAGING.value,
        paper_fill_rows=[
            {
                "analysis_run_id": 1106,
                "ca": "CA_MANAGING",
                "position_id": "position_manage",
                "side": "SELL",
                "filled_at": "2026-03-31T11:04:00Z",
            }
        ],
        paper_position_rows=[
            {
                "analysis_run_id": 1106,
                "ca": "CA_MANAGING",
                "position_id": "position_manage",
                "event_type": "UPDATED",
                "qty_after": 40.0,
                "event_at": "2026-03-31T11:04:01Z",
            }
        ],
        paper_trade_close_rows=[
            {
                "analysis_run_id": 1106,
                "ca": "CA_MANAGING",
                "position_id": "position_manage",
                "partial": True,
                "recorded_at": "2026-03-31T11:04:02Z",
            }
        ],
    )

    exit_result = bridge_ledger_primary_state(
        analysis_run_id=1107,
        ca="CA_EXITED",
        current_state=StrategySignalState.MANAGING.value,
        paper_fill_rows=[
            {
                "analysis_run_id": 1107,
                "ca": "CA_EXITED",
                "position_id": "position_exit",
                "side": "SELL",
                "filled_at": "2026-03-31T11:05:00Z",
            }
        ],
        paper_position_rows=[
            {
                "analysis_run_id": 1107,
                "ca": "CA_EXITED",
                "position_id": "position_exit",
                "event_type": "CLOSED",
                "qty_after": 0.0,
                "event_at": "2026-03-31T11:05:01Z",
            }
        ],
        paper_trade_close_rows=[
            {
                "analysis_run_id": 1107,
                "ca": "CA_EXITED",
                "position_id": "position_exit",
                "partial": False,
                "recorded_at": "2026-03-31T11:05:02Z",
            }
        ],
    )

    assert partial_result["next_state"] == StrategySignalState.MANAGING.value
    assert partial_result["reason"] == "ledger_position_still_open"
    assert exit_result["next_state"] == StrategySignalState.EXITED.value
    assert exit_result["reason"] == "ledger_position_closed"
