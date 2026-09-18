# 2026-09-17 · annual-lift T5 残部刀法（LH3 + SX0 FLIP 之后）

**性质**：只预注册一把刀、门和停手标签；本轮不实现、不重训、不跑 IC、不跑 PortAna/BT、不改线上

**裁决**：选 **CYQ**，编号 **T5-CYQ1**；不选泛化特征池，不重开行业/市值中性化

**线上默认**：仍是 **10/3 LGB**；默认 pred 仍是 `8a061ea4`（recorder `8a061ea428e04bb3a199a485ade49d0e`）

**依据**：PR #74 的 annual-lift handoff、PR #75 的 T5-LH3 预检及其 FLIP 交接、PR #76 的 T6-SX0 刀法，以及 `t6-sx0-flip-result.md` 的实跑结果

一句话刀法：**固定当前标签与 `8a061ea4`，先检验精确 CYQ 获利盘比例在控制现有 score 后能否给 2025/2026 同向增量 RankIC；只有过门才允许给原 LGB 增加这一列，模型信号再次过门后才允许做固定 10/3 的配对 PortAna。**

这是一条有先后闸门的单刀，不是“CYQ/特征/阈值”的菜单。任一闸失败，后续阶段取消，禁止改口径继续试。

## 1. 两记 FLIP 已经回答了什么

### 1.1 T5-LH3：`LABEL_HORIZON_FLIP`

上一把把当前一持有期标签与唯一的三持有期标签做了两窗预检，结果已经封死标签周期路线：

| 窗 / 切片 | 已披露结果 | 裁决含义 |
|---|---|---|
| 2025 valid | 候选 `ΔRankIC ≈ +0.012`，但候选 Top10 信号差反而低于当前标签 | 横截面相关与头部兑现分叉，S2 不过 |
| 2026 OOS | `ΔRankIC ≈ 0`，95% CI 穿 0；候选 Top10 信号差为负 | 没有 OOS 增量证据，头部方向也错 |
| 2026 季度 | Q2、Q3 的 `ΔRankIC` 为负 | 不是稳定的小正增量 |

因此 verdict 为 **`LABEL_HORIZON_FLIP`**。以上 `≈` 是现有交接披露的约数；不伪造交接中没有附带的精确 `window_summary`。动作已经锁死：不再换 label，不扫 h=2/4/5/10，也不借另一个窗口复活 horizon。

### 1.2 T6-SX0：`SCORE_EXIT_FLIP`

固定同一 `8a061ea4`、固定 10/3 全关后，候选只增加 `score <= 0` 的额外卖出，结果仍然跨窗翻转：

| 窗 | 对照 C | SX0 候选 X | `ΔNetReturn = X-C` |
|---|---:|---:|---:|
| 2025 | +190.61% | +253.04% | **+62.4339%** |
| 2026 | −12.940% | −12.974% | **−0.0342%** |

- S0 语义隔离通过，但 S1 因两窗反号不过。
- 2026 的 5 日 moving-block bootstrap 95% CI 为 **[−39.54%, +40.36%]**，穿 0，S2 不过。
- S3 单独看通过：Q1 **+1.40%**、Q2 **−2.73%**、Q3 **+0.94%**，`majority_negative=false`、`single_quarter_driven=false`；但不能越过 S1/S2。
- SX0 并非没有触发：2025 为 **486 笔 / 206 日**，2026 为 **201 笔 / 109 日**。

因此 verdict 为 **`SCORE_EXIT_FLIP`**。这说明问题不是“零阈值没被用到”，而是这类额外卖出在两个已观察窗口不能迁移。下一刀不再改卖出阈值、数量、冷却期、trail、止盈或止损；应先问现有 score 之外是否还有跨窗稳定的信息。

## 2. 为什么只选 CYQ

三条 T5 残部并不处于同一起跑线：

| 残部 | 已有证据 | 本轮裁决 |
|---|---|---|
| 泛化特征 | `turnover_resist_approx` 已从短窗 IC **+0.138** 翻到出窗 **−0.069**；当前没有另一列已经预注册且无需筛选 | 不开特征候选池；否则会退化为按 2026 挑列的网格 |
| 行业/市值中性化 | M3D-D 已做 raw/industry/size/both 两窗；长窗名单重叠高、命中不改善，短窗大改名单但命中原地，结论是默认关 | 不以“再换窗”重开已收官路线 |
| 精确 CYQ | 本仓算法与 SSOT/Rust 同输入可对到浮点误差；对 QMT 的 Spearman **0.921**、MAE **0.066**、`<10%` 召回 **0.950**，对券商 `winratio` 的 Spearman **0.942** | 测量质量已足够；尚未回答的唯一问题是：它在相近现有 score 下，是否仍有 2025/2026 独立增量 |

过去 CYQ 的正面线索主要来自 50/5 宽名单和资格过滤语境，不能直接搬到 10/3。T5-CYQ1 不把 `<10%` 过滤器再开一次，也不预设 PortAna 会涨；它先用条件 RankIC 判断“这列到底有没有被 `8a061ea4` 漏掉的信息”。这正好避开 LH3 的标签错配路线和 SX0 的卖出路线。

## 3. 冻结清单

| 层 | 锁定值 / 禁令 |
|---|---|
| 标签 | 只用当前 `Ref($close,-2)/Ref($close,-1)-1`；禁止改 label 或 horizon |
| 基线 pred | `8a061ea428e04bb3a199a485ade49d0e`；2026 原 `pred.pkl`、2025 同模型补分 CSV 均只读，不覆盖、不回写；`55c5bf77` 也不读写 |
| 唯一候选量 | `my_scripts/build_winner_ratio.py` 的连续 `winner_ratio`；`--shares free --window 1000 --step 0.01`。信息门固定看 `cyq_signal = -winner_ratio`，即获利盘越低，信号越高 |
| 唯一 CYQ 数据件 | 只运行一次 `build_winner_ratio.py --test 2020-01-01:2026-09-14 --window 1000 --step 0.01 --shares free`，生成一份 2020–2026 parquet；A/B/C 共用该文件及其 SHA-256，A 只切片 2025/2026，禁止另建短窗文件或过 A 后按更长历史重算 |
| CYQ 变体 | 不试 `circ`、券商 `winratio`、QMT、Quantile 代理、Rust 数值、ASR/CKDW/PRP、阈值或衍生窗口；不做跨仓筹码量拼接 |
| 训练 | 只有信息门过后才可复制 `8a061ea4` 的 LGB 配置，唯一差异是把同一 CYQ sidecar 在现成 handler 帧上按 `(instrument, datetime)` 左连为原始连续列 `CYQ_WR_1000_FREE`，禁止为这一列重做 9×11G 表达式；train 2020–2024、valid 2025、test 2026、seed/超参/早停/scaler/训练宇宙全冻结；涨停出池开、`DropLimitUpLearn` 关 |
| 组合 | PortAna 只有模型信号门过后才可运行；固定 10/3、`hold_thresh=1`、top/bottom，买入状态/ST/年龄/5日15% 全关，止损/trail/止盈全关 |
| 两窗 | A/B/C 统一为 2025 valid `2025-01-03～2025-12-31`、2026 OOS `2026-01-01～2026-09-14`；本刀不跑 BT，不另设成交首日窗口 |
| 尺子 | qlib `$close` 后复权 bin；买5bp/卖15bp/最低5；拒单0.095、不追买、整手向下；本金1e8、`risk_degree=0.95`、基准 SH000300 |
| 已死路线 | 不换树、不月滚、不 per-fold scaler、不跑 20/3、不把关 15% 升默认、不重建 9×11G handler；不扫闸/止损/trail/止盈/宽度/`n_drop` |
| 线上 | 始终仍是 `8a061ea4` + 10/3；即使本刀全过也只得到候选标签，不自动替换 pred 或线上参数 |

2025 是早停/valid 已消费窗，2026 也已被反复研究；两者都不是新盲窗。两窗只用于同向与 OOS 强度门，不把已见窗口包装成上线证据。

## 4. 具体刀法：T5-CYQ1 有序单刀

### 4.1 A 段：先做条件信息门，禁止 PortAna

在每个交易日的共同样本上，只保留 `score`、当前标签、`winner_ratio` 均有限的股票：

1. 令 `s = percentile_rank(score)`、`c = percentile_rank(-winner_ratio)`、`y = percentile_rank(label)`。
2. 当日分别做 `c ~ 1 + s` 与 `y ~ 1 + s` 的 OLS，取两组残差的 Pearson 相关，定义为当日 **CYQ partial RankIC**。这是控制现有 score 后的截面秩增量，不是把 CYQ 与 score 任意加权。
3. 两窗的主统计量是日 CYQ partial RankIC 的 **mean**；同时报 median、ICIR、有效日数、退化日数及原因、共同股票数中位数、CYQ 缺失率，2026 按自然季度列 mean partial RankIC。截面样本不足以估计上述 OLS/Pearson，或任一残差为零方差/非有限时，该日不得填 0，须剔除，并分别披露退化日数与剔除后的有效日数。
4. 对每日 partial RankIC 用 5 交易日 moving-block bootstrap，固定 10,000 次、seed `20260917`，报 95% CI。

共同样本只用于诊断；不得因 CYQ 缺失重定义 `8a061ea4` 宇宙。两窗共同样本覆盖率均须至少 98%，值域须在 `[0,1]`，日期 t 的 CYQ 只能使用截至 t 收盘的数据。A/B 的 `score`、pred 与标签均按 `(instrument, datetime)` 的**特征日索引**对齐；不得用成交日偏移或 `pred_minus_one` 计算 RankIC。训练臂中极少量缺失严格沿现网链在 `RobustZScoreNorm` 后 `Fillna(0)`，不得另加缺失指示列；2020–2024 训练期的 CYQ 覆盖率必须报告，但不另开杀门。

A 段不是独立造数阶段：它只从冻结的 2020–2026 CYQ parquet 切片 2025/2026。qlib 日历左端为 `2020-01-02`，会裁掉 `--window 1000` 所需的左侧热身，因此 2020 段存在冷启动；这不算改变 CYQ 口径，也不得据此把 `--window` 改成 250/500，或改用券商 `$winratio`。A 切片与 B/C 实际左连的重叠日 `winner_ratio` 必须来自同一文件且数值一致；任何重算、舍入或预处理造成的不一致一律记 `CYQ_DATA_INVALID` 并停止。

### 4.2 B 段：A 过门后，只加一列训练并再过信号门

A 段全过后，只允许复用 A 已读取的同一份 2020–2026 CYQ 文件建立一个新 recorder；不得再生成或替换 CYQ parquet：

- 对照仍是现成 `8a061ea4`，不重训、不覆盖。
- 候选复制其训练配置，在现成 handler 帧上按 `(instrument, datetime)` 左连同一 sidecar，只在特征矩阵末尾加入原始连续 `CYQ_WR_1000_FREE = winner_ratio`；禁止为新增列重做 9×11G 表达式，LGB 自己决定非线性方向，不增加 `<10%` 指示器或其他 CYQ 派生量。
- 候选同时导出 2025 valid 与 2026 test 分数到新目录。
- 在两窗共同样本上，按特征日索引以当前标签比较候选与 `8a061ea4` 的日 RankIC、Top10 等权信号差，以及 `ΔRankIC` 的同口径 bootstrap CI；不得用 `pred_minus_one` 做 A/B 诊断，仍不跑组合。

### 4.3 C 段：B 过门后，才允许 10/3 PortAna

B 段全过后，才对基线 pred 与候选 pred 做两窗配对 PortAna。两臂的唯一上游差异必须是来自同一冻结 CYQ parquet 的那一列特征；组合、成本、成交、闸和窗口完全一致。C 段用全宇宙 pred 做 PortAna，不以 A/B 的共同样本替代组合输入。输出两臂的输入 hash、末值、区间收益、扣费年化超额、最大回撤、换手、费用，并报季度 `ΔNetReturn` 和 2026 配对日收益差的 5 日 block-bootstrap 95% CI。

PortAna 是第三段，不得用 A 段的 partial RankIC 直接推算 NAV，也不得在 A/B 失败后“跑一下看看”。本刀不授权 BT；PortAna 过门后是否需要新盲窗/BT，另立任务，不在本刀追加。

## 5. 成功门、失败标签与停手规则

### 5.1 全链成功

| 门 | 预注册判据 |
|---|---|
| S0 · 数据/语义 | A/B/C 使用同一份 CYQ parquet 及 SHA-256，A 切片与 B/C 左连的重叠日数值一致；两窗共同样本覆盖率均 `>=98%`；CYQ 值域、t 日可得性通过；B/C 候选配置 diff 只能出现一列 `CYQ_WR_1000_FREE`；训练期覆盖率只报告、不设门 |
| S1 · 条件信息 | 2025、2026 的 mean CYQ partial RankIC 均 `>0`；2026 的 5 日 block-bootstrap 95% CI 下界 `>0`；2026 不得多数季度为负，也不得只靠一个季度为正 |
| S2 · 模型传递 | 候选模型在 2025、2026 均同时满足 `RankIC(candidate)>RankIC(8a)` 与 `Top10Spread(candidate)>Top10Spread(8a)`；2026 `ΔRankIC` 的 95% CI 下界 `>0`，季度稳定性通过 |
| S3 · 组合兑现 | 固定 10/3 locked-cost PortAna 在 2025、2026 均 `ΔNetReturn>0` 且扣费年化超额排序候选>基线；2026 `ΔNetReturn` 的 95% CI 下界 `>0`，`majority_negative=false`、`single_quarter_driven=false` |

S0–S3 全过才打 **`CYQ_FEATURE_CANDIDATE`**。它只表示“精确 CYQ 单列在两个已观察窗口完成了信息→模型→组合的同向传递”，不表示已经获得新盲窗或可以改线上。

A 段通过时只记中间状态 `CYQ_INFORMATION_PASS`，B 段通过时只记 `CYQ_MODEL_SIGNAL_PASS`；二者都不是最终成功标签，也都不授权跳过下一道门。

2026 季度稳定性统一按自然季度切分，并保留截至 9 月 14 日的不完整 Q3：

- `majority_negative = 负增量季度数 / 季度数 > 50%`；
- `single_quarter_driven = 全窗增量 > 0 且正增量季度数 <= 1`。

A 段的“增量”是 partial RankIC，B 段是候选减基线的 RankIC/Top10 spread，C 段是 locked-cost `ΔNetReturn`；三段指标不得混写。

### 5.2 失败标签按阶段互斥裁决

| 优先级 | 标签 | 命中条件 | 动作 |
|---:|---|---|---|
| 1 | `CYQ_DATA_INVALID` | S0 不过，或 A 切片与 B/C 的重叠日 `winner_ratio` 不一致 | 停；只允许修数据可得性/代码错误后按原协议重跑，不得另建短窗/长窗数据件或改 CYQ 口径 |
| 2 | `CYQ_CONDITIONAL_FLIP` | A 段 2025/2026 mean partial RankIC 反号，或 2026 多数季度为负 | CYQ 单列路线停止；不改方向、不切季度、不试阈值 |
| 3 | `CYQ_CONDITIONAL_NO_EDGE` | 未翻号但 A 段 2026 CI 下界 `<=0`，或只靠单季 | 证据不足即停；不得以 PortAna 复活 |
| 4 | `CYQ_MODEL_NO_TRANSFER` | A 过而 B 任一窗 `RankIC(candidate)<=RankIC(8a)`、任一窗 `Top10Spread(candidate)<=Top10Spread(8a)`，或 2026 CI/季度门不过 | 独立信息没有传进模型或头部兑现不成立；停，不加第二个 CYQ 特征、不改树/seed/早停 |
| 5 | `CYQ_PORTANA_FLIP` | A/B 过而 C 段 2025/2026 locked-cost `ΔNetReturn` 反号，或 2026 多数季度为负 | 组合兑现窗口依赖；停，不改 10/3 或成本救结果 |
| 6 | `CYQ_PORTANA_NO_EDGE` | 未翻号但 C 段 2026 CI 下界 `<=0`、单季驱动或任一 S3 条件不过 | 无可兑现增量；停，不转扫阈值、宽度、`n_drop` 或卖出 |

运行/实现错误不是研究 verdict。修复只能恢复本页固定语义；任一研究失败标签一旦命中，整把 T5-CYQ1 收工，禁止滑成 `shares × window × threshold × feature × seed` 网格。

## 6. 后续跑数命令草案（本轮不执行）

以下是未来实现 PR 的接口草案，**本轮禁止执行**。当前仓已有 `build_winner_ratio.py`；`diag_cyq_increment.py`、`train_cyq_feature_arm.py`、`diag_pred_pair.py`、`portana_pred_pair.py` 尚不存在，须在后续实现 PR 中按本页协议落地，并对已存在输出目录 fail-closed，不能删除后复用。

### 6.1 唯一一次 CYQ 构建 + A 段条件 RankIC

```powershell
Set-Location D:\PycharmProjects\MyQuant
$py = "D:/anaconda3/envs/vanna312/python.exe"
$cyqFile = "F:/stock_data/cyq_winner_ratio/t5_cyq1_2020_2026_20260917.parquet"

& $py -u my_scripts/build_winner_ratio.py `
  --test 2020-01-01:2026-09-14 --window 1000 --step 0.01 `
  --shares free --workers 8 --out $cyqFile

& $py -u my_scripts/diag_cyq_increment.py `
  --experiment alpha158_cost_kdj_lgb `
  --recorder-id 8a061ea428e04bb3a199a485ade49d0e `
  --pred-2025 my_scripts/预测结果_8a061ea4_2025valid.csv `
  --cyq-file $cyqFile --cyq-column winner_ratio --direction lower `
  --label "Ref(`$close,-2)/Ref(`$close,-1)-1" `
  --window 2025-01-03:2025-12-31 `
  --window 2026-01-01:2026-09-14 `
  --min-coverage 0.98 --block-days 5 --bootstrap-reps 10000 --seed 20260917 `
  --out-dir exports/analysis/t5_cyq1_information_20260917
```

若终端 verdict 不是 `CYQ_INFORMATION_PASS`，立即停，不执行后两段。

`build_winner_ratio.py` 在整把 T5-CYQ1 中只允许执行上述一次。A 诊断必须从 `$cyqFile` 切出 2025/2026，并记录整文件 SHA-256 与切片行键/数值摘要；后续 B/C 必须校验同一 SHA-256 和重叠日数值，任一不一致立即输出 `CYQ_DATA_INVALID`。不得在 A 通过后换成长历史文件重算，也不得为绕开 2020 冷启动另建短窗 parquet。

### 6.2 B 段：只加一列训练 + 模型信号门

```powershell
& $py -u my_scripts/train_cyq_feature_arm.py `
  --clone-recorder 8a061ea428e04bb3a199a485ade49d0e `
  --cyq-file $cyqFile --cyq-column winner_ratio `
  --feature-name CYQ_WR_1000_FREE --only-extra-feature CYQ_WR_1000_FREE `
  --train 2020-01-01:2024-12-31 --valid 2025-01-01:2025-12-31 `
  --test 2026-01-01:2026-09-14 --no-portana `
  --out-dir exports/analysis/t5_cyq1_model_20260917

& $py -u my_scripts/diag_pred_pair.py `
  --control-recorder 8a061ea428e04bb3a199a485ade49d0e `
  --candidate-recorder <CYQ_RECORDER_ID> `
  --control-pred-2025 my_scripts/预测结果_8a061ea4_2025valid.csv `
  --candidate-pred-2025 exports/analysis/t5_cyq1_model_20260917/pred_2025.csv `
  --window 2025-01-03:2025-12-31 `
  --window 2026-01-01:2026-09-14 `
  --label "Ref(`$close,-2)/Ref(`$close,-1)-1" --topk 10 `
  --block-days 5 --bootstrap-reps 10000 --seed 20260917 `
  --out-dir exports/analysis/t5_cyq1_pred_pair_20260917
```

`<CYQ_RECORDER_ID>` 只能替换为上一步新建 recorder；若 verdict 不是 `CYQ_MODEL_SIGNAL_PASS`，立即停，不执行 PortAna。

### 6.3 C 段：最后才做两窗 10/3 PortAna

```powershell
& $py -u my_scripts/portana_pred_pair.py `
  --control-recorder 8a061ea428e04bb3a199a485ade49d0e `
  --candidate-recorder <CYQ_RECORDER_ID> `
  --control-pred-2025 my_scripts/预测结果_8a061ea4_2025valid.csv `
  --candidate-pred-2025 exports/analysis/t5_cyq1_model_20260917/pred_2025.csv `
  --window 2025-01-03:2025-12-31 `
  --window 2026-01-01:2026-09-14 `
  --topk 10 --n-drop 3 --hold-thresh 1 `
  --open-cost 0.0005 --close-cost 0.0015 --min-cost 5 `
  --account 100000000 --risk-degree 0.95 --benchmark SH000300 `
  --all-buy-gates-off --all-price-exits-off `
  --block-days 5 --bootstrap-reps 10000 --seed 20260917 `
  --out-dir exports/analysis/t5_cyq1_portana_pair_20260917
```

三个阶段都须记录代码 commit、参数 JSON、输入文件 SHA-256、共同样本口径和输出目录。任何脚本若不能证明配置 diff 只有预注册项，应拒绝运行而不是给研究 verdict。

## 7. 两本账的永久边界

| 账 | 本刀允许回答 | 不允许回答 |
|---|---|---|
| 线上导向 10/3 账 | 同一当前标签、固定 10/3 时，单列精确 CYQ 能否依次通过两窗信息门、模型门和 PortAna 兑现门 | 即使全过也不能直接替换 `8a061ea4`、改线上或把 2025 valid 当未来年化；2025/2026 NAV 不相加、不相乘 |
| 50/5 研究账 | 保留作现尺子对齐、机制归因与历史审计 | 不得把 109.65M/114.64M、+23.1%/+29.3% 超额、过滤或止损单窗峰值搬来证明 CYQ 对 10/3 有效；不得用 50/5 选 CYQ 阈值或改本刀成功门 |

最终立场：**SX0 已证明继续改卖出没有跨窗证据；T5-CYQ1 只检验一个更靠前的问题——精确筹码状态是否提供现有 score 尚未吸收、且能从 IC 一路传到固定 10/3 的信息。** 如果这条链中任何一环断掉，就按对应失败标签停止，不再从 T5 残部拼第二把刀。
