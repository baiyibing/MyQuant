# 三仓协同路线图：信号厂 → 规则回测 → 执行栈

- 日期：2026-09-12
- 状态：v1.2。近期项已拍板；中远期为方向性共识，进入阶段时再细化。里程碑表当预期，不当承诺维护。长期保鲜的是 §1 定位、§2 决定、§6 负面清单，以及以后的两篇契约。
- 涉及仓库：MyQuant（本仓）/ MyQuant-backtrader / OSkhQuant1.3
- 上游输入：2026-09-11~12 三仓架构讨论；本仓走查见 `my_docs/qlib_backtest_walkthrough_results.md`
- 文档分放：计划进 `docs/`，笔记留 `my_docs/`。不合并。

v1.2 相对 v1.1：名单多源（Qlib 不是唯一选股来源；技术分析出名单住 backtrader 仓）；弃用 Qlib PortAnaRecord 与 Cerebro/Backtrader 框架（不是弃用 MyQuant 仓或 MyQuant-backtrader 仓）；成交只保留向量化 + LEBS + MockQMT。
v1.1 相对 v1：补三仓对照（含「不该再做」）、研究两层、Qlib 降成选股器、共享面收窄、R0 三条硬约束；§7 里程碑改名，避免和中期 M1–M5 撞号。

---

## 1. 定位（不变项）

三仓不是同一条回测链的三个入口，是一条流水线的三段。昨晚按两仓说时漏了 MyQuant；「backtrader 仓 = Qlib 那一层」不准确——Qlib 在本仓，backtrader 仓是规则 + 分钟向量化。两层都叫研究，问题不同。

**仓名 ≠ 引擎。** 「弃用 backtrader」指 Cerebro / vendor Backtrader 框架，不是弃用 MyQuant-backtrader 这个仓库。该仓留下的是向量化引擎，以及技术分析选股（筹码、换手阻力、手工/规则名单）。

| | MyQuant | MyQuant-backtrader | OSkhQuant1.3 |
|---|---|---|---|
| 问的问题 | 模型每天该买哪些（排序/打分） | ① 技术分析谁进名单 ② 给定日名单，按规则怎么成交 | 同一套决策核过 Paper / MockQMT / 真栈会怎样 |
| 留下的引擎 | 无成交回测。训练 + IC + 导出日 CSV | 向量化：6/8 策略书 + 7 的 simulate_v7 | LEBS（bar 环 + MockQMT）+ true-stack |
| 弃用的回测 | Qlib PortAnaRecord / Exchange（不再当产品） | Cerebro / Rolling / vendor Backtrader（对照化石，不接新策略） | 第一方 Cerebro 已拆，保持 |
| 数据 | 自有 Qlib bin（`~/.qlib/...` 或仓内 `.qlib/qlib_data/cn_data`）；dump_bin 可吃 CSV/parquet | F 湖 parquet，只读 | 写湖 + 交易栈 |
| 名单（多源，同一契约） | Qlib pred → 日 CSV（来源之一） | 技术分析 / chip / TR / 手工 CSV（来源之二及以后）；消费侧统一 `parse_pool_csv` | 海龟只认 stock_pool_turtle/；CSV 研究认 stock_pool/ |
| 不该再做 | 分钟触价、T+1 抠成交、接 QMT；加强 Qlib 回测；把 6/7/8 写成 Qlib Strategy | 复刻 Redis / live、再造 LEBS；用 simulate_v7 跑 Alpha158；新策略写进 Cerebro | 接回 Cerebro、在 LEBS 里重写 6/8/7 |

走查里过滤器没接到训练/回测、pred 和成交日可能错位，是 Qlib 日频组合的问题，不是 6/8/7 或 LEBS 的问题。

行业惯例对照（我们踩的就是这套，不再重开）：

| 行业概念 | 业界做法 | 三仓对应 |
|---|---|---|
| 信号/执行解耦 | 多名单源，执行系统负责成交 | Qlib 与 backtrader 仓技术分析都出 CSV；成交只走向量化 / LEBS / MockQMT |
| 仿真保真度阶梯 | 向量化 → 事件驱动 → paper → live | 6/8/7 → LEBS → MockQMT |
| intended vs realized 对账 | 净值不逐级对齐，只在决策粒度对账 | 比名单、reason、可卖、涨跌停 |
| 数据契约当 API | 跨系统只共享 schema + 完整性门禁 | CSV 名单 + F 湖，就两个接口 |
| feature store / training-serving skew | 特征一份定义 + parity test | 筹码因子三处实现是风险点 |
| 实验可复现 | run manifest | timing JSON + backtest_output 是雏形 |

六条原则：

1. 只共享规则和数据契约，不共享引擎。不合仓。
2. 成交回测只保留三件：backtrader 仓向量化、1.3 LEBS、1.3 MockQMT 真栈。Qlib PortAnaRecord 与 Cerebro/Backtrader 框架弃用（不当产品，不加强，不接新策略）。Qlib 留下训练和导出名单。
3. 对账只比名单、reason、可卖股、涨跌停。不要拿已弃用的 Qlib / Cerebro 净值和向量化、MockQMT 拧成一个数。
4. 跨仓接口只有两个：CSV 名单、F 湖。各自一篇短契约文档。名单多源：Qlib 是来源之一，不是唯一。
5. 研究分两层：本仓管因子/模型/打分；backtrader 仓管技术分析选股 + 名单后的向量化成交。不要把 Qlib 搬进 backtrader 仓，也不要用 Cerebro 跑新名单。
6. 共享面收窄。日历、代码后缀、涨跌停：backtrader 仓和 1.3 对齐（parse_pool_csv / canonical_from_bare_code）。本仓继续用 Qlib REG_CN 和 SZ300190 方言；不要把 PMC / csv_pool 塞进 Qlib Exchange。数据是唯一值得跨三仓谈的契约——bin 是 F 湖衍生品，不是第二套行情（目标态，M1 落地后成立）。

晋升门（要上 Paper 才走完）。名单先汇流，再成交：

```
名单源 A  MyQuant / Qlib     模型打分 → 日 CSV
名单源 B  MyQuant-backtrader 技术分析 / chip / TR / 手工
              ↓  同一契约（YYYYMMDD.csv，裸六位码）
MyQuant-backtrader
  向量化锁规则（6/8 策略书；7 是金榕元仓位机，只吃海龟池）
       ↓  要上 Paper 才走
1.3 trade_decision 纯函数 → LEBS 扫描 → MockQMT 真栈
```

已弃用、不再进入这条链：Qlib PortAnaRecord、Cerebro / Rolling。

### 1.1 Qlib：降成选股器，不加强回测

Qlib 弱的是 A 股成交，不是策略种类不够。它的产品就是日频排序选股：按 pred 取 TopK、丢掉持有最久的 N 只、按开盘/收盘调仓、出 IC / 换手 / 超额。TopkDropout 就是这个形态。

| 问题 | 放哪 | 策略长什么样 |
|---|---|---|
| 模型觉得哪只该进池 | 本仓 / Qlib | TopN（或打分后的日名单） |
| 技术分析谁进名单 | MyQuant-backtrader（chip / TR / 规则） | 日 CSV，与 Qlib 同一契约 |
| 名单进来后怎么买卖 | MyQuant-backtrader 向量化 | 6/8 策略书；7 独立仓位机 |
| 过不下单栈会怎样 | 1.3 LEBS / MockQMT | trade_decision + 报单回报 |

「策略只有 TopN」只在第一层成立。海龟、隔夜、尾盘均分本来就不该写成 Qlib Strategy。本仓已经试过往里加（TopkDropoutStrategyWithFilter、AvoidLimitUpStrategy、KDJStrategy）；继续在 generate_trade_decision 里补规则，是在日频组合器上仿交易系统，补不完。

**Qlib 停在信号，回测弃用。** 训练 → pred.pkl → IC/IR → 日 CSV。PortAnaRecord / Exchange 不再当产品（16 交易日 −12.75% 只是历史烟雾，见 `my_scripts/position_analysis.txt`）。IC 可以留作模型体检，不当成交真相。有价值的产物是日名单。

Qlib 里只变怎么排序、怎么出名单，不变成交：行业/市值中性后再取 TopN；换 topk / n_drop / 持有天数；筹码、换手阻力当特征；涨停从训练集剔除。路径依赖（试仓、加仓、5 日计时）一律出 Qlib，走向量化或 1.3。

---

## 2. 已拍板的六个决定（2026-09-12）

1. **MyQuant 定位 = 信号厂之一**（不是独立回测家，也不是学习化石）。IC 研究照做，产物规格先定死：模型哪天配得上，哪天就接得上流水线。timing 实测（handler_init ~907s、model_fit ~5.6s）表明本仓天然是批处理形态，产品就是日名单。
2. **名单多源，同一契约。** Qlib 不是唯一选股来源。技术分析（筹码过滤、换手阻力、规则/手工名单）住 MyQuant-backtrader，写出同一套 YYYYMMDD.csv。下游只认契约，不认来源。
3. **成交回测只留三件：向量化、LEBS、MockQMT。** Qlib PortAnaRecord 弃用；Cerebro / vendor Backtrader 弃用（化石对照，不接新策略）。「弃用 backtrader」不是弃用 MyQuant-backtrader 仓。
4. **名单 as-of 语义**：文件名 = 买入日 T；Qlib 源内容来自 pred(T−1)。技术分析源按各自计算日写入同一文件名语义。下游 6/8「当天读当天文件」，零歧义。走查里 pred/成交日错位的根因就是这里从未定义。
5. **筹码 SSOT 政策**：研究期允许三处各写（本仓 COST/KDJ、backtrader 仓 qlib_cost / 换手阻力）。名字像，实现不是一份。晋升门 = golden-value parity test（同一根 bar，两仓输出在容差内一致才过门）。现在不统一。
6. **计划与笔记分开放**：本文件在 `docs/`；走查、学习笔记留 `my_docs/`。

---

## 3. 近期（约两周）：契约落地 + 信号厂最小闭环

目标一句话：**让「pred → 日名单 CSV → backtrader 仓 6/8 向量化回测」第一次跑通。**

| # | 任务 | 仓 | 交付物 | 验收 |
|---|---|---|---|---|
| R0 | 贯通弹（先于一切工程投入） | 两仓 | 一次性脚本把 `my_scripts/position_analysis.txt` 有持仓的交易日转成 YYYYMMDD.csv（SZ300190→300190），写入独立目录，喂 6/8 **日线**策略书 | 管道走通：能被 parse_pool_csv 吃下、湖能读到、出 summary.txt。不看赚亏，不当 M5 |
| R1 | 名单契约 v1 | backtrader 仓（canonical，挨着 parse_pool_csv）；本仓 docs/ 链接 | 30 行契约：格式（YYYYMMDD.csv、首列裸 6 位码、可带名称列、utf-8-sig、可有表头）+ as-of 语义 + 方言链；空文件 / 缺日 = 当日不买 | 三仓 README 均链接 |
| R2 | 导出脚本 | MyQuant `my_scripts/export_daily_pool.py` | pred.pkl → 按日 TopN → YYYYMMDD.csv（Qlib SZ300190 → 裸 300190 在导出侧转换） | `my_tests/` 单测：无后缀、文件名=买入日、代码非空非 NaN |
| R3 | 修走查三问题 | MyQuant `my_scripts/custom_train_backtest.py` | ① 过滤器接入训练与回测 ② processor 传父类 ③ pred/成交日对齐（R2 落地即闭环） | 单测 + 走查复跑确认 |
| R4 | 文档修复 | backtrader 仓 | README「主入口 LEBS」腐烂句修正（LEBS 在 1.3）；三仓拓扑文档落其 docs/，MyQuant / 1.3 README 互链 | review 通过 |
| R5 | 首次闭环 | 两仓 | 用现有 alpha158_cost_kdj_lgb 模型出 2026-03-02~03-23 一窗名单（与 position_analysis.txt 同窗），喂 6/8 策略书跑向量化 | 出回测报告；名单文件过 R1 契约校验 |

### 3.1 R0 硬约束（比「持仓 ≈ pred 前十」更要紧）

`position_analysis.txt` 对得上：16 个交易日，2026-03-02～03-23，代码是 SZ300190 方言。贯通弹比 R2/R3 先做。下列三条写进验收，避免把管道实验读成模型结论：

1. **这是已实现持仓，不是当日新信号。** TopkDropout 会留仓，SZ300243、SH601020 能挂 6–9 天。喂给 6/8 等于「每天把还在账上的票再当买入名单」。只验证管道；「名单有没有价值」比中期 M5 还脏一档，不要拿这窗净值判断模型。
2. **首日是空仓。** 2026-03-02 持仓列表是空的。backtrader 仓 load_pool_days 空文件直接丢掉。不要为这天造空 CSV，也不要当成管道坏了。有持仓的约 15 天即可。
3. **R0 用日线，不要一上来分钟；不要喂策略 7。** 16 天 × 十来只，csv_daily + `--strategy version6`（再视情况加 version8）就能打穿：转码 → 契约格式 → 补后缀 → 读湖 → 落盘。分钟缓存若是冷的，一小时预算会先耗在 I/O 上。名单里有 BJ920014、688、301，正好打 canonical_from_bare_code 和涨跌停档。7 是金榕元仓位机，不是 TopN 日名单的下游。

导出目录用独立路径（例如本仓 `exports/r0_20260302_20260323/`），**不要写进** backtrader 仓 `stock_pool/`。那个目录是隔夜短线名单，和 Qlib 持仓不是一回事。

代码方言链（转换责任：导出侧管 Qlib 方言，下游 SSOT 已存在）：

```
Qlib SZ300190  →  CSV 裸 300190  →  湖分区 300190_SZ  →  交易层 300190.SZ
   (MyQuant)      (名单契约)        (F 湖)              (canonical_from_bare_code)
```

---

## 4. 中期（1~2 个月）：数据契约 + 防 skew + 名单质量

| # | 任务 | 说明 |
|---|---|---|
| M1 | F 湖 → Qlib bin | `qlib_scripts/dump_bin.py` 走 parquet；bin 定性为**衍生品**（可从湖重建、不入库）；完整性检查对齐 backtrader 仓 oskh_data.integrity；刷新机制（手动/定时）进阶段时再定 |
| M2 | 筹码 parity test | 选一段 bar，本仓 COST 特征 vs backtrader 仓 qlib_cost 输出对齐（容差内）；作晋升门，不做日常 CI |
| M3 | 模型迭代（只动排序，不动成交） | 行业/市值中性化后取 TopN；topk / n_drop / 持有天数扫描；筹码、换手阻力当特征；涨停股剔出训练集 |
| M4 | run manifest 约定 | 把 timing_*.json 升级为标准 manifest（配置 hash、代码版本、产物指纹、耗时）；三仓同格式，结果可追溯 |
| M5 | 名单质量归因 | **严格导出的** Qlib 名单 vs 手工名单在同一 6/8 策略书下对照回测，隔离「名单本身的价值」。R0 持仓转名单不作此结论 |

---

## 5. 远期（季度级）：晋升链 + paper

| # | 任务 | 说明 |
|---|---|---|
| L1 | 晋升门量化 | IC/IR 阈值、名单命中率（数值到时定）；达标才进 L2 |
| L2 | 1.3 对接 | 名单 → trade_decision 纯函数 → LEBS 扫描 → MockQMT paper |
| L3 | 对账自动化 | intended vs realized 日报：名单、reason、可卖、涨跌停差异；不做净值逐级对齐 |
| L4 | 真栈 | 视 paper 结果单独评审，本计划不承诺 |

---

## 6. 负面清单（明确不做）

- 不把 6/7/8 写成 Qlib BaseStrategy；不在 Qlib Exchange 里补分钟、T+1、涨停排队；不把 PortAnaRecord 当产品或对照基准
- 不把 Qlib D.calendar 当三仓交易日 SSOT（本仓内部用 REG_CN 无妨）
- 不把 PMC / csv_pool 塞进 Qlib Exchange
- 不合仓、不共享引擎；不把 Qlib 搬进 backtrader 仓
- 不为「策略更丰富」造第四套引擎；新策略不进 Cerebro / Rolling
- 路径依赖类规则（试仓、加仓、计时）一律出 Qlib，走向量化或 1.3
- R0 不写进 stock_pool/；不喂策略 7；不用 R0 窗净值判断模型
- 1.3：不接回 Cerebro；不在 LEBS 里重写 6/8/7；LEBS 不承诺和实盘 parity
- 技术分析选股的新代码住 MyQuant-backtrader，不在 MyQuant 里用 Qlib 策略仿一套

---

## 7. 阶段预期（不当排期承诺）

编号不用 M1–M4，避免和 §4 中期任务撞名。到阶段再细化，否则会腐烂成 backtrader 仓 README「主入口 LEBS」那类句子。

| 阶段 | 内容 | 怎样算过 | 依赖 |
|---|---|---|---|
| 当天起 | R0 贯通弹；随后 R1–R4 | 日线管道先跑通一次；契约与文档合入，单测绿 | 无 |
| 约两周 | R5 首次闭环 | 回测报告 + 契约校验通过 | R0–R4 |
| 约 1 个月 | 中期 M1、M4 | bin 可从湖重建；manifest 落地 | R5 |
| 约 2 个月 | 中期 M2、M5 | parity test 有结论；名单归因报告（非 R0 持仓） | 上一阶段 |
| 季度级 | 远期 L1–L3 | paper 跑起来，对账日报 | 上一阶段 |

建议先 commit 本文件，再跑 R0。plan 和回测数字分开：R0 的 CSV / summary.txt 另记。

---

## 8. 风险与未决

- **as-of 假设待实测**：R2 动手前先确认 Qlib pred 的 label 期（例如 close 的 Ref 平移）与「文件名=买入日」的假设一致，不一致以实测为准修契约，不硬套。
- IC 阈值、bin 刷新机制：中期 M3 / 远期 L1 前再定。
- 三仓净值差异属预期；任何时候不因「对不上」回退到统一引擎。
- backtrader 仓仍待做、且不在本仓实施：市场层抽薄（不抽撮合）、1/2/5 做成 6/8 策略书、Cerebro 当对照化石。与本路线图并行，不阻塞 R0。
