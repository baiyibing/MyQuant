# 2026-09-18 · annual-lift 下一刀（AMIHUD_CONDITIONAL_NO_EDGE 之后）

**性质**：只预注册一把刀、有序门和互斥终态标签。本轮**不实现、不导数、不计算 IC/RankIC、不重训、不跑 PortAna/BT、不改线上**。

**裁决**：选 **T5-MXR1：固定 20 交易日最大单日收益反向截面秩**，只允许一列 `MAXRET20_ANTI_RANK`。

**线上默认**：仍为 **10/3 LGB**；默认 pred 仍为 `8a061ea4`（recorder `8a061ea428e04bb3a199a485ade49d0e`），全程只读。

一句话刀法：**固定当前 label、`8a061ea4`、原 handler 宇宙和唯一 20 日公式，先检验“近期没有极端单日上涨”是否在 2025/2026 对现有 score 有同向正的增量 RankIC；A 过才允许只加 `MAXRET20_ANTI_RANK` 一列重训，B 过才允许做固定 10/3 的配对 PortAna，任一门失败即停。**

## 0. 上一刀结果与新刀一句话

T5-AMI1 已在 `newtest_4090` 收工，最终标签是 **`AMIHUD_CONDITIONAL_NO_EDGE`**，刀法基线为 PR #79 @ `b2b675c`，sidecar SHA-256 为 `e5ec2bc7cba8e580cbc33e1253605f00166119f740542c699fdc6c4b4822746d`：

| 门 | 已知结果 | 裁决 |
|---|---|---|
| A 条件信息门 | 2025 mean AMIHUD partial RankIC `+0.018829`，交接未单列其 CI；2026 为 `+0.015922`，95% CI `[-0.007202, +0.042791]` | 两窗均值同号为正，但 2026 CI 下沿 `<=0`，A 失败 |
| B 模型信号门 | 未进入 | 未重训 |
| C 组合门 | 未进入 | 未跑 PortAna/BT |

该次执行未改 pred、未改线上 10/3。本页不为交接未提供的 2025 CI 补值，也不把正均值改写成“几乎通过”。

**新刀一句话**：T5-MXR1 离开筹码水平、跨源获利盘残差和成交额价格冲击，唯一检验固定 20 日内的最大单日收益是否存在“彩票偏好后低收益”的、现有 score 尚未吸收的跨窗信息。

## 1. 为什么在 AMI1 A 门失败后选这把

### 1.1 唯一假设与唯一公式

AMI1 的失败发生在最便宜的条件信息门，含义是固定 20 日 Amihud 列尚不足以支持训练；正确动作是停止整个成交冲击族，而不是在 lookback、方向或变换上寻找幸存者。T5-MXR1 改到价格路径的**极端值**维度：近期极端单日上涨越大，彩票偏好与过度追逐风险越强，预注册方向为未来收益越低。

对股票 `i`、特征日 `t`：

```text
r[i,d] = close[i,d] / close[i,d-1] - 1
maxret20[i,t] = max(r[i,d], d = t-19..t)
MAXRET20_ANTI_RANK[i,t] = rank_pct_cross_section(-maxret20[i,t])
```

- `close` 只用冻结 qlib provider 的后复权 `$close`；`t-19..t` 是包含 `t` 的固定 20 个市场交易日，需 21 个完整、有限且 `>0` 的 close 点。
- 窗内历史涨停或大涨日不剔除、不截尾；它正是本特征要度量的极端价格路径。缺任一点则该行缺失，禁止用个股更早日期补足、前向填充或以 0 代替原始输入。
- 截面只在冻结 handler 当日成员与有效 `maxret20` 的交集上，用 `pandas.Series.rank(method="average", pct=True)` 对 `-maxret20` 排一次。值越大，代表最近 20 日最大单日上涨越小。
- 方向固定为“`MAXRET20_ANTI_RANK` 越高 -> 当前 label 的期望收益越高”。若结果为负，不得现场去掉负号、改做原始 `MAXRET20_RANK`。

这不是候选池：只有一个 20 日窗、一个 close-to-close 最大值、一个反向截面秩和一个方向。不得追加 5/10/60/120/250 日、top-3 平均、最大绝对收益、上影线、隔夜/日内拆分、winsorize、阈值、分箱、lag、交互、异 seed 或第二棵树。

### 1.2 为什么不是相邻路线

| 路线 | 已有裁决 | 本轮边界 |
|---|---|---|
| 精确 CYQ | `CYQ_CONDITIONAL_NO_EDGE`，停在 A | 不重算 free/1000，不改 shares/window/threshold，也不把 CYQ 与本列组合 |
| 券商 winratio 残差 | `WINRATIO_GAP_MODEL_NO_TRANSFER`，A 过但 B 停 | 不试 raw `$winratio`、另一种残差、平滑、lag、交互、异 seed 或新树 |
| 固定 Amihud | `AMIHUD_CONDITIONAL_NO_EDGE`，2026 CI 穿 0，停在 A | 不试 5/10/60 日、翻方向、EWMA、signed return、量/流通盘归一、阈值或 lag；MXR1 不使用 `$amount`，不是 AMI1 补救 |
| 卖出 / horizon | `score<=0` 额外卖出为 `SCORE_EXIT_FLIP`；label/horizon 为 `LABEL_HORIZON_FLIP` | 不改卖出、trail、止盈、止损、持有期或 label；也不扫宽度、`n_drop` 或闸 |
| 换树 / 月滚 / scaler / 大 handler | 已有停手结论 | 若 A 过，只复制 `8a061ea4` 的冻结训练配置并左连一列；不借新特征重开训练架构 |

选择 MXR1 的理由不是“再找一个 20 日技术指标”，而是用一个可复算、无外部口径拼接、经济方向预先确定的极端收益假设，切换出已失败的筹码/流动性家族。Alpha158 可能已间接吸收相近价格信息，因此 A 门明确控制现有 score；若没有剩余条件信息，`MAXRET_CONDITIONAL_NO_EDGE` 就是终点，不以“树也许能学到非线性”为由越过 A。

## 2. 冻结表

| 层 | 锁定值 / 禁令 |
|---|---|
| 当前 label | 只用 `Ref($close,-2)/Ref($close,-1)-1`；禁止换 label 或 horizon |
| 基线 pred | `8a061ea428e04bb3a199a485ade49d0e`；2026 `pred.pkl` 与 2025 同模型补分 CSV 只读，不覆盖、不回写；不读写 `55c5bf77` |
| 唯一候选 | `MAXRET20_ANTI_RANK`，严格按 §1.1 构造；禁止任何窗口、公式、方向、阈值、变换、lag、交互或 seed 网格 |
| 原始数据 | 只读与 `8a061ea4` 一致的冻结 qlib provider 快照及 `$close`；记录 provider 路径、快照指纹、交易日历指纹和代码 commit；A 后不得刷新数据 |
| 构造时点 | 特征日 `t` 只用 `t` 及以前数据；市场日 `t-19..t` 的 20 个收益需 21 个 close；停牌/缺日不得向前扩窗 |
| 构造宇宙 | 先按冻结市场日历逐股票算 `maxret20`，再只在 `alpha158_cost_kdj_lgb / 8a061ea4` 冻结 handler 的当日索引与有效值交集上排一次截面秩；不得先全市场 rank 再切 handler |
| 唯一 sidecar | 一次性导出覆盖 train/valid/test 的不可变 sidecar，至少保留 `(instrument, datetime)`、20 日逐日输入摘要、`maxret20`、`MAXRET20_ANTI_RANK`、有效性与缺失原因；写 SHA-256 和行键摘要。A 只切片，B 只左连这一份，C 只认 B recorder 血缘中的同一 SHA-256 |
| 两窗 | A/B/C 统一为 2025 valid `2025-01-03~2025-12-31`、2026 OOS `2026-01-01~2026-09-14`；两窗均已被研究，不包装为新盲窗 |
| 训练 | A 全过后才可复制 `8a061ea4` 的 LGB 配置；唯一差异是向原 handler 帧左连一列 `MAXRET20_ANTI_RANK`；train 2020-2024、valid 2025、test 2026，seed、超参、早停、scaler、训练宇宙全冻结，涨停出池开、`DropLimitUpLearn` 关 |
| 组合 | B 全过后才可做 paired PortAna；只有 10/3，`hold_thresh=1`、top/bottom；buy-state、ST、年龄、5 日 15% 全关，止损、trail、止盈全关 |
| 尺子 | qlib `$close` 后复权 bin；买 5bp / 卖 15bp / 最低 5；拒单 0.095、不追买、整手向下；本金 1e8、`risk_degree=0.95`、基准 SH000300 |
| 禁止项 | 不扫任何参数或特征；不换树、月滚、per-fold scaler、20/3、50/5 PortAna、15% 关闸默认或大 handler 重建；不把 CYQ、winratio、Amihud 中间产物并入本刀 |
| 线上 | 全程仍为 `8a061ea4` + 10/3；即使全链成功也只得到候选标签，不自动替换 pred、特征或线上参数 |

## 3. A/B/C 有序门

### 3.1 A 门：跨窗条件信息门；禁止重训与 PortAna

先从冻结 provider 快照一次性构造唯一 sidecar。导出器可为 2020 起始日读取足够前置市场日，但只输出冻结 handler 键；不得读取 label，也不得在 A 通过后重算历史。

数据门：

- 每个 `(instrument, datetime)` 的 21 个 close、20 个收益、最大值、截面成员和最终秩必须可复算；等值用 average rank，不得以股票代码破 tie。
- sidecar 必须通过列集、唯一键、日期范围、provider/日历/sidecar hash、行键摘要、随机抽样复算与时点检查。
- A/B 重叠键上的 `MAXRET20_ANTI_RANK` 必须逐值一致；任何 hash、成员集合或值不一致均为 `MAXRET_DATA_INVALID`。
- 2025、2026 的共同样本覆盖率均须 `>=98%`。分母是冻结 handler 当日有限 score 行，分子是其中 score、当前 label 和候选列均有限的行；另报 close 非法、窗口不完整等缺失原因。
- feature day `t` 与 score/label 按同一 `(instrument, datetime)` 键对齐；禁止 `pred_minus_one`、成交日偏移或使用 `t+1` 数据。

信息量定义：每个特征日，在 score、label、`MAXRET20_ANTI_RANK` 均有限且 `n>=4` 的共同样本上，令 `s=rank_pct(score)`、`m=MAXRET20_ANTI_RANK`、`y=rank_pct(label)`；分别做 `m ~ 1+s` 与 `y ~ 1+s`，取两组残差的 Pearson 相关，定义当日 **MAXRET partial RankIC**。残差化只用于信息门，候选训练列仍只能是原 sidecar 的 `MAXRET20_ANTI_RANK`，不得另造“MAXRET 对 score 残差”训练列。

每窗报告 mean、median、ICIR、有效/退化日数与原因、共同股票数中位数及覆盖率；2026 按自然季度报告 mean MAXRET partial RankIC。对逐日 IC 做 5 交易日 moving-block bootstrap，固定 10,000 次、seed `20260918`，报告 95% CI。

**A 门全过条件**：数据门通过；2025、2026 mean MAXRET partial RankIC 均 `>0`；2026 的 95% CI 下界 `>0`；2026 不得多数季度为负，也不得只靠一个季度为正。未全过立即按 §4 裁决，B/C 取消。

### 3.2 B 门：只加一列重训，再做模型信号门

A 全过后才允许建立一个新 recorder：

- 对照仍是现成 `8a061ea4`，不得重训或覆盖。
- 候选只复制其冻结训练配置，在现成 handler 帧按 `(instrument, datetime)` 左连同一 sidecar 的 `MAXRET20_ANTI_RANK`；不得同时加 raw `maxret20`、缺失指示、其他窗口、CYQ、winratio、Amihud 或其他衍生列。
- 少量缺失只沿用现网的 `RobustZScoreNorm` 后 `Fillna(0)` 链，不得删股票、换宇宙或另拟 scaler。
- 只导出候选 2025 valid 和 2026 test 分数到新目录。在两窗共同样本上，以当前 label 比较候选与基线的日 RankIC、Top10Spread 和 `ΔRankIC` 的同口径 bootstrap CI。Top10Spread 固定为等权 Top10 减共同宇宙等权，禁止换成 Top10-Bottom10；此时仍不得跑组合。

**B 门全过条件**：候选在 2025、2026 均同时满足 `RankIC(candidate)>RankIC(8a)` 与 `Top10Spread(candidate)>Top10Spread(8a)`；2026 `ΔRankIC` 的 95% CI 下界 `>0`；2026 不得多数季度为负或单季驱动。未全过立即停止，C 取消。

### 3.3 C 门：最后才做固定 10/3 paired PortAna

B 全过后，才允许对基线 pred 与候选 pred 做两窗配对 PortAna：

- 两臂唯一上游差异必须是 `MAXRET20_ANTI_RANK` 一列；输入 hash、组合、成交、费用、闸和窗口全部冻结。
- C 使用各臂全宇宙 pred，不用 A/B 的共同有限样本重定义组合宇宙。
- 每窗报告末值、区间收益、扣费年化超额、最大回撤、换手与费用；报告 2026 自然季度 `ΔNetReturn`，并对 2026 配对日收益差做同样 5 日、10,000 次、seed `20260918` 的 bootstrap CI。

**C 门全过条件**：2025、2026 均 `ΔNetReturn>0` 且扣费年化超额排序候选高于基线；2026 `ΔNetReturn` 的 95% CI 下界 `>0`；2026 `majority_negative=false` 且 `single_quarter_driven=false`。

三门的 2026 季度口径统一：保留截至 9 月 14 日的不完整 Q3；`majority_negative = 负增量季度数 / 季度数 > 50%`；`single_quarter_driven = 全窗增量 > 0 且正增量季度数 <= 1`。A 的增量是 MAXRET partial RankIC，B 是候选减基线的 RankIC/Top10Spread，C 是 locked-cost `ΔNetReturn`，不得混写。

## 4. 成功标签 / 失败瀑布

一次合规执行最终必须且只能产生下表中的**一个**终态标签。A/B 的“通过”只记 gate boolean，不另打中间成功标签；裁决按优先级自上而下，命中即停止，因此成功标签与所有失败标签互斥。

| 优先级 | 唯一终态标签 | 命中条件 | 停手动作 |
|---:|---|---|---|
| 1 | `MAXRET_DATA_INVALID` | 任一数据、时点、覆盖、公式复算、hash、行键或配置隔离门失败 | 停；只允许修实现错误后按原协议复跑，不得换数据或公式 |
| 2 | `MAXRET_CONDITIONAL_FLIP` | A 中 2025/2026 mean partial RankIC 反号，或 2026 多数季度为负 | 停；不翻方向、不挑季度、不换窗口 |
| 3 | `MAXRET_CONDITIONAL_NO_EDGE` | 未命中 1/2，但任一窗均值 `<=0`、2026 CI 下界 `<=0`、单季驱动或任一 A 信息门不过 | 停；不改窗口、极值定义、方向或变换 |
| 4 | `MAXRET_MODEL_NO_TRANSFER` | A 过而 B 任一窗 RankIC/Top10Spread 不同时胜基线，或 2026 CI/季度门不过 | 停；不加 raw 列、第二列、交互、异 seed 或新树 |
| 5 | `MAXRET_PORTANA_FLIP` | A/B 过而 C 的两窗 locked-cost `ΔNetReturn` 反号，或 2026 多数季度为负 | 停；不改 10/3、成本、闸、卖出或窗口 |
| 6 | `MAXRET_PORTANA_NO_EDGE` | 未命中 1-5，但 C 的 2026 CI 下界 `<=0`、单季驱动或任一 C 门不过 | 停；不转扫宽度、`n_drop`、阈值或 50/5 |
| 7 | `MAXRET_FEATURE_CANDIDATE` | A、B、C 全部通过 | 只登记候选；不自动改线上，是否需要新盲窗/实盘观察另立任务 |

程序崩溃、资源不足等运行错误不是研究 verdict；修复只能恢复本页冻结语义。任一研究失败标签一旦命中，T5-MXR1 收工，禁止滑成 `lookback x extreme-definition x direction x transform x seed x model` 网格。

## 5. 实现接口草案（本轮禁止执行）

以下只定义未来实现 PR 的接口形状。**当前 PR 不得创建这些脚本、不得导出 sidecar、不得计算 IC/RankIC、不得重训、不得跑 PortAna/BT。**脚本名均为未来接口，不假定当前仓已存在；所有阶段遇到既存输出目录须 fail-closed，不得删除、清空或复用旧目录。

### 5.1 唯一 sidecar + A 门

```powershell
$py = "D:/anaconda3/envs/vanna312/python.exe"
$out = "exports/analysis/t5_mxr1_20260918"

& $py -u my_scripts/export_maxret20_sidecar.py `
  --experiment alpha158_cost_kdj_lgb `
  --recorder-id 8a061ea428e04bb3a199a485ade49d0e `
  --handler-index-source recorder-handler `
  --provider-uri "C:/Users/wangc/.qlib/qlib_data/my_data" `
  --freeze-provider-snapshot --close-field "`$close" `
  --lookback-market-days 20 --require-complete-window `
  --daily-return close-to-close --aggregate max `
  --multiply-before-rank -1 `
  --rank-method average --rank-pct pandas-pct-true `
  --feature-name MAXRET20_ANTI_RANK `
  --emit-source-qc --emit-hash-and-key-digest `
  --out-dir "$out/sidecar" --fail-if-out-exists

$sidecarSha256 = "<SIDECAR_SHA256_EMITTED_BY_EXPORT_MANIFEST>"

& $py -u my_scripts/diag_conditional_information.py `
  --experiment alpha158_cost_kdj_lgb `
  --recorder-id 8a061ea428e04bb3a199a485ade49d0e `
  --pred-2025 my_scripts/预测结果_8a061ea4_2025valid.csv `
  --sidecar "$out/sidecar/MAXRET20_ANTI_RANK.parquet" `
  --sidecar-manifest "$out/sidecar/manifest.json" `
  --sidecar-sha256 $sidecarSha256 --verify-key-digest `
  --feature MAXRET20_ANTI_RANK --control-score `
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
  --sidecar "$out/sidecar/MAXRET20_ANTI_RANK.parquet" `
  --sidecar-sha256 $sidecarSha256 --verify-key-digest `
  --only-extra-feature MAXRET20_ANTI_RANK `
  --train 2020-01-01:2024-12-31 --valid 2025-01-01:2025-12-31 `
  --test 2026-01-01:2026-09-14 --no-portana `
  --out-dir "$out/model" --fail-if-out-exists

& $py -u my_scripts/diag_pred_pair.py `
  --control-recorder 8a061ea428e04bb3a199a485ade49d0e `
  --candidate-recorder <MAXRET_RECORDER_ID> `
  --control-pred-2025 my_scripts/预测结果_8a061ea4_2025valid.csv `
  --candidate-pred-2025 "$out/model/pred_2025.csv" `
  --label "Ref(`$close,-2)/Ref(`$close,-1)-1" --topk 10 `
  --top10-spread-vs common-universe-equal-weight `
  --window 2025-01-03:2025-12-31 `
  --window 2026-01-01:2026-09-14 `
  --block-days 5 --bootstrap-reps 10000 --seed 20260918 `
  --out-dir "$out/pred_pair" --fail-if-out-exists
```

`<MAXRET_RECORDER_ID>` 只能是本次单列候选训练新建的 recorder，并须记录 sidecar SHA-256、行键摘要、列名单和相对 `8a061ea4` 的配置 diff；无法证明唯一变量隔离时拒绝运行。

### 5.3 C 门：固定 10/3 paired PortAna

```powershell
& $py -u my_scripts/portana_pred_pair.py `
  --control-recorder 8a061ea428e04bb3a199a485ade49d0e `
  --candidate-recorder <MAXRET_RECORDER_ID> `
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

C 不得重导 sidecar 或改训练配置，只能沿用 B recorder 中的同一特征血缘；B 未全过时不得运行。

## 6. 10/3 与 50/5 永久分账

| 账 | 本刀允许回答 | 本刀禁止回答 |
|---|---|---|
| 线上导向 10/3 账 | 固定当前 label 与 `8a061ea4` 时，`MAXRET20_ANTI_RANK` 能否依次通过两窗信息门、模型门和固定 10/3 兑现门 | 即使全过也不能直接替换线上 pred/特征；2025 valid 不得写成可外推年化；2025/2026 NAV 不相加、不相乘 |
| 50/5 研究账 | 本刀不产生新 50/5 结果，只保留历史分账 | 不跑 50/5 PortAna；不用 50/5 历史 NAV、超额、过滤、止损或宽度结果选方向、选窗口、定阈值或证明 MXR1 对 10/3 有效 |

最终立场：**AMI1 已在 A 门证明固定 Amihud 条件增量证据不足，因此不改窗口或方向续跑，也不返回 CYQ/winratio、卖出或 horizon。下一刀只给 `MAXRET20_ANTI_RANK` 这个价格极端值假设一次“先信息、后模型、再固定 10/3 组合”的证伪机会；任一门失败，整把刀停止。**
