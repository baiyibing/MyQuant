# 2026-09-18 · annual-lift 下一刀（BETA_CONDITIONAL_FLIP 之后）

**性质**：只预注册一把刀、有序门和互斥终态标签。本轮**不实现、不导数、不计算 IC/RankIC、不重训、不跑 PortAna/BT、不改线上**。

**裁决**：选 **T5-DSV1：固定 20 个市场交易日的下行半偏差反向截面秩**，只允许一列 `DSEM20_ANTI_RANK`。

**线上默认**：仍为 **10/3 LGB**；默认 pred 仍为 `8a061ea4`（recorder `8a061ea428e04bb3a199a485ade49d0e`），全程只读。

一句话刀法：**固定当前 label、`8a061ea4`、原 handler 宇宙和唯一的 20 日下行半偏差公式，先检验“较低的近期下行波动”是否在 2025/2026 对现有 score 有同向正的增量 RankIC；A 全过才允许只加 `DSEM20_ANTI_RANK` 一列重训，B 全过才允许做固定 10/3 的配对 PortAna，任一门失败即停。**

## 0. 上一刀结果与新刀一句话

T5-BETA1 已在 `newtest_4090` 收工，最终标签为 **`BETA_CONDITIONAL_FLIP`**，停在 A 门；B/C 未跑，没有重训、PortAna 或 BT。刀法尖是 PR #81 commit `f75022e`，sidecar SHA-256 为 `2021a4393a5ddd8d2dff3cae82f127130d459a376d7a9c0610c0f07043dfd5c3`。

失败特征 `BETA60_ANTI_RANK` 是股票对冻结 `SH000300` 的固定 60 个市场交易日、带截距 OLS beta（同一后复权 close 的 close-to-close 简单收益），再在冻结 handler 当日索引上对 `-beta60` 做截面秩；它**不是** Alpha158 BETA60。

| 窗 | mean BETA partial RankIC | median | ICIR | 天数 | 当日股票中点 | 95% CI |
|---|---:|---:|---:|---:|---:|---|
| 2025 | -0.003630 | -0.019013 | -0.0170 | 242 | 5308.5 | 未报告 |
| 2026 | +0.004667 | +0.006605 | +0.0194 | 169 | 5372 | [-0.029287, +0.042903] |

2026 自然季度 mean partial RankIC 为 Q1 `+0.011179`（56 日）、Q2 `-0.040246`（60 日）、Q3 `+0.048631`（53 日，截止 2026-09-14）。`majority_negative=false` 且 `single_quarter_driven=false`，但季度规则没有、也不能推翻两窗均值反号的强制停止条件；2026 CI 下沿也不大于 0。数据门已经通过：2025 覆盖率 99.56%（1279173/1284876），2026 为 98.82%（907395/918193），均达到 98% 门槛，所以失败不能归因于覆盖不足。

交接没有报告 2025 CI、Top10 或任何 B 门数字；本页不补造。基线 recorder `8a061ea4`、线上 10/3 均未改。

**新刀一句话**：T5-DSV1 离开“对市场共同波动的敏感度”，只检验股票自身近期全部负收益的二阶下行风险；它不需要基准序列、协方差或回归，也不从 BETA1 的失败结果反选方向。

## 1. 为什么只选 T5-DSV1

### 1.1 唯一、冻结且可证伪的假设

对股票 `i`、特征日 `t`，仅用冻结 qlib provider 的后复权 `$close`：

```text
r[i,d] = close[i,d] / close[i,d-1] - 1
down[i,d] = min(r[i,d], 0)
dsem20[i,t] = sqrt(mean(down[i,d]^2, d = t-19..t))
DSEM20_ANTI_RANK[i,t] = rank_pct_cross_section(-dsem20[i,t])
```

- `t-19..t` 固定为包含 `t` 的 20 个市场交易日收益，需要对应的 21 个 close 点全部有限且 `>0`；任一点不合格则该行缺失，禁止向更早日期扩窗、前向填充或以 0 补原始收益。
- 正收益日的 `down` 按公式固定为 0；若 20 日均无负收益，`dsem20=0` 是有效值而不是缺失。平方项分母固定为 20，不在样本标准差的 19 与总体均方的 20 之间选择。
- 截面只在冻结 handler 当日成员与有效 `dsem20` 的交集上，用 `pandas.Series.rank(method="average", pct=True)` 对 `-dsem20` 排一次；值越大表示近期下行半偏差越低。
- 唯一预注册方向是“`DSEM20_ANTI_RANK` 越高，当前 label 的期望收益越高”，即低下行风险方向。结果为负时不得现场去掉负号。

20 日只代表预先固定的一个交易月观察窗。本刀没有 5/10/60/120 日候选，没有 total/upside volatility、Sortino、阈值、分箱、winsorize、EWMA、lag、交互、异 seed 或第二棵树；也不先看 2025/2026 再选方向。因此它是一把单刀，不是波动率特征池。

冻结模型的 Alpha158/KDJ/DDX 特征可能已经间接吸收部分波动信息，本页不假定 DSV1 天然独立或有效；正因如此，A 门先控制现有 score，只问这一个“下行二阶矩”定义是否还剩跨窗条件增量。若已被吸收，就在最便宜的 A 门以失败标签收工，不以“树可能会学出交互”为由越门重训。

### 1.2 BETA_CONDITIONAL_FLIP 为什么不能救 BETA

数据门已过，而预注册的低 beta 方向在 2025/2026 的 mean partial RankIC 分别为负、正，且 2026 CI 穿 0。这回答的是原假设不能稳定跨窗，不是“负号写反了”或“60 日不合适”：

- 翻成 `rank(+beta60)` 会直接用已经观察到的符号反选方向，2025/2026 仍会互换正负，不能消除跨窗翻转。
- 改 60 日窗、去截距、换 simple/log return、做滚动相关或下行 beta，都会改变估计量；在失败后逐个尝试会形成定义网格。
- 换 `000300.SH`、510300、等权、行业或截面均值会改变共同风险基准，不能被解释成修复已通过的数据门。
- 改用 Alpha158 BETA60、加 lag/阈值、换 seed 或新树都绕过了 A 门已经给出的停止裁决。
- 季度 `majority_negative=false` 与 `single_quarter_driven=false` 只是没有触发额外失败条件，不是救援条款；跨窗反号已经先命中 `BETA_CONDITIONAL_FLIP`。

T5-DSV1 不读市场基准，不估 beta、相关或回归残差，也不以 BETA1 的季度形状定窗口。它研究的是单股负收益幅度的均方根，而非系统性暴露，因此不是翻 beta 方向、改窗或换基准的别名。

### 1.3 为什么也不重开其他死亡路线

| 已停止路线 | 已有裁决 | T5-DSV1 的边界 |
|---|---|---|
| MAXRET | `MAXRET_MODEL_NO_TRANSFER` | 不翻 `MAXRET20_ANTI_RANK`，不改其窗口，不用 `$high`、top-3、隔夜/日内拆分；DSV1 不取任何最大值，不读 MAXRET sidecar，也不与 MAXRET 联合训练。它固定汇总 20 日中**全部负收益**的平方，不是正向单日极值补救 |
| 固定 Amihud | `AMIHUD_CONDITIONAL_NO_EDGE` | 不读 `$amount`，不改 Amihud 的窗口、方向或归一方式；下行收益的二阶幅度不是成交额价格冲击 |
| 精确 CYQ | `CYQ_CONDITIONAL_NO_EDGE` | 不读 winner-ratio parquet，不改 shares/window/threshold，不用获利盘水平或衍生量 |
| winratio 残差 | `WINRATIO_GAP_MODEL_NO_TRANSFER` | 不读 `$winratio`，不换残差、平滑或 lag，不用跨源筹码口径差 |
| label / horizon | `LABEL_HORIZON_FLIP` | 当前 label 原样冻结，不试任何新 horizon |
| `score<=0` 卖出 | `SCORE_EXIT_FLIP` | 不改卖出、trail、止盈、止损、宽度、`n_drop` 或任一执行阈值 |

同时继续禁止 2026 扫闸、换树、月滚、per-fold scaler、20/3、把 15% 关闸升为默认、大 handler 重建，以及用 50/5 研究账改线上 10/3。DSV1 即使通过 A，也必须重新证明单列信息能穿过冻结模型信号门；不能把 A 的统计量直接当成 NAV 证据。

## 2. 冻结表

| 层 | 锁定值 / 禁令 |
|---|---|
| 当前 label | 只用 `Ref($close,-2)/Ref($close,-1)-1`；禁止换 label 或 horizon |
| 基线 pred | `8a061ea428e04bb3a199a485ade49d0e`；2026 `pred.pkl` 与 2025 同模型补分 CSV 只读，不覆盖、不回写；不读写 `55c5bf77` |
| 唯一候选 | `DSEM20_ANTI_RANK`，严格按 §1.1 构造；禁止窗口、收益、分母、方向、变换、阈值、lag、交互或 seed 网格 |
| 原始数据 | 只读与 `8a061ea4` 一致的冻结 qlib provider 快照及 `$close`；记录 provider 路径、快照指纹、交易日历指纹和代码 commit；A 后不得刷新数据 |
| 构造时点 | 特征日 `t` 只使用 `t` 及以前数据；固定 20 个市场日收益、21 个 close 全部有效，不扩窗、不填补 |
| 构造宇宙 | 先按冻结市场日历逐股票算 `dsem20`，再只在 `alpha158_cost_kdj_lgb / 8a061ea4` 冻结 handler 的当日索引与有效值交集上排一次截面秩；不得先全市场 rank 再切 handler |
| 唯一 sidecar | 一次性导出覆盖 train/valid/test 的不可变 sidecar，至少保留 `(instrument, datetime)`、窗起止、20 个收益有效性、负收益日数、`dsem20`、`DSEM20_ANTI_RANK` 与缺失原因；写 SHA-256 和行键摘要。A 只切片，B 只左连这一份，C 只认 B recorder 血缘中的同一 SHA-256 |
| 两窗 | A/B/C 统一为 2025 valid `2025-01-03~2025-12-31`、2026 OOS `2026-01-01~2026-09-14`；两窗均已被研究，不包装为新盲窗 |
| 训练 | A 全过后才可复制 `8a061ea4` 的 LGB 配置；唯一差异是向原 handler 帧左连一列 `DSEM20_ANTI_RANK`；train 2020-2024、valid 2025、test 2026，seed、超参、早停、scaler、训练宇宙全冻结，涨停出池开、`DropLimitUpLearn` 关 |
| 组合 | B 全过后才可做 paired PortAna；只有 10/3，`hold_thresh=1`、top/bottom；buy-state、ST、年龄、5 日 15% 全关，止损、trail、止盈全关 |
| 尺子 | qlib `$close` 后复权 bin；买 5bp / 卖 15bp / 最低 5；拒单 0.095、不追买、整手向下；本金 1e8、`risk_degree=0.95`、基准 SH000300 |
| 禁止项 | 不扫任何参数或特征；不换树、月滚、per-fold scaler、20/3、50/5 PortAna、15% 关闸默认或大 handler 重建；不把 BETA、MAXRET、Amihud、CYQ、winratio 中间产物并入本刀 |
| 线上 | 全程仍为 `8a061ea4` + 10/3；即使全链成功也只得到候选标签，不自动替换 pred、特征或线上参数 |

## 3. A/B/C 有序门

### 3.1 A 门：跨窗条件信息门；禁止重训与 PortAna

先从冻结 provider 快照一次性构造唯一 sidecar。导出器可为 2020 起始日读取恰好 20 个前置市场交易日用于热身，但只输出冻结 handler 键；不得读取 label，也不得在 A 通过后重算历史。

数据门：

- 每个 `(instrument, datetime)` 的 21 个 close、20 个收益、负收益日数、公式结果和截面成员必须可复算；等值使用 average rank，不得用股票代码破 tie。
- sidecar 必须通过列集、唯一键、日期范围、provider/日历/sidecar hash、行键摘要、随机抽样复算和时点检查。
- A/B 重叠键上的 `DSEM20_ANTI_RANK` 必须逐值一致；任何 hash、成员集合或数值不一致均为 `DSEM_DATA_INVALID`。
- 2025、2026 的共同样本覆盖率均须 `>=98%`。分母是冻结 handler 当日有限 score 行，分子是其中 score、当前 label 与候选列均有限的行；另报 close 非法、20 日不完整等缺失原因。
- feature day `t` 与 score/label 按同一 `(instrument, datetime)` 键对齐；禁止 `pred_minus_one`、成交日偏移或使用 `t+1` 数据。

信息量定义：每个特征日，在 score、label、`DSEM20_ANTI_RANK` 均有限且 `n>=4` 的共同样本上，令 `s=rank_pct(score)`、`d=DSEM20_ANTI_RANK`、`y=rank_pct(label)`；分别做 `d ~ 1+s` 与 `y ~ 1+s`，取两组残差的 Pearson 相关，定义当日 **DSEM partial RankIC**。残差化只用于信息门；候选训练列仍只能是 sidecar 中的 `DSEM20_ANTI_RANK`，不得另造“DSEM 对 score 残差”训练列。

每窗报告 mean、median、ICIR、有效/退化日数与原因、共同股票数中位数及覆盖率；2026 按自然季度报告 mean DSEM partial RankIC。对逐日 IC 做 5 交易日 moving-block bootstrap，固定 10,000 次、seed `20260918`，报告 95% CI。

**A 门全过条件**：数据门通过；2025、2026 mean DSEM partial RankIC 均 `>0`；2026 的 95% CI 下界 `>0`；2026 不得多数季度为负，也不得只靠一个季度为正。未全过立即按 §4 裁决，B/C 取消。

### 3.2 B 门：只加一列重训，再做模型信号门

A 全过后才允许建立一个新 recorder：

- 对照仍是现成 `8a061ea4`，不得重训或覆盖。
- 候选只复制其冻结训练配置，在现成 handler 帧按 `(instrument, datetime)` 左连同一 sidecar 的 `DSEM20_ANTI_RANK`；不得同时加入 raw `dsem20`、负收益日数、total/upside volatility、缺失指示或任一死亡路线特征。
- 少量缺失只沿用现网的 `RobustZScoreNorm` 后 `Fillna(0)` 链，不得删股票、换宇宙或另拟 scaler。
- 只导出候选 2025 valid 和 2026 test 分数到新目录。在两窗共同样本上，以当前 label 比较候选与基线的日 RankIC、Top10Spread 和 `ΔRankIC` 的同口径 bootstrap CI。Top10Spread 固定为等权 Top10 减共同宇宙等权，禁止换成 Top10-Bottom10；此时仍不得跑组合。

**B 门全过条件**：候选在 2025、2026 均同时满足 `RankIC(candidate)>RankIC(8a)` 与 `Top10Spread(candidate)>Top10Spread(8a)`；2026 `ΔRankIC` 的 95% CI 下界 `>0`；2026 不得多数季度为负或单季驱动。未全过立即停止，C 取消。

### 3.3 C 门：最后才做固定 10/3 paired PortAna

B 全过后，才允许对基线 pred 与候选 pred 做两窗配对 PortAna：

- 两臂唯一上游差异必须是 `DSEM20_ANTI_RANK` 一列；输入 hash、组合、成交、费用、闸和窗口全部冻结。
- C 使用各臂全宇宙 pred，不用 A/B 的共同有限样本重定义组合宇宙。
- 每窗报告末值、区间收益、扣费年化超额、最大回撤、换手与费用；报告 2026 自然季度 `ΔNetReturn`，并对 2026 配对日收益差做同样 5 日、10,000 次、seed `20260918` 的 bootstrap CI。

**C 门全过条件**：2025、2026 均 `ΔNetReturn>0` 且扣费年化超额排序候选高于基线；2026 `ΔNetReturn` 的 95% CI 下界 `>0`；2026 `majority_negative=false` 且 `single_quarter_driven=false`。

三门的 2026 季度口径统一：保留截至 9 月 14 日的不完整 Q3；`majority_negative = 负增量季度数 / 季度数 > 50%`；`single_quarter_driven = 全窗增量 > 0 且正增量季度数 <= 1`。A 的增量是 DSEM partial RankIC，B 是候选减基线的 RankIC/Top10Spread，C 是 locked-cost `ΔNetReturn`，不得混写。

## 4. 成功标签 / 失败瀑布

一次合规执行最终必须且只能产生下表中的**一个**终态标签。A/B 的“通过”只记 gate boolean，不另打中间成功标签；裁决按优先级自上而下，命中即停止，所以成功标签与所有失败标签互斥。

| 优先级 | 唯一终态标签 | 命中条件 | 停手动作 |
|---:|---|---|---|
| 1 | `DSEM_DATA_INVALID` | 任一数据、时点、覆盖、公式复算、hash、行键或配置隔离门失败 | 停；只允许修实现错误后按原协议复跑，不得改窗口、公式或数据源 |
| 2 | `DSEM_CONDITIONAL_FLIP` | A 中 2025/2026 mean partial RankIC 反号，或 2026 多数季度为负 | 停；不翻方向、不挑季度、不换下行风险定义 |
| 3 | `DSEM_CONDITIONAL_NO_EDGE` | 未命中 1/2，但任一窗均值 `<=0`、2026 CI 下界 `<=0`、单季驱动或任一 A 信息门不过 | 停；不改窗口、分母、方向或变换 |
| 4 | `DSEM_MODEL_NO_TRANSFER` | A 过而 B 任一窗 RankIC/Top10Spread 不同时胜基线，或 2026 CI/季度门不过 | 停；不加 raw DSEM、第二列、交互、异 seed 或新树 |
| 5 | `DSEM_PORTANA_FLIP` | A/B 过而 C 的两窗 locked-cost `ΔNetReturn` 反号，或 2026 多数季度为负 | 停；不改 10/3、成本、闸、卖出或窗口 |
| 6 | `DSEM_PORTANA_NO_EDGE` | 未命中 1-5，但 C 的 2026 CI 下界 `<=0`、单季驱动或任一 C 门不过 | 停；不转扫宽度、`n_drop`、阈值或 50/5 |
| 7 | `DSEM_FEATURE_CANDIDATE` | A、B、C 全部通过 | 只登记候选；不自动改线上，是否需要新盲窗/实盘观察另立任务 |

程序崩溃、资源不足等运行错误不是研究 verdict；修复只能恢复本页冻结语义。任一研究失败标签一旦命中，T5-DSV1 收工，禁止滑成 `lookback x downside-definition x direction x transform x seed x model` 网格。

## 5. 实现接口草案（本轮禁止执行）

以下只定义未来实现 PR 的接口形状。**当前 PR 不得创建这些脚本、不得导出 sidecar、不得计算 IC/RankIC、不得重训、不得跑 PortAna/BT。**脚本名不代表仓库中已经存在实现。所有阶段对既存输出目录都必须 fail-closed，不得删除、清空或复用旧目录。

### 5.1 唯一 sidecar + A 门

```powershell
$py = "D:/anaconda3/envs/vanna312/python.exe"
$out = "exports/analysis/t5_dsv1_20260918"

& $py -u my_scripts/export_dsem20_sidecar.py `
  --experiment alpha158_cost_kdj_lgb `
  --recorder-id 8a061ea428e04bb3a199a485ade49d0e `
  --handler-index-source recorder-handler `
  --provider-uri "C:/Users/wangc/.qlib/qlib_data/my_data" `
  --freeze-provider-snapshot --close-field "`$close" `
  --lookback-market-days 20 --return close-to-close-simple `
  --downside-target zero --root-mean-square --denominator 20 `
  --require-complete-window --no-window-extension --no-return-imputation `
  --multiply-before-rank -1 --rank-method average --rank-pct pandas-pct-true `
  --feature-name DSEM20_ANTI_RANK `
  --emit-source-qc --emit-hash-and-key-digest `
  --out-dir "$out/sidecar" --fail-if-out-exists

$sidecarSha256 = "<SIDECAR_SHA256_EMITTED_BY_EXPORT_MANIFEST>"

& $py -u my_scripts/diag_conditional_information.py `
  --experiment alpha158_cost_kdj_lgb `
  --recorder-id 8a061ea428e04bb3a199a485ade49d0e `
  --pred-2025 my_scripts/预测结果_8a061ea4_2025valid.csv `
  --sidecar "$out/sidecar/DSEM20_ANTI_RANK.parquet" `
  --sidecar-manifest "$out/sidecar/manifest.json" `
  --sidecar-sha256 $sidecarSha256 --verify-key-digest `
  --feature DSEM20_ANTI_RANK --control-score `
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
  --sidecar "$out/sidecar/DSEM20_ANTI_RANK.parquet" `
  --sidecar-sha256 $sidecarSha256 --verify-key-digest `
  --only-extra-feature DSEM20_ANTI_RANK `
  --train 2020-01-01:2024-12-31 --valid 2025-01-01:2025-12-31 `
  --test 2026-01-01:2026-09-14 --no-portana `
  --out-dir "$out/model" --fail-if-out-exists

& $py -u my_scripts/diag_pred_pair.py `
  --control-recorder 8a061ea428e04bb3a199a485ade49d0e `
  --candidate-recorder <DSEM_RECORDER_ID> `
  --control-pred-2025 my_scripts/预测结果_8a061ea4_2025valid.csv `
  --candidate-pred-2025 "$out/model/pred_2025.csv" `
  --label "Ref(`$close,-2)/Ref(`$close,-1)-1" --topk 10 `
  --top10-spread-vs common-universe-equal-weight `
  --window 2025-01-03:2025-12-31 `
  --window 2026-01-01:2026-09-14 `
  --block-days 5 --bootstrap-reps 10000 --seed 20260918 `
  --out-dir "$out/pred_pair" --fail-if-out-exists
```

`<DSEM_RECORDER_ID>` 只能是本次单列候选训练新建的 recorder，并须记录 sidecar SHA-256、行键摘要、列名单及相对 `8a061ea4` 的配置 diff；无法证明唯一变量隔离时拒绝运行。

### 5.3 C 门：固定 10/3 paired PortAna

```powershell
& $py -u my_scripts/portana_pred_pair.py `
  --control-recorder 8a061ea428e04bb3a199a485ade49d0e `
  --candidate-recorder <DSEM_RECORDER_ID> `
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

C 不得重导 sidecar 或改变训练配置，只能沿用 B recorder 中的同一特征血缘；B 未全过时不得运行。

## 6. 10/3 与 50/5 永久分账

| 账 | 本刀允许回答 | 本刀禁止回答 |
|---|---|---|
| 线上导向 10/3 账 | 固定当前 label 与 `8a061ea4` 时，`DSEM20_ANTI_RANK` 能否依次通过两窗信息门、模型门和固定 10/3 兑现门 | 即使全过也不能直接替换线上 pred/特征；2025 valid 不得写成可外推年化；2025/2026 NAV 不相加、不相乘 |
| 50/5 研究账 | 本刀不产生新 50/5 结果，只保留历史分账 | 不跑 50/5 PortAna；不用 50/5 历史 NAV、超额、过滤、止损或宽度结果选方向、选窗口、定阈值或证明 DSV1 对 10/3 有效 |

最终立场：**BETA1 的跨窗反号是停止信号，不是翻方向、改窗口或换基准的邀请；同样也不授权返回 MAXRET、Amihud、CYQ、winratio、horizon 或 score-exit。下一刀只给 `DSEM20_ANTI_RANK` 这一列单股下行风险一次“先跨窗条件信息、后单列重训与模型信号、再固定 10/3 PortAna”的证伪机会；任一门失败，整把刀停止。**
