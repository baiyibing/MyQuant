# R1 · grok · qlib 工程性能（kernels / 过滤路径热点）

**Lane**：a kernels/进程池；c 过滤路径热点（#40/#39 之后）  
**纪律**：只出想法卡；不改产品代码；墙钟/吞吐，不是年化收益。  
**宿主前提**：Windows 是主战场（spawn / 进程池固定开销）；Linux 仅对照。

---

## 卡 1 · [a] Win 默认 kernels=1，按查询粒度自适应抬升（禁止盲拉）

- **标题**：查询粒度自适应 kernels：小查询钉 1，大 Loading 才评估 >1
- **本仓锚点**：HOST §2 — Win 单日 50 股 `D.features` kernels>1 ~**29s** → kernels=1 **0.09s**（#39）；train Loading 16-kernel ~**52 min** vs kernels=1 ~**405s**（#43）；`my_scripts/custom_train_backtest.py:97` 仍硬编码 `kernels=16`；`dump_all --max_workers 16` 在 Win 进程池回收处死锁（路线图钉 8）
- **提案**（调度级 + 纪律级）：
  1. 产品入口（train / 过滤回测 / 导出）**默认 `kernels=1`**，与 #43 实测对齐；CLI/`QLIB_KERNELS` 可覆写但须打 HIT 日志。
  2. 自适应门：仅当单次查询估计规模超过阈值（如 instruments×calendar_days ≥ N，或 handler bare-read 路径）才允许试 `kernels∈{2,4,8}`，且必须带 **Win 墙钟对照表**（同配置 kernels=1 vs k）。
  3. 小查询路径（策略 bar 内 `D.features`、单日 close、补足二次过滤）**硬禁止** kernels>1。
  4. 与 dump 侧纪律对齐：进程池上限与「回收死锁」经验共享，不把 dump 的 8 误当成 features 的好默认。
- **收益（砍哪段墙钟）**：
  - 过滤 bar：防止回退到 ~100s/bar（已从 ~3.6s/bar 修好）；保住整轮分钟级。
  - train Loading：相对 16-kernel miss，砍掉 ~45+ min / 次 init（405s vs 52 min 量级）。
  - 消除「某脚本忘了改仍写 16」导致的偶发数十分钟回退。
- **成本与风险**：自适应阈值若按 Linux 标定会在 Win 误抬升；覆写环境变量被 CI/agent 继承造成「本地快、宿主慢」。正确性无影响（kernels 不改数值），但墙钟回归难测。
- **冻结检查**：同配置 Win 烟测：① 小查询（≤100 股×1 日）kernels=1 墙钟 ≤ 历史 0.1s 量级；② handler Loading kernels=1 不劣于 16；③ 改 kernels 不改变 pred/名单 digest。
- **对抗预填**：「CPU 很多就开满」在 Win spawn 下是负优化；把 dump `max_workers=8` 直接抄到 `qlib.init(kernels=…)` 会再次踩小查询税。
- **建议裁决**：**裁剪后采纳**（默认钉 1 + 入口清掉硬编码 16；自适应抬升登记为可选实验，不进默认）
- **重提条件**：若 Win 上测得某类大查询（全宇宙×长窗 bare-read）kernels=4/8 相对 1 稳定 ≥1.5× 且无死锁/内存尖峰，再把该档写进自适应表。

---

## 卡 2 · [a] 进程池「固定税」仪表：spawn 启动 + 池回收计入 manifest，禁止无税表抬 kernels

- **标题**：ProcessPool 固定税仪表（spawn/回收）进 run-manifest，抬 kernels 必须先过税表
- **本仓锚点**：HOST §1.2 Windows 进程池固定开销、spawn、路径；HOST §2 dump/Loading 与小查询量级差两个数量级；`custom_train_backtest.py` 含 `multiprocessing.freeze_support()`；路线图 Win `max_workers=16` 回收死锁两次复现
- **提案**（纪律级 + IO/调度级）：
  1. 在 `run_manifest` / timer 节点增加：`pool_spawn_ms`、`pool_task_ms`、`pool_join_ms`（或等价：kernels>1 时首包延迟 vs 纯计算）。
  2. 规则：任一入口若 `kernels>1` 且 `pool_spawn_ms / pool_task_ms > τ`（建议先 τ=0.5），自动降回 1 并记 WARN——**税比活高则不许并行**。
  3. 文档化：Linux 烟测通过 ≠ Win 可抬；抬升 PR 必须附 Win 税表截图/日志。
- **收益（砍哪段墙钟）**：不直接砍秒，而是**防止**把已砍掉的 bar/Loading 红利用一次「顺手 kernels=16」吐回去；间接保住 #39/#43 的 10²–10³ 倍量级收益。
- **成本与风险**：timer 埋点要碰 qlib 调用边界或本仓 wrapper，有少量工程面；阈值 τ 过严会永远卡在 1（可接受）。勿为埋点去 patch 上游 qlib 过深。
- **冻结检查**：同任务 kernels=1 与 kernels=k 各跑 1 次，manifest 必出三字段；小查询场景必须触发降级 WARN。
- **对抗预填**：只报「总墙钟」不拆 spawn，会被「偶发快」误导；在 Linux CI 绿灯后直接合 Win 默认 >1。
- **建议裁决**：**采纳**（低成本纪律；与卡 1 配套）
- **重提条件**：若 qlib 上游改为线程池/持久 worker 且 Win 税表显示 spawn≈0，再重新评估默认并行。

---

## 卡 3 · [c] Return-gate 双 `D.features` 合并 + 补足二次过滤去重（#40 close-cache 之后的下一刀）

- **标题**：return gate：首尾两日两次 `D.features` 合一；补足二次调用复用同日 close 视图
- **本仓锚点**：`my_scripts/custom_strategy.py` `_filter_stocks_by_return_threshold`（约 L167–180）对 `prev_dates_last` / `prev_dates_first` **各打一次** `D.features(..., fields=["$close"])`；`generate_trade_decision`（约 L342–361）在凑不满 topk 时 **再进一次** 同 timer 的过滤（候选扩大），可重复 IO。HOST §2：#40 close cache + CYQ 跳过 Quantile 后四开关重回测 **41.6→7.2 min**，bar ~**3.6s**——下一热点就在仍存活的 close/return 路径。
- **提案**（IO 级 + 缓存级）：
  1. 将首尾两日查询改为 **单次** `D.features(stocks, ["$close"], start=last, end=first)`，内存取首/末日；或明确走 #40 close-cache 的 `(instrument, date)→close` 查找，**禁止** cache 已命中时再打 provider。
  2. 同 bar 内第二次补足过滤：复用第一次已取的 close 视图 / cache 切片，只扩大 instruments 集合做差量拉取（MISS 子集）。
  3. 为 `strategy.filter_return_threshold` timer 增加子计数：`df_calls`、`cache_hit`、`n_stocks`，便于证伪。
- **收益（砍哪段墙钟）**：砍 **bar 内 return-gate IO**（当前 ~3.6s/bar 中的 close 往返份额）；乐观估计整轮过滤回测再削 **10–30%** 墙钟（视 cache 命中与二次补足频率）；不碰 handler_init。
- **成本与风险**：单次区间查询若在 kernels>1 下被错误并行，可能比两次单日更慢——必须与卡 1「小查询 kernels=1」绑定。区间 first/last 与「精确两日」在停牌/缺日时语义需对齐（用交易日历定位，勿用自然日）。正确性：return gate 阈值结果须与现实现 bit/名单一致。
- **冻结检查**：同 pred 同窗，开过滤名单 digest 不变；`df_calls` 每 bar 期望从 ≥2（常 ≥4 含补足）降到 1（或 1+差量）；改 lookback/threshold 必须 cache miss。
- **对抗预填**：只合并调用却仍 kernels=16 → 墙钟不降反升；把「区间 first/last」当成自然日滚动导致 gate 漂移（收益纪律污染，本 brainstorm 禁止用快换正确性）。
- **建议裁决**：**采纳**
- **重提条件**：若 timer 显示 return-gate 已 <5% bar 时间，则降级为登记远期，转攻卡 4 的资格链 IO。

---

## 卡 4 · [c] 四开关资格链 bar 内 IO 盘点：ST/CYQ/MA20/斜率 是否仍重复打 provider

- **标题**：#40/#39 之后的资格链残余热点盘点（D.features 次数 × 字段 × 是否可预载）
- **本仓锚点**：HOST §2/#40 已吃掉 close cache + CYQ 跳过 Quantile 的大头；§3.c 仍问：D.features 次数、close 预载之后还有哪些 bar 内重复 IO。四开关（ST PIT / CYQ / 买入资格 / MA20+5 日斜率）与 `TopkDropoutStrategyWithFilter` return gate 叠在同一回测环上；导出路径（`export_daily_pool.py`）也可能二次读 close/市值。
- **提案**（IO 级 + 纪律级，先量后改）：
  1. 在过滤回测开四开关下，对单 bar 做 **调用谱**：每次 `D.features` 的 fields、instruments 规模、起止日、是否命中 close-cache。
  2. 分类：① 可并入日初一次预载的只读字段（`$close`/`$zhangting`/MA 所需）；② 必须按候选子集懒加载；③ 已跳过（Quantile）勿回潮。
  3. 若 MA20/斜率仍按候选反复算表达式：改为 **交易日滚动预计算** 或复用 handler 已算列（仅当列语义与资格闸一致时），禁止为快关掉 gate。
  4. 产出一张「残余热点表」进本评审目录，作为下一刀施工单——本卡本身可先只落地盘点脚本设计，不改产品默认。
- **收益（砍哪段墙钟）**：定位并砍 **bar 内非 return-gate 的重复 IO**；目标把 ~3.6s/bar 中「可证伪的重复读」打到接近纯策略逻辑（亚秒～1s 量级，需实测）。整轮 7.2 min 若 bar 占主导，有望再明显下降。
- **成本与风险**：预载全宇宙多字段有内存尖峰（OOM 纪律：禁 `fetch()` 落巨型 parquet）；资格字段与训练特征筹码不可比（chip-parity）——预载只能服务过滤，勿偷渡进训练特征。Win 预载若用多进程会再付 spawn 税。
- **冻结检查**：盘点报告必须含 HIT/MISS 与每字段调用次数；任何预载 PR 须证明关/开预载名单与净值路径一致（工程一致，非收益优化）。
- **对抗预填**：未盘点就「再加一层 Redis/parquet 缓存」重复 #43 已禁的巨型落盘；把 CYQ 精确路径又接回 Quantile「图个统一」导致 7.5× 红利回吐。
- **建议裁决**：**裁剪后采纳**（先强制盘点+调用谱；预载/合并施工单按热点排序，不一次做完）
- **重提条件**：调用谱显示某字段每 bar ≥2 次 MISS 且占比 ≥20% bar 时间 → 升级该字段预载为「采纳」施工。

---

## 卡 5 · [a+c] 否决扫漏：为吞吐关闭 return gate / 盲目 kernels>1 / fetch→巨 parquet

- **标题**：否决三连——关 gate 换快、盲抬 kernels、fetch 落巨文件
- **本仓锚点**：HOST §1.1 不把「跑得快」当改过滤默认的理由；§1.4 禁 `fetch()` 落巨型 parquet（已 OOM）；§2/#43 明确 handler-cache 用 `to_pickle(dump_all=True)`；§3.g 扫漏否决示例正是「为快关正确性 gate」「盲目拉高 kernels」
- **提案**（纪律级）：本轮及后续 eng-perf 施工单显式 **否决**：
  1. 关闭或放宽 `max_return_threshold` / 四开关「只为少打 D.features」；
  2. 在未附 Win 小查询+Loading 对照表前把默认 kernels 调回 >1；
  3. 以「过滤路径二级缓存」为名再次 `fetch()`→parquet/全宇宙宽表落地。
  允许的替代：卡 1–4 的 kernels=1、调用合并、close-cache 差量、handler-cache pickle、盘点后再预载。
- **收益（砍哪段墙钟）**：无直接加速；防止正确性回退与 OOM，避免「快了但不可复现」。
- **成本与风险**：无代码成本；需评审主持在 R3 裁决时引用本卡挡枪。
- **冻结检查**：任何声称 eng-perf 的 PR 若改 gate 默认或 kernels 默认 >1，必须被本卡否决标签拦住并改走收益册或附税表。
- **对抗预填**：「先关 gate 测纯 IO 上限」若泄漏进默认配置；「Linux 上 kernels=8 很快」直接合入 Win 默认。
- **建议裁决**：**否决**（对上述三条路径本身）；对策方向见卡 1–4
- **重提条件**：仅当收益册单独批准改 gate，或 Win 税表证明某档 kernels>1 全面占优且无死锁——那时走正式变更，不叫「eng-perf 顺手改」。

---

## R1 自检摘要

| # | 方向 | 建议裁决 | 一句话 |
|---|------|----------|--------|
| 1 | a | 裁剪后采纳 | 默认 kernels=1；自适应抬升先实验 |
| 2 | a | 采纳 | spawn/回收税表进 manifest，税高必降 |
| 3 | c | 采纳 | return-gate 双查询合并 + 补足差量 |
| 4 | c | 裁剪后采纳 | 先调用谱盘点，再按热点预载 |
| 5 | a+c/g | 否决（坏路径） | 关 gate / 盲抬 kernels / 巨 parquet |
