# Top10 / Liquidity Canonical Pipeline

## Source Mapping

| Source | Current raw field | Canonical mapping | Notes |
| --- | --- | --- | --- |
| Helius | `top10_ratio=None` | No canonical top10 mapping | Helius currently remains a security source only; observed values stay in `top10_ratio_helius` compatibility field. |
| GMGN page text / regex | `analytics.top10_ratio` | `top10_raw_pct` candidate, `top10_adjusted_pct` fallback candidate | Marked as lower-confidence `GMGN` source; unconfirmed very high values are suppressed by config. |
| Bitquery holders query | `bitquery_top10_ratio` | Primary `top10_raw_pct` candidate, preferred `top10_adjusted_pct` candidate | Supply fallback is still supported, but multiplier and confidence are now config-driven. |
| DexScreener pair liquidity | `liquidity.usd` | `pair_liquidity_usd` | No longer merged with Birdeye by taking the larger value. |
| Birdeye liquidity | `liquidity` | `exit_liquidity_usd` | Explicitly modeled as exit-side liquidity. |
| GMGN header liquidity | `header_liq_usd` | Pair fallback candidate and exit fallback candidate | Used when Dex/Birdeye are missing, with lower confidence. |
| Legacy runtime fields | `top10_ratio`, `liquidity_usd` | Compatibility only | Canonical helpers backfill these for older callers, but new decision code should not read them directly. |

## New Fields

No new table was introduced in this refactor. The canonical fields were added to existing persistence layers:

- `signal_cache_current`
  - `top10_raw_pct`
  - `top10_adjusted_pct`
  - `pair_liquidity_usd`
  - `exit_liquidity_usd`
  - `metric_confidence`
  - `source_conflict`
- `signal_snapshots`
  - `top10_raw_pct`
  - `top10_adjusted_pct`
  - `pair_liquidity_usd`
  - `exit_liquidity_usd`
  - `metric_confidence`
  - `source_conflict`
- `golden_dog_morphology`
  - `top10_raw_pct`
  - `top10_adjusted_pct`
  - `pair_liquidity_usd`
  - `exit_liquidity_usd`
  - `metric_confidence`
  - `source_conflict`

Migration/backfill behavior:

- Signal cache and snapshot rows backfill from `terminal_states` / `stable_snapshot`.
- Training rows backfill from `holder_distribution` JSON plus `liquidity_at_snap`.
- Old compatibility view `signals_snapshot` now exposes the canonical columns as well.

## Canonical Call Sites

These call sites now use canonical helpers instead of reading `top10_ratio` / `liquidity_usd` directly for decisions:

- `main.py`
  - `_resolve_canonical_metrics(...)`
  - `simple_gatekeeper(...)`
  - LightGBM feature assembly in `run_deep_analysis(...)`
  - training snapshot writer in `evolve_database(...)`
- `modules/score_engine.py`
- `modules/strategy_engine.py`
- `modules/risk_engine.py`
- `modules/brain.py`
- `modules/notifier.py`
- `modules/feature_engine.py`
- `modules/watchdog.py`

Compatibility-only writes remain in place for:

- `top10_ratio`
- `top10_ratio_source`
- `top10_ratio_bitquery`
- `top10_ratio_gmgn`
- `top10_ratio_helius`
- `liquidity_usd`

## Thresholds Requiring Manual Confirmation

Decision thresholds already moved into `config/metric_settings.py`, but these values still need product/strategy confirmation:

- Top10 concentration:
  - `top10_green_max_pct`
  - `top10_warn_pct`
  - `top10_danger_pct`
  - `top10_fatal_pct`
- Liquidity absolute levels:
  - `liquidity_low_usd`
  - `liquidity_warn_usd`
  - `liquidity_danger_usd`
  - `liquidity_fatal_usd`
- Liquidity structure ratios:
  - `liquidity_ratio_good`
  - `liquidity_ratio_warn`
  - `liquidity_ratio_fatal`
- Source conflict / trust policy:
  - `top10_conflict_abs_pct`
  - `liquidity_conflict_ratio`
  - `gmgn_unconfirmed_high_pct`
  - `decision_liquidity_field`
- Strategy dynamic adjustments:
  - `dynamic_boost_min_score`
  - `dynamic_clean_top10_max`
  - `dynamic_dirty_top10_min`
  - `dynamic_low_liq_threshold`
- Bitquery fallback policy:
  - `bitquery_supply_fallback_multiplier`
  - `bitquery_confidence`
  - `bitquery_fallback_confidence`
  - `gmgn_confidence`
  - `birdeye_exit_confidence`
  - `dex_pair_confidence`
