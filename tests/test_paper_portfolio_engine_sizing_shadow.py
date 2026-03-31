import pytest

import modules.paper_portfolio_engine as paper_portfolio_engine
from modules.paper_portfolio_engine import PaperPortfolioEngine
from modules.strategy_state import StrategySignalState


def test_open_position_uses_dynamic_action_to_size_bridge_instead_of_fixed_stake(monkeypatch, tmp_path):
    bridge_calls = []

    def fake_build_action_to_size_decision(**kwargs):
        bridge_calls.append(dict(kwargs))
        return {
            "new_entry_size": 0.1234,
            "max_add_size": 0.0,
            "size_clamp_reason": "no_clamp",
            "budget_reason": "armed_new_entry_size",
        }

    monkeypatch.setattr(
        paper_portfolio_engine,
        "build_action_to_size_decision",
        fake_build_action_to_size_decision,
        raising=False,
    )
    monkeypatch.setattr(paper_portfolio_engine, "record_paper_open_fill_sync", lambda **kwargs: None)
    monkeypatch.setattr(paper_portfolio_engine, "log_execution_event_sync", lambda *args, **kwargs: None)

    engine = PaperPortfolioEngine(state_file=str(tmp_path / "paper_portfolio_state.json"))
    ret = engine.open_position(
        ca="CA_DYNAMIC_SIZE",
        symbol="DYNSZ",
        strategy="SMART_TREND",
        entry_price=1.0,
        entry_mcap=100000.0,
        opened_at=1700000000.0,
        signal_state=StrategySignalState.ARMED.value,
        analysis_run_id=1204,
        token_score_snapshot={"analysis_run_id": 1204, "ca": "CA_DYNAMIC_SIZE", "total_score": 0.88},
        token_risk_flags=[],
        wallet_labels=[],
    )

    assert ret["ok"] is True
    assert ret["allocated_sol"] == pytest.approx(0.1234)
    assert bridge_calls
    assert bridge_calls[0]["state"] == StrategySignalState.ARMED.value


def test_open_position_keeps_budget_driven_cash_and_equity_flow_for_next_add_decision(monkeypatch, tmp_path):
    monkeypatch.setattr(paper_portfolio_engine, "record_paper_open_fill_sync", lambda **kwargs: None)
    monkeypatch.setattr(paper_portfolio_engine, "log_execution_event_sync", lambda *args, **kwargs: None)

    engine = PaperPortfolioEngine(state_file=str(tmp_path / "paper_portfolio_state.json"))
    opened = engine.open_position(
        ca="CA_DYNAMIC_FLOW",
        symbol="FLOW",
        strategy="MIXED",
        entry_price=1.0,
        entry_mcap=100000.0,
        opened_at=1700000000.0,
        signal_state=StrategySignalState.ARMED.value,
        analysis_run_id=1205,
        token_score_snapshot={"analysis_run_id": 1205, "ca": "CA_DYNAMIC_FLOW", "total_score": 0.84},
        token_risk_flags=[],
        wallet_labels=[],
    )

    assert opened["ok"] is True

    engine.mark_price("CA_DYNAMIC_FLOW", 1.2, 125000.0)
    partial = engine.partial_take_profit(
        "CA_DYNAMIC_FLOW",
        1.25,
        130000.0,
        0.4,
        "TP1",
        closed_at=1700000300.0,
    )

    assert partial["ok"] is True

    position = engine.open_positions["CA_DYNAMIC_FLOW"]
    current_position_value = position["remaining_qty"] * position["current_price"]

    from modules.action_to_size_bridge import build_action_to_size_decision

    add_decision = build_action_to_size_decision(
        analysis_run_id=1205,
        ca="CA_DYNAMIC_FLOW",
        state=StrategySignalState.MANAGING.value,
        cash=engine.cash_sol,
        equity=engine.current_equity(),
        reserve_cash_sol=engine.reserve_cash_sol,
        token_score_snapshot={"analysis_run_id": 1205, "ca": "CA_DYNAMIC_FLOW", "total_score": 0.84},
        token_risk_flag_rows=[],
        wallet_label_rows=[],
        current_position_value=current_position_value,
    )

    assert add_decision["max_add_size"] > 0.0
    assert add_decision["max_add_size"] <= add_decision["available_cash"]
    assert add_decision["max_add_size"] <= max(0.0, add_decision["max_position_value"] - current_position_value) + 1e-9
