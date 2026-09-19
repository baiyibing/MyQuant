# 2026-09-18 · annual-lift 下一刀（H52_DATA_INVALID 之后）

**性质**：只预注册一把刀、有序门和互斥终态标签。本轮**不实现、不导数、不计算 IC/RankIC、不重训、不跑 PortAna/BT、不改线上**。

**裁决**：选 **T5-DSTR1：固定 5 个市场交易日上限的连续下跌收盘 streak 截面秩**，只允许一列 `DOWNSTREAK5_RANK`。

**线上默认**：仍为 **10/3 LGB**；默认 pred 仍为 `8a061ea4`（recorder `8a061ea428e04bb3a199a485ade49d0e`），全程只读。

一句话刀法：**固定当前 label、`8a061ea4`、原 handler 宇宙和唯一的一周连续下跌状态，先检验“截至特征日连续下跌越久，下一持有期反转越强”是否在 2025/2026 对现有 score 有同向正的增量 RankIC；A 全过才允许只加 `DOWNSTREAK5_RANK` 一列重训，B 全过才允许做固定 10/3 的配对 PortAna，任一门失败即停。**

## 0. 上一刀结果与新刀一句话

T5-H52A1 已在 `newtest_4090` 收工，唯一官方终态为 **`H52_DATA_INVALID`**，停在优先级 1 覆盖率门；B/C 未跑，没有 Top10、B 门、C 门、PortAna 或新候选 recorder 数字。刀法尖是 PR #83 commit `6d6593f393cf4e62ee38f33db121a3ca5c3eabbf`，该 PR 仍 open 且不在本分支基线。

失败特征严格是 `HIGH252_PROX_RANK`：`close[t] / max(adj $close over market days t-251..t, including t)`，随后在冻结 handler 当日索引与有效 prox 的交集上对该比值做 `rank(method="average", pct=True)`，不取负；合法区间为 `0 < prox <= 1`，不截断。

H52 的共同样本覆盖率如下；分母是冻结 handler 中 score 有限的行：

| 窗 | 覆盖率 | 分子/分母 | 锁定门 |
|---|---:|---:|---:|
| 2025 | 91.02% | 1169512/1284876 | 低于 98% |
| 2026 | 88.30% | 810769/918193 | 低于 98% |

illegal closes 为 0/0；不完整 252 日窗口分别为 2025 的 114615 行和 2026 的 102055 行，这些缺失行全部属于 `incomplete_window`。公式与秩并没有坏：16 行抽样复算通过，3 日截面秩 `max_abs_diff=0`。sidecar SHA-256 为 `215c78b34c936457354f926ab46958666d874946ef9b13258d0ae745898a8acb`；calendar SHA-256 为 `9e07c43e1fcb0f8031c150712f9675dadb5392dfa4b40ed1cdc162075399cdc6`，对应 2020-01-02 至 2026-09-15 共 1626 个市场日。

因此 H52 的停止不是公式 bug 或实现错误，不能套用“修实现后按原协议复跑”。失败原因正是预注册的完整 252 日窗口排除了过多名字；协议已经说明覆盖不足即停，不能把失败改写为数据清洗任务。

数据门失败后虽计算了 partial RankIC，但它们**不是裁决**：2025 mean 为 -0.024097、2026 mean 为 +0.000370；2025 的 95% CI 为 [-0.039560, -0.007026]，2026 为 [-0.025080, +0.024624]。本页不使用这组两窗反号来挑新刀方向、缩短窗口或翻转 H52；H52 的官方停止仍只有覆盖率门。

**新刀一句话**：T5-DSTR1 不再问“离年度高点多远”，而只问一个离散路径问题——在最近一周内，截至今天连续出现了多少个负的 close-to-close 收益；若短期连续抛压存在过度反应，较长的下跌 streak 应对下一持有期收益给出正的条件反转信息。

## 1. 为什么只选 T5-DSTR1

### 1.1 唯一、冻结且可证伪的假设

对股票 `i`、特征日 `t`，只使用冻结 qlib provider 的后复权 `$close`。先计算最近 5 个市场日的 close-to-close 简单收益：

```text
r[i,d] = close[i,d] / close[i,prev_market_day(d)] - 1

downstreak5[i,t]
  = sum(k=1..5, product(j=0..k-1, 1[r[i,t-j] < 0]))

DOWNSTREAK5_RANK[i,t]
  = rank_pct_cross_section(downstreak5[i,t])
```

- `downstreak5` 只能取 `{0,1,2,3,4,5}`：从 `t` 向前数连续负收益的长度，上限固定为 5；收益等于 0 会打断 streak。
- 构造需要 `t-5..t` 共 6 个连续市场日的 close 全部有限且 `>0`。任一点不合格则该行缺失；禁止向更早日期扩窗、前向填充、把缺失/零收益当作负收益，或按个股上市长度改定义。
- 截面只在冻结 handler 当日索引与有效 `downstreak5` 的交集上，用 `pandas.Series.rank(method="average", pct=True)` 排一次。并列必须保留 average tie；不得用股票代码、随机数或 score 破 tie。
- 唯一方向是“`DOWNSTREAK5_RANK` 越高，下一持有期反转收益越高”。结果为负时不得现场翻成追跌势，结果不显著时不得改 3/10/20 日、改成上涨 streak、累计跌幅、阈值、分箱或交互。

5 是“一周内连续状态”的语义上限，不是根据 H52 覆盖率从 20/60/120/250/252 中挑出的短窗。本刀不计算窗口最高价、距高点、最大单日收益、波动率、市场 beta、成交冲击或筹码状态；也不把“更容易达到 98%”当作有效性证明。它仍须从自己的数据门开始，若覆盖不足就打 `DSTR_DATA_INVALID`，不得再缩成 3 日或放宽完整窗口。

当前 Alpha158/自定义列可能已经间接表达短期价格路径，本页不假定 streak 必然带来新信息。A 门先控制现有 score；若显式连续状态没有剩余条件信息，就以最低成本停止。即使 A 过，B 仍须证明一列离散状态能传入冻结模型，而不是用“树可以学非线性”替代证据。

### 1.2 H52 的数据失败为什么不给任何补救许可

`H52_DATA_INVALID` 不支持以下任何动作：

- 不把完整 252 日最高收盘价锚缩成 250/120/60/20 日；不改为 `min_periods`、可变窗或“上市以来”高点。覆盖失败是已冻结定义的停止线，不是以更多名字过门为目标的调参信号。
- 不把最高**收盘价**换成 `$high`，不截断 prox 到 `(0,1]`，不翻成距高点距离的秩，也不换 seed 或新树。
- 不把 H52 改成 MAXRET 式最大单日收益。年度价格水平之锚和单日收益极值是不同假设；MAXRET 路线也已经独立停止。
- 不写成“修实现并重跑同一把 H52”。公式抽样和截面秩复算均已通过，当前失败不是实现错误。

T5-DSTR1 的 5 日上限在研究问题上先验固定，只统计连续负收益的**符号路径**，不含任何高点或极值幅度。因此它不是 H52 的短窗版本，也不消费 H52 sidecar。H52 数据门后的 partial RankIC 两窗反号只保留为“计算了，但不是裁决”的审计事实；它没有参与 DSTR 的正向反转方向、窗口或成功门选择。

### 1.3 为什么也不重开其他死亡路线

| 已停止路线 | 已有终态 | T5-DSTR1 的严格边界 |
|---|---|---|
| DSEM | `DSEM_CONDITIONAL_NO_EDGE` | 不翻 `DSEM20_ANTI_RANK`，不改 20 日窗、分母或负收益平均法，不换 total/upside volatility 或 Sortino；DSTR 只数结尾处连续负号，不估半偏差或任何波动幅度 |
| BETA | `BETA_CONDITIONAL_FLIP` | 不翻 beta、不改 60 日窗/截距/收益定义/基准，不用 Alpha158 BETA60；DSTR 不读市场序列，不做回归、相关或协方差 |
| MAXRET | `MAXRET_MODEL_NO_TRANSFER` | 不翻 `MAXRET20_ANTI_RANK`，不改窗，不用 `$high`、top-3、隔夜/日内拆分；DSTR 不取最大收益、不比较收益幅度，也不以极端日阈值定义 streak |
| 固定 Amihud | `AMIHUD_CONDITIONAL_NO_EDGE` | 不改其窗口、方向、成交量/流通盘归一或变换；DSTR 不读 `$amount`、`$volume` 或成交冲击 |
| 精确 CYQ | `CYQ_CONDITIONAL_NO_EDGE` | 不重算 `winner_ratio`，不改 shares/window/threshold；DSTR 不读筹码分布 |
| winratio 残差 | `WINRATIO_GAP_MODEL_NO_TRANSFER` | 不读 `$winratio`，不换残差、平滑或 lag；DSTR 不使用跨源筹码差 |
| label / horizon | `LABEL_HORIZON_FLIP` | 当前 label 原样冻结，不试任何新 horizon |
| `score<=0` 卖出 | `SCORE_EXIT_FLIP` | 不改卖出、trail、止盈、止损、宽度、`n_drop` 或执行阈值 |

同时继续禁止 2026 扫闸、止损、trail、止盈、宽度或 `n_drop`，以及换树、月滚、per-fold scaler、20/3、把 15% 关闸升为默认、大 handler 重建和用 50/5 研究账改线上 10/3。DSTR 是新的单列条件信息假设，不是上述任何路线的补救；任一门失败后也不得把这些路线接在后面。

## 2. 冻结表

| 层 | 锁定值 / 禁令 |
|---|---|
| 当前 label | 只用 `Ref($close,-2)/Ref($close,-1)-1`；禁止换 label 或 horizon |
| 基线 pred | `8a061ea428e04bb3a199a485ade49d0e`；2026 `pred.pkl` 与 2025 同模型补分 CSV 只读，不覆盖、不回写；不读写 `55c5bf77` |
| 唯一候选 | `DOWNSTREAK5_RANK`，严格按 §1.1 构造；禁止改上限、收益符号、方向、变换、阈值、lag、交互或 seed |
| 原始数据 | 只读与 `8a061ea4` 一致的冻结 qlib provider 快照及 `$close`；记录 provider 路径、快照指纹、交易日历指纹和代码 commit；A 后不得刷新数据 |
| 构造时点 | 特征日 `t` 只使用 `t` 及以前的数据；固定 6 个 close 产生 5 个收益，不扩窗、不填补、不使用 `t+1` 数据 |
| 构造宇宙 | 先按冻结市场日历逐股票计算 `downstreak5`，再只在 `alpha158_cost_kdj_lgb / 8a061ea4` 冻结 handler 的当日索引与有效值交集上排一次截面秩；不得先在另一市场池 rank 再切 handler |
| 唯一 sidecar | 一次性导出覆盖 train/valid/test 的不可变 sidecar，至少保留 `(instrument, datetime)`、6 个 close 的日期与有效性、5 个收益的负号位图、`downstreak5`、`DOWNSTREAK5_RANK` 与缺失原因；写 SHA-256 和行键摘要。A 只切片，B 只左连这一份，C 只认 B recorder 血缘中的同一 SHA-256 |
| 两窗 | A/B/C 统一为 2025 valid `2025-01-03~2025-12-31`、2026 OOS `2026-01-01~2026-09-14`；两窗均已被研究，不包装为新盲窗 |
| 训练 | A 全过后才可复制 `8a061ea4` 的 LGB 配置；唯一差异是向原 handler 帧左连一列 `DOWNSTREAK5_RANK`；train 2020-2024、valid 2025、test 2026，seed、超参、早停、scaler、训练宇宙全冻结，涨停出池开、`DropLimitUpLearn` 关 |
| 组合 | B 全过后才可做 paired PortAna；只有 10/3，`hold_thresh=1`、top/bottom；buy-state、ST、年龄、5 日 15% 全关，止损、trail、止盈全关 |
| 尺子 | qlib `$close` 后复权 bin；买 5bp / 卖 15bp / 最低 5；拒单 0.095、不追买、整手向下；本金 1e8、`risk_degree=0.95`、基准 SH000300 |
| 禁止项 | 不扫任何参数或特征；不换树、月滚、per-fold scaler、20/3、50/5 PortAna、15% 关闸默认或大 handler 重建；不把 H52、DSEM、BETA、MAXRET、Amihud、CYQ、winratio 中间产物并入本刀 |
| 线上 | 全程仍为 `8a061ea4` + 10/3；即使全链成功也只得到候选标签，不自动替换 pred、特征或线上参数 |

## 3. A/B/C 有序门

### 3.1 A 门：跨窗条件信息门；禁止重训与 PortAna

先从冻结 provider 快照一次性构造唯一 sidecar。导出器可为 2020 起始日只读恰好 5 个前置市场交易日用于热身，但只输出冻结 handler 键；不得读取 label，也不得在 A 通过后重算历史。

数据门：

- 每个 `(instrument, datetime)` 的 6 个 close 日期、5 个收益符号、streak 递推、取值范围和截面成员必须可复算；`downstreak5` 必须是 `{0,1,2,3,4,5}` 中的整数，`DOWNSTREAK5_RANK` 的有限值必须落在 `(0,1]`。
- sidecar 必须通过列集、唯一键、日期范围、provider/日历/sidecar hash、行键摘要、抽样复算和时点检查。A/B 重叠键上的 `DOWNSTREAK5_RANK` 必须逐值一致。
- 2025、2026 的共同样本覆盖率均须 `>=98%`。分母是冻结 handler 当日 score 有限的行；分子是其中 score、当前 label 与候选列均有限的行。另报 close 非法、6-close 窗口不完整和其他缺失原因；覆盖不足即 `DSTR_DATA_INVALID`，不得缩窗、扩窗或填值。
- feature day `t` 与 score/label 按同一 `(instrument, datetime)` 键对齐；禁止 `pred_minus_one`、成交日偏移或使用 `t+1` 数据。

信息量定义：每个特征日，在 score、label、`DOWNSTREAK5_RANK` 均有限且 `n>=4` 的共同样本上，令 `s=rank_pct(score)`、`d=DOWNSTREAK5_RANK`、`y=rank_pct(label)`；分别做 `d ~ 1+s` 与 `y ~ 1+s`，取两组残差的 Pearson 相关，定义当日 **DSTR partial RankIC**。残差化只用于信息门；候选训练列仍只能是 sidecar 中的 `DOWNSTREAK5_RANK`，不得另造“DSTR 对 score 残差”训练列。

每窗报告 mean、median、ICIR、有效/退化日数与原因、共同股票数中位数及覆盖率；2026 按自然季度报告 mean DSTR partial RankIC。对逐日 IC 做 5 交易日 moving-block bootstrap，固定 10,000 次、seed `20260918`，报告 95% CI。

**A 门全过条件**：数据门通过；2025、2026 mean DSTR partial RankIC 均 `>0`；2026 的 95% CI 下界 `>0`；2026 不得多数季度为负，也不得只靠一个季度为正。未全过立即按 §4 裁决，B/C 取消。

### 3.2 B 门：只加一列重训，再做模型信号门

A 全过后才允许建立一个新 recorder：

- 对照仍是现成 `8a061ea4`，不得重训或覆盖。
- 候选只复制其冻结训练配置，在现成 handler 帧按 `(instrument, datetime)` 左连同一 sidecar 的 `DOWNSTREAK5_RANK`；不得同时加入 raw `downstreak5`、上涨 streak、累计跌幅、缺失指示、其他上限或任何死亡路线特征。
- 少量缺失只沿用现网的 `RobustZScoreNorm` 后 `Fillna(0)` 链，不得删股票、换宇宙或另拟 scaler。
- 只导出候选 2025 valid 和 2026 test 分数到新目录。在两窗共同样本上，以当前 label 比较候选与基线的日 RankIC、Top10Spread 和 `ΔRankIC` 的同口径 bootstrap CI。Top10Spread 固定为等权 Top10 减共同宇宙等权，禁止换成 Top10-Bottom10；此时仍不得跑组合。

**B 门全过条件**：候选在 2025、2026 均同时满足 `RankIC(candidate)>RankIC(8a)` 与 `Top10Spread(candidate)>Top10Spread(8a)`；2026 `ΔRankIC` 的 95% CI 下界 `>0`；2026 不得多数季度为负或单季驱动。未全过立即停止，C 取消。

### 3.3 C 门：最后才做固定 10/3 paired PortAna

B 全过后，才允许对基线 pred 与候选 pred 做两窗配对 PortAna：

- 两臂唯一上游差异必须是 `DOWNSTREAK5_RANK` 一列；输入 hash、组合、成交、费用、闸和窗口全部冻结。
- C 使用各臂全宇宙 pred，不用 A/B 的共同有限样本重定义组合宇宙。
- 每窗报告末值、区间收益、扣费年化超额、最大回撤、换手与费用；报告 2026 自然季度 `ΔNetReturn`，并对 2026 配对日收益差做同样 5 日、10,000 次、seed `20260918` 的 bootstrap CI。

**C 门全过条件**：2025、2026 均 `ΔNetReturn>0` 且扣费年化超额排序候选高于基线；2026 `ΔNetReturn` 的 95% CI 下界 `>0`；2026 `majority_negative=false` 且 `single_quarter_driven=false`。

三门的 2026 季度口径统一：保留截至 9 月 14 日的不完整 Q3；`majority_negative = 负增量季度数 / 季度数 > 50%`；`single_quarter_driven = 全窗增量 > 0 且正增量季度数 <= 1`。A 的增量是 DSTR partial RankIC，B 是候选减基线的 RankIC/Top10Spread，C 是 locked-cost `ΔNetReturn`，不得混写。

## 4. 成功标签 / 失败瀑布

一次合规执行最终必须且只能产生下表中的**一个**终态标签。A/B 的通过只记 gate boolean，不另打中间成功标签；裁决按优先级自上而下，命中即停止，所以成功标签与所有失败标签互斥。

| 优先级 | 唯一终态标签 | 命中条件 | 停手动作 |
|---:|---|---|---|
| 1 | `DSTR_DATA_INVALID` | 任一数据、时点、覆盖、公式复算、hash、行键或配置隔离门失败 | 停；不得缩成 3 日、放宽完整窗、填值或改 streak 定义 |
| 2 | `DSTR_CONDITIONAL_FLIP` | A 中 2025/2026 mean partial RankIC 反号，或 2026 多数季度为负 | 停；不翻方向、不改成上涨 streak、不挑季度 |
| 3 | `DSTR_CONDITIONAL_NO_EDGE` | 未命中 1/2，但任一窗均值 `<=0`、2026 CI 下界 `<=0`、单季驱动或任一 A 信息门不过 | 停；不改上限、收益符号、变换或阈值 |
| 4 | `DSTR_MODEL_NO_TRANSFER` | A 过而 B 任一窗 RankIC/Top10Spread 不同时胜基线，或 2026 CI/季度门不过 | 停；不加 raw streak、第二列、交互、异 seed 或新树 |
| 5 | `DSTR_PORTANA_FLIP` | A/B 过而 C 的两窗 locked-cost `ΔNetReturn` 反号，或 2026 多数季度为负 | 停；不改 10/3、成本、闸、卖出或窗口 |
| 6 | `DSTR_PORTANA_NO_EDGE` | 未命中 1-5，但 C 的 2026 CI 下界 `<=0`、单季驱动或任一 C 门不过 | 停；不转扫宽度、`n_drop`、阈值或 50/5 |
| 7 | `DSTR_FEATURE_CANDIDATE` | A、B、C 全部通过 | 只登记候选；不自动改线上，是否需要新盲窗/实盘观察另立任务 |

程序崩溃、资源不足等运行错误不是研究 verdict；修复只能恢复本页冻结语义。任何研究失败标签一旦命中，T5-DSTR1 收工，禁止滑成 `streak-side x cap x transform x seed x model` 网格，也不得回到 H52 或其他死亡路线。

## 5. 实现接口草案（本轮禁止执行）

以下只定义未来实现 PR 的接口形状。**当前 PR 不得创建这些脚本、不得导出 sidecar、不得计算 IC/RankIC、不得重训、不得跑 PortAna/BT。**脚本名不代表仓库中已经存在实现。所有阶段对既存输出目录都必须 fail-closed，不得删除、清空或复用旧目录。

### 5.1 唯一 sidecar + A 门

```powershell
$py = "D:/anaconda3/envs/vanna312/python.exe"
$out = "exports/analysis/t5_dstr1_20260918"

& $py -u my_scripts/export_downstreak_sidecar.py `
  --experiment alpha158_cost_kdj_lgb `
  --recorder-id 8a061ea428e04bb3a199a485ade49d0e `
  --handler-index-source recorder-handler `
  --provider-uri "C:/Users/wangc/.qlib/qlib_data/my_data" `
  --freeze-provider-snapshot --close-field "`$close" `
  --streak-side down --max-market-days 5 --exclude-zero-return `
  --require-complete-window --no-window-extension --no-close-imputation `
  --rank-method average --rank-pct pandas-pct-true `
  --feature-name DOWNSTREAK5_RANK `
  --emit-source-qc --emit-hash-and-key-digest `
  --out-dir "$out/sidecar" --fail-if-out-exists

$sidecarSha256 = "<SIDECAR_SHA256_EMITTED_BY_EXPORT_MANIFEST>"

& $py -u my_scripts/diag_conditional_information.py `
  --experiment alpha158_cost_kdj_lgb `
  --recorder-id 8a061ea428e04bb3a199a485ade49d0e `
  --pred-2025 my_scripts/预测结果_8a061ea4_2025valid.csv `
  --sidecar "$out/sidecar/DOWNSTREAK5_RANK.parquet" `
  --sidecar-manifest "$out/sidecar/manifest.json" `
  --sidecar-sha256 $sidecarSha256 --verify-key-digest `
  --feature DOWNSTREAK5_RANK --control-score `
  --label "Ref(`$close,-2)/Ref(`$close,-1)-1" `
  --window 2025-01-03:2025-12-31 `
  --window 2026-01-01:2026-09-14 `
  --min-coverage 0.98 --block-days 5 --bootstrap-reps 10000 --seed 20260918 `
  --out-dir "$out/information" --fail-if-out-exists
```

A gate boolean 非全真时，后两段不得执行。

### 5.2 B 门：单列训练与信号诊断

```powershell
& $py -u my_scripts/train_sidecar_feature_arm.py `
  --clone-recorder 8a061ea428e04bb3a199a485ade49d0e `
  --sidecar "$out/sidecar/DOWNSTREAK5_RANK.parquet" `
  --sidecar-sha256 $sidecarSha256 --verify-key-digest `
  --only-extra-feature DOWNSTREAK5_RANK `
  --train 2020-01-01:2024-12-31 --valid 2025-01-01:2025-12-31 `
  --test 2026-01-01:2026-09-14 --no-portana `
  --out-dir "$out/model" --fail-if-out-exists

& $py -u my_scripts/diag_pred_pair.py `
  --control-recorder 8a061ea428e04bb3a199a485ade49d0e `
  --candidate-recorder <DSTR_RECORDER_ID> `
  --control-pred-2025 my_scripts/预测结果_8a061ea4_2025valid.csv `
  --candidate-pred-2025 "$out/model/pred_2025.csv" `
  --label "Ref(`$close,-2)/Ref(`$close,-1)-1" --topk 10 `
  --top10-spread-vs common-universe-equal-weight `
  --window 2025-01-03:2025-12-31 `
  --window 2026-01-01:2026-09-14 `
  --block-days 5 --bootstrap-reps 10000 --seed 20260918 `
  --out-dir "$out/pred_pair" --fail-if-out-exists
```

`<DSTR_RECORDER_ID>` 只能是本次单列候选训练新建的 recorder，并须记录 sidecar SHA-256、行键摘要、列名单及相对 `8a061ea4` 的配置 diff；无法证明唯一变量隔离时拒绝运行。

### 5.3 C 门：固定 10/3 paired PortAna

```powershell
& $py -u my_scripts/portana_pred_pair.py `
  --control-recorder 8a061ea428e04bb3a199a485ade49d0e `
  --candidate-recorder <DSTR_RECORDER_ID> `
  --control-pred-2025 my_scripts/预测结果_8a061ea4_2025valid.csv `
  --candidate-pred-2025 "$out/model/pred_2025.csv" `
  --window 2025-01-03:2025-12-31 `
  --window 2026-01-01:2026-09-14 `
  --topk 10 --n-drop 3 --hold-thresh 1 `
  --open-cost 0.0005 --close-cost 0.0015 --min-cost 5 `
  --account 100000000 --risk-degree 0.95 --benchmark SH000300 `
  --all-buy-gates-off --all-price-exits-off `
  --block-days 5 --bootstrap-reps 10000 --seed 20260918 `
  --out-dir "$out/portana_pair" --fail-if-out-exists
```

C 不得重导 sidecar 或改变训练配置，只能沿用 B recorder 中同一特征血缘；B 未全过时不得运行。

## 6. 10/3 与 50/5 永久分账

| 账 | 本刀允许回答 | 本刀禁止回答 |
|---|---|---|
| 线上导向 10/3 账 | 固定当前 label 与 `8a061ea4` 时，`DOWNSTREAK5_RANK` 能否依次通过两窗信息门、模型门和固定 10/3 兑现门 | 即使全过也不能直接替换线上 pred/特征；2025 valid 不得写成可外推年化；2025/2026 NAV 不相加、不相乘 |
| 50/5 研究账 | 本刀不产生新 50/5 结果，只保留历史分账 | 不跑 50/5 PortAna；不用 50/5 历史 NAV、超额、过滤、止损或宽度结果选择 streak 方向、上限或证明它对 10/3 有效 |

最终立场：**H52A1 因完整 252 日窗口覆盖率低于锁定 98% 而停，且公式复算已经通过；这不授权缩短高点锚、改价格字段、换成 MAXRET 或修实现重跑，也不授权重开 DSEM、BETA、MAXRET、Amihud、CYQ、winratio、horizon 或 score-exit。下一刀只给 `DOWNSTREAK5_RANK` 这个一周连续下跌反转状态一次“先跨窗条件信息、后单列重训与模型信号、再固定 10/3 PortAna”的证伪机会；本轮只写协议，不实现、不跑数，任一门失败整把刀停止。**
