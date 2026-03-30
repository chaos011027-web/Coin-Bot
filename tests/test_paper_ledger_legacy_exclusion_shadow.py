import asyncio

import pytest

import modules.paper_ledger_service as paper_ledger_service
from modules.paper_ledger_repository import InMemoryPaperLedgerRepository
from modules.paper_portfolio_engine import PaperPortfolioEngine
from modules.strategy_state import AnalysisPathKind, lifecycle_context_scope


async def _drain_tasks():
    await asyncio.sleep(0)
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_legacy_direct_enter_is_excluded_from_first_batch_paper_ledger(monkeypatch, tmp_path):
    repo = InMemoryPaperLedgerRepository()
    engine = PaperPortfolioEngine(state_file=str(tmp_path / "paper_portfolio_state.json"))

    monkeypatch.setattr(paper_ledger_service, "paper_ledger_repository", repo)

    with lifecycle_context_scope(
        path_kind=AnalysisPathKind.LEGACY_DIRECT_ENTER.value,
        source="test_legacy_direct_enter",
        analysis_run_id=123,
        legacy_path=True,
        metadata={
            "trace_link": "CA_LEGACY:55:66",
            "lifecycle_key": "legacy_direct_enter:CA_LEGACY:55:66",
        },
    ):
        order_id = await paper_ledger_service.create_paper_order(
            ca="CA_LEGACY",
            side="BUY",
            intent="open",
            requested_price=1.0,
            strategy_id="MIXED",
            reason="legacy_direct_enter",
            repository=repo,
        )
        ret = engine.open_position(
            ca="CA_LEGACY",
            symbol="LEGACY",
            strategy="MIXED",
            entry_price=1.0,
            entry_mcap=90000.0,
            opened_at=1700000000.0,
            order_id=order_id,
        )

    await _drain_tasks()

    assert order_id is None
    assert ret["ok"] is True
    assert engine.open_positions["CA_LEGACY"]["ledger_excluded"] is True
    assert repo.orders == []
    assert repo.fills == []
    assert repo.positions_ledger == []
    assert repo.cash_ledger == []
    assert repo.trade_closes == []
