import pytest

from modules.position_sizing_policy import build_position_sizing_decision
from modules.strategy_state import StrategySignalState


def test_position_sizing_policy_zeroes_sizes_for_hard_veto_risks_without_deciding_rejected_state():
    decision = build_position_sizing_decision(
        state=StrategySignalState.ARMED.value,
        cash=1.0,
        equity=1.2,
        reserve_cash_sol=0.25,
        current_position_value=0.0,
        token_score_snapshot={"total_score": 0.95},
        token_risk_flags=[{"risk_flag": "AUTHORITY_RISK"}],
        wallet_labels=[],
    )

    assert decision["state"] == StrategySignalState.ARMED.value
    assert decision["new_entry_size"] == pytest.approx(0.0)
    assert decision["max_add_size"] == pytest.approx(0.0)
    assert decision["hard_veto_risk_flags"] == ["AUTHORITY_RISK"]
    assert "AUTHORITY_RISK" in decision["size_clamp_reason"]
    assert "rejected" not in decision["budget_reason"].lower()


def test_position_sizing_policy_uses_total_score_as_base_conviction_and_clamp_flags_only_reduce_size():
    base = build_position_sizing_decision(
        state=StrategySignalState.ARMED.value,
        cash=1.0,
        equity=1.2,
        reserve_cash_sol=0.25,
        current_position_value=0.0,
        token_score_snapshot={"total_score": 0.90},
        token_risk_flags=[],
        wallet_labels=[],
    )
    clamped = build_position_sizing_decision(
        state=StrategySignalState.ARMED.value,
        cash=1.0,
        equity=1.2,
        reserve_cash_sol=0.25,
        current_position_value=0.0,
        token_score_snapshot={"total_score": 0.90},
        token_risk_flags=[
            {"risk_flag": "LOW_LIQUIDITY"},
            {"risk_flag": "TOP10_CONCENTRATION"},
        ],
        wallet_labels=[],
    )
    low_score = build_position_sizing_decision(
        state=StrategySignalState.ARMED.value,
        cash=1.0,
        equity=1.2,
        reserve_cash_sol=0.25,
        current_position_value=0.0,
        token_score_snapshot={"total_score": 0.55},
        token_risk_flags=[],
        wallet_labels=[],
    )

    assert base["new_entry_size"] > 0.0
    assert 0.0 < clamped["new_entry_size"] < base["new_entry_size"]
    assert 0.0 < low_score["new_entry_size"] < base["new_entry_size"]


def test_position_sizing_policy_treats_wallet_labels_as_auxiliary_adjustment_not_primary_driver():
    base = build_position_sizing_decision(
        state=StrategySignalState.ARMED.value,
        cash=1.0,
        equity=1.2,
        reserve_cash_sol=0.25,
        current_position_value=0.0,
        token_score_snapshot={"total_score": 0.80},
        token_risk_flags=[],
        wallet_labels=[],
    )
    smart_money = build_position_sizing_decision(
        state=StrategySignalState.ARMED.value,
        cash=1.0,
        equity=1.2,
        reserve_cash_sol=0.25,
        current_position_value=0.0,
        token_score_snapshot={"total_score": 0.80},
        token_risk_flags=[],
        wallet_labels=[{"label_name": "SMART_MONEY_WALLET", "confidence": 0.85}],
    )
    suspicious = build_position_sizing_decision(
        state=StrategySignalState.ARMED.value,
        cash=1.0,
        equity=1.2,
        reserve_cash_sol=0.25,
        current_position_value=0.0,
        token_score_snapshot={"total_score": 0.80},
        token_risk_flags=[],
        wallet_labels=[{"label_name": "SUSPICIOUS_CLUSTER_WALLET", "confidence": 0.90}],
    )

    assert base["new_entry_size"] > 0.0
    assert smart_money["new_entry_size"] >= base["new_entry_size"]
    assert 0.0 < suspicious["new_entry_size"] < base["new_entry_size"]
