# Residual Legacy Metric Usage

## 扫描范围

- 扫描命令：
  `rg -n --glob '!venv/**' --glob '!.venv/**' --glob '!data/**' --glob '!logs/**' --glob '!__pycache__/**' "\btop10_ratio(?:_[A-Za-z0-9]+)?\b|\bliquidity_usd\b" .`
- 本清单只保留“真正访问旧字段”的命中点。
- `min_liquidity_usd`、`decision_liquidity_field`、`bitquery_top10_ratio` 这类新配置/新源字段不计入。

## 分类口径

- `兼容保留`：为了兼容旧缓存、旧表、旧 payload 或旧调用方而保留。
- `展示用途`：只出现在文档/展示层，不参与运行时逻辑。
- `日志用途`：仅用于日志输出。
- `实际决策用途`：旧字段仍会影响 canonical 解析或后续评分/风控/策略决策。
- `风险：不应继续存在的旧依赖`：不属于必要兼容，但旧字段名仍被继续依赖，建议尽快清掉。

## 总结

- 未发现 `score_engine`、`strategy_engine`、`risk_engine`、`brain`、`notifier` 直接读取 `top10_ratio` / `liquidity_usd`。
- 旧字段仍会影响决策，但已被收敛到 [`modules/canonical_metrics.py`](modules/canonical_metrics.py) 这一层。
- `main.py` 和 [`modules/data_fetcher.py`](modules/data_fetcher.py) 里还保留了不少兼容写入/兼容搬运点。
- 本次扫描未发现“仅日志用途”的独立旧字段调用点。

## 逐项清单

### `main.py`

- `_merge_existing_terminal` (`217-237`)：从旧 `terminal_states` / `stable_snapshot` 回填 `liquidity_usd`、`top10_ratio`、`top10_ratio_source`、`top10_ratio_bitquery`、`top10_ratio_gmgn`、`top10_ratio_helius` 到当前 `token_data`。分类：`兼容保留`。建议：等历史缓存都完成 canonical backfill 后，从 merge 白名单里移除旧字段。
- `_apply_helius_security` (`273-278`)：读取 Helius payload 里的 `top10_ratio`，转存到 `top10_ratio_helius` 兼容字段。分类：`兼容保留`。建议：把 Helius 原始输入名改成 `helius_top10_pct_observed` 之类的 source-native 字段，避免再把 `top10_ratio` 当作源字段名。
- `_build_stable_snapshot` (`293-323`)：把 `liquidity_usd`、`top10_ratio`、`top10_ratio_source`、`top10_ratio_*` 一起序列化进稳定快照，供旧读取方继续工作。分类：`兼容保留`。建议：待所有读取方完成迁移后，停止向 `stable_snapshot` 写旧字段。
- `_apply_gmgn_analytics` (`364-428`)：继续从 GMGN 分析结果读取 `analytics["liquidity_usd"]` 和 `analytics["top10_ratio"]`，并写入 `top10_ratio_gmgn`。分类：`兼容保留`。建议：把 GMGN 输入先规范成 `gmgn_header_liquidity_usd` / `gmgn_top10_pct_observed`，再由 canonical 层统一回填兼容字段。
- `normalize_token_data` (`528-576`)：构造初始 `token_data` 时继续填充兼容字段 `liquidity_usd`。分类：`兼容保留`。建议：保留到旧通知/旧缓存完全下线为止，后续只保留 `pair_liquidity_usd` 和 `exit_liquidity_usd`。
- `process_new_signal` (`763-780`)：首次落 `terminal_states_fast` 时继续写 `liquidity_usd`。分类：`兼容保留`。建议：等旧快照消费者迁完后，删掉该兼容字段，只保留 canonical 字段。
- `run_deep_analysis` (`827-830`, `947-953`)：深度分析重试行情时继续回写 `token_data["liquidity_usd"]`，并把 `liquidity_usd` 存进最终 `terminal_states`。分类：`兼容保留`。建议：将兼容写入压缩到一个统一 helper，避免业务流程里散落旧字段赋值。
- `evolve_database` (`989-998`)：写训练样本时继续把 `top10_ratio_source` 放进 `holder_distribution.source`。分类：`兼容保留`。建议：改成新的 canonical 命名，例如 `top10_primary_source`，避免训练数据继续传播旧命名。
- `_resolve_top10_ratio` (`288-289`)：旧函数名仍然存在，但实际只是转调 `_resolve_canonical_metrics`。分类：`风险：不应继续存在的旧依赖`。建议：直接删除该 wrapper，避免后续新代码再次沿用旧命名。

### `modules/canonical_metrics.py`

- `get_canonical_top10_pct` (`47-57`)：当 `top10_adjusted_pct` / `top10_raw_pct` 缺失时，回退读取 `top10_ratio`。分类：`实际决策用途`。建议：新增 `allow_legacy_metric_fallback` 配置；当前阶段默认 `true`，完成历史数据 backfill 验证后切到 `false`。
- `get_pair_liquidity_usd` (`60-62`)：当 `pair_liquidity_usd` 缺失时，回退读取 `liquidity_usd`。分类：`实际决策用途`。建议：进入严格模式后仅接受 `pair_liquidity_usd`，必要时回 0 或标记低置信度，而不是继续把旧字段当 canonical。
- `get_exit_liquidity_usd` (`65-73`)：当 `exit_liquidity_usd` / `pair_liquidity_usd` 缺失时，回退读取 `liquidity_usd`。分类：`实际决策用途`。建议：和上面一样，改为显式的 legacy fallback 开关，不再无条件吸收旧字段。
- `apply_canonical_metrics` (`101-149`)：在 canonical 计算完成后，继续反向回填 `top10_ratio`、`top10_ratio_source`、`top10_ratio_*`、`liquidity_usd` 给旧调用方。分类：`兼容保留`。建议：集中保留在这一层是对的；后续可以把兼容写出做成单独 helper，便于未来整体删除。
- `_build_top10_candidates` (`154-206`)：除了 Bitquery / GMGN / Helius 外，还会把 `top10_ratio + top10_ratio_source` 作为候选源重新喂回决策。分类：`实际决策用途`。建议：仅在迁移窗口内允许该 legacy candidate；后续要求来源必须来自 source-native 字段或 canonical 列。
- `_build_liquidity_candidates` (`273-334`)：把 `liquidity_usd` 作为 `LEGACY_LIQUIDITY` 候选重新参与 exit liquidity 解析。分类：`实际决策用途`。建议：迁移完成后移除 `LEGACY_LIQUIDITY` 候选，只保留 `pair_liquidity_usd` / `exit_liquidity_usd` / `birdeye_liquidity_usd` / `gmgn_header_liquidity_usd`。

### `modules/data_fetcher.py`

- `get_market_data` (`636-756`)：行情抓取结果仍继续输出 `liquidity_usd` 兼容字段，并把它设置为 `exit_liquidity_usd` 或 `pair_liquidity_usd` 的 fallback。分类：`兼容保留`。建议：让抓取层只输出 canonical 字段；`liquidity_usd` 兼容别名应只在 canonical bridge 层生成。
- `get_helius_security` (`882-903`)：返回 payload 时仍带 `top10_ratio: None`。分类：`兼容保留`。建议：删掉这个旧 key，或替换成明确的 source-native 观察字段名。
- `_sync_scrape_gmgn` (`1400-1586`)：GMGN 抓取结果仍把页面文本/正则结果写到 `top10_ratio`。分类：`兼容保留`。建议：改成 `gmgn_top10_pct_observed`，并由 canonical 层映射到 `top10_raw_pct`。
- `fetch_gmgn_analytics` (`1673-1678`)：用 `result.get("top10_ratio")` 判定本次 GMGN 抓取是否“有用”。分类：`风险：不应继续存在的旧依赖`。建议：改为检查 `gmgn_top10_pct_observed`、`header_liq_usd`、`raw_data` 等 source-native 字段，避免控制流继续依赖旧字段名。

### `modules/database.py`

- `_extract_signal_metric_payload` (`42-69`)：从旧 `terminal_states` / `stable_snapshot` 提取 canonical 字段时，会用 `liquidity_usd` 作为 `pair_liquidity_usd` / `exit_liquidity_usd` 的 fallback。分类：`兼容保留`。建议：这是合理的历史兼容桥；等旧 JSON 基本清完后可以移除 fallback。

### `modules/db_schema.py`

- `_backfill_signal_metric_columns` (`186-257`)：migration/backfill 会从旧 JSON 路径里的 `top10_ratio`、`liquidity_usd` 回填到 canonical 列。分类：`兼容保留`。建议：保留，这正是旧字段应该存在的位置。
- `_backfill_golden_dog_metric_columns` (`511-559`)：训练表 backfill 会从 `holder_distribution.top10_ratio` 等旧路径回填到 canonical 列。分类：`兼容保留`。建议：保留，直到历史训练数据全部完成 canonical 化。

### 文档与注释

- `train_model.py` (`42`)：注释仍写着 `liquidity_at_snap` 对应 `main.py` 里的 `liquidity_usd`。分类：`风险：不应继续存在的旧依赖`。建议：改成“对应 decision liquidity / canonical liquidity snapshot”，避免后续训练特征继续绑定旧字段名。
- `docs/top10_liquidity_pipeline_refactor.md` (`7-13`, `49`, `66-71`)：文档仍在说明 `top10_ratio` / `liquidity_usd` 兼容层与旧字段。分类：`展示用途`。建议：可以保留，但最好补一句“仅迁移兼容，不可作为新代码读取入口”。

## 仍参与决策的旧字段引用

当前仍会影响实际决策结果的旧字段依赖，全部集中在 [`modules/canonical_metrics.py`](modules/canonical_metrics.py)：

- `get_canonical_top10_pct`：旧 `top10_ratio` 仍可作为最终 top10 的 fallback。
- `get_pair_liquidity_usd`：旧 `liquidity_usd` 仍可作为 pair liquidity fallback。
- `get_exit_liquidity_usd`：旧 `liquidity_usd` 仍可作为 exit liquidity fallback。
- `_build_top10_candidates`：旧 `top10_ratio + top10_ratio_source` 仍会被放回候选池。
- `_build_liquidity_candidates`：旧 `liquidity_usd` 仍会以 `LEGACY_LIQUIDITY` 候选参与 liquidity 决策。

### 修复建议

- 增加配置项 `allow_legacy_metric_fallback`，先默认 `true`，等一轮 migration/backfill 验证通过后切到 `false`。
- 在 `canonical_metrics` 里区分两种模式：
  `compat mode` 允许旧字段兜底；
  `strict mode` 只能读 canonical 字段和 source-native 字段。
- 对 top10：
  只允许 `top10_raw_pct` / `top10_adjusted_pct` 或 Bitquery/GMGN/Helius 的 source-native 输入参与候选构建；
  停止把 `top10_ratio` 当作候选源。
- 对 liquidity：
  只允许 `pair_liquidity_usd`、`exit_liquidity_usd`、`birdeye_liquidity_usd`、`gmgn_header_liquidity_usd` 参与候选构建；
  移除 `LEGACY_LIQUIDITY` 候选。
- 在数据库层保留 legacy backfill，但在运行时决策层逐步禁用 legacy fallback。

## 建议清理顺序

1. 先改 [`modules/canonical_metrics.py`](modules/canonical_metrics.py)，把旧字段 fallback 做成可关闭配置。
2. 再改 [`modules/data_fetcher.py`](modules/data_fetcher.py)，让 GMGN / Helius / market fetch 只产出 source-native 或 canonical 字段。
3. 然后删掉 [`main.py`](main.py) 里 `_resolve_top10_ratio` 这类旧命名 wrapper，并逐步减少 `terminal_states` / `stable_snapshot` 里的旧字段写入。
4. 最后更新 [`train_model.py`](train_model.py) 注释和 [`docs/top10_liquidity_pipeline_refactor.md`](docs/top10_liquidity_pipeline_refactor.md) 文档说明。
