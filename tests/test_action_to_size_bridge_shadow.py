import inspect

import pytest

from modules.action_to_size_bridge import build_action_to_size_decision
from modules.strategy_state import AnalysisPathKind, StrategySignalState


def test_action_to_size_bridge_signature_does_not_accept_runtime_patch_inputs():
    parameters = set(inspect.signature(build_action_to_size_decision).parameters)

    assert "token_data" not in parameters
    assert "terminal_states" not in parameters
    assert "runtime_patch" not in parameters


def test_action_to_size_bridge_attaches_new_entry_to_armed_and_add_budget_to_managing():
    armed = build_action_to_size_decision(
        analysis_run_id=1201,
        ca="CA_ARMED_SIZE",
        state=StrategySignalState.ARMED.value,
        cash=1.0,
        equity=1.2,
        reserve_cash_sol=0.25,
        token_score_snapshot={"analysis_run_id": 1201, "ca": "CA_ARMED_SIZE", "total_score": 0.84},
        token_risk_flag_rows=[],
        wallet_label_rows=[],
        current_position_value=0.0,
    )
    observing = build_action_to_size_decision(
        analysis_run_id=1202,
        ca="CA_OBSERVING_SIZE",
        state=StrategySignalState.OBSERVING.value,
        cash=1.0,
        equity=1.2,
        reserve_cash_sol=0.25,
        token_score_snapshot={"analysis_run_id": 1202, "ca": "CA_OBSERVING_SIZE", "total_score": 0.90},
        token_risk_flag_rows=[],
        wallet_label_rows=[],
        current_position_value=0.0,
    )
    managing = build_action_to_size_decision(
        analysis_run_id=1203,
        ca="CA_MANAGING_SIZE",
        state=StrategySignalState.MANAGING.value,
        cash=0.78,
        equity=1.04,
        reserve_cash_sol=0.25,
        token_score_snapshot={"analysis_run_id": 1203, "ca": "CA_MANAGING_SIZE", "total_score": 0.82},
        token_risk_flag_rows=[],
        wallet_label_rows=[],
        current_position_value=0.18,
    )

    assert armed["new_entry_size"] > 0.0
    assert armed["max_add_size"] == pytest.approx(0.0)
    assert observing["new_entry_size"] == pytest.approx(0.0)
    assert observing["max_add_size"] == pytest.approx(0.0)
    assert managing["new_entry_size"] == pytest.approx(0.0)
    assert managing["max_add_size"] > 0.0
    assert managing["max_add_size"] <= managing["available_cash"]
    assert managing["max_add_size"] <= max(0.0, managing["max_position_value"] - 0.18) + 1e-9


def test_action_to_size_bridge_excludes_legacy_direct_enter_from_first_batch_sizing():
    decision = build_action_to_size_decision(
        analysis_run_id=1299,
        ca="CA_LEGACY_SIZE",
        state=StrategySignalState.ARMED.value,
        cash=1.0,
        equity=1.2,
        reserve_cash_sol=0.25,
        token_score_snapshot={"analysis_run_id": 1299, "ca": "CA_LEGACY_SIZE", "total_score": 0.95},
        token_risk_flag_rows=[],
        wallet_label_rows=[],
        current_position_value=0.0,
        path_kind=AnalysisPathKind.LEGACY_DIRECT_ENTER.value,
        legacy_path=True,
    )

    assert decision["new_entry_size"] == pytest.approx(0.0)
    assert decision["max_add_size"] == pytest.approx(0.0)
    assert decision["budget_reason"] == "legacy_path_excluded"
