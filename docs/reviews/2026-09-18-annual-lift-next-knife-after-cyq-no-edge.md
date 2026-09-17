# 2026-09-18 · annual-lift 下一刀（T5-CYQ1 NO_EDGE 之后）

**性质**：只预注册一把刀、门和停手标签；本轮不实现、不导数、不算 IC、不重训、不跑 PortAna/BT、不改线上

**裁决**：选 **T5-WRD1：券商 `$winratio` − 精确 CYQ 的截面分歧残差**。这是一把显式新刀，不是 T5-CYQ1 换数据源续跑。

**线上默认**：仍为 **10/3 LGB**；默认 pred 仍为 `8a061ea4`（recorder `8a061ea428e04bb3a199a485ade49d0e`），全程只读。

一句话刀法：**固定当前标签、`8a061ea4` 和已跑过的 free/1000 精确 CYQ，唯一候选量取券商 `$winratio` 在逐日截面上不能被精确 CYQ 排名解释的“更深洗”残差；先检验它在控制现有 score 与精确 CYQ 后能否给 2025/2026 同向增量 RankIC，过门后才允许只加这一列重训，模型信号再过门后才允许做固定 10/3 的配对 PortAna。**

## 0. 上一刀结果与新刀一句话

PR #77 的 T5-CYQ1 已在 `newtest_4090` 跑完并停在 **A 门**，最终标签是 **`CYQ_CONDITIONAL_NO_EDGE`**：

| 窗 | mean partial RankIC | 5 日 moving-block bootstrap 95% CI | 判读 |
|---|---:|---:|---|
| 2025 valid | +0.032364 | [0.018986, 0.043564] | 有正向条件信息 |
| 2026 OOS | +0.016444 | [−0.005880, 0.037817] | 均值同号但 CI 下界不大于 0，证据不足 |

- 两窗没有反号，所以不是 FLIP；但预注册门要求 2026 CI 下界 `>0`，因此失败即停。
- T5-CYQ1 **未进入 B/C**，没有重训、没有 PortAna，未改 pred，也未改线上 10/3。
- 该刀使用 `build_winner_ratio.py --shares free --window 1000` 的唯一 CYQ 文件：`E:\stock_data\cyq_winner_ratio\t5_cyq1_2020_2026_20260917.parquet`，SHA-256 为 `d167d27916920ea7c49a3f0cb2202de2bb64b7a4425a7852de64f0b278c88a34`。本页只能只读复用，禁止重算或改口径。

**新刀一句话**：T5-WRD1 不再问“低获利盘是否有效”，只问“在精确 CYQ 给定后，券商口径相对它的异常分歧是否仍含有跨窗条件信息”。若 A 门不过，券商 `$winratio` 路线就地停止。

## 1. 为什么选这把，而不是重开已死路线

### 1.1 与 T5-CYQ1 不同的可证伪假设

两刀的问题和候选量不同：

| 刀 | 被检验的假设 | 候选量 |
|---|---|---|
| 已失败 T5-CYQ1 | 精确 free/1000 获利盘的**水平**越低，是否在现有 score 外仍预示更高未来收益 | `rank(-exact_winner_ratio)` |
| 新刀 T5-WRD1 | 给定精确 CYQ 水平后，券商因有效流通盘、除权处理、衰减或源数据口径而产生的**相对分歧**，是否在现有 score 外预示更高未来收益 | `rank(-$winratio)` 对 `rank(-exact_winner_ratio)` 的逐日截面 OLS 残差 |

现有对拍给这把刀一个具体而非任意的切口：券商 `$winratio` 与精确 CYQ 在 2026 年 909,663 个重叠样本上的 Spearman 为 `0.942`、MAE 为 `0.075`；整体排序很近，但仍有稳定的口径差。T5-WRD1 **只取不能被精确 CYQ 排名解释的剩余部分**，不以 raw `$winratio` 替换失败的 CYQ，也不再检验 `<10%` 门槛。

该假设可直接被证伪：若分歧残差在 2025/2026 不能给出同向、且 2026 CI 下界为正的 partial RankIC，说明口径差只是测量差异或噪声，而不是遗漏信息；此时禁止再试 raw `$winratio`、券商阈值、平滑、lag、交互项或另一种残差算法。

### 1.2 为什么不是相邻路线

| 路线 | 已有结论 | 本轮动作 |
|---|---|---|
| 精确 CYQ 网格 | T5-CYQ1 已是 `CYQ_CONDITIONAL_NO_EDGE`；2026 CI 穿 0 | free/1000 文件与方向只读冻结；不试 circ、250/500 窗、阈值、ASR/CKDW/PRP、QMT 或 CYQ 衍生量 |
| raw 券商 `$winratio` 换源 | 与精确 CYQ 高度同序，直接替换只是在 CYQ1 失败后偷换测量源 | 不测 raw 水平；只测预注册的“券商相对精确 CYQ 的正交分歧” |
| label / horizon | T5-LH3 已为 `LABEL_HORIZON_FLIP` | 不改标签，不扫 h=2/4/5/10 |
| 卖出 | T6-SX0 已为 `SCORE_EXIT_FLIP`；2025 `ΔNetReturn=+62.4339%`，2026 `−0.0342%`，2026 CI `[−39.54%, +40.36%]` | 不改 score 阈值、卖出数量、冷却、trail、止盈或止损 |
| 泛化特征池 | `turnover_resist_approx` 已从短窗 IC `+0.138` 翻到出窗 `−0.069`，且没有另一列预注册候选 | 不开字段筛选；本刀只有一个由既有对拍差异定义的候选量 |
| 行业/市值中性化 | M3D-D 已收官为默认关 | 本刀的残差化只隔离两种获利盘口径，不改 score 的行业/市值暴露，不重开中性化 |
| 扫闸/宽度/训练架构 | 2026 扫闸、止损、trail、止盈、宽度、`n_drop` 及换树、月滚、per-fold scaler 等均已封死 | 全部冻结，不作为失败后的救援分支 |

先做 A 门的原因也因此明确：券商黑盒口径有差异，不等于差异有预测信息。必须先证明它在两个已观察窗口中对当前标签有独立信息，才值得付出一次重训；不得先用 NAV 倒选特征。

## 2. 冻结表

| 层 | 锁定值 / 禁令 |
|---|---|
| 当前标签 | 只用 `Ref($close,-2)/Ref($close,-1)-1`；禁止换 label 或 horizon |
| 基线 pred | `8a061ea428e04bb3a199a485ade49d0e`；2026 原 `pred.pkl` 与 2025 同模型补分 CSV 只读，不覆盖、不回写；不读写 `55c5bf77` |
| 精确 CYQ 控制量 | 只读上一刀的 `t5_cyq1_2020_2026_20260917.parquet` 及上述 SHA-256；列为 free/1000 `winner_ratio`；禁止重建、舍入、换分母或换窗 |
| 券商源 | qlib 独立字段 `$winratio`，源口径 `[0,1]`、两位小数；后续执行时一次性导出 2020-01-02～2026-09-14 的不可变 sidecar 并记录 provider 快照、行键摘要与 SHA-256；A/B/C 共用，禁止中途刷新或换包 |
| 唯一候选特征 | `BROKER_WR_GAP`，严格按 §3.1 构造；不试 raw `$winratio`、差值、比值、阈值、分桶、平滑、lag、交互、方向翻转或另一种 rank/回归定义 |
| 宇宙 | 特征构造逐日使用冻结 `8a061ea4` handler 对应分段的样本索引，不因 `$winratio`/CYQ 缺失改写基线宇宙；A/B 比较只在共同有限样本上诊断，C 仍吃各臂全宇宙 pred |
| 训练 | A 全过后才可复制 `8a061ea4` 的 LGB 配置；唯一差异是在原 handler 帧左连一列 `BROKER_WR_GAP`；train 2020–2024、valid 2025、test 2026，seed/超参/早停/scaler/训练宇宙冻结；涨停出池开、`DropLimitUpLearn` 关 |
| 两窗 | A/B/C 统一为 2025 valid `2025-01-03～2025-12-31`、2026 OOS `2026-01-01～2026-09-14`；两窗均已被研究，不包装为新盲窗 |
| 组合 | 只有 B 全过后才可做 paired PortAna；固定 10/3、`hold_thresh=1`、top/bottom，buy-state/ST/年龄/5日15% 全关，止损/trail/止盈全关 |
| 尺子 | qlib `$close` 后复权 bin；买5bp/卖15bp/最低5；拒单0.095、不追买、整手向下；本金1e8、`risk_degree=0.95`、基准 SH000300 |
| 禁止项 | 不扫任何参数或特征；不换树、月滚、per-fold scaler、20/3、15% 关闸默认、大 handler 重建；不以 50/5 改 10/3 |
| 线上 | 全程仍为 `8a061ea4` + 10/3；即使全链成功也只得到候选标签，不自动替换 pred、特征或线上参数 |

## 3. A/B/C 有序门

### 3.1 A 门：分歧残差条件信息门；禁止重训与 PortAna

先在每个特征日 `t`，仅以当日可见数据构造唯一 sidecar 特征。构造不得读取 label 或未来数据：

1. 在冻结 handler 当日索引中，取精确 CYQ 与券商 `$winratio` 都有限的股票；两列均须在 `[0,1]`。
2. 用固定的 average-tie percentile rank 定义 `q = rank_pct(-exact_winner_ratio)`、`v = rank_pct(-$winratio)`；负号使“获利盘更低 / 更深洗”方向为正。
3. 当日做带截距 OLS `v ~ 1 + q`，取残差 `g`，写为唯一候选列 `BROKER_WR_GAP`。`g>0` 表示券商相对精确 CYQ 给出更强的“深洗”判断。样本不足、`q`/`v` 零方差、秩亏或非有限时，该日特征为缺失并记退化原因，不得填造数值。
4. A 门在 `score`、当前标签、`q`、`g` 均有限的共同样本上，令 `s=rank_pct(score)`、`y=rank_pct(label)`；分别做 `g ~ 1+s+q` 与 `y ~ 1+s+q`，取两组残差的 Pearson 相关，定义当日 **WR-gap partial RankIC**。

这一定义把现有 score 与已失败的精确 CYQ 水平同时列为控制量。A 门检验的是券商独有分歧，不得改成 `corr(-$winratio, label)`，也不得在看到结果后删去 `q` 以放大相关性。

每窗须报告 mean、median、ICIR、有效/退化日数及原因、共同股票数中位数、券商/精确 CYQ/联合缺失率；2026 按自然季度报告 mean WR-gap partial RankIC。对逐日值用 5 交易日 moving-block bootstrap，固定 10,000 次、seed `20260918`，报告 95% CI。

数据门同时要求：

- 2025、2026 的共同样本覆盖率均 `>=98%`；2020–2024 训练期覆盖率只报告，不另设研究门；
- feature day `t` 的两种获利盘只能使用截至 `t` 收盘的数据，A/B 均按 `(instrument, datetime)` 特征日索引对齐，禁止成交日偏移或 `pred_minus_one`；
- sidecar 的 `BROKER_WR_GAP` 必须与固定公式逐日复算一致；OLS 残差与 `q` 的样本内相关只允许浮点误差；
- 精确 CYQ SHA-256、券商 sidecar SHA-256、行键摘要一经写入 manifest，A/B/C 不得变化。

**A 门全过条件**：数据门通过；2025、2026 mean WR-gap partial RankIC 均 `>0`；2026 的 95% CI 下界 `>0`；2026 不得多数季度为负，也不得只靠一个季度为正。未全过立即进入 §4 失败瀑布，B/C 取消。

### 3.2 B 门：只加分歧残差一列重训，再做模型信号门

A 全过后才允许建立一个新 recorder：

- 对照仍是现成 `8a061ea4`，不得重训或覆盖。
- 候选只复制其冻结训练配置，并在现成 handler 帧按 `(instrument, datetime)` 左连同一 sidecar 的 `BROKER_WR_GAP`；不得同时加入 raw `$winratio`、精确 CYQ、缺失指示或其他衍生列。
- 少量缺失严格沿现网 `RobustZScoreNorm` 后 `Fillna(0)` 的链处理，不得因缺失删股票、换宇宙或另拟 scaler。
- 候选导出 2025 valid 与 2026 test 分数到新目录。在两窗共同样本上，以当前标签比较候选与基线的日 RankIC、Top10 等权信号差以及 `ΔRankIC` 的同口径 bootstrap CI；仍不得跑组合。

**B 门全过条件**：候选在 2025、2026 均同时满足 `RankIC(candidate)>RankIC(8a)` 与 `Top10Spread(candidate)>Top10Spread(8a)`；2026 `ΔRankIC` 的 95% CI 下界 `>0`；2026 不得多数季度为负或单季驱动。未全过立即停止，C 取消。

### 3.3 C 门：最后才做固定 10/3 paired PortAna

B 全过后，才允许对基线 pred 与候选 pred 做两窗配对 PortAna：

- 两臂唯一上游差异必须是 `BROKER_WR_GAP` 一列；输入 hash、组合、成交、费用、闸与窗口全部冻结。
- C 使用各臂全宇宙 pred，不以 A/B 的共同样本重定义组合宇宙。
- 每窗报告末值、区间收益、扣费年化超额、最大回撤、换手与费用；报告 2026 自然季度 `ΔNetReturn`，并对 2026 配对日收益差做同样 5 日、10,000 次、seed `20260918` 的 bootstrap CI。

**C 门全过条件**：2025、2026 均 `ΔNetReturn>0` 且扣费年化超额排序候选高于基线；2026 `ΔNetReturn` 的 95% CI 下界 `>0`；2026 `majority_negative=false` 且 `single_quarter_driven=false`。

季度口径在三门统一：保留截至 9 月 14 日的不完整 Q3；`majority_negative = 负增量季度数 / 季度数 > 50%`；`single_quarter_driven = 全窗增量 > 0 且正增量季度数 <= 1`。A 的增量是 WR-gap partial RankIC，B 是候选减基线的 RankIC/Top10 spread，C 是 locked-cost `ΔNetReturn`，不得混写。

## 4. 成功标签 / 失败瀑布

一次合规执行最终必须且只能产生下表中的**一个**终态标签；A/B 的“通过”只记 gate boolean，不另打中间标签，因此成功与所有失败标签互斥。

| 优先级 | 唯一终态标签 | 命中条件 | 停手动作 |
|---:|---|---|---|
| 1 | `WINRATIO_GAP_DATA_INVALID` | 任一数据/时点/覆盖/复算/hash/配置隔离门失败 | 停；只允许修实现错误后按原协议复跑，不得换源、改公式或改覆盖门 |
| 2 | `WINRATIO_GAP_CONDITIONAL_FLIP` | A 中 2025/2026 mean partial RankIC 反号，或 2026 多数季度为负 | 停；不翻方向、不挑季度、不退回 raw `$winratio` |
| 3 | `WINRATIO_GAP_CONDITIONAL_NO_EDGE` | 未命中 1/2，但 A 的 2026 CI 下界 `<=0`、单季驱动或任一 A 信息门不过 | 停；券商分歧路线关闭，不以重训/NAV 复活 |
| 4 | `WINRATIO_GAP_MODEL_NO_TRANSFER` | A 过而 B 任一窗 RankIC/Top10 spread 不同时胜基线，或 2026 CI/季度门不过 | 停；不加 raw winratio、第二列、交互、异 seed 或新树 |
| 5 | `WINRATIO_GAP_PORTANA_FLIP` | A/B 过而 C 的两窗 locked-cost `ΔNetReturn` 反号，或 2026 多数季度为负 | 停；不改 10/3、成本、闸、卖出或窗口 |
| 6 | `WINRATIO_GAP_PORTANA_NO_EDGE` | 未命中 1–5，但 C 的 2026 CI 下界 `<=0`、单季驱动或任一 C 门不过 | 停；不转扫宽度、`n_drop`、阈值或 50/5 |
| 7 | `WINRATIO_GAP_FEATURE_CANDIDATE` | A、B、C 全部通过 | 只登记候选；不自动改线上，是否需要新盲窗/BT 另立任务 |

优先级就是唯一裁决梯。程序崩溃、资源不足等运行错误不是研究 verdict；修复只能恢复本页固定语义。任一研究失败标签一旦命中，T5-WRD1 收工，禁止滑成 `source × threshold × smoothing × lag × residualization × seed` 网格。

## 5. 实现接口草案（本轮禁止执行）

以下仅定义未来实现 PR 的接口形状。当前 PR **不得创建这些脚本、不得导出 `$winratio`、不得计算 IC、不得重训、不得跑 PortAna/BT**。脚本目前不存在；未来实现必须对已存在输出目录 fail-closed，不得删除旧目录后复用。

### 5.1 一次性冻结 sidecar + A 门

```powershell
Set-Location D:\PycharmProjects\MyQuant
$py = "D:/anaconda3/envs/vanna312/python.exe"
$cyqFile = "E:/stock_data/cyq_winner_ratio/t5_cyq1_2020_2026_20260917.parquet"
$out = "exports/analysis/t5_wrd1_20260918"

& $py -u my_scripts/export_winratio_gap.py `
  --provider-uri "C:/Users/wangc/.qlib/qlib_data/my_data" `
  --broker-field "`$winratio" `
  --cyq-file $cyqFile --cyq-column winner_ratio `
  --cyq-sha256 d167d27916920ea7c49a3f0cb2202de2bb64b7a4425a7852de64f0b278c88a34 `
  --start 2020-01-02 --end 2026-09-14 `
  --rank-method average --direction lower `
  --feature-name BROKER_WR_GAP `
  --out-dir "$out/sidecar"

& $py -u my_scripts/diag_winratio_gap.py `
  --experiment alpha158_cost_kdj_lgb `
  --recorder-id 8a061ea428e04bb3a199a485ade49d0e `
  --pred-2025 my_scripts/预测结果_8a061ea4_2025valid.csv `
  --sidecar "$out/sidecar/BROKER_WR_GAP.parquet" `
  --feature BROKER_WR_GAP --control-cyq-column exact_winner_ratio `
  --label "Ref(`$close,-2)/Ref(`$close,-1)-1" `
  --window 2025-01-03:2025-12-31 `
  --window 2026-01-01:2026-09-14 `
  --min-coverage 0.98 --block-days 5 --bootstrap-reps 10000 --seed 20260918 `
  --out-dir "$out/information"
```

若 A gate boolean 不是全真，立即按 §4 裁决，禁止执行后两段。

### 5.2 B 门：只加一列训练与信号诊断

```powershell
& $py -u my_scripts/train_sidecar_feature_arm.py `
  --clone-recorder 8a061ea428e04bb3a199a485ade49d0e `
  --sidecar "$out/sidecar/BROKER_WR_GAP.parquet" `
  --only-extra-feature BROKER_WR_GAP `
  --train 2020-01-01:2024-12-31 --valid 2025-01-01:2025-12-31 `
  --test 2026-01-01:2026-09-14 --no-portana `
  --out-dir "$out/model"

& $py -u my_scripts/diag_pred_pair.py `
  --control-recorder 8a061ea428e04bb3a199a485ade49d0e `
  --candidate-recorder <WRD_RECORDER_ID> `
  --control-pred-2025 my_scripts/预测结果_8a061ea4_2025valid.csv `
  --candidate-pred-2025 "$out/model/pred_2025.csv" `
  --label "Ref(`$close,-2)/Ref(`$close,-1)-1" --topk 10 `
  --window 2025-01-03:2025-12-31 `
  --window 2026-01-01:2026-09-14 `
  --block-days 5 --bootstrap-reps 10000 --seed 20260918 `
  --out-dir "$out/pred_pair"
```

`<WRD_RECORDER_ID>` 只能是该唯一候选训练新建的 recorder。B 未全过即停，禁止运行 C。

### 5.3 C 门：最后才做 10/3 paired PortAna

```powershell
& $py -u my_scripts/portana_pred_pair.py `
  --control-recorder 8a061ea428e04bb3a199a485ade49d0e `
  --candidate-recorder <WRD_RECORDER_ID> `
  --control-pred-2025 my_scripts/预测结果_8a061ea4_2025valid.csv `
  --candidate-pred-2025 "$out/model/pred_2025.csv" `
  --window 2025-01-03:2025-12-31 `
  --window 2026-01-01:2026-09-14 `
  --topk 10 --n-drop 3 --hold-thresh 1 `
  --open-cost 0.0005 --close-cost 0.0015 --min-cost 5 `
  --account 100000000 --risk-degree 0.95 --benchmark SH000300 `
  --all-buy-gates-off --all-price-exits-off `
  --block-days 5 --bootstrap-reps 10000 --seed 20260918 `
  --out-dir "$out/portana_pair"
```

三个阶段都必须记录代码 commit、参数 JSON、provider 快照、输入 SHA-256、行键摘要、共同样本口径与候选/基线配置 diff。无法证明唯一变量隔离时，必须拒绝运行，不能手写研究标签。

## 6. 10/3 与 50/5 永久分账

| 账 | 本刀允许回答 | 本刀禁止回答 |
|---|---|---|
| 线上导向 10/3 账 | 固定当前标签与 `8a061ea4` 时，券商相对精确 CYQ 的口径分歧能否依次通过两窗信息门、模型门与固定 10/3 兑现门 | 即使全过也不能直接替换线上 pred/特征；不能把 2025 valid 当未来年化；2025/2026 NAV 不相加、不相乘 |
| 50/5 研究账 | 只保留作历史对齐、机制归因与审计 | 不得把 109.65M/114.64M、+23.1%/+29.3% 超额、CYQ 过滤或止损峰值搬来证明 WRD1 对 10/3 有效；不得用 50/5 选方向、阈值或成功门 |

最终立场：**T5-CYQ1 已否定“精确 CYQ 水平有足够稳定的条件增量”，T5-WRD1 只给已有跨源对拍中尚未回答的“口径分歧残差”一次先信息、后模型、再组合的证伪机会。它不是 CYQ 参数补跑，也不为已经死亡的卖出或 horizon 路线开后门；任何一门失败，整把刀停止。**
