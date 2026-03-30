import asyncio
import copy

import pytest

import main
import modules.training_sample_builder as training_sample_builder
from modules.lifecycle_models import LifecycleContext
from modules.strategy_state import (
    AnalysisPathKind,
    lifecycle_context_scope,
    set_current_lifecycle_context,
)


class _RecordLike:
    def __init__(self, payload):
        self._payload = dict(payload)

    def __getitem__(self, key):
        return self._payload[key]

    def __iter__(self):
        return iter(self._payload.items())

    def keys(self):
        return self._payload.keys()


@pytest.mark.asyncio
async def test_run_deep_analysis_non_legacy_creates_first_class_training_sample(monkeypatch):
    repo = training_sample_builder.InMemoryTrainingSampleRepository()

    async def fake_start_analysis_run(
        ca,
        *,
        source,
        path_kind,
        chat_id=None,
        message_id=None,
        metadata=None,
        legacy_path=False,
        repository=None,
    ):
        context = LifecycleContext(
            path_kind=path_kind,
            source=source,
            analysis_run_id=701,
            chat_id=chat_id,
            message_id=message_id,
            legacy_path=legacy_path,
            metadata=dict(metadata or {}),
        )
        token = set_current_lifecycle_context(context)
        return context, token

    async def fake_noop(*args, **kwargs):
        return None

    async def fake_get_signal_snapshot(ca):
        return {}

    async def fake_update_signal_analysis(*args, **kwargs):
        return None

    async def fake_ensure_token_avatar(*args, **kwargs):
        return ""

    async def fake_get_baseline_metrics(*args, **kwargs):
        return {"baseline_price": 1.0}

    async def fake_analyze_static(*args, **kwargs):
        return {}

    async def fake_analyze_dynamic(*args, **kwargs):
        return {"verdict": main.ACTION_ENTER, "reason": "sample entry"}

    async def fake_apply_execution_state_machine(*args, **kwargs):
        return {"verdict": main.ACTION_ENTER, "reason": "sample entry", "score": 88.0}, main.SIGNAL_STATE_ENTERED

    monkeypatch.setattr(training_sample_builder, "training_sample_repository", repo)
    monkeypatch.setattr(main, "start_analysis_run", fake_start_analysis_run)
    monkeypatch.setattr(main, "finish_analysis_run", fake_noop)
    monkeypatch.setattr(main.db, "get_signal_snapshot", fake_get_signal_snapshot)
    monkeypatch.setattr(main.db, "save_initial_signal", fake_noop)
    monkeypatch.setattr(main.db, "update_signal_analysis", fake_update_signal_analysis)
    monkeypatch.setattr(main.fetcher, "ensure_token_avatar", fake_ensure_token_avatar)
    monkeypatch.setattr(main.tp_tracker, "ensure_observing", fake_noop)
    monkeypatch.setattr(main.tp_tracker, "get_baseline_metrics", fake_get_baseline_metrics)
    monkeypatch.setattr(main, "get_rugcheck_data", fake_noop)
    monkeypatch.setattr(main, "get_goplus_security", fake_noop)
    monkeypatch.setattr(main.bitquery, "fetch_comprehensive_data", fake_noop)
    monkeypatch.setattr(main, "get_gmgn_analytics", fake_noop)
    monkeypatch.setattr(main.brain, "analyze_static_narrative", fake_analyze_static)
    monkeypatch.setattr(main.brain, "analyze_dynamic_strategy", fake_analyze_dynamic)
    monkeypatch.setattr(main, "detect_strategy", lambda token_data: ("SMART_TREND", {"score": 88.0}))
    monkeypatch.setattr(main, "apply_final_gate", lambda token_data, decision, _: (decision, {}, None))
    monkeypatch.setattr(main, "_apply_execution_state_machine", fake_apply_execution_state_machine)
    monkeypatch.setattr(main, "update_user_message", fake_noop)
    monkeypatch.setattr(main, "log_decision_chain", fake_noop)
    monkeypatch.setattr(main, "evolve_database", fake_noop)
    monkeypatch.setattr(main, "LGB_AVAILABLE", False)

    await main.run_deep_analysis(
        "CA_SAMPLE_MAIN",
        {
            "symbol": "SMP",
            "price_usd": 1.25,
            "cap_usd": 125000.0,
            "liquidity_usd": 45000.0,
            "pair_liquidity_usd": 45000.0,
            "exit_liquidity_usd": 43000.0,
        },
        message_id=22,
        chat_id=11,
        use_insightx=False,
    )

    await asyncio.sleep(0)

    assert len(repo.samples) == 1
    sample = repo.samples[0]
    assert isinstance(sample["sample_id"], str)
    assert sample["sample_id"]
    assert sample["sample_id"] != str(sample["analysis_run_id"])
    assert sample["analysis_run_id"] == 701
    assert sample["ca"] == "CA_SAMPLE_MAIN"
    assert sample["final_action"] == main.ACTION_ENTER
    assert sample["strategy_id"] == "SMART_TREND"
    assert sample["trace_link"] == "CA_SAMPLE_MAIN:11:22"
    assert sample["path_kind"] == AnalysisPathKind.MAIN_STATE_MACHINE.value
    assert sample["legacy_path"] is False
    assert sample["frozen_features"]["symbol"] == "SMP"
    assert sample["feature_sources"]["symbol"] == "stable_snapshot"


@pytest.mark.asyncio
async def test_training_sample_builder_freezes_feature_payload():
    repo = training_sample_builder.InMemoryTrainingSampleRepository()
    frozen_features = {
        "cap_usd": 99000.0,
        "maker_vol_ratio": 1.25,
        "smart_money_delta": 2.0,
    }
    feature_sources = {
        "cap_usd": "canonical",
        "maker_vol_ratio": "feature_engine",
        "smart_money_delta": "feature_engine",
    }
    expected_features = copy.deepcopy(frozen_features)
    expected_sources = copy.deepcopy(feature_sources)

    with lifecycle_context_scope(
        path_kind=AnalysisPathKind.MAIN_STATE_MACHINE.value,
        source="test_feature_freeze",
        analysis_run_id=702,
        legacy_path=False,
        metadata={
            "trace_link": "CA_FREEZE:33:44",
            "lifecycle_key": "deep_analysis:CA_FREEZE:33:44",
        },
    ):
        sample_id = await training_sample_builder.create_training_sample(
            ca="CA_FREEZE",
            final_action="ENTER",
            strategy_id="SMART_TREND",
            frozen_features=frozen_features,
            feature_sources=feature_sources,
            repository=repo,
        )

    frozen_features["maker_vol_ratio"] = 999.0
    feature_sources["maker_vol_ratio"] = "recomputed_at_export"

    assert sample_id
    assert len(repo.samples) == 1
    sample = repo.samples[0]
    assert sample["sample_id"] == sample_id
    assert sample["analysis_run_id"] == 702
    assert sample["frozen_features"] == expected_features
    assert sample["feature_sources"] == expected_sources


@pytest.mark.asyncio
async def test_legacy_direct_enter_is_excluded_from_training_sample_generation():
    repo = training_sample_builder.InMemoryTrainingSampleRepository()

    with lifecycle_context_scope(
        path_kind=AnalysisPathKind.LEGACY_DIRECT_ENTER.value,
        source="test_legacy_training_sample_exclusion",
        analysis_run_id=703,
        legacy_path=True,
        metadata={
            "trace_link": "CA_LEGACY_SAMPLE:55:66",
            "lifecycle_key": "legacy_direct_enter:CA_LEGACY_SAMPLE:55:66",
        },
    ):
        sample_id = await training_sample_builder.create_training_sample(
            ca="CA_LEGACY_SAMPLE",
            final_action="ENTER",
            strategy_id="MIXED",
            frozen_features={"cap_usd": 88000.0},
            feature_sources={"cap_usd": "canonical"},
            repository=repo,
        )

    assert sample_id is None
    assert repo.samples == []


@pytest.mark.asyncio
async def test_database_training_sample_repository_normalizes_fetch_rows(monkeypatch):
    repo = training_sample_builder.DatabaseTrainingSampleRepository()

    async def fake_fetchrow(*args, **kwargs):
        return _RecordLike(
            {
                "sample_id": "sample_db_1",
                "analysis_run_id": 704,
                "ca": "CA_DB_SAMPLE",
                "final_action": "ENTER",
                "strategy_id": "SMART_TREND",
                "trace_link": "CA_DB_SAMPLE:1:2",
                "path_kind": AnalysisPathKind.MAIN_STATE_MACHINE.value,
                "source": "run_deep_analysis",
                "legacy_path": False,
                "frozen_features": {"cap_usd": 100000.0},
                "feature_sources": {"cap_usd": "stable_snapshot"},
                "metadata": {},
            }
        )

    async def fake_fetch(*args, **kwargs):
        return [
            _RecordLike(
                {
                    "sample_id": "sample_db_1",
                    "analysis_run_id": 704,
                    "ca": "CA_DB_SAMPLE",
                    "final_action": "ENTER",
                    "strategy_id": "SMART_TREND",
                    "trace_link": "CA_DB_SAMPLE:1:2",
                    "path_kind": AnalysisPathKind.MAIN_STATE_MACHINE.value,
                    "source": "run_deep_analysis",
                    "legacy_path": False,
                    "frozen_features": {"cap_usd": 100000.0},
                    "feature_sources": {"cap_usd": "stable_snapshot"},
                    "metadata": {},
                }
            )
        ]

    monkeypatch.setattr(training_sample_builder.db, "fetchrow", fake_fetchrow)
    monkeypatch.setattr(training_sample_builder.db, "fetch", fake_fetch)

    row = await repo.get_sample("sample_db_1")
    rows = await repo.list_samples()

    assert isinstance(row, dict)
    assert row["sample_id"] == "sample_db_1"
    assert isinstance(rows, list)
    assert isinstance(rows[0], dict)
    assert rows[0]["ca"] == "CA_DB_SAMPLE"
