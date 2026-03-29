import json
import logging
import os
from typing import Any, Dict, List, Optional

import asyncpg

from modules.db_schema import SIGNAL_CACHE_TABLE, SIGNAL_SNAPSHOT_TABLE, ensure_schema

logger = logging.getLogger("Database")


def _optional_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        if isinstance(value, str):
            text = value.replace(",", "").strip()
            if text.endswith("%"):
                text = text[:-1].strip()
            if not text:
                return None
            return float(text)
        return float(value)
    except Exception:
        return None


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _json_payload(value: Any) -> Optional[str]:
    if value is None:
        return None
    return json.dumps(value)


def _default_status_for_insert(status: Optional[str]) -> str:
    text = str(status).strip() if status is not None else ""
    return text or "pending"


def _extract_signal_metric_payload(terminal_states: Optional[dict]) -> Dict[str, Any]:
    terminal = terminal_states if isinstance(terminal_states, dict) else {}
    stable = terminal.get("stable_snapshot") if isinstance(terminal.get("stable_snapshot"), dict) else {}

    pair_liq = _optional_float(
        _first_present(
            stable.get("pair_liquidity_usd"),
            terminal.get("pair_liquidity_usd"),
            stable.get("liquidity_usd"),
            terminal.get("liquidity_usd"),
        )
    )
    exit_liq = _optional_float(
        _first_present(
            stable.get("exit_liquidity_usd"),
            terminal.get("exit_liquidity_usd"),
            stable.get("liquidity_usd"),
            terminal.get("liquidity_usd"),
            pair_liq,
        )
    )

    metric_confidence = _first_present(
        stable.get("metric_confidence"),
        terminal.get("metric_confidence"),
    )
    source_conflict = _first_present(
        stable.get("source_conflict"),
        terminal.get("source_conflict"),
    )

    return {
        "top10_raw_pct": _optional_float(
            _first_present(stable.get("top10_raw_pct"), terminal.get("top10_raw_pct"))
        ),
        "top10_adjusted_pct": _optional_float(
            _first_present(stable.get("top10_adjusted_pct"), terminal.get("top10_adjusted_pct"))
        ),
        "pair_liquidity_usd": pair_liq,
        "exit_liquidity_usd": exit_liq,
        "metric_confidence": metric_confidence if isinstance(metric_confidence, dict) and metric_confidence else None,
        "source_conflict": source_conflict if isinstance(source_conflict, dict) and source_conflict else None,
    }


class Database:
    _pool: Optional[asyncpg.Pool] = None

    @classmethod
    async def init_pool(cls):
        if cls._pool:
            return

        dsn = os.getenv("DB_DSN", "postgresql://postgres:011027@localhost:5432/solana_hunter")
        cls._pool = await asyncpg.create_pool(dsn, min_size=5, max_size=20)
        logger.info("Database pool initialized.")
        await cls._setup_tables()

    @classmethod
    async def _setup_tables(cls):
        if not cls._pool:
            return

        async with cls._pool.acquire() as conn:
            await ensure_schema(conn)
        logger.info("Database schema verified.")

    @classmethod
    async def close_pool(cls):
        if cls._pool:
            await cls._pool.close()
            cls._pool = None
            logger.info("Database pool closed.")

    @classmethod
    async def fetch_one(cls, query: str, *args) -> Optional[Dict[str, Any]]:
        if not cls._pool:
            await cls.init_pool()
        async with cls._pool.acquire() as conn:
            row = await conn.fetchrow(query, *args)
            return dict(row) if row else None

    @classmethod
    async def fetch_all(cls, query: str, *args) -> List[Dict[str, Any]]:
        if not cls._pool:
            await cls.init_pool()
        async with cls._pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
            return [dict(row) for row in rows]

    @classmethod
    async def execute(cls, query: str, *args) -> str:
        if not cls._pool:
            await cls.init_pool()
        async with cls._pool.acquire() as conn:
            return await conn.execute(query, *args)

    @classmethod
    async def fetch(cls, query: str, *args) -> List[Dict[str, Any]]:
        return await cls.fetch_all(query, *args)

    @classmethod
    async def fetchrow(cls, query: str, *args) -> Optional[Dict[str, Any]]:
        return await cls.fetch_one(query, *args)

    @classmethod
    async def save_initial_signal(
        cls,
        ca: str,
        source: str,
        entry_price: float,
        initial_msg_id: int,
        terminal_states: dict,
        status: Optional[str] = None,
    ):
        payload = json.dumps(terminal_states or {})
        metrics = _extract_signal_metric_payload(terminal_states)
        await cls.execute(
            f"""
            -- Snapshot rows must be derived from the actual cache upsert result
            -- so cache/snapshot stay on the same persisted values.
            WITH upserted AS (
                INSERT INTO {SIGNAL_CACHE_TABLE}
                (
                    ca, source, status, entry_price, last_notified_price, initial_msg_id,
                    top10_raw_pct, top10_adjusted_pct, pair_liquidity_usd, exit_liquidity_usd,
                    metric_confidence, source_conflict, terminal_states
                )
                VALUES
                    ($1, $2, $3, $4, $4, $5, $6, $7, $8, $9, $10::jsonb, $11::jsonb, $12::jsonb)
                ON CONFLICT (ca) DO UPDATE
                SET source = EXCLUDED.source,
                    status = COALESCE($13, {SIGNAL_CACHE_TABLE}.status),
                    entry_price = EXCLUDED.entry_price,
                    last_notified_price = EXCLUDED.last_notified_price,
                    initial_msg_id = EXCLUDED.initial_msg_id,
                    top10_raw_pct = COALESCE(EXCLUDED.top10_raw_pct, {SIGNAL_CACHE_TABLE}.top10_raw_pct),
                    top10_adjusted_pct = COALESCE(EXCLUDED.top10_adjusted_pct, {SIGNAL_CACHE_TABLE}.top10_adjusted_pct),
                    pair_liquidity_usd = COALESCE(EXCLUDED.pair_liquidity_usd, {SIGNAL_CACHE_TABLE}.pair_liquidity_usd),
                    exit_liquidity_usd = COALESCE(EXCLUDED.exit_liquidity_usd, {SIGNAL_CACHE_TABLE}.exit_liquidity_usd),
                    metric_confidence = COALESCE(EXCLUDED.metric_confidence, {SIGNAL_CACHE_TABLE}.metric_confidence),
                    source_conflict = COALESCE(EXCLUDED.source_conflict, {SIGNAL_CACHE_TABLE}.source_conflict),
                    terminal_states = EXCLUDED.terminal_states,
                    updated_at = NOW()
                RETURNING ca, source, status, rank_score, ai_narrative,
                          entry_price, last_notified_price, initial_msg_id,
                          top10_raw_pct, top10_adjusted_pct, pair_liquidity_usd, exit_liquidity_usd,
                          metric_confidence, source_conflict, terminal_states, updated_at
            )
            INSERT INTO {SIGNAL_SNAPSHOT_TABLE}
                (
                    ca, source, snapshot_time, status, rank_score, ai_narrative,
                    entry_price, last_notified_price, initial_msg_id,
                    top10_raw_pct, top10_adjusted_pct, pair_liquidity_usd, exit_liquidity_usd,
                    metric_confidence, source_conflict, terminal_states
                )
            SELECT
                ca, source, updated_at, status, rank_score, ai_narrative,
                entry_price, last_notified_price, initial_msg_id,
                top10_raw_pct, top10_adjusted_pct, pair_liquidity_usd, exit_liquidity_usd,
                metric_confidence, source_conflict, terminal_states
            FROM upserted
            """,
            ca,
            source,
            _default_status_for_insert(status),
            float(entry_price),
            initial_msg_id,
            metrics.get("top10_raw_pct"),
            metrics.get("top10_adjusted_pct"),
            metrics.get("pair_liquidity_usd"),
            metrics.get("exit_liquidity_usd"),
            _json_payload(metrics.get("metric_confidence")),
            _json_payload(metrics.get("source_conflict")),
            payload,
            status,
        )

    @classmethod
    async def get_signal_snapshot(cls, ca: str) -> Optional[Dict[str, Any]]:
        row = await cls.fetch_one(f"SELECT * FROM {SIGNAL_CACHE_TABLE} WHERE ca = $1", ca)
        if row:
            if row.get("terminal_states"):
                try:
                    if isinstance(row["terminal_states"], str):
                        row["terminal_states"] = json.loads(row["terminal_states"])
                except Exception:
                    row["terminal_states"] = {}
            for key in ("metric_confidence", "source_conflict"):
                if isinstance(row.get(key), str):
                    try:
                        row[key] = json.loads(row[key])
                    except Exception:
                        row[key] = None
        return row

    @classmethod
    async def update_signal_analysis(
        cls,
        ca: str,
        rank_score: float,
        ai_narrative: str,
        status: Optional[str] = None,
    ):
        await cls.execute(
            f"""
            WITH upserted AS (
                INSERT INTO {SIGNAL_CACHE_TABLE} (ca, status, rank_score, ai_narrative, updated_at)
                VALUES ($1, $2, $3, $4, NOW())
                ON CONFLICT (ca) DO UPDATE
                -- Keep existing lifecycle state unless the caller explicitly passes a new one.
                SET status = COALESCE($5, {SIGNAL_CACHE_TABLE}.status),
                    rank_score = EXCLUDED.rank_score,
                    ai_narrative = EXCLUDED.ai_narrative,
                    updated_at = NOW()
                RETURNING ca, source, status, rank_score, ai_narrative,
                          entry_price, last_notified_price, initial_msg_id,
                          top10_raw_pct, top10_adjusted_pct, pair_liquidity_usd, exit_liquidity_usd,
                          metric_confidence, source_conflict, terminal_states, updated_at
            )
            INSERT INTO {SIGNAL_SNAPSHOT_TABLE}
                (ca, source, snapshot_time, status, rank_score, ai_narrative,
                 entry_price, last_notified_price, initial_msg_id,
                 top10_raw_pct, top10_adjusted_pct, pair_liquidity_usd, exit_liquidity_usd,
                 metric_confidence, source_conflict, terminal_states)
            SELECT
                ca, source, updated_at, status, rank_score, ai_narrative,
                entry_price, last_notified_price, initial_msg_id,
                top10_raw_pct, top10_adjusted_pct, pair_liquidity_usd, exit_liquidity_usd,
                metric_confidence, source_conflict, terminal_states
            FROM upserted
            """,
            ca,
            _default_status_for_insert(status),
            float(rank_score),
            ai_narrative or "",
            status,
        )

    @classmethod
    async def update_milestone(cls, ca: str, new_price: float):
        await cls.execute(
            f"""
            WITH updated AS (
                UPDATE {SIGNAL_CACHE_TABLE}
                SET last_notified_price = $1,
                    updated_at = NOW()
                WHERE ca = $2
                RETURNING ca, source, status, rank_score, ai_narrative,
                          entry_price, last_notified_price, initial_msg_id,
                          top10_raw_pct, top10_adjusted_pct, pair_liquidity_usd, exit_liquidity_usd,
                          metric_confidence, source_conflict, terminal_states, updated_at
            )
            INSERT INTO {SIGNAL_SNAPSHOT_TABLE}
                (ca, source, snapshot_time, status, rank_score, ai_narrative,
                 entry_price, last_notified_price, initial_msg_id,
                 top10_raw_pct, top10_adjusted_pct, pair_liquidity_usd, exit_liquidity_usd,
                 metric_confidence, source_conflict, terminal_states)
            SELECT
                ca, source, updated_at, status, rank_score, ai_narrative,
                entry_price, last_notified_price, initial_msg_id,
                top10_raw_pct, top10_adjusted_pct, pair_liquidity_usd, exit_liquidity_usd,
                metric_confidence, source_conflict, terminal_states
            FROM updated
            """,
            float(new_price),
            ca,
        )

    @classmethod
    async def update_terminal_states(cls, ca: str, terminal_states: dict, status: Optional[str] = None):
        payload = json.dumps(terminal_states or {})
        metrics = _extract_signal_metric_payload(terminal_states)
        await cls.execute(
            f"""
            WITH updated AS (
                UPDATE {SIGNAL_CACHE_TABLE}
                SET terminal_states = $1::jsonb,
                    top10_raw_pct = COALESCE($2, top10_raw_pct),
                    top10_adjusted_pct = COALESCE($3, top10_adjusted_pct),
                    pair_liquidity_usd = COALESCE($4, pair_liquidity_usd),
                    exit_liquidity_usd = COALESCE($5, exit_liquidity_usd),
                    metric_confidence = COALESCE($6::jsonb, metric_confidence),
                    source_conflict = COALESCE($7::jsonb, source_conflict),
                    status = COALESCE($8, status),
                    updated_at = NOW()
                WHERE ca = $9
                RETURNING ca, source, status, rank_score, ai_narrative,
                          entry_price, last_notified_price, initial_msg_id,
                          top10_raw_pct, top10_adjusted_pct, pair_liquidity_usd, exit_liquidity_usd,
                          metric_confidence, source_conflict, terminal_states, updated_at
            )
            INSERT INTO {SIGNAL_SNAPSHOT_TABLE}
                (ca, source, snapshot_time, status, rank_score, ai_narrative,
                 entry_price, last_notified_price, initial_msg_id,
                 top10_raw_pct, top10_adjusted_pct, pair_liquidity_usd, exit_liquidity_usd,
                 metric_confidence, source_conflict, terminal_states)
            SELECT
                ca, source, updated_at, status, rank_score, ai_narrative,
                entry_price, last_notified_price, initial_msg_id,
                top10_raw_pct, top10_adjusted_pct, pair_liquidity_usd, exit_liquidity_usd,
                metric_confidence, source_conflict, terminal_states
            FROM updated
            """,
            payload,
            metrics.get("top10_raw_pct"),
            metrics.get("top10_adjusted_pct"),
            metrics.get("pair_liquidity_usd"),
            metrics.get("exit_liquidity_usd"),
            _json_payload(metrics.get("metric_confidence")),
            _json_payload(metrics.get("source_conflict")),
            status,
            ca,
        )


db = Database
