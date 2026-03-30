import pytest

import modules.training_label_builder as training_label_builder
import modules.training_sample_builder as training_sample_builder
from modules.paper_ledger_repository import InMemoryPaperLedgerRepository
from modules.strategy_state import AnalysisPathKind, lifecycle_context_scope


class _RecordLike:
    def __init__(self, payload):
        self._payload = dict(payload)

    def __getitem__(self, key):
        return self._payload[key]

    def __iter__(self):
        return iter(self._payload.items())

    def keys(self):
        return self._payload.keys()


async def _create_sample(sample_repo, *, analysis_run_id, ca, final_action):
    with lifecycle_context_scope(
        path_kind=AnalysisPathKind.MAIN_STATE_MACHINE.value,
        source="test_training_label_builder",
        analysis_run_id=analysis_run_id,
        legacy_path=False,
        metadata={
            "trace_link": f"{ca}:77:88",
            "lifecycle_key": f"deep_analysis:{ca}:77:88",
        },
    ):
        return await training_sample_builder.create_training_sample(
            ca=ca,
            final_action=final_action,
            strategy_id="SMART_TREND",
            frozen_features={
                "cap_usd": 123000.0,
                "maker_vol_ratio": 1.5,
            },
            feature_sources={
                "cap_usd": "canonical",
                "maker_vol_ratio": "feature_engine",
            },
            repository=sample_repo,
        )


@pytest.mark.asyncio
async def test_label_builder_uses_paper_trade_close_truth_for_trade_result():
    sample_repo = training_sample_builder.InMemoryTrainingSampleRepository()
    label_repo = training_label_builder.InMemoryTrainingLabelRepository()
    paper_repo = InMemoryPaperLedgerRepository()

    sample_id = await _create_sample(
        sample_repo,
        analysis_run_id=801,
        ca="CA_LABEL",
        final_action="ENTER",
    )

    paper_repo.orders.append(
        {
            "order_id": "ord_open_label_1",
            "analysis_run_id": 801,
            "ca": "CA_LABEL",
            "position_id": "pos_label_1",
            "intent": "open",
            "side": "BUY",
        }
    )
    paper_repo.trade_closes.append(
        {
            "trade_close_id": "close_label_1",
            "position_id": "pos_label_1",
            "order_id": "ord_close_label_1",
            "fill_id": "fill_close_label_1",
            "ca": "CA_LABEL",
            "strategy": "SMART_TREND",
            "opened_at": 1700000000.0,
            "closed_at": 1700001000.0,
            "close_reason": "CLOSED_TP",
            "partial": False,
            "close_ratio": 1.0,
            "entry_notional_sol": 1.0,
            "exit_notional_sol": 1.9,
            "total_fee_sol": 0.05,
            "realized_pnl_sol": 0.85,
            "realized_return_pct": 85.0,
        }
    )

    label = await training_label_builder.build_training_label_for_sample(
        sample_id=sample_id,
        sample_repository=sample_repo,
        paper_ledger_repository=paper_repo,
        repository=label_repo,
    )

    assert len(label_repo.labels) == 1
    assert label["sample_id"] == sample_id
    assert label["analysis_run_id"] == 801
    assert label["ca"] == "CA_LABEL"
    assert label["label_kind"] == "trade_closed"
    assert label["label_source"] == "paper_trade_closes"
    assert label["position_ids"] == ["pos_label_1"]
    assert label["close_legs"] == 1
    assert label["realized_pnl_sol"] == pytest.approx(0.85)
    assert label["realized_return_pct"] == pytest.approx(85.0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("analysis_run_id", "final_action", "expected_label_kind"),
    [
        (802, "WATCH", "no_trade"),
        (803, "ENTER", "no_fill"),
    ],
)
async def test_label_builder_generates_explicit_no_trade_and_no_fill_labels(
    analysis_run_id,
    final_action,
    expected_label_kind,
):
    sample_repo = training_sample_builder.InMemoryTrainingSampleRepository()
    label_repo = training_label_builder.InMemoryTrainingLabelRepository()
    paper_repo = InMemoryPaperLedgerRepository()

    sample_id = await _create_sample(
        sample_repo,
        analysis_run_id=analysis_run_id,
        ca=f"CA_{expected_label_kind.upper()}",
        final_action=final_action,
    )

    label = await training_label_builder.build_training_label_for_sample(
        sample_id=sample_id,
        sample_repository=sample_repo,
        paper_ledger_repository=paper_repo,
        repository=label_repo,
    )

    assert len(label_repo.labels) == 1
    assert label["sample_id"] == sample_id
    assert label["analysis_run_id"] == analysis_run_id
    assert label["label_kind"] == expected_label_kind
    assert label["label_source"] == "paper_ledger"
    assert label["close_legs"] == 0
    assert label["realized_pnl_sol"] == pytest.approx(0.0)
    assert label["realized_return_pct"] == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_label_builder_aggregates_multi_leg_trade_into_single_sample_label():
    sample_repo = training_sample_builder.InMemoryTrainingSampleRepository()
    label_repo = training_label_builder.InMemoryTrainingLabelRepository()
    paper_repo = InMemoryPaperLedgerRepository()

    sample_id = await _create_sample(
        sample_repo,
        analysis_run_id=804,
        ca="CA_MULTI",
        final_action="ENTER",
    )

    paper_repo.orders.append(
        {
            "order_id": "ord_open_multi_1",
            "analysis_run_id": 804,
            "ca": "CA_MULTI",
            "position_id": "pos_multi_1",
            "intent": "open",
            "side": "BUY",
        }
    )
    paper_repo.trade_closes.extend(
        [
            {
                "trade_close_id": "close_multi_1",
                "position_id": "pos_multi_1",
                "order_id": "ord_reduce_multi_1",
                "fill_id": "fill_reduce_multi_1",
                "ca": "CA_MULTI",
                "strategy": "SMART_TREND",
                "opened_at": 1700000000.0,
                "closed_at": 1700000500.0,
                "close_reason": "止盈1",
                "partial": True,
                "close_ratio": 0.5,
                "entry_notional_sol": 0.5,
                "exit_notional_sol": 0.72,
                "total_fee_sol": 0.02,
                "realized_pnl_sol": 0.20,
                "realized_return_pct": 40.0,
            },
            {
                "trade_close_id": "close_multi_2",
                "position_id": "pos_multi_1",
                "order_id": "ord_close_multi_1",
                "fill_id": "fill_close_multi_1",
                "ca": "CA_MULTI",
                "strategy": "SMART_TREND",
                "opened_at": 1700000000.0,
                "closed_at": 1700001000.0,
                "close_reason": "CLOSED_TP",
                "partial": False,
                "close_ratio": 1.0,
                "entry_notional_sol": 0.5,
                "exit_notional_sol": 1.10,
                "total_fee_sol": 0.03,
                "realized_pnl_sol": 0.57,
                "realized_return_pct": 114.0,
            },
        ]
    )

    label = await training_label_builder.build_training_label_for_sample(
        sample_id=sample_id,
        sample_repository=sample_repo,
        paper_ledger_repository=paper_repo,
        repository=label_repo,
    )

    assert len(label_repo.labels) == 1
    assert label["sample_id"] == sample_id
    assert label["analysis_run_id"] == 804
    assert label["label_kind"] == "trade_closed"
    assert label["label_source"] == "paper_trade_closes"
    assert label["position_ids"] == ["pos_multi_1"]
    assert label["close_legs"] == 2
    assert label["realized_pnl_sol"] == pytest.approx(0.77)
    assert label["realized_return_pct"] == pytest.approx(77.0)
    assert "CLOSED_TP" in label["close_reasons"]


def test_build_training_labels_batch_entry_generates_labels_for_all_samples():
    sample_repo = training_sample_builder.InMemoryTrainingSampleRepository()
    label_repo = training_label_builder.InMemoryTrainingLabelRepository()
    paper_repo = InMemoryPaperLedgerRepository()

    sample_repo.samples.extend(
        [
            {
                "sample_id": "sample_batch_trade_1",
                "analysis_run_id": 805,
                "ca": "CA_BATCH_TRADE",
                "final_action": "ENTER",
                "strategy_id": "SMART_TREND",
                "trace_link": "CA_BATCH_TRADE:1:2",
                "path_kind": AnalysisPathKind.MAIN_STATE_MACHINE.value,
                "source": "run_deep_analysis",
                "legacy_path": False,
                "frozen_features": {"cap_usd": 100000.0},
                "feature_sources": {"cap_usd": "stable_snapshot"},
                "metadata": {},
            },
            {
                "sample_id": "sample_batch_watch_1",
                "analysis_run_id": 806,
                "ca": "CA_BATCH_WATCH",
                "final_action": "WATCH",
                "strategy_id": "SMART_TREND",
                "trace_link": "CA_BATCH_WATCH:1:2",
                "path_kind": AnalysisPathKind.MAIN_STATE_MACHINE.value,
                "source": "run_deep_analysis",
                "legacy_path": False,
                "frozen_features": {"cap_usd": 90000.0},
                "feature_sources": {"cap_usd": "stable_snapshot"},
                "metadata": {},
            },
        ]
    )
    paper_repo.orders.append(
        {
            "order_id": "ord_batch_open_1",
            "analysis_run_id": 805,
            "ca": "CA_BATCH_TRADE",
            "position_id": "pos_batch_1",
            "intent": "open",
            "side": "BUY",
        }
    )
    paper_repo.trade_closes.append(
        {
            "trade_close_id": "close_batch_1",
            "position_id": "pos_batch_1",
            "order_id": "ord_batch_close_1",
            "fill_id": "fill_batch_close_1",
            "ca": "CA_BATCH_TRADE",
            "strategy": "SMART_TREND",
            "opened_at": 1700000000.0,
            "closed_at": 1700001000.0,
            "close_reason": "CLOSED_TP",
            "partial": False,
            "close_ratio": 1.0,
            "entry_notional_sol": 1.0,
            "exit_notional_sol": 1.6,
            "total_fee_sol": 0.04,
            "realized_pnl_sol": 0.56,
            "realized_return_pct": 56.0,
        }
    )

    labels = training_label_builder.build_training_labels(
        sample_repository=sample_repo,
        paper_ledger_repository=paper_repo,
        repository=label_repo,
    )

    assert len(labels) == 2
    assert len(label_repo.labels) == 2
    by_sample = {row["sample_id"]: row for row in labels}
    assert by_sample["sample_batch_trade_1"]["label_kind"] == "trade_closed"
    assert by_sample["sample_batch_watch_1"]["label_kind"] == "no_trade"


@pytest.mark.asyncio
async def test_label_builder_normalizes_db_rows_before_access(monkeypatch):
    label_repo = training_label_builder.InMemoryTrainingLabelRepository()

    class _SampleRepo:
        async def get_sample(self, sample_id):
            return _RecordLike(
                {
                    "sample_id": sample_id,
                    "analysis_run_id": 807,
                    "ca": "CA_DB_LABEL",
                    "final_action": "ENTER",
                    "strategy_id": "SMART_TREND",
                    "trace_link": "CA_DB_LABEL:1:2",
                    "path_kind": AnalysisPathKind.MAIN_STATE_MACHINE.value,
                    "source": "run_deep_analysis",
                    "legacy_path": False,
                    "frozen_features": {"cap_usd": 120000.0},
                    "feature_sources": {"cap_usd": "stable_snapshot"},
                    "metadata": {},
                }
            )

    async def fake_fetch(query, *args):
        if "FROM paper_orders" in query:
            return [
                _RecordLike(
                    {
                        "order_id": "ord_db_label_1",
                        "analysis_run_id": 807,
                        "ca": "CA_DB_LABEL",
                        "position_id": "pos_db_label_1",
                        "intent": "open",
                        "side": "BUY",
                        "legacy_path": False,
                    }
                )
            ]
        if "FROM paper_trade_closes" in query:
            return [
                _RecordLike(
                    {
                        "trade_close_id": "close_db_label_1",
                        "position_id": "pos_db_label_1",
                        "order_id": "ord_db_close_1",
                        "fill_id": "fill_db_close_1",
                        "analysis_run_id": 807,
                        "ca": "CA_DB_LABEL",
                        "strategy": "SMART_TREND",
                        "opened_at": 1700000000.0,
                        "closed_at": 1700001000.0,
                        "close_reason": "CLOSED_TP",
                        "partial": False,
                        "close_ratio": 1.0,
                        "entry_notional_sol": 1.0,
                        "exit_notional_sol": 1.8,
                        "total_fee_sol": 0.05,
                        "realized_pnl_sol": 0.75,
                        "realized_return_pct": 75.0,
                        "legacy_path": False,
                    }
                )
            ]
        raise AssertionError(f"unexpected query: {query}")

    monkeypatch.setattr(training_label_builder.db, "fetch", fake_fetch)

    label = await training_label_builder.build_training_label_for_sample(
        sample_id="sample_db_label_1",
        sample_repository=_SampleRepo(),
        paper_ledger_repository=None,
        repository=label_repo,
    )

    assert label["label_kind"] == "trade_closed"
    assert label["position_ids"] == ["pos_db_label_1"]
    assert label["realized_pnl_sol"] == pytest.approx(0.75)
