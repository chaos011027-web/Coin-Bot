# MEMORY.md

## 1. 项目定位
SolanaHunter V3 / V3.6 是一个 Solana 短线 / 信号监控系统。

核心目标：
- 监听 Telegram 群和私聊中的 CA
- 快速抓取代币基础信息
- 尽快生成中文首卡
- 后续根据 GMGN、DexScreener、Birdeye、Bitquery、GoPlus 等数据补刷卡片
- 进行 AI 风控分析和策略判断

当前最高优先级不是新增功能，而是：
- 保证首卡体验
- 保证 GMGN 工作页恢复
- 保证补刷准确
- 保证头像、流动性、Top10、标签等字段不被错误来源污染

---

## 2. 当前架构约束（禁止推翻）
### 2.1 双 Fetcher 架构必须保留
当前存在两套 fetcher：
- interactive / foreground fetcher
- background / watchdog fetcher

禁止回退成单 fetcher 架构。  
只能在现有骨架上修 bug，不允许大重构。

### 2.2 已确认正确且不要反复重修的部分
以下方向已基本确认正确，不要作为主问题重复修改：
- dual fetcher / 双浏览器分流骨架
- watchdog/background 重复 market fetch 已修
- main 启动阶段区分 fetcher 预热结果
- raw_market 传递链
- 中文卡片模板主体结构
- 按钮结构
- AI 分析主流程
- 价格监控与里程碑播报主流程

---

## 3. 当前最高优先级原则
### 3.1 首卡优先
首卡优先争取这些字段：
- 头像
- 1m
- GMGN header liquidity
- safety
- Top10
- tags

但不能无限等待。  
必须短窗口抢字段，晚到字段交给补刷。

### 3.2 不允许错误页 / 遮罩页“先抓一点再说”
以下页面必须视为 invalid：
- overlay / popup_blocked
- shell page
- target_not_ready
- layout_not_ready
- header_not_ready
- error page
- 初始化页 / 首页 / 壳页

禁止在 invalid page 上：
- best-effort parse
- 写正式 canonical 结果
- 写 runtime state

### 3.3 Top10 规则不能再破坏
Top10 只能与 “Top 10” 标签邻域绑定提取。  
禁止：
- window 最大百分比猜测
- bundle / rat / phishing / 其他百分比污染 Top10

### 3.4 流动性规则不能再破坏
以下值不能作为可靠流动性直接污染首卡：
- 0
- 0.007
- 3.0
- 5.16
- 其他明显异常极小值

GMGN header liquidity 与低质量 fallback 必须区分。

### 3.5 安全字段语义不能再破坏
- burned=True 是正向信息
- locked=None 不能渲染成 ❌
- freeze=False 如果语义是“无冻结风险”，不能简单映射成负向

---

## 4. 当前已确认的主问题
当前主问题不是新增功能，而是这些残留 bug：

1. 首卡头像主路径仍不稳
2. GMGN 工作页恢复仍未真正锁到用户配置页
3. overlay / popup 页面仍会卡住抓取
4. 标签抓取在页面不完整时容易 partial
5. fast mode 仍被错误页面或 overlay 拖慢

---

## 5. 旧版可工作链（必须优先学习）
### 5.1 GMGN 设置页 / 已设置窗口恢复链
遇到 GMGN 已设置页面相关问题时，优先参考旧版可工作函数：
- prepare_browser_profile
- _load_gmgn_saved_state
- _apply_gmgn_saved_state
- _build_gmgn_token_url
- _wait_gmgn_target_page
- _get_or_create_gmgn_tab

原则：
- 优先恢复已保存工作页
- 用保存状态构造 token URL
- 不要先开首页再修复
- 不要让复杂 fallback 覆盖主链

### 5.2 头像抓取链
遇到头像问题时，优先参考旧版可工作函数：
- _pick_gmgn_avatar
- _fetch_dex_avatar_url
- _fetch_pump_avatar_url
- _fetch_warm_gmgn_avatar_url
- prime_avatar_sources
- ensure_token_avatar

当前阶段的新规则：
- 首卡头像主链优先收缩为：
  stable_cache -> Dex -> Helius/DAS -> metadata URI
- 首卡阶段暂时不让以下来源占主预算：
  - Pump
  - BirdEye
  - GMGN warm / page DOM
- 页面型头像只允许作为后补链研究，不得主导首卡
- 保留旧函数，但不要再让页面依赖型头像链阻塞首卡
- URL 命中后 materialize / cache 链继续保留，不要误判 downloader 为主断点

---

## 6. 当前已确认错误模式（禁止再次引入）
### 6.1 GMGN 页面识别相关
禁止：
- new_tab("https://gmgn.ai/") 作为默认起点
- 先开首页再恢复
- overlay 明确时继续 heavy fallback
- 复杂 page gate 盖过已设置窗口恢复主链

### 6.2 walkthrough / 弹窗处理相关
禁止：
- 全局按钮评分
- 颜色识别
- 绿色按钮识别
- primary 按钮识别
- z-index / fixed / sticky / 大小评分
- 点击 买入 / Buy / 卖出 / Sell / Swap / Trade / Holders / All

当前 walkthrough 原则：  
只允许点击：
- 下一步
- 下一个
- 完成
- Next
- Done
- Finish

### 6.3 fast path 相关
禁止：
- overlay_mask / popup_blocked 明确后继续 strong_bootstrap_retry
- interactive fast 被拖成 30~40 秒
- deep fallback 点击链进入首卡主路径

### 6.4 代码组织相关
禁止：
- 大面积重构
- 为了“更优雅”重写整文件
- 顺手修改无关模块
- 在未验证旧功能边界前改动 notifier / Top10 / main.py

---

## 7. 双浏览器状态原则
当前双浏览器目录：
- data/browser_profile_interactive
- data/browser_profile_background

旧单浏览器目录：
- data/browser_profile

注意：
- 旧 browser_profile 中保存过用户手工配置好的 GMGN 页面状态
- 双浏览器后，状态可能分裂
- 复制旧 profile 数据到 interactive/background 作为种子是合理的

原则：
- interactive 应尽量作为主工作页来源
- background 不应长期漂移成另一套独立页面记忆
- 但当前修 bug 优先级仍高于继续扩展状态同步逻辑

---

## 8. 修改代码时的硬性流程
每次改代码必须按这个顺序：

1. 先读 MEMORY.md
2. 先看日志、截图、当前代码
3. 明确问题发生在哪一层：
   - data source
   - parser
   - canonical / merge
   - queue / timing
   - browser_state
   - page_gate
   - render
4. 优先做最小必要修改
5. 先修 bug，再考虑优化
6. 改完必须自检：
   - 是否破坏首卡
   - 是否破坏头像链
   - 是否破坏 Top10
   - 是否破坏 notifier
   - 是否破坏 dual fetcher 架构

---

## 9. 给 Codex 的默认约束
每次让 Codex 改代码时，默认附加这些约束：

- 先阅读 MEMORY.md
- 只修改指定文件与指定函数
- 禁止修改无关模块
- 禁止重构整文件
- 先替换旧版可工作函数体，再做最小改动
- 输出完整可替换函数
- 最后输出自检结论

---

## 10. 当前推荐工作流
### 10.1 ChatGPT 负责
- 看日志
- 看截图
- 看旧代码与当前代码差异
- 输出《修改规划书》

### 10.2 Codex 负责
- 只根据规划书修改指定函数
- 不越界改动

### 10.3 ChatGPT 再负责
- 审核 Codex 输出
- 检查是否引入多余复杂度
- 检查是否误删旧功能

---

## 11. 当前最值得优先补测试的点
后续应逐步为以下行为建立最小测试：

1. _get_or_create_gmgn_tab 不再默认打开首页
2. walkthrough 只点击 6 个固定词
3. interactive + fast + overlay_mask 时直接弱返回
4. prime_avatar_sources 保持旧版优先级
5. saved_state 能构造出正确 seed_url

## 当前新增确认的问题（2026-03-20）
1. AvatarEnrichment 已经改成 patch 方向，但 terminal_states 仍可能缺 name，导致头像补刷仍可能刷出坏中间态卡片。
2. AvatarEnrichment 最终仍走通用 update_user_message，而不是头像专用 patch refresh。
3. data_fetcher._sync_scrape_gmgn 已有 hard_deadline 骨架，但运行日志证明 fast 模式仍会实际跑到 90+ 秒，说明 deadline 还没有压进所有阻塞 helper。
4. 当前优先级最高的两个测试保护点：
   - AvatarEnrichment 不能覆盖已有 name/cap/safety/top10
   - GMGN fast 在 overlay_mask 时必须在预算内早退

## 当前新增硬规则
- AvatarEnrichment refresh 只允许补头像，不允许用稀疏 payload 覆盖已有业务字段
- GMGN fast 的“超时”必须是底层真实结束，不接受仅外层 wait_for 超时、线程仍继续跑

---

## 12. 当前阶段的 clean-room 研究定位（新增）
当前阶段先暂时抛开 bot 主流程大修，不优先继续改整套 bot，而是先做 4 个 clean-room 研究模块：

### 12.1 AvatarLab
- 研究如何稳定拿到代币头像
- 明确哪些来源适合首卡，哪些只适合后补
- 首卡优先非页面源，页面型来源只作后补

### 12.2 TokenInfoFastPath
- 研究首轮基础信息如何通过 API / RPC / metadata / risk services 快速获得
- 重点字段：
  - 流动性
  - market cap
  - Top10
  - authority
  - 基础安全字段
  - 名称 / symbol / image

### 12.3 TokenInfoSlowPath
- 研究后补强结果
- 负责：
  - heavier holder analysis
  - 更强风险解释
  - 页面型补字段
  - page-only image

### 12.4 GMGNLayoutKeeperLab / GMGNPageReaderLab
- LayoutKeeper 负责恢复和保持工作页
- Reader 负责读取当前正确页
- 两者禁止再混在一起

---

## 13. 当前最新已确认结论（新增）
### 13.1 头像结论
- 首卡头像真正快的是 stable_cache
- Dex 是有限覆盖但真实有效的首卡非页面源之一
- Pump 当前请求链不稳定，不再占首卡主预算
- BirdEye 当前额度问题明确，不再占首卡主预算
- GMGN warm / page DOM 只允许作为后补链研究，不得主导首卡

### 13.2 基础信息结论
- 首轮基础信息应优先走 API / RPC / metadata / risk services
- 页面型字段不进入首轮主链
- Top10 只能来自权威持仓来源，不允许猜
- maker_count 只能作为 holder_count 的弱估计，不能用于 Top10 比例
- 弱流动性值必须 estimated 或待确认，不得直接污染首卡

### 13.3 GMGN 结论
- 当前最重要的不是继续修整套页面恢复链，而是拆开：
  - LayoutKeeper
  - Passive Attach Reader
- Reader 必须只读当前手工打开的正确页
- Reader 禁止主动导航、bootstrap、homepage fallback、walkthrough
- 错页、shell 页、初始化页、target_not_ready 页必须 invalid / weak 返回

---

## 14. GMGN Reader 与 Keeper 硬规则（新增）
### 14.1 LayoutKeeper
以下逻辑属于 Keeper：
- _load_gmgn_saved_state
- _apply_gmgn_saved_state
- _build_gmgn_token_url
- _persist_gmgn_runtime_state
- _bootstrap_gmgn_tab_layout
- _finish_gmgn_walkthrough
- prepare_browser_profile

Keeper 负责：
- saved_state
- last_known_good_layout_url
- prewarm / restore
- walkthrough

### 14.2 Passive Attach Reader
Reader 只允许：
1. 读取当前已有 tab/url/title
2. 跑 page gate
3. gate=true 时做块级读取：
   - header
   - safety
   - top10
   - holder_tags

Reader 禁止：
- tab.get(...)
- window.location.href = ...
- _bootstrap_gmgn_tab_layout(...)
- _apply_gmgn_saved_state(...)
- _finish_gmgn_walkthrough(...)
- homepage fallback

Reader 只要发现以下状态，必须 invalid / weak 返回：
- overlay / popup_blocked
- shell page
- target_not_ready
- layout_not_ready
- header_not_ready
- error page
- 初始化页 / 首页 / 壳页

---

## 15. 当前推荐的数据链路（新增）
### 15.1 首卡头像链
stable_cache -> Dex -> Helius/DAS -> metadata URI

### 15.2 首轮基础信息 FastPath
- DexScreener：
  - 流动性
  - market cap
  - pair age
  - price / volume
- Solana RPC：
  - getTokenLargestAccounts
  - supply
  - authority
- Helius / DAS：
  - metadata
  - image
  - symbol
  - name
- RugCheck / GoPlus：
  - 安全字段

### 15.3 后补 SlowPath
- heavier holder analysis
- page-only 字段
- page-only image
- 更强风险解释
- 页面型标签

---

## 16. 给 Codex 的最新默认工作流（新增）
从现在开始，Codex 默认必须按这个顺序工作：

1. 先阅读 MEMORY.md
2. 先分析当前代码、日志、截图、测试状态
3. 先做虚拟替换 / 影子补丁
4. 先补最小失败测试
5. 自己运行：
   - py_compile
   - pytest
6. 只有在相关测试通过后，才允许修改真实代码
7. 若测试未通过，必须停止，不得越界扩大改动范围

### 16.1 默认测试重点
后续优先补这些测试：
1. 首卡头像链不再依赖页面
2. Pump 不再占首卡头像主预算
3. Top10 不会从非权威来源猜值
4. 弱流动性值不会污染首卡
5. Passive Attach Reader 不会主动导航
6. 初始化页 / shell 页 / target_not_ready 页不会产出正式字段

### 16.2 默认停止条件
若出现以下任一情况，Codex 必须停止并报告：
- 测试环境不可用
- import / syntax 问题无法最小范围内解决
- 修改开始扩散到 notifier / AI / 按钮 / 价格监控 / 无关模块
- Reader 和 Keeper 再次被混改