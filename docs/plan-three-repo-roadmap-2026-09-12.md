# 三仓协同路线图：信号厂 → 规则回测 → 执行栈

- 日期：2026-09-12（v1.3 回写 2026-09-13；§0.2 补 M4/M3-A/M2/M3-B/C/D + 宿主真跑结果）
- 状态：**v1.3**。近期 R0–R5 与首轮 M5 已落地；中远期仍为方向性共识。里程碑表当预期，不当承诺维护。长期保鲜的是 §1 定位、§2 决定、§6 负面清单，以及名单/F 湖两篇契约。
- 涉及仓库：MyQuant（本仓）/ MyQuant-backtrader / OSkhQuant1.3
- 上游输入：2026-09-11~12 三仓架构讨论；本仓走查见 `my_docs/qlib_backtest_walkthrough_results.md`
- 文档分放：计划进 `docs/`，笔记留 `my_docs/`。不合并。

v1.3 相对 v1.2：把 2026-09-12~13 已合入的管道、训练厂、名单归因和 1.3 执行栈进展写回 §0 / §3 / §4 / §7 / §8。§1–§2–§6 决定不改。
v1.2 相对 v1.1：名单多源（Qlib 不是唯一选股来源；技术分析出名单住 backtrader 仓）；弃用 Qlib PortAnaRecord 与 Cerebro/Backtrader 框架（不是弃用 MyQuant 仓或 MyQuant-backtrader 仓）；成交只保留向量化 + LEBS + MockQMT。
v1.1 相对 v1：补三仓对照（含「不该再做」）、研究两层、Qlib 降成选股器、共享面收窄、R0 三条硬约束；§7 里程碑改名，避免和中期 M1–M5 撞号。

---

## 0. 2026-09-13 进度回写（新功能 / 已落地）

只记已经合入或本机验收过的能力。PR 号：MyQuant `baiyibing/MyQuant`，backtrader `baiyibing/MyQuant-backtrader`，1.3 用其仓内编号。2026-09-13 宿主真跑：M3-A/B/C 数字与两起事故（DropLimitUpLearn module_path / mlflow 逃生口 + manifest 中途切分支）见 §0.2；事故随 followups 任务 1/2 根治。

### 0.1 MyQuant-backtrader（研究脸：名单契约 + 向量化成交）

| 能力 | 状态 | 落点 |
|------|------|------|
| 策略 1–8 共用向量化引擎；6/8 策略书；7 独立海龟仓位机 | 已合 | #11–#17；`csv_strategy_books` / `csv_minute_backtest_v7` |
| A 股成交核：全卖因跌停 defer、板档 10/20/30 + ST 名 5%、Decimal 涨跌停价、停牌净值 last close | 已合 | #18；`engine-ashare-correctness.md` E-R1–E-R4 |
| ST 名称按日 as-of（`ymd<=ds`，禁止看未来） | 已合 | #21 P-R2 |
| 加载侧丢 `volume==0` 占位 K（≡ 缺 K） | 已合 | #21 P-R3 |
| 名单契约 + `validate_pool_dir`（严格六位门） | 已合 | #21；`pool-csv-contract.md` |
| R0 持仓 → 独立 `exports/r0_*`（忽略 `日期范围:`） | 已合 | #21 / #23；不写 `stock_pool/`，不喂 7 |
| R2/R5 消费：`--pool-dir` + 无湖 fixture 回路 | 已合 | #24 |
| `csv_daily --out-dir`；手工池截断 TopN | 已合 | #27 |
| 三引擎定位 / README 不再写「主入口 LEBS」 | 已合 | #15 / U1；即原 R4 |
| 首轮 M5：同一 version6 书比 pred Top10 / 手工原样 / 手工 Top10 | 本机 C 齐；报告 [#28](https://github.com/baiyibing/MyQuant-backtrader/pull/28) | 结论：**名单几乎不重叠**（pred∩hand10 = 15/15 空）。不是模型晋升 |

### 0.2 MyQuant（信号厂）

| 能力 | 状态 | 落点 |
|------|------|------|
| `--asof pred_minus_one`（文件名=买入日 T，内容=pred[T−1]） | 已合 | #2；`my_docs/pred_asof_r2_2026-09-12.md` |
| `export_daily_pool.py`：pred → 日 TopN 裸六位 CSV；Windows 锁 LF | 已合 | #2 / #4 |
| processors 传入 `Alpha158`/`DataHandlerLP` 父类 | 已合 | #3 slice A |
| `D.instruments(..., filter_pipe=[exclude, $zhangting])`；默认不建第二 handler | 已合 | #3 slice B/C |
| `benchmark = SH000300` | 已合 | #3 slice D |
| pred vs PortAna report 对齐自检 | 已合 | #5；第 4 轮重训 16 日对齐 0 缺日 |
| R3 后新 `预测结果.csv`（约 8.4 万行 / 16 日，过滤后少于 pre-R3） | 本机 2026-09-12 23:45 | 不入库 |
| F 湖指数 → qlib bin 修补（000300/000001；指数不进 `all.txt`） | 脚本 [#6](https://github.com/baiyibing/MyQuant/pull/6)（当时未合）+ 本机已跑通 | **不是**完整 M1 |
| M1-A `refresh_mydata.py` 骨架 + `--dry-run`（三件套子进程编排；`max_workers=8`；禁 dump_update） | 已合 | [#8](https://github.com/baiyibing/MyQuant/pull/8)；中期计划 §1 |
| M1-B 原子 swap + 四门禁（日历/抽样/无指数/宇宙 diff；失败不换目录） | 已合 | #8 |
| M1-C `--archive` / `--offsite`（7z + MD5；路径可配，缺 F/G 不挡 PR） | 已合 | #8 |
| M1-D 文档：`qlib-data-state` 标准刷新=orchestrator；提示词指向它 | 已合 | #8；**M1 轨道完成** |
| M4-A `run_manifest.py`（myquant.run-manifest/1 构建/校验/写盘） | 本分支已提交 | 中期计划 §2 |
| M4-B 训练收尾写 train manifest（helper 可单测；VM 跳过 18min 重训） | 本分支已提交 | 中期计划 §2；宿主机合批验收 |
| M3-A learn-only `DropLimitUpLearn`（infer/导出池 as-of 不动） | **宿主真跑** | IC **0.0183**（持平）/ RankIC **0.0048**（基线 3.4×）；**首个真 train manifest**；代码已合 #9 |
| M4-C 导出写 export manifest + `docs/run-manifest-spec.md` | 本分支已提交 | 中期计划 §2；BT 仓后续对齐用 |
| M2-A 筹码概念映射 `docs/chip-parity-map.md`（结论：不可比） | 本分支已提交 | 中期计划 §3；合法关门 |
| M2-B `chip_parity_check.py` + 注入 fake bt 单测；live 报 not comparable | 本分支已提交 | 中期计划 §3；fixture-only |
| M2-C 晋升门 + `chip-parity-report-2026-09-13.md`（closed as 不可比） | 本分支已提交 | 中期计划 §3；**M2 轨道完成** |
| M3-B ranking sweep harness + 宿主 6 格真网格 | **宿主真跑** | 代码 #11/#12；6 格：`topk5_ndrop2` 双指标最佳（hit **0.5625** / ann **2.65**）；`topk10` 两指标皆最差；**16 日单窗线索**；共享一次 handler_init |
| M3-B OOS 出窗复验（2026-04~08，104 交易日；--segments 参数化 #15/#16） | **宿主真跑** | **三月冠军 `topk5_ndrop2` 出窗垫底（hit 0.4712 / 年化 −0.39）= 窗口依赖出局**；两窗 IR 同正者仅 ndrop3 大名单族（topk20_ndrop3 / topk10_ndrop3），无一配置两窗同排序；按预锁纪律**不改线上 topk 默认**（改参需第三窗佐证） |
| M3-C bin-16 特征实验（换手/阻力近似） | **负结果（宿主真筛）** | 代码 #11/#12；`turnover_resist_approx` 三月 **+0.138** → 六至八月 **−0.069** 符号翻转；四候选不入选 |
| M3-D 行业/市值中性化 | **源就绪（实现片待开）** | gildata 申万 L1 全量 5210 只映射入 git（`exports/m3d_industry/sw_l1_map.csv`，PR #19，.gitignore 例外）；wind 复核 35/53+ 批后 Kimi 5h 额度中断，续跑指引 `docs/kimi-wind-m3d-resume-2026-09-13.md`（PR #17），续跑点 q0035..q0053；`M3D_STATUS=ready`（Kimi 未提交遗作，随实现片一并提交） |
| 宿主事故根治（followups） | 已合 #14 | ① 共享 `host_env`（mlflow file-store 逃生口，告别每脚本一份） ② manifest `git_commit` 改为**启动时** HEAD + `git_branch`/`git_dirty`（中途切分支不再污染溯源） |
| Kimi 行业采集中断封存 | 已处理 | 现场 242 文件 / 2.3MB 入 git（PR #19）+ `m3d_industry_kimi_20260913.7z` 本地与 F: 备份；**续跑必须回 Kimi**（wind MCP 只在它那） |
| M5 二轮任务书 | 已派 | PR #18：六个月长窗（20260303~20260908）三源归因——Codex 出 `predict_extended.py`（不跑 PortAna），BT 仓跑三源对照；判读预锁（不据此改参；重叠度变化本身是结论） |
| CI 启用 | 进行中 | 仓转 public 后走 PR #20：windows-latest + py3.12 + qlib 钉 79633dd9 源码装 + 全量 pytest；首跑失败根因=`custom_utils` 顶层 matplotlib/seaborn 未进 requirements，已修重跑 |

PortAna 第 4 轮用真沪深300 出过烟雾报告。按 §2.3 / §6：**不当产品、不当 M5 对照列。**

### 0.3 OSkhQuant1.3（执行栈；不重写 6/8/7）

近期（2026-09-11~12）仍在交易栈，不接研究名单管道：

| 能力 | 状态 | 落点 |
|------|------|------|
| MockQMT / true-stack：海龟加仓 `max_units`、卖拒单节流、9-red 恢复 | 已合 | #992–#995 |
| executor 进程心跳 + 死亡告警 | 已合 | #986 |
| 日名单继续进本仓 `stock_pool/`（研究对照用，不是 Qlib TopN） | 例行 | 如 #989 |
| 全仓行业对齐重构方案 | 文档 | #996 v1.1；**GO 前禁编码** |
| 研究脸（向量化 / chip / L2 ETL） | 已迁出 | 2026-09 S1/S2 → MyQuant-backtrader |

1.3 的完成定义仍是 LEBS / MockQMT / 真栈，不是本路线图 R0–R5。L2（名单 → trade_decision → LEBS）未开工。

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

走查里过滤器没接到训练、processors 没进父类，已在 R3 修。pred 与本仓买入日的错位用 `--asof pred_minus_one` 锁死。剩下的是 Qlib 日频组合器本身弱成交，不是 6/8/7 或 LEBS 的问题。

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

目标一句话：**让「pred → 日名单 CSV → backtrader 仓 6/8 向量化回测」第一次跑通。** **v1.3：已跑通。**

| # | 任务 | 仓 | 状态 | 交付物 / 验收 |
|---|---|---|---|---|
| R0 | 贯通弹 | 两仓 | **✅** backtrader #21/#23 | `scripts/data/r0_positions_to_pool.py`；15 日 CSV；version6 `summary.txt`。不看赚亏 |
| R1 | 名单契约 v1 | backtrader canonical | **✅** #21（本仓 README 链契约）。1.3 / 本仓 README 互链仍欠，不阻塞 | `pool-csv-contract.md` + `validate_pool_dir` |
| R2 | 导出脚本 | MyQuant | **✅** #2/#4 | `export_daily_pool.py`；`--asof pred_minus_one`；LF |
| R3 | 修走查 | MyQuant | **✅** #3/#5；第 4 轮重训本机绿 | processors 进父类；`D.instruments`+`$zhangting`；SH000300；pred/report 对齐自检 |
| R4 | 文档修复 | backtrader | **✅** 主入口句 + 定位 SSOT。外仓互链仍欠 | `engine-positioning-ssot.md` |
| R5 | 首次闭环 | 两仓 | **✅** #24 + 本机真 pred/F 湖 | R3 后 pred TopN → validate → version6。管道验收，不当模型结论 |

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
| M1 | F 湖 → Qlib bin | **刷新管道已固化**（`refresh_mydata.py` A–D：dry-run / 四门禁+原子 swap / archive+offsite / 文档）。个股仍走 archive+CSV 拼接而非纯湖 7 列；定时刷新与 `oskh_data.integrity` 对齐仍后置 |
| M2 | 筹码 parity test | **已做（不可比关门）**。映射 + checker + 晋升门；无同构量，未强制数值对齐 |
| M3 | 模型迭代（只动排序，不动成交） | **部分**。M3-A 已合 #9；M3-B/C 本分支已交（sweep + bin-16 特征筛）；M3-D blocked（无行业源）。IC/IR 真重训与 live sweep 仍待宿主 |
| M4 | run manifest 约定 | **未做**。仍是 `timing_*.json` + `backtest_output` 雏形 |
| M5 | 名单质量归因 | **首轮已做**（2026-03 version6 三列）。结论「几乎不重叠」，禁止读成模型优于手工。R0 不作此结论。加长窗 / 冻结手工快照 / 同宇宙排序对比 = 下一轮，不重开成交核 |

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
| 当天起 | R0 贯通弹；随后 R1–R4 | **已过**（2026-09-12） | — |
| 约两周 | R5 首次闭环 | **已过**（#24 + 本机真窗） | R0–R4 |
| 约两周+ | 首轮 M5 | **已过**（工具 #27 + 本机三列；结论不重叠） | R3 后 pred |
| 下一步 | 中期 M1 收口、M4 | bin 可从湖重建个股+指数；manifest 落地 | R5 |
| 其后 | M2、M3、加长窗名单归因 | parity；只动排序；同宇宙再比 | M1 或现成特征 |
| 季度级 | 远期 L1–L3 | paper；1.3 接名单 | 上一阶段 |

plan 和回测数字分开：R0/R5/M5 的 CSV / `summary.txt` 不入库。数字见 backtrader `docs/backtest/m5-list-attribution-2026-03.md`。

---

## 8. 风险与未决

- **as-of**：已锁 `--asof=pred_minus_one`（Qlib `shift=1` + Alpha158 `Ref($close,-2)/Ref($close,-1)-1`）。第 4 轮 pred 与 PortAna report 同 16 日，那是 Qlib 自己的索引，**不要**据此改成本仓 identity 买入日。要改须改契约 + 本文件 §2.4。
- IC 阈值、bin 全量刷新：M3 / L1 / 收口后的 M1 再定。
- 三仓净值差异属预期；任何时候不因「对不上」回退到统一引擎。PortAna 烟雾 ≠ version6。
- v1.2 写的 backtrader「仍待做」三项 **已做完**（市场层 / 1–8 书 / Cerebro 化石门），不再当未决。
- 1.3 行业对齐方案（#996）与 MockQMT 海龟修补并行于本路线图，不替代 L2。
