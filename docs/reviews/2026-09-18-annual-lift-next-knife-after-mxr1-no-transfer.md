# 2026-09-18 · annual-lift 下一刀（MAXRET_MODEL_NO_TRANSFER 之后）

**性质**：只预注册一把刀、有序门和互斥终态标签。本轮**不实现、不导数、不计算 IC/RankIC、不重训、不跑 PortAna/BT、不改线上**。

**裁决**：选 **T5-BETA1：固定 60 个市场交易日、相对沪深300的滚动 OLS beta 反向截面秩**，只允许一列 `BETA60_ANTI_RANK`。

**线上默认**：仍为 **10/3 LGB**；默认 pred 仍为 `8a061ea4`（recorder `8a061ea428e04bb3a199a485ade49d0e`），全程只读。

一句话刀法：**固定当前 label、`8a061ea4`、原 handler 宇宙和唯一 60 日 beta 公式，先检验“较低的沪深300系统性暴露”是否在 2025/2026 对现有 score 有同向正的增量 RankIC；A 过才允许只加 `BETA60_ANTI_RANK` 一列重训，B 过才允许做固定 10/3 的配对 PortAna，任一门失败即停。**

## 0. 上一刀结果与新刀一句话

T5-MXR1 已在 `newtest_4090` 收工，最终标签是 **`MAXRET_MODEL_NO_TRANSFER`**。刀法基线为 PR #80 @ `112faf4`，sidecar SHA-256 为 `27320f8b7f6de3854802f97325f682039732470ce387f21bc9cd6c3083b7b348`，候选 recorder 为 `d03e8ffcb6d14668b4d6fc2b192bc8c7`：

| 门 | 已知结果 | 裁决 |
|---|---|---|
| A 条件信息门 | 2025 mean MAXRET partial RankIC `+0.044092`，交接未单列其 CI；2026 为 `+0.038542`，95% CI `[+0.004456, +0.073341]` | A 过 |
| B 模型信号门 | 2025 Top10Spread 候选未胜基线 `8a061ea4`，交接未给出具体 Top10 数值；2026 `ΔRankIC` 95% CI 下沿 `-0.000556 <= 0` | B 失败并停止 |
| C 组合门 | 未进入 | 未跑 PortAna/BT |

该次执行未改 pred、未改线上 10/3。本页不补造未披露的 2025 CI、2025 Top10Spread 或其他模型指标。

**新刀一句话**：T5-BETA1 不再改写单股 20 日极端收益，而是唯一检验股票对共同市场波动的 60 日系统性暴露；低 beta 是否含有现有单股技术/筹码 score 尚未吸收的跨窗信息，先由条件信息门回答。

## 1. 为什么在 MXR1 的 B 门失败后选这把

### 1.1 MXR1 留下的约束

MXR1 的 A 门已证明 `MAXRET20_ANTI_RANK` 自身存在条件信息，但 B 门证明这不等于加进冻结 LGB 后能稳定改善两窗头部排序。所以下一刀必须同时遵守两点：不把 MAXRET 改方向、改窗口或改极值定义来追 B 门；新假设即使通过信息门，也仍须重新通过模型信号门，不能凭 A 门直接跑 NAV。

T5-BETA1 切换到基线特征缺少的**跨资产共同波动**维度。对股票 `i`、特征日 `t`，固定市场基准 `m = SH000300`：

```text
r[i,d] = close[i,d] / close[i,d-1] - 1
r[m,d] = close[m,d] / close[m,d-1] - 1
r[i,d] = alpha[i,t] + beta60[i,t] * r[m,d] + epsilon[i,d]
             for d = t-59..t
BETA60_ANTI_RANK[i,t] = rank_pct_cross_section(-beta60[i,t])
```

- 股票和沪深300都只用冻结 qlib provider 的后复权 `$close`；基准代码固定为 `SH000300`，不得换等权市场收益、全 A 收益、中证500或行业指数。
- `t-59..t` 是包含 `t` 的固定 60 个市场交易日收益，最多读取 61 个 close 点。OLS 固定带截距；在该固定窗内至少需要 40 个股票/基准均有限且 close `>0` 的配对收益，禁止向 `t-60` 之前扩窗凑样本、前向填充或以 0 补收益。
- 基准的 60 个收益必须全部有限且其样本方差 `>0`；股票有效配对少于 40、回归秩亏或 beta 非有限时，该行缺失并记录原因。
- 截面只在冻结 handler 当日成员与有效 `beta60` 的交集上，用 `pandas.Series.rank(method="average", pct=True)` 对 `-beta60` 排一次。值越大表示对沪深300的系统性暴露越低。
- 唯一预注册方向是“`BETA60_ANTI_RANK` 越高 -> 当前 label 的期望收益越高”，对应低 beta/拥挤高 beta 的横截面假设。若结果为负，不得现场去掉负号。

这不是候选池：只有一个 60 日窗、一个沪深300基准、一个带截距 OLS beta、一个反向截面秩和一个方向。不得追加 20/120/250 日、滚动相关、下行 beta、残差波动、行业 beta、等权市场 beta、shrinkage、winsorize、阈值、分箱、lag、交互、异 seed 或第二棵树。

### 1.2 为什么不是相邻死亡路线

| 路线 | 已有裁决 | 本轮边界 |
|---|---|---|
| MAXRET 方向/窗口/定义变体 | `MAXRET_MODEL_NO_TRANSFER`，A 过但 B 停 | 不试 `MAXRET20_RANK`、5/10/60 日、`$high`、top-3 平均、隔夜/日内拆分、阈值或 lag；BETA1 不取最大值，也不把 beta 与 MAXRET 联合训练 |
| 精确 CYQ | `CYQ_CONDITIONAL_NO_EDGE`，停在 A | 不重算 free/1000，不改 shares/window/threshold，不把 CYQ 并入候选列 |
| 券商 winratio 残差 | `WINRATIO_GAP_MODEL_NO_TRANSFER`，A 过但 B 停 | 不试 raw `$winratio`、另一种残差、平滑、lag、交互、异 seed 或新树 |
| 固定 Amihud | `AMIHUD_CONDITIONAL_NO_EDGE`，停在 A | 不改窗口、方向、成交额归一或变换；BETA1 不使用 `$amount`，不是流动性冲击补跑 |
| 卖出 / horizon | `SCORE_EXIT_FLIP` / `LABEL_HORIZON_FLIP` | 不改卖出、trail、止盈、止损、持有期或 label，也不扫宽度、`n_drop` 或闸 |
| 换树 / 月滚 / scaler / 大 handler | 已有停手结论 | A 过后也只复制 `8a061ea4` 的冻结训练配置并左连一列，不借新特征重开训练架构 |

选 BETA1 的原因是它回答一个此前各刀都没有回答的问题：单股相对共同市场收益的**系统性敏感度**是否提供条件增量。MXR1 度量一只股票自身 20 日路径中的单日上尾，BETA1 度量 60 日成对收益的协方差斜率；二者的数据结构、经济假设和统计量均不同。它也不依赖已经失败的筹码水平、跨源获利盘差异或成交额价格冲击。Alpha158 可能已间接吸收部分波动信息，因此 A 门必须控制现有 score；若没有剩余信息，直接以 BETA 条件信息失败标签收工，不以“LGB 也许能学到”越门。

## 2. 冻结表

| 层 | 锁定值 / 禁令 |
|---|---|
| 当前 label | 只用 `Ref($close,-2)/Ref($close,-1)-1`；禁止换 label 或 horizon |
| 基线 pred | `8a061ea428e04bb3a199a485ade49d0e`；2026 `pred.pkl` 与 2025 同模型补分 CSV 只读，不覆盖、不回写；不读写 `55c5bf77` |
| 唯一候选 | `BETA60_ANTI_RANK`，严格按 §1.1 构造；禁止窗口、基准、回归、方向、变换、阈值、lag、交互或 seed 网格 |
| 原始数据 | 只读与 `8a061ea4` 一致的冻结 qlib provider 快照及股票/`SH000300` 的 `$close`；记录 provider 路径、快照指纹、交易日历指纹、基准序列指纹和代码 commit；A 后不得刷新数据 |
| 构造时点 | 特征日 `t` 只用 `t` 及以前数据；固定 60 市场日窗内至少 40 个有效配对收益，不向更早日期扩窗，不填补停牌/缺失收益 |
| 构造宇宙 | 先按冻结市场日历逐股票算 `beta60`，再只在 `alpha158_cost_kdj_lgb / 8a061ea4` 冻结 handler 的当日索引与有效值交集上排一次截面秩；不得先全市场 rank 再切 handler |
| 唯一 sidecar | 一次性导出覆盖 train/valid/test 的不可变 sidecar，至少保留 `(instrument, datetime)`、窗起止、有效配对数、基准方差、`beta60`、`BETA60_ANTI_RANK`、有效性与缺失原因；写 SHA-256 和行键摘要。A 只切片，B 只左连这一份，C 只认 B recorder 血缘中的同一 SHA-256 |
| 两窗 | A/B/C 统一为 2025 valid `2025-01-03~2025-12-31`、2026 OOS `2026-01-01~2026-09-14`；两窗均已被研究，不包装为新盲窗 |
| 训练 | A 全过后才可复制 `8a061ea4` 的 LGB 配置；唯一差异是向原 handler 帧左连一列 `BETA60_ANTI_RANK`；train 2020-2024、valid 2025、test 2026，seed、超参、早停、scaler、训练宇宙全冻结，涨停出池开、`DropLimitUpLearn` 关 |
| 组合 | B 全过后才可做 paired PortAna；只有 10/3，`hold_thresh=1`、top/bottom；buy-state、ST、年龄、5 日 15% 全关，止损、trail、止盈全关 |
| 尺子 | qlib `$close` 后复权 bin；买 5bp / 卖 15bp / 最低 5；拒单 0.095、不追买、整手向下；本金 1e8、`risk_degree=0.95`、基准 SH000300 |
| 禁止项 | 不扫任何参数或特征；不换树、月滚、per-fold scaler、20/3、50/5 PortAna、15% 关闸默认或大 handler 重建；不把 MAXRET、CYQ、winratio、Amihud 中间产物并入本刀 |
| 线上 | 全程仍为 `8a061ea4` + 10/3；即使全链成功也只得到候选标签，不自动替换 pred、特征或线上参数 |

## 3. A/B/C 有序门

### 3.1 A 门：跨窗条件信息门；禁止重训与 PortAna

先从冻结 provider 快照一次性构造唯一 sidecar。导出器须为 2020 起始日读取至多 60 个前置市场交易日用于热身，但只输出冻结 handler 键；不得读取 label，也不得在 A 通过后重算历史。

数据门：

- `SH000300` 的日期、close、收益和指纹唯一；股票与基准必须按同一冻结市场交易日配对。任何自动换基准、使用当日截面均值代替基准或基准缺日插值均为数据失败。
- 每个 `(instrument, datetime)` 的窗口边界、有效配对数、带截距 OLS beta 和截面成员必须可复算；等值用 average rank，不得以股票代码破 tie。
- sidecar 必须通过列集、唯一键、日期范围、provider/日历/基准/sidecar hash、行键摘要、随机抽样复算与时点检查。
- A/B 重叠键上的 `BETA60_ANTI_RANK` 必须逐值一致；任何 hash、成员集合或值不一致均为 `BETA_DATA_INVALID`。
- 2025、2026 的共同样本覆盖率均须 `>=98%`。分母是冻结 handler 当日有限 score 行，分子是其中 score、当前 label 和候选列均有限的行；另报股票 close 非法、有效配对不足、基准异常、回归退化等缺失原因。
- feature day `t` 与 score/label 按同一 `(instrument, datetime)` 键对齐；禁止 `pred_minus_one`、成交日偏移或使用 `t+1` 数据。

信息量定义：每个特征日，在 score、label、`BETA60_ANTI_RANK` 均有限且 `n>=4` 的共同样本上，令 `s=rank_pct(score)`、`b=BETA60_ANTI_RANK`、`y=rank_pct(label)`；分别做 `b ~ 1+s` 与 `y ~ 1+s`，取两组残差的 Pearson 相关，定义当日 **BETA partial RankIC**。残差化只用于信息门，候选训练列仍只能是 sidecar 中的 `BETA60_ANTI_RANK`，不得另造“BETA 对 score 残差”训练列。

每窗报告 mean、median、ICIR、有效/退化日数与原因、共同股票数中位数及覆盖率；2026 按自然季度报告 mean BETA partial RankIC。对逐日 IC 做 5 交易日 moving-block bootstrap，固定 10,000 次、seed `20260918`，报告 95% CI。

**A 门全过条件**：数据门通过；2025、2026 mean BETA partial RankIC 均 `>0`；2026 的 95% CI 下界 `>0`；2026 不得多数季度为负，也不得只靠一个季度为正。未全过立即按 §4 裁决，B/C 取消。

### 3.2 B 门：只加一列重训，再做模型信号门

A 全过后才允许建立一个新 recorder：

- 对照仍是现成 `8a061ea4`，不得重训或覆盖。
- 候选只复制其冻结训练配置，在现成 handler 帧按 `(instrument, datetime)` 左连同一 sidecar 的 `BETA60_ANTI_RANK`；不得同时加 raw `beta60`、alpha、残差波动、相关系数、缺失指示、MAXRET、CYQ、winratio、Amihud 或其他衍生列。
- 少量缺失只沿用现网的 `RobustZScoreNorm` 后 `Fillna(0)` 链，不得删股票、换宇宙或另拟 scaler。
- 只导出候选 2025 valid 和 2026 test 分数到新目录。在两窗共同样本上，以当前 label 比较候选与基线的日 RankIC、Top10Spread 和 `ΔRankIC` 的同口径 bootstrap CI。Top10Spread 固定为等权 Top10 减共同宇宙等权，禁止换成 Top10-Bottom10；此时仍不得跑组合。

**B 门全过条件**：候选在 2025、2026 均同时满足 `RankIC(candidate)>RankIC(8a)` 与 `Top10Spread(candidate)>Top10Spread(8a)`；2026 `ΔRankIC` 的 95% CI 下界 `>0`；2026 不得多数季度为负或单季驱动。未全过立即停止，C 取消。

### 3.3 C 门：最后才做固定 10/3 paired PortAna

B 全过后，才允许对基线 pred 与候选 pred 做两窗配对 PortAna：

- 两臂唯一上游差异必须是 `BETA60_ANTI_RANK` 一列；输入 hash、组合、成交、费用、闸和窗口全部冻结。
- C 使用各臂全宇宙 pred，不用 A/B 的共同有限样本重定义组合宇宙。
- 每窗报告末值、区间收益、扣费年化超额、最大回撤、换手与费用；报告 2026 自然季度 `ΔNetReturn`，并对 2026 配对日收益差做同样 5 日、10,000 次、seed `20260918` 的 bootstrap CI。

**C 门全过条件**：2025、2026 均 `ΔNetReturn>0` 且扣费年化超额排序候选高于基线；2026 `ΔNetReturn` 的 95% CI 下界 `>0`；2026 `majority_negative=false` 且 `single_quarter_driven=false`。

三门的 2026 季度口径统一：保留截至 9 月 14 日的不完整 Q3；`majority_negative = 负增量季度数 / 季度数 > 50%`；`single_quarter_driven = 全窗增量 > 0 且正增量季度数 <= 1`。A 的增量是 BETA partial RankIC，B 是候选减基线的 RankIC/Top10Spread，C 是 locked-cost `ΔNetReturn`，不得混写。

## 4. 成功标签 / 失败瀑布

一次合规执行最终必须且只能产生下表中的**一个**终态标签。A/B 的“通过”只记 gate boolean，不另打中间成功标签；裁决按优先级自上而下，命中即停止，因此成功标签与所有失败标签互斥。

| 优先级 | 唯一终态标签 | 命中条件 | 停手动作 |
|---:|---|---|---|
| 1 | `BETA_DATA_INVALID` | 任一数据、基准、时点、覆盖、公式复算、hash、行键或配置隔离门失败 | 停；只允许修实现错误后按原协议复跑，不得换基准、窗口或公式 |
| 2 | `BETA_CONDITIONAL_FLIP` | A 中 2025/2026 mean partial RankIC 反号，或 2026 多数季度为负 | 停；不翻方向、不挑季度、不换 beta 定义 |
| 3 | `BETA_CONDITIONAL_NO_EDGE` | 未命中 1/2，但任一窗均值 `<=0`、2026 CI 下界 `<=0`、单季驱动或任一 A 信息门不过 | 停；不改窗口、基准、最小样本数、方向或变换 |
| 4 | `BETA_MODEL_NO_TRANSFER` | A 过而 B 任一窗 RankIC/Top10Spread 不同时胜基线，或 2026 CI/季度门不过 | 停；不加 raw beta、第二列、交互、异 seed 或新树 |
| 5 | `BETA_PORTANA_FLIP` | A/B 过而 C 的两窗 locked-cost `ΔNetReturn` 反号，或 2026 多数季度为负 | 停；不改 10/3、成本、闸、卖出或窗口 |
| 6 | `BETA_PORTANA_NO_EDGE` | 未命中 1-5，但 C 的 2026 CI 下界 `<=0`、单季驱动或任一 C 门不过 | 停；不转扫宽度、`n_drop`、阈值或 50/5 |
| 7 | `BETA_FEATURE_CANDIDATE` | A、B、C 全部通过 | 只登记候选；不自动改线上，是否需要新盲窗/实盘观察另立任务 |

程序崩溃、资源不足等运行错误不是研究 verdict；修复只能恢复本页冻结语义。任一研究失败标签一旦命中，T5-BETA1 收工，禁止滑成 `benchmark x lookback x beta-definition x direction x transform x seed x model` 网格。

## 5. 实现接口草案（本轮禁止执行）

以下只定义未来实现 PR 的接口形状。**当前 PR 不得创建这些脚本、不得导出 sidecar、不得计算 IC/RankIC、不得重训、不得跑 PortAna/BT。**脚本名均为未来接口，不假定当前仓已存在；所有阶段遇到既存输出目录须 fail-closed，不得删除、清空或复用旧目录。

### 5.1 唯一 sidecar + A 门

```powershell
$py = "D:/anaconda3/envs/vanna312/python.exe"
$out = "exports/analysis/t5_beta1_20260918"

& $py -u my_scripts/export_beta60_sidecar.py `
  --experiment alpha158_cost_kdj_lgb `
  --recorder-id 8a061ea428e04bb3a199a485ade49d0e `
  --handler-index-source recorder-handler `
  --provider-uri "C:/Users/wangc/.qlib/qlib_data/my_data" `
  --freeze-provider-snapshot --close-field "`$close" `
  --benchmark SH000300 --lookback-market-days 60 `
  --return close-to-close --ols-with-intercept --min-valid-pairs 40 `
  --no-window-extension --no-return-imputation `
  --multiply-before-rank -1 `
  --rank-method average --rank-pct pandas-pct-true `
  --feature-name BETA60_ANTI_RANK `
  --emit-source-qc --emit-benchmark-digest --emit-hash-and-key-digest `
  --out-dir "$out/sidecar" --fail-if-out-exists

$sidecarSha256 = "<SIDECAR_SHA256_EMITTED_BY_EXPORT_MANIFEST>"

& $py -u my_scripts/diag_conditional_information.py `
  --experiment alpha158_cost_kdj_lgb `
  --recorder-id 8a061ea428e04bb3a199a485ade49d0e `
  --pred-2025 my_scripts/预测结果_8a061ea4_2025valid.csv `
  --sidecar "$out/sidecar/BETA60_ANTI_RANK.parquet" `
  --sidecar-manifest "$out/sidecar/manifest.json" `
  --sidecar-sha256 $sidecarSha256 --verify-key-digest --verify-benchmark-digest `
  --feature BETA60_ANTI_RANK --control-score `
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
  --sidecar "$out/sidecar/BETA60_ANTI_RANK.parquet" `
  --sidecar-sha256 $sidecarSha256 --verify-key-digest `
  --only-extra-feature BETA60_ANTI_RANK `
  --train 2020-01-01:2024-12-31 --valid 2025-01-01:2025-12-31 `
  --test 2026-01-01:2026-09-14 --no-portana `
  --out-dir "$out/model" --fail-if-out-exists

& $py -u my_scripts/diag_pred_pair.py `
  --control-recorder 8a061ea428e04bb3a199a485ade49d0e `
  --candidate-recorder <BETA_RECORDER_ID> `
  --control-pred-2025 my_scripts/预测结果_8a061ea4_2025valid.csv `
  --candidate-pred-2025 "$out/model/pred_2025.csv" `
  --label "Ref(`$close,-2)/Ref(`$close,-1)-1" --topk 10 `
  --top10-spread-vs common-universe-equal-weight `
  --window 2025-01-03:2025-12-31 `
  --window 2026-01-01:2026-09-14 `
  --block-days 5 --bootstrap-reps 10000 --seed 20260918 `
  --out-dir "$out/pred_pair" --fail-if-out-exists
```

`<BETA_RECORDER_ID>` 只能是本次单列候选训练新建的 recorder，并须记录 sidecar SHA-256、行键摘要、列名单和相对 `8a061ea4` 的配置 diff；无法证明唯一变量隔离时拒绝运行。

### 5.3 C 门：固定 10/3 paired PortAna

```powershell
& $py -u my_scripts/portana_pred_pair.py `
  --control-recorder 8a061ea428e04bb3a199a485ade49d0e `
  --candidate-recorder <BETA_RECORDER_ID> `
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
| 线上导向 10/3 账 | 固定当前 label 与 `8a061ea4` 时，`BETA60_ANTI_RANK` 能否依次通过两窗信息门、模型门和固定 10/3 兑现门 | 即使全过也不能直接替换线上 pred/特征；2025 valid 不得写成可外推年化；2025/2026 NAV 不相加、不相乘 |
| 50/5 研究账 | 本刀不产生新 50/5 结果，只保留历史分账 | 不跑 50/5 PortAna；不用 50/5 历史 NAV、超额、过滤、止损或宽度结果选方向、选窗口、定阈值或证明 BETA1 对 10/3 有效 |

最终立场：**MXR1 已证明“有条件信息”仍可能无法转移到冻结模型的两窗头部排序，因此不翻 MAXRET 方向、不改窗，也不返回 CYQ/winratio/Amihud、卖出或 horizon。下一刀只给 `BETA60_ANTI_RANK` 这个跨资产系统性暴露假设一次“先信息、后模型、再固定 10/3 组合”的证伪机会；任一门失败，整把刀停止。**
