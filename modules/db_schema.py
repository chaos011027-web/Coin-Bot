import os
from typing import Iterable, List, Optional, Sequence, Tuple

import asyncpg

# Official schema baseline:
# - signal_cache_current: authoritative current-signal cache table
# - signal_snapshots: authoritative append-only signal history table
# - signals_snapshot: compatibility view only, kept for legacy reads
SIGNAL_CACHE_TABLE = "signal_cache_current"
SIGNAL_SNAPSHOT_TABLE = "signal_snapshots"
LEGACY_SIGNAL_CACHE_TABLE = "signals_snapshot_legacy_cache"
LEGACY_SIGNAL_HISTORY_TABLE = "signals_snapshot_legacy_history"
TOKENS_META_TABLE = "tokens_meta"
PERFORMANCE_LABELS_TABLE = "performance_labels"
GOLDEN_DOG_TABLE = "golden_dog_morphology"
SMART_WALLET_TABLE = "smart_wallet_intel"
WALLET_CLUSTERS_TABLE = "wallet_clusters"
SIGNALS_SNAPSHOT_VIEW = "signals_snapshot"
ANALYSIS_RUNS_TABLE = "analysis_runs"
STATE_TRANSITIONS_TABLE = "strategy_state_transitions"
DECISION_EVENTS_TABLE = "decision_events"
EXECUTION_EVENTS_TABLE = "execution_events"
PAPER_ORDERS_TABLE = "paper_orders"
PAPER_FILLS_TABLE = "paper_fills"
PAPER_POSITIONS_LEDGER_TABLE = "paper_positions_ledger"
PAPER_CASH_LEDGER_TABLE = "paper_cash_ledger"
PAPER_TRADE_CLOSES_TABLE = "paper_trade_closes"


async def ensure_schema(conn: asyncpg.Connection) -> None:
    # Single schema authority for init, upgrade, and compatibility migrations.
    async with conn.transaction():
        await _ensure_tokens_meta(conn)
        await _ensure_signal_cache_table(conn)
        await _ensure_signal_snapshot_table(conn)
        await _migrate_legacy_signals_snapshot(conn)
        await _ensure_signal_metric_columns(conn, SIGNAL_CACHE_TABLE)
        await _ensure_signal_metric_columns(conn, SIGNAL_SNAPSHOT_TABLE)
        await _backfill_signal_metric_columns(conn, SIGNAL_CACHE_TABLE)
        await _backfill_signal_metric_columns(conn, SIGNAL_SNAPSHOT_TABLE)
        await _ensure_performance_labels(conn)
        await _ensure_golden_dog_table(conn)
        await _backfill_golden_dog_metric_columns(conn)
        await _ensure_smart_wallet_table(conn)
        await _ensure_wallet_clusters_table(conn)
        await _ensure_analysis_runs_table(conn)
        await _ensure_strategy_state_transitions_table(conn)
        await _ensure_decision_events_table(conn)
        await _ensure_execution_events_table(conn)
        await _ensure_paper_orders_table(conn)
        await _ensure_paper_fills_table(conn)
        await _ensure_paper_positions_ledger_table(conn)
        await _ensure_paper_cash_ledger_table(conn)
        await _ensure_paper_trade_closes_table(conn)
        await _ensure_signals_snapshot_view(conn)


async def migrate_database(dsn: Optional[str] = None) -> None:
    target_dsn = dsn or os.getenv("DATABASE_URL") or os.getenv("DB_DSN")
    if not target_dsn:
        raise RuntimeError("DATABASE_URL or DB_DSN must be configured before running migrations.")

    conn = await asyncpg.connect(target_dsn)
    try:
        await ensure_schema(conn)
    finally:
        await conn.close()


async def _ensure_tokens_meta(conn: asyncpg.Connection) -> None:
    await conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TOKENS_META_TABLE} (
            ca TEXT PRIMARY KEY,
            symbol TEXT,
            name TEXT,
            decimals INT DEFAULT 9,
            security_flags JSONB,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        );
        """
    )

    await _add_column_if_missing(conn, TOKENS_META_TABLE, "symbol", "TEXT")
    await _add_column_if_missing(conn, TOKENS_META_TABLE, "name", "TEXT")
    await _add_column_if_missing(conn, TOKENS_META_TABLE, "decimals", "INT DEFAULT 9")
    await _add_column_if_missing(conn, TOKENS_META_TABLE, "security_flags", "JSONB")
    await _add_column_if_missing(conn, TOKENS_META_TABLE, "created_at", "TIMESTAMP DEFAULT NOW()")
    await _add_column_if_missing(conn, TOKENS_META_TABLE, "updated_at", "TIMESTAMP DEFAULT NOW()")


async def _ensure_signal_cache_table(conn: asyncpg.Connection) -> None:
    await conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SIGNAL_CACHE_TABLE} (
            ca TEXT PRIMARY KEY,
            source TEXT,
            status TEXT DEFAULT 'pending',
            rank_score DOUBLE PRECISION,
            ai_narrative TEXT,
            entry_price DOUBLE PRECISION,
            last_notified_price DOUBLE PRECISION,
            initial_msg_id BIGINT,
            top10_raw_pct DOUBLE PRECISION,
            top10_adjusted_pct DOUBLE PRECISION,
            pair_liquidity_usd DOUBLE PRECISION,
            exit_liquidity_usd DOUBLE PRECISION,
            metric_confidence JSONB,
            source_conflict JSONB,
            terminal_states JSONB DEFAULT '{{}}'::jsonb,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        );
        """
    )

    await _add_column_if_missing(conn, SIGNAL_CACHE_TABLE, "source", "TEXT")
    await _add_column_if_missing(conn, SIGNAL_CACHE_TABLE, "status", "TEXT DEFAULT 'pending'")
    await _add_column_if_missing(conn, SIGNAL_CACHE_TABLE, "rank_score", "DOUBLE PRECISION")
    await _add_column_if_missing(conn, SIGNAL_CACHE_TABLE, "ai_narrative", "TEXT")
    await _add_column_if_missing(conn, SIGNAL_CACHE_TABLE, "entry_price", "DOUBLE PRECISION")
    await _add_column_if_missing(conn, SIGNAL_CACHE_TABLE, "last_notified_price", "DOUBLE PRECISION")
    await _add_column_if_missing(conn, SIGNAL_CACHE_TABLE, "initial_msg_id", "BIGINT")
    await _add_column_if_missing(conn, SIGNAL_CACHE_TABLE, "top10_raw_pct", "DOUBLE PRECISION")
    await _add_column_if_missing(conn, SIGNAL_CACHE_TABLE, "top10_adjusted_pct", "DOUBLE PRECISION")
    await _add_column_if_missing(conn, SIGNAL_CACHE_TABLE, "pair_liquidity_usd", "DOUBLE PRECISION")
    await _add_column_if_missing(conn, SIGNAL_CACHE_TABLE, "exit_liquidity_usd", "DOUBLE PRECISION")
    await _add_column_if_missing(conn, SIGNAL_CACHE_TABLE, "metric_confidence", "JSONB")
    await _add_column_if_missing(conn, SIGNAL_CACHE_TABLE, "source_conflict", "JSONB")
    await _add_column_if_missing(conn, SIGNAL_CACHE_TABLE, "terminal_states", "JSONB DEFAULT '{}'::jsonb")
    await _add_column_if_missing(conn, SIGNAL_CACHE_TABLE, "created_at", "TIMESTAMP DEFAULT NOW()")
    await _add_column_if_missing(conn, SIGNAL_CACHE_TABLE, "updated_at", "TIMESTAMP DEFAULT NOW()")


async def _ensure_signal_snapshot_table(conn: asyncpg.Connection) -> None:
    await conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SIGNAL_SNAPSHOT_TABLE} (
            id BIGSERIAL PRIMARY KEY,
            legacy_signal_id BIGINT UNIQUE,
            ca TEXT NOT NULL,
            snapshot_time TIMESTAMP DEFAULT NOW(),
            source TEXT,
            status TEXT DEFAULT 'pending',
            rank_score DOUBLE PRECISION,
            features JSONB,
            ai_narrative TEXT,
            entry_price DOUBLE PRECISION,
            last_notified_price DOUBLE PRECISION,
            initial_msg_id BIGINT,
            top10_raw_pct DOUBLE PRECISION,
            top10_adjusted_pct DOUBLE PRECISION,
            pair_liquidity_usd DOUBLE PRECISION,
            exit_liquidity_usd DOUBLE PRECISION,
            metric_confidence JSONB,
            source_conflict JSONB,
            terminal_states JSONB,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """
    )

    await _add_column_if_missing(conn, SIGNAL_SNAPSHOT_TABLE, "legacy_signal_id", "BIGINT")
    await _add_column_if_missing(conn, SIGNAL_SNAPSHOT_TABLE, "ca", "TEXT")
    await _add_column_if_missing(conn, SIGNAL_SNAPSHOT_TABLE, "snapshot_time", "TIMESTAMP DEFAULT NOW()")
    await _add_column_if_missing(conn, SIGNAL_SNAPSHOT_TABLE, "source", "TEXT")
    await _add_column_if_missing(conn, SIGNAL_SNAPSHOT_TABLE, "status", "TEXT DEFAULT 'pending'")
    await _add_column_if_missing(conn, SIGNAL_SNAPSHOT_TABLE, "rank_score", "DOUBLE PRECISION")
    await _add_column_if_missing(conn, SIGNAL_SNAPSHOT_TABLE, "features", "JSONB")
    await _add_column_if_missing(conn, SIGNAL_SNAPSHOT_TABLE, "ai_narrative", "TEXT")
    await _add_column_if_missing(conn, SIGNAL_SNAPSHOT_TABLE, "entry_price", "DOUBLE PRECISION")
    await _add_column_if_missing(conn, SIGNAL_SNAPSHOT_TABLE, "last_notified_price", "DOUBLE PRECISION")
    await _add_column_if_missing(conn, SIGNAL_SNAPSHOT_TABLE, "initial_msg_id", "BIGINT")
    await _add_column_if_missing(conn, SIGNAL_SNAPSHOT_TABLE, "top10_raw_pct", "DOUBLE PRECISION")
    await _add_column_if_missing(conn, SIGNAL_SNAPSHOT_TABLE, "top10_adjusted_pct", "DOUBLE PRECISION")
    await _add_column_if_missing(conn, SIGNAL_SNAPSHOT_TABLE, "pair_liquidity_usd", "DOUBLE PRECISION")
    await _add_column_if_missing(conn, SIGNAL_SNAPSHOT_TABLE, "exit_liquidity_usd", "DOUBLE PRECISION")
    await _add_column_if_missing(conn, SIGNAL_SNAPSHOT_TABLE, "metric_confidence", "JSONB")
    await _add_column_if_missing(conn, SIGNAL_SNAPSHOT_TABLE, "source_conflict", "JSONB")
    await _add_column_if_missing(conn, SIGNAL_SNAPSHOT_TABLE, "terminal_states", "JSONB")
    await _add_column_if_missing(conn, SIGNAL_SNAPSHOT_TABLE, "created_at", "TIMESTAMP DEFAULT NOW()")

    await conn.execute(
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_{SIGNAL_SNAPSHOT_TABLE}_legacy_signal_id
        ON {SIGNAL_SNAPSHOT_TABLE} (legacy_signal_id)
        WHERE legacy_signal_id IS NOT NULL;
        """
    )
    await conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{SIGNAL_SNAPSHOT_TABLE}_ca_snapshot_time
        ON {SIGNAL_SNAPSHOT_TABLE} (ca, snapshot_time DESC);
        """
    )


async def _ensure_signal_metric_columns(conn: asyncpg.Connection, table_name: str) -> None:
    await _add_column_if_missing(conn, table_name, "top10_raw_pct", "DOUBLE PRECISION")
    await _add_column_if_missing(conn, table_name, "top10_adjusted_pct", "DOUBLE PRECISION")
    await _add_column_if_missing(conn, table_name, "pair_liquidity_usd", "DOUBLE PRECISION")
    await _add_column_if_missing(conn, table_name, "exit_liquidity_usd", "DOUBLE PRECISION")
    await _add_column_if_missing(conn, table_name, "metric_confidence", "JSONB")
    await _add_column_if_missing(conn, table_name, "source_conflict", "JSONB")


async def _backfill_signal_metric_columns(conn: asyncpg.Connection, table_name: str) -> None:
    top10_raw_expr = _coalesce_numeric_from_json(
        "terminal_states",
        [
            ("stable_snapshot", "top10_raw_pct"),
            ("top10_raw_pct",),
            ("stable_snapshot", "top10_ratio"),
            ("top10_ratio",),
        ],
    )
    top10_adjusted_expr = _coalesce_numeric_from_json(
        "terminal_states",
        [
            ("stable_snapshot", "top10_adjusted_pct"),
            ("top10_adjusted_pct",),
            ("stable_snapshot", "top10_ratio"),
            ("top10_ratio",),
        ],
    )
    pair_liq_expr = _coalesce_numeric_from_json(
        "terminal_states",
        [
            ("stable_snapshot", "pair_liquidity_usd"),
            ("pair_liquidity_usd",),
            ("stable_snapshot", "liquidity_usd"),
            ("liquidity_usd",),
        ],
    )
    exit_liq_expr = _coalesce_numeric_from_json(
        "terminal_states",
        [
            ("stable_snapshot", "exit_liquidity_usd"),
            ("exit_liquidity_usd",),
            ("stable_snapshot", "liquidity_usd"),
            ("liquidity_usd",),
        ],
    )
    metric_confidence_expr = _coalesce_jsonb_from_paths(
        "terminal_states",
        [
            ("stable_snapshot", "metric_confidence"),
            ("metric_confidence",),
        ],
    )
    source_conflict_expr = _coalesce_jsonb_from_paths(
        "terminal_states",
        [
            ("stable_snapshot", "source_conflict"),
            ("source_conflict",),
        ],
    )

    await conn.execute(
        f"""
        UPDATE {table_name}
        SET top10_raw_pct = COALESCE(top10_raw_pct, {top10_raw_expr}),
            top10_adjusted_pct = COALESCE(top10_adjusted_pct, {top10_adjusted_expr}),
            pair_liquidity_usd = COALESCE(pair_liquidity_usd, {pair_liq_expr}),
            exit_liquidity_usd = COALESCE(exit_liquidity_usd, {exit_liq_expr}),
            metric_confidence = COALESCE(metric_confidence, {metric_confidence_expr}),
            source_conflict = COALESCE(source_conflict, {source_conflict_expr})
        WHERE terminal_states IS NOT NULL
          AND (
              top10_raw_pct IS NULL
              OR top10_adjusted_pct IS NULL
              OR pair_liquidity_usd IS NULL
              OR exit_liquidity_usd IS NULL
              OR metric_confidence IS NULL
              OR source_conflict IS NULL
          );
        """
    )


async def _migrate_legacy_signals_snapshot(conn: asyncpg.Connection) -> None:
    if await _table_exists(conn, SIGNALS_SNAPSHOT_VIEW):
        legacy_columns = await _get_columns(conn, SIGNALS_SNAPSHOT_VIEW)
        if "id" in legacy_columns:
            if not await _table_exists(conn, LEGACY_SIGNAL_HISTORY_TABLE):
                await conn.execute(
                    f"ALTER TABLE {SIGNALS_SNAPSHOT_VIEW} RENAME TO {LEGACY_SIGNAL_HISTORY_TABLE};"
                )
        else:
            if not await _table_exists(conn, LEGACY_SIGNAL_CACHE_TABLE):
                await conn.execute(
                    f"ALTER TABLE {SIGNALS_SNAPSHOT_VIEW} RENAME TO {LEGACY_SIGNAL_CACHE_TABLE};"
                )

    if await _table_exists(conn, LEGACY_SIGNAL_CACHE_TABLE):
        legacy_columns = await _get_columns(conn, LEGACY_SIGNAL_CACHE_TABLE)
        await conn.execute(
            f"""
            INSERT INTO {SIGNAL_CACHE_TABLE}
                (ca, source, status, rank_score, ai_narrative, entry_price,
                 last_notified_price, initial_msg_id, top10_raw_pct, top10_adjusted_pct,
                 pair_liquidity_usd, exit_liquidity_usd, metric_confidence, source_conflict,
                 terminal_states, created_at, updated_at)
            SELECT
                ca,
                {_legacy_expr(legacy_columns, 'source', 'NULL::text')},
                {_legacy_expr(legacy_columns, 'status', "'pending'::text")},
                {_legacy_expr(legacy_columns, 'rank_score', 'NULL::double precision')},
                {_legacy_expr(legacy_columns, 'ai_narrative', 'NULL::text')},
                {_legacy_expr(legacy_columns, 'entry_price', 'NULL::double precision')},
                {_legacy_expr(legacy_columns, 'last_notified_price', 'NULL::double precision')},
                {_legacy_expr(legacy_columns, 'initial_msg_id', 'NULL::bigint')},
                {_legacy_numeric_expr(legacy_columns, ('top10_raw_pct', 'top10_ratio'))},
                {_legacy_numeric_expr(legacy_columns, ('top10_adjusted_pct', 'top10_raw_pct', 'top10_ratio'))},
                {_legacy_numeric_expr(legacy_columns, ('pair_liquidity_usd', 'liquidity_usd'))},
                {_legacy_numeric_expr(legacy_columns, ('exit_liquidity_usd', 'liquidity_usd', 'pair_liquidity_usd'))},
                {_legacy_json_first_expr(legacy_columns, ('metric_confidence',), 'NULL::jsonb')},
                {_legacy_json_first_expr(legacy_columns, ('source_conflict',), 'NULL::jsonb')},
                {_legacy_json_expr(legacy_columns, 'terminal_states', "'{}'::jsonb")},
                {_first_available_expr(legacy_columns, ('created_at', 'updated_at'), 'NOW()')},
                {_first_available_expr(legacy_columns, ('updated_at', 'created_at'), 'NOW()')}
            FROM {LEGACY_SIGNAL_CACHE_TABLE}
            WHERE ca IS NOT NULL
            ON CONFLICT (ca) DO UPDATE
            SET source = COALESCE(EXCLUDED.source, {SIGNAL_CACHE_TABLE}.source),
                status = COALESCE(EXCLUDED.status, {SIGNAL_CACHE_TABLE}.status),
                rank_score = COALESCE(EXCLUDED.rank_score, {SIGNAL_CACHE_TABLE}.rank_score),
                ai_narrative = COALESCE(EXCLUDED.ai_narrative, {SIGNAL_CACHE_TABLE}.ai_narrative),
                entry_price = COALESCE(EXCLUDED.entry_price, {SIGNAL_CACHE_TABLE}.entry_price),
                last_notified_price = COALESCE(EXCLUDED.last_notified_price, {SIGNAL_CACHE_TABLE}.last_notified_price),
                initial_msg_id = COALESCE(EXCLUDED.initial_msg_id, {SIGNAL_CACHE_TABLE}.initial_msg_id),
                top10_raw_pct = COALESCE(EXCLUDED.top10_raw_pct, {SIGNAL_CACHE_TABLE}.top10_raw_pct),
                top10_adjusted_pct = COALESCE(EXCLUDED.top10_adjusted_pct, {SIGNAL_CACHE_TABLE}.top10_adjusted_pct),
                pair_liquidity_usd = COALESCE(EXCLUDED.pair_liquidity_usd, {SIGNAL_CACHE_TABLE}.pair_liquidity_usd),
                exit_liquidity_usd = COALESCE(EXCLUDED.exit_liquidity_usd, {SIGNAL_CACHE_TABLE}.exit_liquidity_usd),
                metric_confidence = COALESCE(EXCLUDED.metric_confidence, {SIGNAL_CACHE_TABLE}.metric_confidence),
                source_conflict = COALESCE(EXCLUDED.source_conflict, {SIGNAL_CACHE_TABLE}.source_conflict),
                terminal_states = COALESCE(EXCLUDED.terminal_states, {SIGNAL_CACHE_TABLE}.terminal_states),
                updated_at = GREATEST({SIGNAL_CACHE_TABLE}.updated_at, EXCLUDED.updated_at);
            """
        )

    if await _table_exists(conn, LEGACY_SIGNAL_HISTORY_TABLE):
        legacy_columns = await _get_columns(conn, LEGACY_SIGNAL_HISTORY_TABLE)
        await conn.execute(
            f"""
            INSERT INTO {SIGNAL_SNAPSHOT_TABLE}
                (legacy_signal_id, ca, snapshot_time, source, status, rank_score,
                 features, ai_narrative, entry_price, last_notified_price,
                 initial_msg_id, top10_raw_pct, top10_adjusted_pct, pair_liquidity_usd,
                 exit_liquidity_usd, metric_confidence, source_conflict, terminal_states, created_at)
            SELECT
                id,
                ca,
                {_first_available_expr(legacy_columns, ('snapshot_time', 'trigger_time', 'created_at'), 'NOW()')},
                {_legacy_expr(legacy_columns, 'source', 'NULL::text')},
                {_legacy_expr(legacy_columns, 'status', "'pending'::text")},
                {_legacy_expr(legacy_columns, 'rank_score', 'NULL::double precision')},
                {_legacy_json_expr(legacy_columns, 'features', 'NULL::jsonb')},
                {_legacy_expr(legacy_columns, 'ai_narrative', 'NULL::text')},
                {_legacy_expr(legacy_columns, 'entry_price', 'NULL::double precision')},
                {_legacy_expr(legacy_columns, 'last_notified_price', 'NULL::double precision')},
                {_legacy_expr(legacy_columns, 'initial_msg_id', 'NULL::bigint')},
                {_legacy_numeric_expr(legacy_columns, ('top10_raw_pct', 'top10_ratio'))},
                {_legacy_numeric_expr(legacy_columns, ('top10_adjusted_pct', 'top10_raw_pct', 'top10_ratio'))},
                {_legacy_numeric_expr(legacy_columns, ('pair_liquidity_usd', 'liquidity_usd'))},
                {_legacy_numeric_expr(legacy_columns, ('exit_liquidity_usd', 'liquidity_usd', 'pair_liquidity_usd'))},
                {_legacy_json_first_expr(legacy_columns, ('metric_confidence',), 'NULL::jsonb')},
                {_legacy_json_first_expr(legacy_columns, ('source_conflict',), 'NULL::jsonb')},
                {_legacy_json_expr(legacy_columns, 'terminal_states', 'NULL::jsonb')},
                {_first_available_expr(legacy_columns, ('created_at', 'trigger_time', 'snapshot_time'), 'NOW()')}
            FROM {LEGACY_SIGNAL_HISTORY_TABLE}
            WHERE ca IS NOT NULL
            ON CONFLICT (legacy_signal_id) DO UPDATE
            SET ca = EXCLUDED.ca,
                snapshot_time = EXCLUDED.snapshot_time,
                source = COALESCE(EXCLUDED.source, {SIGNAL_SNAPSHOT_TABLE}.source),
                status = COALESCE(EXCLUDED.status, {SIGNAL_SNAPSHOT_TABLE}.status),
                rank_score = COALESCE(EXCLUDED.rank_score, {SIGNAL_SNAPSHOT_TABLE}.rank_score),
                features = COALESCE(EXCLUDED.features, {SIGNAL_SNAPSHOT_TABLE}.features),
                ai_narrative = COALESCE(EXCLUDED.ai_narrative, {SIGNAL_SNAPSHOT_TABLE}.ai_narrative),
                entry_price = COALESCE(EXCLUDED.entry_price, {SIGNAL_SNAPSHOT_TABLE}.entry_price),
                last_notified_price = COALESCE(EXCLUDED.last_notified_price, {SIGNAL_SNAPSHOT_TABLE}.last_notified_price),
                initial_msg_id = COALESCE(EXCLUDED.initial_msg_id, {SIGNAL_SNAPSHOT_TABLE}.initial_msg_id),
                top10_raw_pct = COALESCE(EXCLUDED.top10_raw_pct, {SIGNAL_SNAPSHOT_TABLE}.top10_raw_pct),
                top10_adjusted_pct = COALESCE(EXCLUDED.top10_adjusted_pct, {SIGNAL_SNAPSHOT_TABLE}.top10_adjusted_pct),
                pair_liquidity_usd = COALESCE(EXCLUDED.pair_liquidity_usd, {SIGNAL_SNAPSHOT_TABLE}.pair_liquidity_usd),
                exit_liquidity_usd = COALESCE(EXCLUDED.exit_liquidity_usd, {SIGNAL_SNAPSHOT_TABLE}.exit_liquidity_usd),
                metric_confidence = COALESCE(EXCLUDED.metric_confidence, {SIGNAL_SNAPSHOT_TABLE}.metric_confidence),
                source_conflict = COALESCE(EXCLUDED.source_conflict, {SIGNAL_SNAPSHOT_TABLE}.source_conflict),
                terminal_states = COALESCE(EXCLUDED.terminal_states, {SIGNAL_SNAPSHOT_TABLE}.terminal_states),
                created_at = LEAST({SIGNAL_SNAPSHOT_TABLE}.created_at, EXCLUDED.created_at);
            """
        )

        await conn.execute(
            f"""
            INSERT INTO {SIGNAL_CACHE_TABLE}
                (ca, source, status, rank_score, ai_narrative, entry_price,
                 last_notified_price, initial_msg_id, top10_raw_pct, top10_adjusted_pct,
                 pair_liquidity_usd, exit_liquidity_usd, metric_confidence, source_conflict,
                 terminal_states, created_at, updated_at)
            SELECT DISTINCT ON (ca)
                ca,
                source,
                status,
                rank_score,
                ai_narrative,
                entry_price,
                last_notified_price,
                initial_msg_id,
                top10_raw_pct,
                top10_adjusted_pct,
                pair_liquidity_usd,
                exit_liquidity_usd,
                metric_confidence,
                source_conflict,
                COALESCE(terminal_states, '{{}}'::jsonb),
                created_at,
                COALESCE(snapshot_time, created_at, NOW())
            FROM {SIGNAL_SNAPSHOT_TABLE}
            WHERE ca IS NOT NULL
            ORDER BY ca, snapshot_time DESC, id DESC
            ON CONFLICT (ca) DO UPDATE
            SET source = COALESCE(EXCLUDED.source, {SIGNAL_CACHE_TABLE}.source),
                status = COALESCE(EXCLUDED.status, {SIGNAL_CACHE_TABLE}.status),
                rank_score = COALESCE(EXCLUDED.rank_score, {SIGNAL_CACHE_TABLE}.rank_score),
                ai_narrative = COALESCE(EXCLUDED.ai_narrative, {SIGNAL_CACHE_TABLE}.ai_narrative),
                entry_price = COALESCE(EXCLUDED.entry_price, {SIGNAL_CACHE_TABLE}.entry_price),
                last_notified_price = COALESCE(EXCLUDED.last_notified_price, {SIGNAL_CACHE_TABLE}.last_notified_price),
                initial_msg_id = COALESCE(EXCLUDED.initial_msg_id, {SIGNAL_CACHE_TABLE}.initial_msg_id),
                top10_raw_pct = COALESCE(EXCLUDED.top10_raw_pct, {SIGNAL_CACHE_TABLE}.top10_raw_pct),
                top10_adjusted_pct = COALESCE(EXCLUDED.top10_adjusted_pct, {SIGNAL_CACHE_TABLE}.top10_adjusted_pct),
                pair_liquidity_usd = COALESCE(EXCLUDED.pair_liquidity_usd, {SIGNAL_CACHE_TABLE}.pair_liquidity_usd),
                exit_liquidity_usd = COALESCE(EXCLUDED.exit_liquidity_usd, {SIGNAL_CACHE_TABLE}.exit_liquidity_usd),
                metric_confidence = COALESCE(EXCLUDED.metric_confidence, {SIGNAL_CACHE_TABLE}.metric_confidence),
                source_conflict = COALESCE(EXCLUDED.source_conflict, {SIGNAL_CACHE_TABLE}.source_conflict),
                terminal_states = COALESCE(EXCLUDED.terminal_states, {SIGNAL_CACHE_TABLE}.terminal_states),
                updated_at = GREATEST({SIGNAL_CACHE_TABLE}.updated_at, EXCLUDED.updated_at);
            """
        )


async def _ensure_performance_labels(conn: asyncpg.Connection) -> None:
    await conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {PERFORMANCE_LABELS_TABLE} (
            signal_id BIGINT,
            snapshot_id BIGINT,
            max_pnl_1h DOUBLE PRECISION,
            max_pnl_6h DOUBLE PRECISION,
            max_pnl_24h DOUBLE PRECISION,
            is_winner BOOLEAN DEFAULT FALSE,
            updated_at TIMESTAMP DEFAULT NOW()
        );
        """
    )

    await _add_column_if_missing(conn, PERFORMANCE_LABELS_TABLE, "signal_id", "BIGINT")
    await _add_column_if_missing(conn, PERFORMANCE_LABELS_TABLE, "snapshot_id", "BIGINT")
    await _add_column_if_missing(conn, PERFORMANCE_LABELS_TABLE, "max_pnl_1h", "DOUBLE PRECISION")
    await _add_column_if_missing(conn, PERFORMANCE_LABELS_TABLE, "max_pnl_6h", "DOUBLE PRECISION")
    await _add_column_if_missing(conn, PERFORMANCE_LABELS_TABLE, "max_pnl_24h", "DOUBLE PRECISION")
    await _add_column_if_missing(conn, PERFORMANCE_LABELS_TABLE, "is_winner", "BOOLEAN DEFAULT FALSE")
    await _add_column_if_missing(conn, PERFORMANCE_LABELS_TABLE, "updated_at", "TIMESTAMP DEFAULT NOW()")

    await conn.execute(
        f"""
        UPDATE {PERFORMANCE_LABELS_TABLE} AS labels
        SET snapshot_id = snaps.id
        FROM {SIGNAL_SNAPSHOT_TABLE} AS snaps
        WHERE labels.snapshot_id IS NULL
          AND labels.signal_id IS NOT NULL
          AND snaps.legacy_signal_id = labels.signal_id;
        """
    )

    if not await _constraint_exists(conn, PERFORMANCE_LABELS_TABLE, "performance_labels_snapshot_id_fkey"):
        await conn.execute(
            f"""
            ALTER TABLE {PERFORMANCE_LABELS_TABLE}
            ADD CONSTRAINT performance_labels_snapshot_id_fkey
            FOREIGN KEY (snapshot_id)
            REFERENCES {SIGNAL_SNAPSHOT_TABLE}(id)
            ON DELETE SET NULL;
            """
        )

    await conn.execute(
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_{PERFORMANCE_LABELS_TABLE}_snapshot_id
        ON {PERFORMANCE_LABELS_TABLE} (snapshot_id)
        WHERE snapshot_id IS NOT NULL;
        """
    )


async def _ensure_golden_dog_table(conn: asyncpg.Connection) -> None:
    await conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {GOLDEN_DOG_TABLE} (
            ca TEXT NOT NULL,
            snapshot_time TIMESTAMP DEFAULT NOW(),
            token_age_mins_at_snap DOUBLE PRECISION DEFAULT 0,
            market_cap_at_snap DOUBLE PRECISION DEFAULT 0,
            liquidity_at_snap DOUBLE PRECISION DEFAULT 0,
            top10_raw_pct DOUBLE PRECISION,
            top10_adjusted_pct DOUBLE PRECISION,
            pair_liquidity_usd DOUBLE PRECISION,
            exit_liquidity_usd DOUBLE PRECISION,
            metric_confidence JSONB,
            source_conflict JSONB,
            holder_distribution TEXT,
            smart_money_metrics TEXT,
            momentum_metrics TEXT,
            social_signal TEXT,
            peak_multiplier DOUBLE PRECISION DEFAULT 1,
            created_at TIMESTAMP DEFAULT NOW(),
            time_stage VARCHAR(20) DEFAULT 'T_0',
            price_usd DOUBLE PRECISION DEFAULT 0,
            smart_money_delta INT DEFAULT 0,
            maker_vol_ratio DOUBLE PRECISION DEFAULT 0,
            overhang_ratio DOUBLE PRECISION DEFAULT 0,
            breakout_vol_ratio DOUBLE PRECISION DEFAULT 0,
            label INT DEFAULT -1,
            PRIMARY KEY (ca, snapshot_time)
        );
        """
    )

    await _add_column_if_missing(conn, GOLDEN_DOG_TABLE, "snapshot_time", "TIMESTAMP DEFAULT NOW()")
    await _add_column_if_missing(conn, GOLDEN_DOG_TABLE, "token_age_mins_at_snap", "DOUBLE PRECISION DEFAULT 0")
    await _add_column_if_missing(conn, GOLDEN_DOG_TABLE, "market_cap_at_snap", "DOUBLE PRECISION DEFAULT 0")
    await _add_column_if_missing(conn, GOLDEN_DOG_TABLE, "liquidity_at_snap", "DOUBLE PRECISION DEFAULT 0")
    await _add_column_if_missing(conn, GOLDEN_DOG_TABLE, "top10_raw_pct", "DOUBLE PRECISION")
    await _add_column_if_missing(conn, GOLDEN_DOG_TABLE, "top10_adjusted_pct", "DOUBLE PRECISION")
    await _add_column_if_missing(conn, GOLDEN_DOG_TABLE, "pair_liquidity_usd", "DOUBLE PRECISION")
    await _add_column_if_missing(conn, GOLDEN_DOG_TABLE, "exit_liquidity_usd", "DOUBLE PRECISION")
    await _add_column_if_missing(conn, GOLDEN_DOG_TABLE, "metric_confidence", "JSONB")
    await _add_column_if_missing(conn, GOLDEN_DOG_TABLE, "source_conflict", "JSONB")
    await _add_column_if_missing(conn, GOLDEN_DOG_TABLE, "holder_distribution", "TEXT")
    await _add_column_if_missing(conn, GOLDEN_DOG_TABLE, "smart_money_metrics", "TEXT")
    await _add_column_if_missing(conn, GOLDEN_DOG_TABLE, "momentum_metrics", "TEXT")
    await _add_column_if_missing(conn, GOLDEN_DOG_TABLE, "social_signal", "TEXT")
    await _add_column_if_missing(conn, GOLDEN_DOG_TABLE, "peak_multiplier", "DOUBLE PRECISION DEFAULT 1")
    await _add_column_if_missing(conn, GOLDEN_DOG_TABLE, "created_at", "TIMESTAMP DEFAULT NOW()")
    await _add_column_if_missing(conn, GOLDEN_DOG_TABLE, "time_stage", "VARCHAR(20) DEFAULT 'T_0'")
    await _add_column_if_missing(conn, GOLDEN_DOG_TABLE, "price_usd", "DOUBLE PRECISION DEFAULT 0")
    await _add_column_if_missing(conn, GOLDEN_DOG_TABLE, "smart_money_delta", "INT DEFAULT 0")
    await _add_column_if_missing(conn, GOLDEN_DOG_TABLE, "maker_vol_ratio", "DOUBLE PRECISION DEFAULT 0")
    await _add_column_if_missing(conn, GOLDEN_DOG_TABLE, "overhang_ratio", "DOUBLE PRECISION DEFAULT 0")
    await _add_column_if_missing(conn, GOLDEN_DOG_TABLE, "breakout_vol_ratio", "DOUBLE PRECISION DEFAULT 0")
    await _add_column_if_missing(conn, GOLDEN_DOG_TABLE, "label", "INT DEFAULT -1")

    pk_name, pk_columns = await _primary_key_info(conn, GOLDEN_DOG_TABLE)
    if pk_name and pk_columns != ["ca", "snapshot_time"]:
        await conn.execute(f"ALTER TABLE {GOLDEN_DOG_TABLE} DROP CONSTRAINT {pk_name};")

    for constraint_name, columns in await _unique_constraints(conn, GOLDEN_DOG_TABLE):
        if list(columns) == ["ca"]:
            await conn.execute(f"ALTER TABLE {GOLDEN_DOG_TABLE} DROP CONSTRAINT {constraint_name};")

    if not await _has_unique_or_primary_constraint(conn, GOLDEN_DOG_TABLE, ["ca", "snapshot_time"]):
        await conn.execute(
            f"""
            ALTER TABLE {GOLDEN_DOG_TABLE}
            ADD CONSTRAINT golden_dog_morphology_ca_snapshot_time_key
            UNIQUE (ca, snapshot_time);
            """
        )


async def _backfill_golden_dog_metric_columns(conn: asyncpg.Connection) -> None:
    holder_json_expr = _holder_distribution_jsonb_expr()
    top10_raw_expr = _coalesce_numeric_from_json(
        holder_json_expr,
        [
            ("top10_raw_pct",),
            ("top10_adjusted_pct",),
            ("top10",),
            ("top10_ratio",),
        ],
    )
    top10_adjusted_expr = _coalesce_numeric_from_json(
        holder_json_expr,
        [
            ("top10_adjusted_pct",),
            ("top10_raw_pct",),
            ("top10",),
            ("top10_ratio",),
        ],
    )
    pair_liq_expr = _coalesce_numeric_from_json(
        holder_json_expr,
        [
            ("pair_liquidity_usd",),
            ("exit_liquidity_usd",),
        ],
    )
    exit_liq_expr = _coalesce_numeric_from_json(
        holder_json_expr,
        [
            ("exit_liquidity_usd",),
            ("pair_liquidity_usd",),
        ],
    )
    metric_confidence_expr = _coalesce_jsonb_from_paths(
        holder_json_expr,
        [("metric_confidence",)],
    )
    source_conflict_expr = _coalesce_jsonb_from_paths(
        holder_json_expr,
        [("source_conflict",)],
    )

    await conn.execute(
        f"""
        UPDATE {GOLDEN_DOG_TABLE}
        SET top10_raw_pct = COALESCE(top10_raw_pct, {top10_raw_expr}),
            top10_adjusted_pct = COALESCE(top10_adjusted_pct, {top10_adjusted_expr}),
            pair_liquidity_usd = COALESCE(pair_liquidity_usd, {pair_liq_expr}, NULLIF(liquidity_at_snap, 0)),
            exit_liquidity_usd = COALESCE(exit_liquidity_usd, {exit_liq_expr}, NULLIF(liquidity_at_snap, 0)),
            metric_confidence = COALESCE(metric_confidence, {metric_confidence_expr}),
            source_conflict = COALESCE(source_conflict, {source_conflict_expr})
        WHERE
            top10_raw_pct IS NULL
            OR top10_adjusted_pct IS NULL
            OR pair_liquidity_usd IS NULL
            OR exit_liquidity_usd IS NULL
            OR metric_confidence IS NULL
            OR source_conflict IS NULL;
        """
    )


async def _ensure_smart_wallet_table(conn: asyncpg.Connection) -> None:
    await conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SMART_WALLET_TABLE} (
            wallet_address TEXT PRIMARY KEY,
            tags TEXT,
            total_trades INT DEFAULT 0,
            avg_entry_mcap DOUBLE PRECISION DEFAULT 0,
            last_active TIMESTAMP DEFAULT NOW(),
            created_at TIMESTAMP DEFAULT NOW()
        );
        """
    )

    await _add_column_if_missing(conn, SMART_WALLET_TABLE, "tags", "TEXT")
    await _add_column_if_missing(conn, SMART_WALLET_TABLE, "total_trades", "INT DEFAULT 0")
    await _add_column_if_missing(conn, SMART_WALLET_TABLE, "avg_entry_mcap", "DOUBLE PRECISION DEFAULT 0")
    await _add_column_if_missing(conn, SMART_WALLET_TABLE, "last_active", "TIMESTAMP DEFAULT NOW()")
    await _add_column_if_missing(conn, SMART_WALLET_TABLE, "created_at", "TIMESTAMP DEFAULT NOW()")

    await conn.execute(
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_{SMART_WALLET_TABLE}_wallet_address
        ON {SMART_WALLET_TABLE} (wallet_address);
        """
    )


async def _ensure_wallet_clusters_table(conn: asyncpg.Connection) -> None:
    await conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {WALLET_CLUSTERS_TABLE} (
            cluster_id TEXT NOT NULL,
            wallet_address TEXT NOT NULL,
            discovered_in_token TEXT,
            behavior_tag TEXT,
            risk_level INT DEFAULT 0,
            total_wallets_in_cluster INT DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW(),
            PRIMARY KEY (cluster_id, wallet_address)
        );
        """
    )

    await _add_column_if_missing(conn, WALLET_CLUSTERS_TABLE, "discovered_in_token", "TEXT")
    await _add_column_if_missing(conn, WALLET_CLUSTERS_TABLE, "behavior_tag", "TEXT")
    await _add_column_if_missing(conn, WALLET_CLUSTERS_TABLE, "risk_level", "INT DEFAULT 0")
    await _add_column_if_missing(conn, WALLET_CLUSTERS_TABLE, "total_wallets_in_cluster", "INT DEFAULT 0")
    await _add_column_if_missing(conn, WALLET_CLUSTERS_TABLE, "created_at", "TIMESTAMP DEFAULT NOW()")

    await conn.execute(
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_{WALLET_CLUSTERS_TABLE}_cluster_wallet
        ON {WALLET_CLUSTERS_TABLE} (cluster_id, wallet_address);
        """
    )


async def _ensure_analysis_runs_table(conn: asyncpg.Connection) -> None:
    await conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {ANALYSIS_RUNS_TABLE} (
            id BIGSERIAL PRIMARY KEY,
            ca TEXT NOT NULL,
            source TEXT,
            path_kind TEXT,
            status TEXT DEFAULT 'STARTED',
            chat_id BIGINT,
            message_id BIGINT,
            legacy_path BOOLEAN DEFAULT FALSE,
            metadata JSONB,
            started_at TIMESTAMP DEFAULT NOW(),
            finished_at TIMESTAMP
        );
        """
    )

    await _add_column_if_missing(conn, ANALYSIS_RUNS_TABLE, "ca", "TEXT")
    await _add_column_if_missing(conn, ANALYSIS_RUNS_TABLE, "source", "TEXT")
    await _add_column_if_missing(conn, ANALYSIS_RUNS_TABLE, "path_kind", "TEXT")
    await _add_column_if_missing(conn, ANALYSIS_RUNS_TABLE, "status", "TEXT DEFAULT 'STARTED'")
    await _add_column_if_missing(conn, ANALYSIS_RUNS_TABLE, "chat_id", "BIGINT")
    await _add_column_if_missing(conn, ANALYSIS_RUNS_TABLE, "message_id", "BIGINT")
    await _add_column_if_missing(conn, ANALYSIS_RUNS_TABLE, "legacy_path", "BOOLEAN DEFAULT FALSE")
    await _add_column_if_missing(conn, ANALYSIS_RUNS_TABLE, "metadata", "JSONB")
    await _add_column_if_missing(conn, ANALYSIS_RUNS_TABLE, "started_at", "TIMESTAMP DEFAULT NOW()")
    await _add_column_if_missing(conn, ANALYSIS_RUNS_TABLE, "finished_at", "TIMESTAMP")

    await conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{ANALYSIS_RUNS_TABLE}_ca_started_at
        ON {ANALYSIS_RUNS_TABLE} (ca, started_at DESC);
        """
    )


async def _ensure_strategy_state_transitions_table(conn: asyncpg.Connection) -> None:
    await conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {STATE_TRANSITIONS_TABLE} (
            id BIGSERIAL PRIMARY KEY,
            analysis_run_id BIGINT,
            ca TEXT NOT NULL,
            from_state TEXT,
            to_state TEXT,
            action TEXT,
            source TEXT,
            path_kind TEXT,
            legacy_path BOOLEAN DEFAULT FALSE,
            transition_reason TEXT,
            metadata JSONB,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """
    )

    await _add_column_if_missing(conn, STATE_TRANSITIONS_TABLE, "analysis_run_id", "BIGINT")
    await _add_column_if_missing(conn, STATE_TRANSITIONS_TABLE, "ca", "TEXT")
    await _add_column_if_missing(conn, STATE_TRANSITIONS_TABLE, "from_state", "TEXT")
    await _add_column_if_missing(conn, STATE_TRANSITIONS_TABLE, "to_state", "TEXT")
    await _add_column_if_missing(conn, STATE_TRANSITIONS_TABLE, "action", "TEXT")
    await _add_column_if_missing(conn, STATE_TRANSITIONS_TABLE, "source", "TEXT")
    await _add_column_if_missing(conn, STATE_TRANSITIONS_TABLE, "path_kind", "TEXT")
    await _add_column_if_missing(conn, STATE_TRANSITIONS_TABLE, "legacy_path", "BOOLEAN DEFAULT FALSE")
    await _add_column_if_missing(conn, STATE_TRANSITIONS_TABLE, "transition_reason", "TEXT")
    await _add_column_if_missing(conn, STATE_TRANSITIONS_TABLE, "metadata", "JSONB")
    await _add_column_if_missing(conn, STATE_TRANSITIONS_TABLE, "created_at", "TIMESTAMP DEFAULT NOW()")

    await conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{STATE_TRANSITIONS_TABLE}_ca_created_at
        ON {STATE_TRANSITIONS_TABLE} (ca, created_at DESC);
        """
    )
    await conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{STATE_TRANSITIONS_TABLE}_analysis_run_id
        ON {STATE_TRANSITIONS_TABLE} (analysis_run_id);
        """
    )


async def _ensure_decision_events_table(conn: asyncpg.Connection) -> None:
    await conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {DECISION_EVENTS_TABLE} (
            id BIGSERIAL PRIMARY KEY,
            analysis_run_id BIGINT,
            ca TEXT NOT NULL,
            event_type TEXT,
            candidate_action TEXT,
            ai_verdict TEXT,
            risk_adjusted_action TEXT,
            final_action TEXT,
            strategy_id TEXT,
            score DOUBLE PRECISION,
            reason TEXT,
            risk_flags JSONB,
            source TEXT,
            path_kind TEXT,
            legacy_path BOOLEAN DEFAULT FALSE,
            metadata JSONB,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """
    )

    await _add_column_if_missing(conn, DECISION_EVENTS_TABLE, "analysis_run_id", "BIGINT")
    await _add_column_if_missing(conn, DECISION_EVENTS_TABLE, "ca", "TEXT")
    await _add_column_if_missing(conn, DECISION_EVENTS_TABLE, "event_type", "TEXT")
    await _add_column_if_missing(conn, DECISION_EVENTS_TABLE, "candidate_action", "TEXT")
    await _add_column_if_missing(conn, DECISION_EVENTS_TABLE, "ai_verdict", "TEXT")
    await _add_column_if_missing(conn, DECISION_EVENTS_TABLE, "risk_adjusted_action", "TEXT")
    await _add_column_if_missing(conn, DECISION_EVENTS_TABLE, "final_action", "TEXT")
    await _add_column_if_missing(conn, DECISION_EVENTS_TABLE, "strategy_id", "TEXT")
    await _add_column_if_missing(conn, DECISION_EVENTS_TABLE, "score", "DOUBLE PRECISION")
    await _add_column_if_missing(conn, DECISION_EVENTS_TABLE, "reason", "TEXT")
    await _add_column_if_missing(conn, DECISION_EVENTS_TABLE, "risk_flags", "JSONB")
    await _add_column_if_missing(conn, DECISION_EVENTS_TABLE, "source", "TEXT")
    await _add_column_if_missing(conn, DECISION_EVENTS_TABLE, "path_kind", "TEXT")
    await _add_column_if_missing(conn, DECISION_EVENTS_TABLE, "legacy_path", "BOOLEAN DEFAULT FALSE")
    await _add_column_if_missing(conn, DECISION_EVENTS_TABLE, "metadata", "JSONB")
    await _add_column_if_missing(conn, DECISION_EVENTS_TABLE, "created_at", "TIMESTAMP DEFAULT NOW()")

    await conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{DECISION_EVENTS_TABLE}_ca_created_at
        ON {DECISION_EVENTS_TABLE} (ca, created_at DESC);
        """
    )
    await conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{DECISION_EVENTS_TABLE}_analysis_run_id
        ON {DECISION_EVENTS_TABLE} (analysis_run_id);
        """
    )


async def _ensure_execution_events_table(conn: asyncpg.Connection) -> None:
    await conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {EXECUTION_EVENTS_TABLE} (
            id BIGSERIAL PRIMARY KEY,
            analysis_run_id BIGINT,
            ca TEXT NOT NULL,
            event_type TEXT,
            action TEXT,
            signal_state TEXT,
            status TEXT,
            source TEXT,
            path_kind TEXT,
            legacy_path BOOLEAN DEFAULT FALSE,
            metadata JSONB,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """
    )

    await _add_column_if_missing(conn, EXECUTION_EVENTS_TABLE, "analysis_run_id", "BIGINT")
    await _add_column_if_missing(conn, EXECUTION_EVENTS_TABLE, "ca", "TEXT")
    await _add_column_if_missing(conn, EXECUTION_EVENTS_TABLE, "event_type", "TEXT")
    await _add_column_if_missing(conn, EXECUTION_EVENTS_TABLE, "action", "TEXT")
    await _add_column_if_missing(conn, EXECUTION_EVENTS_TABLE, "signal_state", "TEXT")
    await _add_column_if_missing(conn, EXECUTION_EVENTS_TABLE, "status", "TEXT")
    await _add_column_if_missing(conn, EXECUTION_EVENTS_TABLE, "source", "TEXT")
    await _add_column_if_missing(conn, EXECUTION_EVENTS_TABLE, "path_kind", "TEXT")
    await _add_column_if_missing(conn, EXECUTION_EVENTS_TABLE, "legacy_path", "BOOLEAN DEFAULT FALSE")
    await _add_column_if_missing(conn, EXECUTION_EVENTS_TABLE, "metadata", "JSONB")
    await _add_column_if_missing(conn, EXECUTION_EVENTS_TABLE, "created_at", "TIMESTAMP DEFAULT NOW()")

    await conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{EXECUTION_EVENTS_TABLE}_ca_created_at
        ON {EXECUTION_EVENTS_TABLE} (ca, created_at DESC);
        """
    )
    await conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{EXECUTION_EVENTS_TABLE}_analysis_run_id
        ON {EXECUTION_EVENTS_TABLE} (analysis_run_id);
        """
    )


async def _ensure_paper_orders_table(conn: asyncpg.Connection) -> None:
    await conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {PAPER_ORDERS_TABLE} (
            order_id TEXT PRIMARY KEY,
            analysis_run_id BIGINT,
            ca TEXT NOT NULL,
            position_id TEXT,
            side TEXT,
            intent TEXT,
            requested_qty DOUBLE PRECISION,
            requested_notional_sol DOUBLE PRECISION,
            requested_price DOUBLE PRECISION,
            strategy_id TEXT,
            source TEXT,
            path_kind TEXT,
            legacy_path BOOLEAN DEFAULT FALSE,
            reason TEXT,
            metadata JSONB,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """
    )
    await _add_column_if_missing(conn, PAPER_ORDERS_TABLE, "analysis_run_id", "BIGINT")
    await _add_column_if_missing(conn, PAPER_ORDERS_TABLE, "ca", "TEXT")
    await _add_column_if_missing(conn, PAPER_ORDERS_TABLE, "position_id", "TEXT")
    await _add_column_if_missing(conn, PAPER_ORDERS_TABLE, "side", "TEXT")
    await _add_column_if_missing(conn, PAPER_ORDERS_TABLE, "intent", "TEXT")
    await _add_column_if_missing(conn, PAPER_ORDERS_TABLE, "requested_qty", "DOUBLE PRECISION")
    await _add_column_if_missing(conn, PAPER_ORDERS_TABLE, "requested_notional_sol", "DOUBLE PRECISION")
    await _add_column_if_missing(conn, PAPER_ORDERS_TABLE, "requested_price", "DOUBLE PRECISION")
    await _add_column_if_missing(conn, PAPER_ORDERS_TABLE, "strategy_id", "TEXT")
    await _add_column_if_missing(conn, PAPER_ORDERS_TABLE, "source", "TEXT")
    await _add_column_if_missing(conn, PAPER_ORDERS_TABLE, "path_kind", "TEXT")
    await _add_column_if_missing(conn, PAPER_ORDERS_TABLE, "legacy_path", "BOOLEAN DEFAULT FALSE")
    await _add_column_if_missing(conn, PAPER_ORDERS_TABLE, "reason", "TEXT")
    await _add_column_if_missing(conn, PAPER_ORDERS_TABLE, "metadata", "JSONB")
    await _add_column_if_missing(conn, PAPER_ORDERS_TABLE, "created_at", "TIMESTAMP DEFAULT NOW()")
    await conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{PAPER_ORDERS_TABLE}_ca_created_at
        ON {PAPER_ORDERS_TABLE} (ca, created_at DESC);
        """
    )
    await conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{PAPER_ORDERS_TABLE}_position_id
        ON {PAPER_ORDERS_TABLE} (position_id);
        """
    )


async def _ensure_paper_fills_table(conn: asyncpg.Connection) -> None:
    await conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {PAPER_FILLS_TABLE} (
            fill_id TEXT PRIMARY KEY,
            order_id TEXT NOT NULL,
            analysis_run_id BIGINT,
            ca TEXT NOT NULL,
            position_id TEXT,
            side TEXT,
            fill_qty DOUBLE PRECISION,
            fill_price DOUBLE PRECISION,
            gross_notional_sol DOUBLE PRECISION,
            fee_sol DOUBLE PRECISION,
            slippage_sol DOUBLE PRECISION,
            fixed_cost_sol DOUBLE PRECISION,
            total_cost_sol DOUBLE PRECISION,
            source TEXT,
            path_kind TEXT,
            legacy_path BOOLEAN DEFAULT FALSE,
            metadata JSONB,
            filled_at TIMESTAMP DEFAULT NOW()
        );
        """
    )
    await _add_column_if_missing(conn, PAPER_FILLS_TABLE, "analysis_run_id", "BIGINT")
    await _add_column_if_missing(conn, PAPER_FILLS_TABLE, "ca", "TEXT")
    await _add_column_if_missing(conn, PAPER_FILLS_TABLE, "position_id", "TEXT")
    await _add_column_if_missing(conn, PAPER_FILLS_TABLE, "side", "TEXT")
    await _add_column_if_missing(conn, PAPER_FILLS_TABLE, "fill_qty", "DOUBLE PRECISION")
    await _add_column_if_missing(conn, PAPER_FILLS_TABLE, "fill_price", "DOUBLE PRECISION")
    await _add_column_if_missing(conn, PAPER_FILLS_TABLE, "gross_notional_sol", "DOUBLE PRECISION")
    await _add_column_if_missing(conn, PAPER_FILLS_TABLE, "fee_sol", "DOUBLE PRECISION")
    await _add_column_if_missing(conn, PAPER_FILLS_TABLE, "slippage_sol", "DOUBLE PRECISION")
    await _add_column_if_missing(conn, PAPER_FILLS_TABLE, "fixed_cost_sol", "DOUBLE PRECISION")
    await _add_column_if_missing(conn, PAPER_FILLS_TABLE, "total_cost_sol", "DOUBLE PRECISION")
    await _add_column_if_missing(conn, PAPER_FILLS_TABLE, "source", "TEXT")
    await _add_column_if_missing(conn, PAPER_FILLS_TABLE, "path_kind", "TEXT")
    await _add_column_if_missing(conn, PAPER_FILLS_TABLE, "legacy_path", "BOOLEAN DEFAULT FALSE")
    await _add_column_if_missing(conn, PAPER_FILLS_TABLE, "metadata", "JSONB")
    await _add_column_if_missing(conn, PAPER_FILLS_TABLE, "filled_at", "TIMESTAMP DEFAULT NOW()")
    await conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{PAPER_FILLS_TABLE}_order_id
        ON {PAPER_FILLS_TABLE} (order_id);
        """
    )
    await conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{PAPER_FILLS_TABLE}_ca_filled_at
        ON {PAPER_FILLS_TABLE} (ca, filled_at DESC);
        """
    )


async def _ensure_paper_positions_ledger_table(conn: asyncpg.Connection) -> None:
    await conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {PAPER_POSITIONS_LEDGER_TABLE} (
            position_event_id TEXT PRIMARY KEY,
            position_id TEXT NOT NULL,
            order_id TEXT,
            fill_id TEXT,
            analysis_run_id BIGINT,
            ca TEXT NOT NULL,
            event_type TEXT,
            qty_delta DOUBLE PRECISION,
            qty_after DOUBLE PRECISION,
            invested_sol_after DOUBLE PRECISION,
            realized_pnl_sol_after DOUBLE PRECISION,
            avg_entry_price_after DOUBLE PRECISION,
            source TEXT,
            path_kind TEXT,
            legacy_path BOOLEAN DEFAULT FALSE,
            metadata JSONB,
            event_at TIMESTAMP DEFAULT NOW()
        );
        """
    )
    await _add_column_if_missing(conn, PAPER_POSITIONS_LEDGER_TABLE, "order_id", "TEXT")
    await _add_column_if_missing(conn, PAPER_POSITIONS_LEDGER_TABLE, "fill_id", "TEXT")
    await _add_column_if_missing(conn, PAPER_POSITIONS_LEDGER_TABLE, "analysis_run_id", "BIGINT")
    await _add_column_if_missing(conn, PAPER_POSITIONS_LEDGER_TABLE, "ca", "TEXT")
    await _add_column_if_missing(conn, PAPER_POSITIONS_LEDGER_TABLE, "event_type", "TEXT")
    await _add_column_if_missing(conn, PAPER_POSITIONS_LEDGER_TABLE, "qty_delta", "DOUBLE PRECISION")
    await _add_column_if_missing(conn, PAPER_POSITIONS_LEDGER_TABLE, "qty_after", "DOUBLE PRECISION")
    await _add_column_if_missing(conn, PAPER_POSITIONS_LEDGER_TABLE, "invested_sol_after", "DOUBLE PRECISION")
    await _add_column_if_missing(conn, PAPER_POSITIONS_LEDGER_TABLE, "realized_pnl_sol_after", "DOUBLE PRECISION")
    await _add_column_if_missing(conn, PAPER_POSITIONS_LEDGER_TABLE, "avg_entry_price_after", "DOUBLE PRECISION")
    await _add_column_if_missing(conn, PAPER_POSITIONS_LEDGER_TABLE, "source", "TEXT")
    await _add_column_if_missing(conn, PAPER_POSITIONS_LEDGER_TABLE, "path_kind", "TEXT")
    await _add_column_if_missing(conn, PAPER_POSITIONS_LEDGER_TABLE, "legacy_path", "BOOLEAN DEFAULT FALSE")
    await _add_column_if_missing(conn, PAPER_POSITIONS_LEDGER_TABLE, "metadata", "JSONB")
    await _add_column_if_missing(conn, PAPER_POSITIONS_LEDGER_TABLE, "event_at", "TIMESTAMP DEFAULT NOW()")
    await conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{PAPER_POSITIONS_LEDGER_TABLE}_position_id
        ON {PAPER_POSITIONS_LEDGER_TABLE} (position_id, event_at DESC);
        """
    )
    await conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{PAPER_POSITIONS_LEDGER_TABLE}_ca_event_at
        ON {PAPER_POSITIONS_LEDGER_TABLE} (ca, event_at DESC);
        """
    )


async def _ensure_paper_cash_ledger_table(conn: asyncpg.Connection) -> None:
    await conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {PAPER_CASH_LEDGER_TABLE} (
            cash_event_id TEXT PRIMARY KEY,
            ref_type TEXT,
            ref_id TEXT,
            analysis_run_id BIGINT,
            ca TEXT,
            position_id TEXT,
            event_type TEXT,
            delta_sol DOUBLE PRECISION,
            balance_after_sol DOUBLE PRECISION,
            source TEXT,
            path_kind TEXT,
            legacy_path BOOLEAN DEFAULT FALSE,
            metadata JSONB,
            event_at TIMESTAMP DEFAULT NOW()
        );
        """
    )
    await _add_column_if_missing(conn, PAPER_CASH_LEDGER_TABLE, "ref_type", "TEXT")
    await _add_column_if_missing(conn, PAPER_CASH_LEDGER_TABLE, "ref_id", "TEXT")
    await _add_column_if_missing(conn, PAPER_CASH_LEDGER_TABLE, "analysis_run_id", "BIGINT")
    await _add_column_if_missing(conn, PAPER_CASH_LEDGER_TABLE, "ca", "TEXT")
    await _add_column_if_missing(conn, PAPER_CASH_LEDGER_TABLE, "position_id", "TEXT")
    await _add_column_if_missing(conn, PAPER_CASH_LEDGER_TABLE, "event_type", "TEXT")
    await _add_column_if_missing(conn, PAPER_CASH_LEDGER_TABLE, "delta_sol", "DOUBLE PRECISION")
    await _add_column_if_missing(conn, PAPER_CASH_LEDGER_TABLE, "balance_after_sol", "DOUBLE PRECISION")
    await _add_column_if_missing(conn, PAPER_CASH_LEDGER_TABLE, "source", "TEXT")
    await _add_column_if_missing(conn, PAPER_CASH_LEDGER_TABLE, "path_kind", "TEXT")
    await _add_column_if_missing(conn, PAPER_CASH_LEDGER_TABLE, "legacy_path", "BOOLEAN DEFAULT FALSE")
    await _add_column_if_missing(conn, PAPER_CASH_LEDGER_TABLE, "metadata", "JSONB")
    await _add_column_if_missing(conn, PAPER_CASH_LEDGER_TABLE, "event_at", "TIMESTAMP DEFAULT NOW()")
    await conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{PAPER_CASH_LEDGER_TABLE}_position_id
        ON {PAPER_CASH_LEDGER_TABLE} (position_id, event_at DESC);
        """
    )
    await conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{PAPER_CASH_LEDGER_TABLE}_event_at
        ON {PAPER_CASH_LEDGER_TABLE} (event_at DESC);
        """
    )


async def _ensure_paper_trade_closes_table(conn: asyncpg.Connection) -> None:
    await conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {PAPER_TRADE_CLOSES_TABLE} (
            trade_close_id TEXT PRIMARY KEY,
            position_id TEXT NOT NULL,
            order_id TEXT,
            fill_id TEXT,
            analysis_run_id BIGINT,
            ca TEXT NOT NULL,
            strategy TEXT,
            opened_at DOUBLE PRECISION,
            closed_at DOUBLE PRECISION,
            close_reason TEXT,
            partial BOOLEAN DEFAULT FALSE,
            close_ratio DOUBLE PRECISION,
            entry_notional_sol DOUBLE PRECISION,
            exit_notional_sol DOUBLE PRECISION,
            total_fee_sol DOUBLE PRECISION,
            realized_pnl_sol DOUBLE PRECISION,
            realized_return_pct DOUBLE PRECISION,
            source TEXT,
            path_kind TEXT,
            legacy_path BOOLEAN DEFAULT FALSE,
            metadata JSONB,
            recorded_at TIMESTAMP DEFAULT NOW()
        );
        """
    )
    await _add_column_if_missing(conn, PAPER_TRADE_CLOSES_TABLE, "order_id", "TEXT")
    await _add_column_if_missing(conn, PAPER_TRADE_CLOSES_TABLE, "fill_id", "TEXT")
    await _add_column_if_missing(conn, PAPER_TRADE_CLOSES_TABLE, "analysis_run_id", "BIGINT")
    await _add_column_if_missing(conn, PAPER_TRADE_CLOSES_TABLE, "ca", "TEXT")
    await _add_column_if_missing(conn, PAPER_TRADE_CLOSES_TABLE, "strategy", "TEXT")
    await _add_column_if_missing(conn, PAPER_TRADE_CLOSES_TABLE, "opened_at", "DOUBLE PRECISION")
    await _add_column_if_missing(conn, PAPER_TRADE_CLOSES_TABLE, "closed_at", "DOUBLE PRECISION")
    await _add_column_if_missing(conn, PAPER_TRADE_CLOSES_TABLE, "close_reason", "TEXT")
    await _add_column_if_missing(conn, PAPER_TRADE_CLOSES_TABLE, "partial", "BOOLEAN DEFAULT FALSE")
    await _add_column_if_missing(conn, PAPER_TRADE_CLOSES_TABLE, "close_ratio", "DOUBLE PRECISION")
    await _add_column_if_missing(conn, PAPER_TRADE_CLOSES_TABLE, "entry_notional_sol", "DOUBLE PRECISION")
    await _add_column_if_missing(conn, PAPER_TRADE_CLOSES_TABLE, "exit_notional_sol", "DOUBLE PRECISION")
    await _add_column_if_missing(conn, PAPER_TRADE_CLOSES_TABLE, "total_fee_sol", "DOUBLE PRECISION")
    await _add_column_if_missing(conn, PAPER_TRADE_CLOSES_TABLE, "realized_pnl_sol", "DOUBLE PRECISION")
    await _add_column_if_missing(conn, PAPER_TRADE_CLOSES_TABLE, "realized_return_pct", "DOUBLE PRECISION")
    await _add_column_if_missing(conn, PAPER_TRADE_CLOSES_TABLE, "source", "TEXT")
    await _add_column_if_missing(conn, PAPER_TRADE_CLOSES_TABLE, "path_kind", "TEXT")
    await _add_column_if_missing(conn, PAPER_TRADE_CLOSES_TABLE, "legacy_path", "BOOLEAN DEFAULT FALSE")
    await _add_column_if_missing(conn, PAPER_TRADE_CLOSES_TABLE, "metadata", "JSONB")
    await _add_column_if_missing(conn, PAPER_TRADE_CLOSES_TABLE, "recorded_at", "TIMESTAMP DEFAULT NOW()")
    await conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{PAPER_TRADE_CLOSES_TABLE}_position_id
        ON {PAPER_TRADE_CLOSES_TABLE} (position_id, recorded_at DESC);
        """
    )
    await conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{PAPER_TRADE_CLOSES_TABLE}_ca_recorded_at
        ON {PAPER_TRADE_CLOSES_TABLE} (ca, recorded_at DESC);
        """
    )


async def _ensure_signals_snapshot_view(conn: asyncpg.Connection) -> None:
    # Compatibility-only surface for older reads; do not extend with new ownership.
    if await _view_exists(conn, SIGNALS_SNAPSHOT_VIEW):
        await conn.execute(f"DROP VIEW {SIGNALS_SNAPSHOT_VIEW};")

    if not await _table_exists(conn, SIGNALS_SNAPSHOT_VIEW):
        await conn.execute(
            f"""
            CREATE VIEW {SIGNALS_SNAPSHOT_VIEW} AS
            SELECT
                NULL::bigint AS id,
                ca,
                updated_at AS trigger_time,
                source,
                status,
                rank_score,
                NULL::jsonb AS features,
                ai_narrative,
                entry_price,
                last_notified_price,
                initial_msg_id,
                top10_raw_pct,
                top10_adjusted_pct,
                pair_liquidity_usd,
                exit_liquidity_usd,
                metric_confidence,
                source_conflict,
                terminal_states,
                created_at,
                updated_at
            FROM {SIGNAL_CACHE_TABLE};
            """
        )


async def _table_exists(conn: asyncpg.Connection, table_name: str) -> bool:
    return bool(
        await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name = $1
                  AND table_type = 'BASE TABLE'
            );
            """,
            table_name,
        )
    )


async def _view_exists(conn: asyncpg.Connection, view_name: str) -> bool:
    return bool(
        await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.views
                WHERE table_schema = 'public'
                  AND table_name = $1
            );
            """,
            view_name,
        )
    )


async def _get_columns(conn: asyncpg.Connection, table_name: str) -> List[str]:
    rows = await conn.fetch(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = $1
        ORDER BY ordinal_position;
        """,
        table_name,
    )
    return [row["column_name"] for row in rows]


async def _add_column_if_missing(
    conn: asyncpg.Connection,
    table_name: str,
    column_name: str,
    column_definition: str,
) -> None:
    columns = await _get_columns(conn, table_name)
    if column_name not in columns:
        await conn.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition};"
        )


async def _constraint_exists(
    conn: asyncpg.Connection,
    table_name: str,
    constraint_name: str,
) -> bool:
    return bool(
        await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.table_constraints
                WHERE table_schema = 'public'
                  AND table_name = $1
                  AND constraint_name = $2
            );
            """,
            table_name,
            constraint_name,
        )
    )


async def _primary_key_info(conn: asyncpg.Connection, table_name: str) -> Tuple[Optional[str], List[str]]:
    rows = await conn.fetch(
        """
        SELECT tc.constraint_name, kcu.column_name, kcu.ordinal_position
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
         AND tc.table_name = kcu.table_name
        WHERE tc.table_schema = 'public'
          AND tc.table_name = $1
          AND tc.constraint_type = 'PRIMARY KEY'
        ORDER BY kcu.ordinal_position;
        """,
        table_name,
    )
    if not rows:
        return None, []

    name = rows[0]["constraint_name"]
    return name, [row["column_name"] for row in rows]


async def _unique_constraints(
    conn: asyncpg.Connection,
    table_name: str,
) -> List[Tuple[str, List[str]]]:
    rows = await conn.fetch(
        """
        SELECT tc.constraint_name, kcu.column_name, kcu.ordinal_position
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
         AND tc.table_name = kcu.table_name
        WHERE tc.table_schema = 'public'
          AND tc.table_name = $1
          AND tc.constraint_type = 'UNIQUE'
        ORDER BY tc.constraint_name, kcu.ordinal_position;
        """,
        table_name,
    )

    grouped = {}
    for row in rows:
        grouped.setdefault(row["constraint_name"], []).append(row["column_name"])
    return [(name, columns) for name, columns in grouped.items()]


async def _has_unique_or_primary_constraint(
    conn: asyncpg.Connection,
    table_name: str,
    columns: Sequence[str],
) -> bool:
    pk_name, pk_columns = await _primary_key_info(conn, table_name)
    if pk_name and list(pk_columns) == list(columns):
        return True

    for _, unique_columns in await _unique_constraints(conn, table_name):
        if list(unique_columns) == list(columns):
            return True
    return False


def _legacy_expr(legacy_columns: Iterable[str], column_name: str, fallback_sql: str) -> str:
    legacy_column_set = set(legacy_columns)
    return column_name if column_name in legacy_column_set else fallback_sql


def _legacy_json_expr(legacy_columns: Iterable[str], column_name: str, fallback_sql: str) -> str:
    legacy_column_set = set(legacy_columns)
    return f"{column_name}::jsonb" if column_name in legacy_column_set else fallback_sql


def _first_available_expr(
    legacy_columns: Iterable[str],
    candidates: Sequence[str],
    fallback_sql: str,
) -> str:
    legacy_column_set = set(legacy_columns)
    for name in candidates:
        if name in legacy_column_set:
            return name
    return fallback_sql


def _json_text_path(base_expr: str, path: Sequence[str]) -> str:
    if not path:
        raise ValueError("JSON path cannot be empty.")

    expr = f"({base_expr})"
    for part in path[:-1]:
        expr = f"{expr}->'{part}'"
    return f"{expr}->>'{path[-1]}'"


def _json_jsonb_path(base_expr: str, path: Sequence[str]) -> str:
    if not path:
        raise ValueError("JSON path cannot be empty.")

    expr = f"({base_expr})"
    for part in path:
        expr = f"{expr}->'{part}'"
    return expr


def _numeric_text_expr(text_expr: str) -> str:
    return (
        "NULLIF("
        f"regexp_replace(COALESCE(({text_expr})::text, ''), '[^0-9.\\-]', '', 'g')"
        ", '')::double precision"
    )


def _legacy_numeric_expr(
    legacy_columns: Iterable[str],
    candidates: Sequence[str],
    fallback_sql: str = "NULL::double precision",
) -> str:
    legacy_column_set = set(legacy_columns)
    exprs = [_numeric_text_expr(name) for name in candidates if name in legacy_column_set]
    exprs.append(fallback_sql)
    return f"COALESCE({', '.join(exprs)})"


def _legacy_json_first_expr(
    legacy_columns: Iterable[str],
    candidates: Sequence[str],
    fallback_sql: str = "NULL::jsonb",
) -> str:
    legacy_column_set = set(legacy_columns)
    for name in candidates:
        if name in legacy_column_set:
            return f"{name}::jsonb"
    return fallback_sql


def _coalesce_numeric_from_json(
    base_expr: str,
    paths: Sequence[Sequence[str]],
    fallback_sql: str = "NULL::double precision",
) -> str:
    exprs = [_numeric_text_expr(_json_text_path(base_expr, path)) for path in paths]
    exprs.append(fallback_sql)
    return f"COALESCE({', '.join(exprs)})"


def _coalesce_jsonb_from_paths(
    base_expr: str,
    paths: Sequence[Sequence[str]],
    fallback_sql: str = "NULL::jsonb",
) -> str:
    exprs = [_json_jsonb_path(base_expr, path) for path in paths]
    exprs.append(fallback_sql)
    return f"COALESCE({', '.join(exprs)})"


def _holder_distribution_jsonb_expr() -> str:
    return (
        "CASE "
        "WHEN holder_distribution IS NULL THEN NULL::jsonb "
        "WHEN btrim(holder_distribution::text) = '' THEN NULL::jsonb "
        "WHEN left(btrim(holder_distribution::text), 1) IN ('{', '[') "
        "THEN holder_distribution::text::jsonb "
        "ELSE NULL::jsonb "
        "END"
    )
