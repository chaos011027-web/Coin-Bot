# Database Schema Unification

## Current State -> Target Structure

| Current state | Problem | Target structure |
| --- | --- | --- |
| `signals_snapshot` is used in `modules/database.py` as a cache table keyed by `ca` | Runtime cache and training history are mixed into one name | `signal_cache_current`: one row per token, current runtime state |
| `signals_snapshot` is created in `init_db.py` as a time-series table with `id` | Same table name means two incompatible schemas | `signal_snapshots`: append-only signal history with `id` and `snapshot_time` |
| `performance_labels.signal_id -> signals_snapshot(id)` | Labels depend on the wrong logical table after the split | `performance_labels.snapshot_id -> signal_snapshots(id)`, keep legacy `signal_id` for compatibility |
| `golden_dog_morphology` is written from runtime code but upgraded separately | No single create/migrate path | Unified schema bootstrap and migration in `modules/db_schema.py` |
| `smart_wallet_intel` is written from `main.py` without a guaranteed create path | Runtime may fail on fresh databases | Explicit table creation and idempotent migration |
| `wallet_clusters` is also written from `main.py` without a create path | Hidden runtime dependency | Explicit table creation and unique key on `(cluster_id, wallet_address)` |

## New Table Responsibilities

- `signal_cache_current`: current signal cache used by runtime, milestone logic, refresh, and exports.
- `signal_snapshots`: append-only time-series snapshots for signal history and training/backfill linkage.
- `performance_labels`: post-hoc performance labels keyed to `signal_snapshots`, with legacy `signal_id` preserved.
- `golden_dog_morphology`: time-series morphology/training feature store for watchdog and Midnight Hunter.
- `smart_wallet_intel`: wallet-level smart money profile cache.
- `wallet_clusters`: cluster membership snapshots discovered from on-chain analysis.
- `signals_snapshot` view: compatibility layer that exposes cache-style data for older reads.

## Migration Notes

- Old `signals_snapshot` data is never dropped.
- If the legacy table looked like a cache table, it is renamed to `signals_snapshot_legacy_cache` and copied into `signal_cache_current`.
- If the legacy table looked like a history table, it is renamed to `signals_snapshot_legacy_history` and copied into `signal_snapshots`.
- `performance_labels.snapshot_id` is backfilled from `signal_snapshots.legacy_signal_id`.

## Rollback Outline

1. Stop the app.
2. Drop the compatibility view `signals_snapshot`.
3. Point code back to the legacy tables or restore the pre-migration code revision.
4. If needed, rename `signals_snapshot_legacy_cache` or `signals_snapshot_legacy_history` back to `signals_snapshot`.
5. Leave new tables in place until verification is complete so no migrated data is lost.
