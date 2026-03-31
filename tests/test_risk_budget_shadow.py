import inspect

import pytest

from modules.risk_budget import build_risk_budget


def test_risk_budget_derives_available_cash_instead_of_accepting_it_as_truth_source():
    parameters = set(inspect.signature(build_risk_budget).parameters)

    assert "available_cash" not in parameters

    budget = build_risk_budget(
        cash=1.0,
        equity=1.4,
        reserve_cash_sol=0.25,
        current_position_value=0.10,
    )

    assert budget["cash"] == pytest.approx(1.0)
    assert budget["equity"] == pytest.approx(1.4)
    assert budget["available_cash"] == pytest.approx(0.75)
    assert 0.0 < budget["max_position_pct_of_equity"] <= 1.0
    assert 0.0 < budget["max_new_entry_pct_of_available_cash"] <= 1.0
    assert 0.0 < budget["max_add_pct"] <= 1.0
    assert 0.0 < budget["risk_per_trade"] <= 1.0


def test_risk_budget_separates_new_entry_and_add_caps_from_equity_and_available_cash():
    budget = build_risk_budget(
        cash=1.0,
        equity=1.4,
        reserve_cash_sol=0.25,
        current_position_value=0.10,
    )

    assert budget["max_position_value"] == pytest.approx(
        budget["equity"] * budget["max_position_pct_of_equity"]
    )
    assert budget["new_entry_budget"] <= budget["available_cash"]
    assert budget["new_entry_budget"] <= budget["max_position_value"]
    assert budget["add_budget"] <= budget["available_cash"]
    assert budget["add_budget"] <= max(0.0, budget["max_position_value"] - 0.10) + 1e-9
