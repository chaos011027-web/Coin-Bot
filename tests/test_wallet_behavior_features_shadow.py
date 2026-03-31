import pytest

import modules.db_schema as db_schema
import modules.wallet_behavior_features as wallet_behavior_features


class _RecordingTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _RecordingConnection:
    def __init__(self):
        self.executed = []

    def transaction(self):
        return _RecordingTransaction()

    async def execute(self, sql, *args):
        self.executed.append(str(sql))

    async def fetch(self, sql, *args):
        return []

    async def fetchval(self, sql, *args):
        return False


@pytest.mark.asyncio
async def test_phase10_schema_adds_db_intelligence_tables_without_drifting_existing_baseline():
    conn = _RecordingConnection()

    await db_schema.ensure_schema(conn)

    executed_sql = "\n".join(conn.executed)
    assert f"CREATE TABLE IF NOT EXISTS {db_schema.WALLET_BEHAVIOR_FEATURES_TABLE}" in executed_sql
    assert f"CREATE TABLE IF NOT EXISTS {db_schema.WALLET_LABEL_EVIDENCE_TABLE}" in executed_sql
    assert f"CREATE TABLE IF NOT EXISTS {db_schema.WALLET_LABELS_TABLE}" in executed_sql
    assert f"CREATE TABLE IF NOT EXISTS {db_schema.TOKEN_RISK_FLAGS_TABLE}" in executed_sql
    assert f"CREATE TABLE IF NOT EXISTS {db_schema.TOKEN_SCORE_SNAPSHOTS_TABLE}" in executed_sql

    assert db_schema.TRAINING_LABELS_TABLE == "training_labels"
    assert db_schema.PAPER_TRADE_CLOSES_TABLE == "paper_trade_closes"


def test_wallet_behavior_features_builds_snapshot_from_current_wallet_materials_and_excludes_legacy():
    rows = wallet_behavior_features.build_wallet_behavior_feature_snapshots(
        smart_wallet_rows=[
            {
                "wallet_address": "wallet_alpha",
                "tags": ["Smart Money", "KOL"],
                "total_trades": 7,
                "avg_entry_mcap": 123456.0,
                "last_active": "2026-03-31T10:00:00Z",
            }
        ],
        wallet_cluster_rows=[
            {
                "cluster_id": "cluster_alpha",
                "wallet_address": "wallet_alpha",
                "discovered_in_token": "CA_ALPHA",
                "behavior_tag": "SUSPICIOUS_CLUSTER",
                "risk_level": 8,
                "total_wallets_in_cluster": 4,
                "created_at": "2026-03-31T10:05:00Z",
            },
            {
                "cluster_id": "cluster_legacy",
                "wallet_address": "wallet_alpha",
                "discovered_in_token": "CA_LEGACY",
                "behavior_tag": "SUSPICIOUS_CLUSTER",
                "risk_level": 9,
                "total_wallets_in_cluster": 9,
                "legacy_path": True,
                "created_at": "2026-03-31T09:00:00Z",
            },
        ],
        morphology_rows=[
            {
                "ca": "CA_ALPHA",
                "social_signal": {"ix_data": {"wallets": ["wallet_alpha", "wallet_beta"]}},
                "holder_distribution": {"top_wallets": [{"owner": "wallet_alpha"}]},
                "snapshot_time": "2026-03-31T10:06:00Z",
            },
            {
                "ca": "CA_LEGACY",
                "social_signal": {"ix_data": {"wallets": ["wallet_alpha"]}},
                "holder_distribution": {"top_wallets": [{"owner": "wallet_alpha"}]},
                "path_kind": "LEGACY_DIRECT_ENTER",
                "snapshot_time": "2026-03-31T09:00:00Z",
            },
        ],
        analysis_run_rows=[
            {"id": 9101, "ca": "CA_ALPHA", "legacy_path": False},
            {"id": 9999, "ca": "CA_LEGACY", "path_kind": "LEGACY_DIRECT_ENTER"},
        ],
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["wallet_address"] == "wallet_alpha"
    assert row["snapshot_at"] == "2026-03-31T10:06:00Z"
    assert row["tag_count"] == 2
    assert row["smart_money_tag_hits"] == 1
    assert row["suspicious_cluster_hits"] == 1
    assert row["cluster_risk_level_max"] == 8.0
    assert row["cluster_wallets_total_max"] == 4
    assert row["total_trades"] == 7
    assert row["avg_entry_mcap"] == 123456.0
    assert row["observed_token_count"] == 1
    assert row["social_signal_token_count"] == 1
    assert row["holder_token_count"] == 1
    assert row["last_seen_ca"] == "CA_ALPHA"
    assert row["last_seen_analysis_run_id"] == 9101
