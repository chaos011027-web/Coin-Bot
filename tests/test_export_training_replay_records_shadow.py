import builtins
from pathlib import Path

import pytest

import export_training_replay_records as training_export
from modules.paper_ledger_repository import InMemoryPaperLedgerRepository
import modules.training_label_builder as training_label_builder
import modules.training_sample_builder as training_sample_builder


class _RecordLike:
    def __init__(self, payload):
        self._payload = dict(payload)

    def __getitem__(self, key):
        return self._payload[key]

    def __iter__(self):
        return iter(self._payload.items())

    def keys(self):
        return self._payload.keys()


def _seed_sample(sample_repo):
    sample_repo.samples.append(
        {
            "sample_id": "sample_export_901",
            "analysis_run_id": 901,
            "ca": "CA_EXPORT",
            "final_action": "ENTER",
            "strategy_id": "SMART_TREND",
            "trace_link": "CA_EXPORT:91:92",
            "path_kind": "main_state_machine",
            "source": "run_deep_analysis",
            "legacy_path": False,
            "frozen_features": {
                "cap_usd": 166000.0,
                "maker_vol_ratio": 1.25,
                "smart_money_delta": 5.0,
            },
            "feature_sources": {
                "cap_usd": "stable_snapshot",
                "maker_vol_ratio": "feature_engine",
                "smart_money_delta": "feature_engine",
            },
            "metadata": {},
        }
    )
    return sample_repo.samples[0]


def _seed_trade_ledger(paper_repo):
    paper_repo.orders.append(
        {
            "order_id": "ord_export_open_1",
            "analysis_run_id": 901,
            "ca": "CA_EXPORT",
            "position_id": "pos_export_1",
            "intent": "open",
            "side": "BUY",
        }
    )
    paper_repo.trade_closes.extend(
        [
            {
                "trade_close_id": "close_export_1",
                "position_id": "pos_export_1",
                "order_id": "ord_export_reduce_1",
                "fill_id": "fill_export_reduce_1",
                "ca": "CA_EXPORT",
                "strategy": "SMART_TREND",
                "opened_at": 1700000000.0,
                "closed_at": 1700000500.0,
                "close_reason": "姝㈢泩1",
                "partial": True,
                "close_ratio": 0.5,
                "entry_notional_sol": 0.5,
                "exit_notional_sol": 0.90,
                "total_fee_sol": 0.02,
                "realized_pnl_sol": 0.38,
                "realized_return_pct": 76.0,
            },
            {
                "trade_close_id": "close_export_2",
                "position_id": "pos_export_1",
                "order_id": "ord_export_close_1",
                "fill_id": "fill_export_close_1",
                "ca": "CA_EXPORT",
                "strategy": "SMART_TREND",
                "opened_at": 1700000000.0,
                "closed_at": 1700001000.0,
                "close_reason": "CLOSED_TP",
                "partial": False,
                "close_ratio": 1.0,
                "entry_notional_sol": 0.5,
                "exit_notional_sol": 1.50,
                "total_fee_sol": 0.03,
                "realized_pnl_sol": 0.95,
                "realized_return_pct": 190.0,
            },
        ]
    )


def test_export_entry_consumes_new_sample_and_generated_label_without_old_state_fallback(monkeypatch):
    sample_repo = training_sample_builder.InMemoryTrainingSampleRepository()
    label_repo = training_label_builder.InMemoryTrainingLabelRepository()
    paper_repo = InMemoryPaperLedgerRepository()
    sample = _seed_sample(sample_repo)
    _seed_trade_ledger(paper_repo)
    labels = training_label_builder.build_training_labels(
        sample_repository=sample_repo,
        paper_ledger_repository=paper_repo,
        repository=label_repo,
    )
    label = labels[0]

    forbidden_files = (
        "paper_portfolio_state.json",
        "tp_tracker.json",
        "strategy_performance.json",
    )
    real_open = builtins.open
    real_path_open = Path.open
    real_path_read_text = Path.read_text

    def _assert_not_legacy_fallback(target):
        path_text = str(target)
        for filename in forbidden_files:
            if filename in path_text:
                raise AssertionError(f"unexpected legacy fallback: {path_text}")

    def guarded_open(file, *args, **kwargs):
        _assert_not_legacy_fallback(file)
        return real_open(file, *args, **kwargs)

    def guarded_path_open(self, *args, **kwargs):
        _assert_not_legacy_fallback(self)
        return real_path_open(self, *args, **kwargs)

    def guarded_read_text(self, *args, **kwargs):
        _assert_not_legacy_fallback(self)
        return real_path_read_text(self, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(Path, "open", guarded_path_open)
    monkeypatch.setattr(Path, "read_text", guarded_read_text)

    records = training_export.build_training_replay_records(
        sample_repository=sample_repo,
        label_repository=label_repo,
    )

    assert len(records) == 1
    record = records[0]
    assert record["sample_id"] == sample["sample_id"]
    assert record["analysis_run_id"] == sample["analysis_run_id"]
    assert record["ca"] == sample["ca"]
    assert record["final_action"] == sample["final_action"]
    assert record["trace_link"] == sample["trace_link"]
    assert record["path_kind"] == sample["path_kind"]
    assert record["frozen_features"] == sample["frozen_features"]
    assert record["feature_sources"] == sample["feature_sources"]
    assert record["label"]["label_kind"] == label["label_kind"]
    assert record["label"]["label_source"] == label["label_source"]
    assert record["label"]["close_legs"] == 2
    assert record["label"]["realized_pnl_sol"] == pytest.approx(1.33)


def test_export_entry_uses_frozen_sample_features_without_recomputing(monkeypatch):
    sample_repo = training_sample_builder.InMemoryTrainingSampleRepository()
    label_repo = training_label_builder.InMemoryTrainingLabelRepository()
    paper_repo = InMemoryPaperLedgerRepository()
    sample = _seed_sample(sample_repo)
    _seed_trade_ledger(paper_repo)
    training_label_builder.build_training_labels(
        sample_repository=sample_repo,
        paper_ledger_repository=paper_repo,
        repository=label_repo,
    )

    if hasattr(training_export, "calculate_ml_features"):
        monkeypatch.setattr(
            training_export,
            "calculate_ml_features",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("export must not recompute features")),
        )

    records = training_export.build_training_replay_records(
        sample_repository=sample_repo,
        label_repository=label_repo,
    )

    assert len(records) == 1
    assert records[0]["frozen_features"]["maker_vol_ratio"] == pytest.approx(1.25)
    assert records[0]["frozen_features"]["smart_money_delta"] == pytest.approx(5.0)


@pytest.mark.parametrize("missing_target", ["sample", "label"])
def test_export_entry_fails_loudly_when_sample_or_label_is_missing(missing_target):
    sample_repo = training_sample_builder.InMemoryTrainingSampleRepository()
    label_repo = training_label_builder.InMemoryTrainingLabelRepository()

    if missing_target == "label":
        _seed_sample(sample_repo)
    else:
        label_repo.labels.append(
            {
                "sample_id": "sample_missing_999",
                "analysis_run_id": 999,
                "ca": "CA_MISSING",
                "label_kind": "trade_closed",
                "label_source": "paper_trade_closes",
                "position_ids": ["pos_missing_1"],
                "close_legs": 1,
                "close_reasons": ["CLOSED_TP"],
                "realized_pnl_sol": 0.42,
                "realized_return_pct": 42.0,
                "metadata": {},
            }
        )

    with pytest.raises(RuntimeError):
        training_export.build_training_replay_records(
            sample_repository=sample_repo,
            label_repository=label_repo,
        )


def test_export_entry_normalizes_record_like_rows_before_merge():
    class _SampleRepo:
        async def list_samples(self):
            return [
                _RecordLike(
                    {
                        "sample_id": "sample_export_db_1",
                        "analysis_run_id": 902,
                        "ca": "CA_EXPORT_DB",
                        "final_action": "ENTER",
                        "strategy_id": "SMART_TREND",
                        "trace_link": "CA_EXPORT_DB:1:2",
                        "path_kind": "main_state_machine",
                        "source": "run_deep_analysis",
                        "legacy_path": False,
                        "frozen_features": {"cap_usd": 155000.0},
                        "feature_sources": {"cap_usd": "stable_snapshot"},
                        "metadata": {},
                    }
                )
            ]

    class _LabelRepo:
        async def list_labels(self):
            return [
                _RecordLike(
                    {
                        "sample_id": "sample_export_db_1",
                        "analysis_run_id": 902,
                        "ca": "CA_EXPORT_DB",
                        "label_kind": "trade_closed",
                        "label_source": "paper_trade_closes",
                        "position_ids": ["pos_export_db_1"],
                        "close_legs": 1,
                        "close_reasons": ["CLOSED_TP"],
                        "realized_pnl_sol": 0.88,
                        "realized_return_pct": 88.0,
                        "metadata": {},
                    }
                )
            ]

    records = training_export.build_training_replay_records(
        sample_repository=_SampleRepo(),
        label_repository=_LabelRepo(),
    )

    assert len(records) == 1
    assert records[0]["sample_id"] == "sample_export_db_1"
    assert records[0]["label"]["label_kind"] == "trade_closed"
    assert records[0]["label"]["realized_pnl_sol"] == pytest.approx(0.88)
