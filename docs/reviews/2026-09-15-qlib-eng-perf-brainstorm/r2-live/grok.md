# R2-live · grok · qlib 工程性能（kernels / 过滤路径热点）

**席位**：grok（真 CLI R2-live）  
**Lane**：a kernels/进程池；c 过滤路径热点  
**相对 R1 / SYNTHESIS**：不重开 P0-4 / P1-1 / P1-2 / P1-6 / N1–N3 原文；本轮只写源码新锚点与施工边界。  
**纪律**：只出想法卡；不改代码、不重训、不跑长实验。墙钟/吞吐，不是年化收益。Windows 宿主是主战场。

R1 已锁定、本轮当作前提：默认 `kernels=1`（自适应仅实验）、ProcessPool 税表、return-gate 双查询合并、四�# R2-live · grok · qlib 工程性能（kernels / 过滤路径热点）

**席位**：grok（真 CLI R2-live）  
**Lane**：a kernels/进程池；c 过滤路径热点  
**相对 R1 / SYNTHESIS**：不重开 P0-4 / P1-1 / P1-2 / P1-6 / N1–N3 原文；本轮只写源码新锚点与施工边界。  
**纪律**：只出想法卡；不改代码、不重训、不跑长实验。墙钟/吞吐，不是年化收益。Windows 宿主是主战场。

R1 已锁定、本轮当作前提：默认 `kernels=1`（自适应仅实验）、ProcessPool 税表、return-gate 双查询合并、四开关调用谱先量后预载、否决关 gate / 盲抬 kernels / fetch→巨 parquet。

---

## 卡 1 · [a] 生产入口漏钉 `kernels=1`：未传参 = 走上游默认核数

- **标题**：`predict_extended` / `sweep_live_adapter` / `feature_experiments` 未传 `kernels`，#43 红利在这些路径上可能从未生效
- **本仓锚点**：
  - `my_scripts/custom_train_backtest.py:92–97` 仍硬编码 `kernels=16`（R1 已点名）。
  - **本轮新点**：`my_scripts/predict_extended.py:180` `qlib.init(provider_uri=..., region="cn")`、`sweep_live_adapter.py:132` 同形、`feature_experiments.py:288` 同形——**三处都不传 `kernels`**。qlib 上游 `C.kernels` 未显式指定时通常落到 `cpu_count` 量级；Win 宿主 Thinkpad 很容易回到 8–16，正是 HOST §2 已证伪区间（小查询 29s vs 0.09s；Loading 52 min vs 405s）。
  - 对照：`qlib_scripts/refresh_mydata.py` 已把 `dump_all --max_workers` 钉死 8；训练/导出入口没有对等的 kernels 钉。
- **提案**（纪律级 + 调度级）：
  1. 凡触碰 `D.features` / handler Loading 的生产入口（train / 过滤回测 / `predict_extended` / `sweep_live_adapter` / 特征实验）**显式** `kernels=1`；禁止「省略参数指望默认碰巧是 1」。
  2. 入口清单门禁（grep / 单测）：`qlib.init(` 必须出现 `kernels=`；缺省即失败。`QLIB_KERNELS` 可覆写但必须打一行 `KERNELS=k source=cli|env|default`。
  3. 与 dump 侧拆开：`dump_all --max_workers=8` ≠ `qlib.init(kernels=)` ≠ `LGBModel num_threads=20`（见卡 2）。本卡只钉第一钮。
  4. `qlib_scripts/custom_train_backtest*.py` / `run_filter.py` / `my_rolling_benchmark.py` 的 `kernels=16` 视为死入口残留，一并列入清扫清单，但不把 notebook 样例当生产默认。
- **收益（砍哪段墙钟）**：
  - 防止 export / 二次 predict / sweep 第一臂 Loading 从 ~405s 回潮到 ~52 min（#43 量级）。
  - 防止这些路径上的小查询 `D.features` 从 ~0.09s 回潮到 ~29s，进而把过滤 bar 从 ~3.6s 打回 ~100s。
  - 不创造新加速曲线，是**把已测红利接到漏网入口**。
- **成本与风险**：正确性无影响（kernels 不改数值）。风险是某条 Linux 烟测路径依赖「默认多核碰巧快」——硬纪律 2：Linux 数字不得当 Win 预算。CI 30 min 不够跑 Loading 对照，门禁只能验「参数存在」，墙钟仍须 Win 宿主。
- **冻结检查**：同 pred 同窗，改 `kernels` 不改变 pred/名单 digest；三处漏网入口日志必现 `KERNELS=1`；故意不传 `kernels=` 的 CI 契约测试必须红。
- **对抗预填**：「不传就是上游默认，默认应该已经是 1」——本仓生产脚本从未验证这一点，且 `custom_train_backtest.py` 仍写 16，说明默认叙事不可信。「先在 Linux 上看省略参数也很快」——禁止用对照机给 Win 入口免钉。
- **建议裁决**：**采纳**
- **重提条件**：若上游 qlib 把未传 `kernels` 的默认改成 1 且本仓 CI 断言锁住，清单可从「强制传参」降为「文档 + 回归断言」；在此之前漏传 = 缺陷。

---

## 卡 2 · [a] 三钮拆开：`kernels` ≠ `dump max_workers` ≠ `LGB num_threads`；kernels=1 时 Redis 非必需

- **标题**：并行度三钮分账；禁止把 dump=8 / 线程=20 抄进 features 进程池
- **本仓锚点**：
  - dump：`docs/qlib-data-state-2026-09-13.md` / `refresh_mydata.py` `DEFAULT_MAX_WORKERS = 8`，禁 16（Win 进程池回收死锁两次）。
  - features 进程池：`qlib.init(kernels=…)`，HOST §2 小查询与 Loading 均显示 Win 上 >1 为负。
  - 训练线程：`custom_train_backtest.py` `LGBModel` `num_threads: 20`；HOST §2 `model_fit` ~**5.6s**（相对 init 可忽略）。
  - Redis：同文件 `qlib.init(..., redis_host='127.0.0.1', redis_password='123456')`，注释写「连接失败则降级为无缓存」。kernels>1 时 qlib 用 Redis 做表达式任务锁；kernels=1 时无 worker 可抢。
- **提案**（纪律级 + 调度级）：
  1. 施工单/评审清单写死三列：`kernels`（features 进程池，Win 默认 1）、`dump max_workers`（刷新编排，默认 8）、`num_threads`（树模型进程内线程，与 spawn 无关）。任何 PR 只许动自己那一列，禁止「挤成一个并行度」。
  2. kernels=1 路径：**不依赖 Redis 存活**；init 失败不得再付 mlflow 级白烧（与 HOST mlflow ~17 min 事故同类：环境半残仍往下跑）。文档一句：开 Redis 不是抬 kernels 的理由。
  3. `num_threads=20` 维持现状即可（fit 已不是墙钟头）；若未来有人把 `num_threads` 改成 `os.cpu_count()` 并声称 eng-perf，必须附 Win fit 对照且不得改 kernels。
- **收益（砍哪段墙钟）**：不直接砍秒；防止把 dump 的 8 或 LGB 的 20 误抄成 `kernels=8/16` 后整轮 Loading/bar 回吐（10²–10³ 倍量级，HOST 已测）。Redis 失败时避免「半残缓存 + 多进程锁」把小查询再次打到 29s 档。
- **成本与风险**：文档/门禁成本低。风险是有人在 Linux 上看到 Redis HIT 很快，要求 Win 默认 kernels>1「才能用表达式缓存」——那是辅层（kimi 车道 expr-cache）问题，不是进程池问题。
- **冻结检查**：改 dump `max_workers` 的 PR 不得改 `qlib.init(kernels)`；改 kernels 的 PR 不得改 dump 默认 8；kernels=1 且 Redis 不可达时，handler_init / 小查询仍须可完成（降级路径）。
- **对抗预填**：「CPU 20 线程，kernels 也开 20」——#43 已否；「dump 用 8 很稳，features 也用 8」——dump 是大文件 CPU 绑定、features 小查询是 spawn 税绑定，税表不同。「不开 Redis 就不算用 qlib」——kernels=1 下 Redis 对墙钟无正贡献。
- **建议裁决**：**裁剪后采纳**（采纳三钮分账 + kernels=1 不依赖 Redis；裁掉任何「为 Redis 缓存而抬 kernels」）
- **重提条件**：仅当 Win 税表（R1 卡 2 / SYNTHESIS P1-2）显示某档 kernels>1 且 Redis 锁等待 ≈0、相对 kernels=1 ≥1.5×，才允许把「Redis+多核」写成实验档；默认仍 1。

---

## 卡 3 · [c] 「极致性能」双单日 `D.features` 是负优化；补足切片再加倍

- **标题**：return-gate 现行实现把一次区间查询拆成两次单日往返，补足 1000:2000 再付一轮
- **本仓锚点**：
  - 现行：`my_scripts/custom_strategy.py` `_filter_stocks_by_return_threshold` L167–180 对 `prev_dates_last` / `prev_dates_first` **各打一次** `D.features(..., fields=["$close"], start=d, end=d)`，注释自称「仅查询 2 天数据」。
  - 死代码对照：同文件 `_filter_stocks_by_return_threshold_old` L65–70 **已经是** 单次 `D.features(..., start=last, end=first)`。所谓「极致性能」是把一次 IPC 拆成两次；在 Win spawn 下每次 `D.features` 都付进程池固定税（HOST：50 股单日 kernels>1 ~29s）。
  - 补足：`generate_trade_decision` L335 先取 `get_first_n(..., 1000)`，凑不满则 L357 `candidate_stocks[1000:2000]` **再进一次** 同函数（L360–363）——最坏 **4 次** `D.features` × 1000 股 / bar。差量不是「只拉缺的 N 只」，而是整块 1000。
  - 日志税：L143 `logger.warning` 把整份股票列表打进 `Filter.log`（`custom_train_backtest.py:72` 按 module 分流）；Win 杀软扫日志时，这不是免费的。
  - HOST §2：#40 后四开关重回测 41.6→7.2 min、bar ~3.6s；SYNTHESIS P0-4 已裁「双查询合一」。本卡补上 **为何现行比 old 更慢** 与 **补足切片的具体形状**。
- **提案**（IO 级；绑 kernels=1）：
  1. 热路径改回「一次查询、内存取首尾」或走 #40 close-cache 的 `(instrument, date)→close` 点查；**禁止** cache 命中后再打 provider。
  2. 正确性钉的是**现行双日点查**语义（两日都有 close 才入交集），不是 old 的 groupby first/last（缺日时 first 可能滑到中间日）。合并查询必须用交易日历对齐两日再切片，不得把缺日滑窗当成涨幅。
  3. 补足改为 **差量**：已查集合做 HIT，只对 `needed - already_filtered` 扩候选；扩步长按 `initial_required_count` 而非固定 1000:2000。
  4. 热路径日志降到 debug；warning 不得 dump 千级股票列表。
- **收益（砍哪段墙钟）**：砍 **bar 内 return-gate IO**（~3.6s/bar 中的 close 往返）。乐观：每 bar 从 2–4 次 `D.features` 降到 1 次（或 1+差量）；整轮过滤回测在 7.2 min 量级上再削一截（幅度以 Win 对照为准，本轮不估死百分比）。不碰 handler_init。
- **成本与风险**：区间查询若在 kernels>1 下被拆任务，可能比两次单日更慢——必须与卡 1 钉 1 绑定。缺日语义若抄 old 的 first/last 会改 return-gate 名单（收益纪律污染）。close-cache 脏读：改 lookback/threshold 必须 miss（硬纪律 3）。
- **冻结检查**：同 pred 同窗，开过滤名单 digest 与现行双日实现一致；`df_calls` 每 bar 从 ≥2（常 ≥4 含补足）降到 1 或 1+差量；改 `lookback_days` / `max_return_threshold` 必须 cache miss。
- **对抗预填**：直接复活 `_old` 函数——日志 + groupby 语义都错，只能借「一次查询」的形状。「区间查询更宽，顺手 kernels=16」——负优化。为少打 `D.features` 放宽 15% 阈值——否决（硬纪律 1，走收益册）。
- **建议裁决**：**采纳**（相对 SYNTHESIS P0-4 的施工细化：语义钉现行点查、补足改差量、热路径禁列表 dump）
- **重提条件**：若 always-on 计数器（卡 4）显示 return-gate `<5%` bar 时间，则本卡降为登记远期，转攻卡 4 的 exchange 逐股 IO。

---

## 卡 4 · [c] bar 计时每 10 步才打一次；#40 后残余更可能在 exchange 逐股 quote

- **标题**：`timing_interval_steps=10` 掩盖热点；下一刀先量 `D.features` 次数 + `is_stock_tradable`/`get_deal_price`/`get_factor`
- **本仓锚点**：
  - `custom_strategy.py:22, 242–247`：`timing_interval_steps` 默认 **10**，仅 `trade_step % 10 == 0` 才把 `strategy.filter_return_threshold` / signal / 买卖循环写入 `TimerRecorder`。90% 的 bar 对墙钟不可见；补足二次过滤（卡 3）是否触发也看不见。
  - 同文件 L274 / L291 / L414 / L459：`trade_exchange.is_stock_tradable` 四个调用点；L468–479 买入循环再打 `get_deal_price` + `get_factor`。这是 qlib `SimulatorExecutor` 逐股读行情/停牌/涨跌停，**不经过** return-gate 的 `D.features`，#40 close-cache / CYQ 跳过 Quantile **盖不到**。
  - 训练默认策略甚至不是这条：`custom_train_backtest.py:352–356` 注释掉 `TopkDropoutStrategyWithFilter`，线上 `port_analysis_config` 走 qlib 原版 `TopkDropoutStrategy`——过滤回测的 3.6s/bar 数字来自**开过滤的那条路径**，不要拿默认 train 配置当「已经没有策略 IO」。
  - SYNTHESIS P1-6「四开关资格链调用谱」仍有效；本卡把谱拆成两层：① 策略 `D.features`（卡 3）；② exchange 逐股 quote。
- **提案**（IO 级 + 纪律级，先量后改）：
  1. 诊断开关：短窗（数日）把 `timing_interval_steps=1`，并加 **always-on** 计数器（不进采样门）：`df_calls`、`n_stocks`、`cache_hit`、`tradable_calls`、`deal_price_calls`、`factor_calls`。正式长跑仍可采样，避免 JSON 膨胀。
  2. 分类：可日初一次预载的只读字段（`$close` / 停牌 / 涨跌停标记 / factor）vs 必须按候选子集懒加载 vs 已跳过（CYQ Quantile）勿回潮。
  3. 若谱显示 exchange 调用占 bar ≥20%：对**当日宇宙或当日候选**做一次 quote 视图（内存 dict），买卖循环只查表。预载不得 `fetch()` 落巨型 parquet（硬纪律 4）；不得把训练 COST-KDJ 的 `Quantile($low/$high, 250)` 塞进 bar 预载（那是 handler_init 特征，chip-parity 不可比）。
  4. `$zhangting` 字段模式的 `UnifiedLimitUpFilter`（`train_wiring.py:25–32`）已经避免价格表达式；盘点时若发现有人改回 `$close/Ref($close,1)` 价格模式，记为回归（见卡 5）。
- **收益（砍哪段墙钟）**：先让 ~3.6s/bar **可证伪**（现在 10 步采样做不到）。若残余在 exchange 逐股 IO，预载/合批有望把 bar 从数秒打到纯策略逻辑量级（亚秒～1s，须 Win 实测）。整轮 7.2 min 若 bar 占主导，可再下一截。不碰 handler_init。
- **成本与风险**：always-on 计数器有轻微开销，须可关。预载全宇宙 quote 有内存尖峰。`only_tradable=True` 时 `get_first_n` 可能扫描远超 topk 的候选——预载范围必须有上限，禁止「全市场逐 bar 物化」。Win 预载若用多进程再付 spawn 税。
- **冻结检查**：短窗诊断报告必须含 HIT/MISS 与每字段/每 exchange API 次数；任何预载 PR 须证明关/开预载名单与成交路径一致（工程一致，非收益优化）；改 gate/窗必须 miss。
- **对抗预填**：未出谱就「再加 Redis/parquet 二级缓存」——重复 #43 已禁路径。把训练侧 `Quantile($low/$high)` 也跳过「图与 CYQ 统一」——改的是 Alpha 特征，不是过滤 IO，且破坏 COST-KDJ。用 Linux 短窗采样数字写 3.6s/bar 的下一刀预算——否决（硬纪律 2）。
- **建议裁决**：**裁剪后采纳**（强制短窗调用谱 + always-on 计数器；预载施工单按谱排序，不一次做完）
- **重提条件**：谱显示某 exchange API 或某字段每 bar ≥2 次 MISS 且占比 ≥20% bar 时间 → 该字段/API 预载升级为「采纳」施工。若谱显示 return-gate 仍 ≥50% bar 时间，则先做完卡 3 再谈本卡预载。

---

## 卡 5 · [a+c] 否决扫漏（R2 增量）：漏传 kernels、dump 钮抄 features、训练 Quantile 当过滤加速、$zhangting 改回价格模式

- **标题**：四条假加速——省略 kernels、三钮混用、跳过 COST-KDJ Quantile、filter_pipe 改回算涨幅
- **本仓锚点**：HOST §1.1/1.4、§3.g；R1 卡 5 / SYNTHESIS N1–N3 已否「关 gate / 盲抬 kernels / 巨 parquet」。本轮源码又露出四条变体：
  1. `predict_extended` / `sweep_live_adapter` **不传** `kernels`（卡 1）——「我没写 16」≠「就是 1」。
  2. 把 `dump_all --max_workers=8` 或 `num_threads=20` 抄进 `qlib.init(kernels=)`（卡 2）。
  3. `custom_handler.py:187–188` 训练 COST-KDJ 仍用 `Quantile($low/$high, N)`；HOST #40「CYQ 跳过 Quantile」是**过滤资格**路径。把训练 Quantile 删掉「图快」= 改特征，不是 eng-perf。
  4. `train_wiring.build_limit_up_filter` 钉 `$zhangting` 字段模式；`custom_filter.py` 价格模式会在 `filter_pipe` 阶段对宇宙打 `$close/Ref($close,1)`。为「少维护一个字段」改回价格模式，等于在 handler_init 再买一轮 `D.features` 风暴。
- **提案**（纪律级）：后续 eng-perf 施工单显式否决上述四条。允许的替代仅：卡 1 入口钉 1、卡 2 三钮分账、卡 3 点查合并 + 差量补足、卡 4 调用谱后预载、#43 pickle handler-cache。
- **收益（砍哪段墙钟）**：无直接加速；防止 #40/#43 红利被「统一/省略/抄作业」回吐，避免假 HIT 与特征漂移。
- **成本与风险**：无代码成本。需 host 在 R2 收敛表引用本卡挡枪。
- **冻结检查**：声称 eng-perf 的 PR 若（a）省略 `kernels=`、（b）改训练 Quantile 表达式、（c）把 limit-up 改回价格模式、（d）改 dump/kernels/threads 中超过一钮——必须挂本卡否决标签，改走收益册或附 Win 税表。
- **对抗预填**：「省略参数更干净」；「训练 Quantile 也很慢，过滤都跳过了」；「$zhangting 偶发与涨幅不一致，改回现场算更正确」——正确性归收益册/数据质量，不归 eng-perf 顺手改。
- **建议裁决**：**否决**（对上述四条路径本身）；对策见卡 1–4
- **重提条件**：训练 Quantile 的替代实现须单独走特征 PR（chip-parity + 第三窗），不得叫 eng-perf；`$zhangting` vs 涨幅不一致须数据修复，不得用价格模式「顺便」重算当加速。

---

## R2-live 自检摘要

| # | 方向 | 建议裁决 | 相对 R1 的增量 |
|---|------|----------|----------------|
| 1 | a | 采纳 | 漏网入口不传 `kernels` ≠ 已钉 1；清单门禁 |
| 2 | a | 裁剪后采纳 | kernels / dump workers / LGB threads 三钮 + Redis 非必需 |
| 3 | c | 采纳 | 「极致性能」双单日相对 old 区间查询是负优化；补足 1000:2000；语义钉现行点查 |
| 4 | c | 裁剪后采纳 | 10 步采样掩盖热点；exchange 逐股 quote 才是 #40 后残余候选 |
| 5 | a+c/g | 否决（坏路径） | 漏传 / 混钮 / 训练 Quantile / 价格模式四条变体 |

不改 topk、不关四开关、不跑长实验。墙钟定案仍须 Win 宿主；本文件只出卡。
