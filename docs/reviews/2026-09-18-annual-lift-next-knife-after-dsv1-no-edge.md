# 2026-09-18 · annual-lift 下一刀（DSEM_CONDITIONAL_NO_EDGE 之后）

**性质**：只预注册一把刀、有序门和互斥终态标签。本轮**不实现、不导数、不计算 IC/RankIC、不重训、不跑 PortAna/BT、不改线上**。

**裁决**：选 **T5-H52A1：固定 252 个市场交易日的年高点接近度截面秩**，只允许一列 `HIGH252_PROX_RANK`。

**线上默认**：仍为 **10/3 LGB**；默认 pred 仍为 `8a061ea4`（recorder `8a061ea428e04bb3a199a485ade49d0e`），全程只读。

一句话刀法：**固定当前 label、`8a061ea4`、原 handler 宇宙和唯一 252 日最高收盘价锚，先检验“价格越接近过去一年最高收盘价”是否在 2025/2026 对现有 score 有同向正的增量 RankIC；A 全过才允许只加 `HIGH252_PROX_RANK` 一列重训，B 全过才允许做固定 10/3 的配对 PortAna，任一门失败即停。**

## 0. 上一刀结果与新刀一句话

T5-DSV1 已在 `newtest_4090` 收工，最终标签为 **`DSEM_CONDITIONAL_NO_EDGE`**，停在 A 门；B/C 未跑，没有重训、PortAna 或 BT。刀法尖是 PR #82 commit `2e64556a22a623b13826d4664f88b6ea35f715cb`，sidecar SHA-256 为 `dc9fe981bba49c3e61910bd155bb3d674d56919a902b13244e351b06e26498d1`。

失败特征 `DSEM20_ANTI_RANK` 是固定 20 个市场交易日下行半偏差的反向截面秩：`r = adj close / prev adj close - 1`，`down = min(r, 0)`，`dsem20 = sqrt(mean(down^2))` 覆盖 `t-19..t` 且分母固定为 20，再在冻结 handler 当日索引与有效 `dsem20` 的交集上对 `-dsem20` 做 `rank(method="average", pct=True)`。窗口内没有负收益时 `dsem20=0` 是有效值。

| 窗 | mean DSEM partial RankIC | 95% CI | 裁决所需事实 |
|---|---:|---:|---|
| 2025 | +0.020675 | 未报告 | 均值为正 |
| 2026 | +0.030425 | [-0.008751, +0.070781] | 均值为正，但 CI 下沿不大于 0 |

两窗均值同号为正，所以这不是方向翻转；2026 的 CI 穿过 0，表示预注册方向的证据强度不足，因此停止。2026 也不是多数季度为负或单季驱动，但交接没有报告季度均值或天数，这两项事实不能推翻 CI 门。本页不补造未报告的 median、ICIR、天数、季度数字、Top10 或 B 门数字。

数据门已经通过：覆盖率 2025 为 99.00%、2026 为 98.24%，均达到不低于 98% 的门槛。因此 `DSEM_CONDITIONAL_NO_EDGE` 不是数据无效，更不授权换定义寻找显著性。

**新刀一句话**：T5-H52A1 离开日收益二阶矩与共同市场暴露，唯一检验一个固定的一年价格锚——当前收盘价接近过去 252 个市场交易日最高收盘价，是否还有现有 score 未吸收的跨窗信息。

## 1. 为什么只选 T5-H52A1

### 1.1 唯一、冻结且可证伪的假设

对股票 `i`、特征日 `t`，只使用冻结 qlib provider 的后复权 `$close`：

```text
high_close_252[i,t] = max(close[i,d], d = t-251..t)
high252_prox[i,t] = close[i,t] / high_close_252[i,t]
HIGH252_PROX_RANK[i,t] = rank_pct_cross_section(high252_prox[i,t])
```

- `t-251..t` 固定为包含 `t` 的 252 个市场交易日，共 252 个 close；全部必须有限且 `>0`。任一点不合格则该行缺失，禁止向更早日期扩窗、前向填充或按个股上市长度改成可变窗。
- 分母只取这 252 个后复权**收盘价**的最大值；不用日内 `$high`，不取最大单日收益，也不使用复权前价格。由于窗口包含 `t`，有限合法值应满足 `0 < high252_prox <= 1`；越界即数据错误，不截断回合法区间。
- 截面只在冻结 handler 当日成员与有效 `high252_prox` 的交集上，用 `pandas.Series.rank(method="average", pct=True)` 排一次；值越大表示越接近过去一年最高收盘价。
- 唯一预注册方向是“`HIGH252_PROX_RANK` 越高，当前 label 的期望收益越高”，对应投资者围绕年高点锚定、信息缓慢反映的假设。结果为负时不得现场翻方向。

252 是“一年市场交易日价格锚”的唯一语义，不是从 5/10/20/60/120/250/252 中筛出的窗口。本刀没有距离历史低点、区间位置、突破指示、阈值、分箱、winsorize、EWMA、lag、交互、异 seed 或第二棵树；也不把 252 改成“上市以来”或允许不完整窗口。因此它是一把单刀，不是 price-anchor 特征池。

Alpha158/KDJ/DDX 可能已经间接包含较短窗的价格位置或动量信息，本页不把“经典因子”当成有效性证明。A 门必须先控制现有 score；若一年锚没有剩余条件信息，就在最便宜的 A 门停止，不以“树可能学到非线性”越门。

### 1.2 DSEM 的结果为什么不能用来改 DSEM

`DSEM_CONDITIONAL_NO_EDGE` 回答的是冻结 `DSEM20_ANTI_RANK` 在当前两窗和当前控制变量下，尚无足够强的稳定条件增量；它没有回答“相反方向更好”或“另一种波动定义更好”：

- 两窗 mean partial RankIC 都为正，方向已经同向；翻成 `rank(+dsem20)` 会事后反选已观察方向，并不修复证据不足。
- 2026 CI 穿 0 是停止线，不是把 20 日改成 5/10/60/120 日以购买更窄 CI 的邀请。
- 分母 20、`down=min(r,0)` 和完整窗口是已执行假设本身；改成 19、只在负收益日内平均、把 `dsem20=0` 当缺失，都会换掉估计量。
- total volatility、upside volatility、Sortino、阈值、分箱、winsorize、EWMA、lag、另一 seed 或新树，都属于在看到失败后扩展同一家族，禁止。
- 覆盖门已过，所以也不能借“数据可能无效”重算另一种 DSEM。

T5-H52A1 不估收益方差或半方差，不区分正负收益日，也不利用 DSEM sidecar。它比较的是当前价格与一年最高**价格水平**的比例，是独立的锚定/缓慢反映假设；选择它不是为了修复 DSEM，而是让一个尚未检验、定义正交的假设从 A 门重新开始。

### 1.3 为什么也不重开其他死亡路线

| 已停止路线 | 已有裁决 | T5-H52A1 的边界 |
|---|---|---|
| BETA | `BETA_CONDITIONAL_FLIP` | 不翻 beta 方向，不改 60 日窗、截距、收益定义或基准；H52A1 不使用市场序列、协方差、相关或回归 |
| MAXRET | `MAXRET_MODEL_NO_TRANSFER` | 不翻 `MAXRET20_ANTI_RANK`，不改其窗口，不用 `$high`、top-3、隔夜/日内拆分；H52A1 不取任何单日收益极值。`max(close)` 只定义固定一年价格锚，随后使用当前价/锚的比例，不是 MAXRET 的变体或补救 |
| 固定 Amihud | `AMIHUD_CONDITIONAL_NO_EDGE` | 不读 `$amount`，不改 Amihud 的窗口、方向或归一方式；价格锚不度量成交冲击 |
| 精确 CYQ | `CYQ_CONDITIONAL_NO_EDGE` | 不读或重算 winner-ratio，不改 shares/window/threshold，不使用筹码水平 |
| winratio 残差 | `WINRATIO_GAP_MODEL_NO_TRANSFER` | 不读 `$winratio`，不换残差、平滑或 lag，不使用跨源筹码口径差 |
| label / horizon | `LABEL_HORIZON_FLIP` | 当前 label 原样冻结，不试任何新 horizon |
| `score<=0` 卖出 | `SCORE_EXIT_FLIP` | 不改卖出、trail、止盈、止损、宽度、`n_drop` 或执行阈值 |

同时继续禁止 2026 扫闸、止损、trail、止盈、宽度或 `n_drop`，以及换树、月滚、per-fold scaler、20/3、把 15% 关闸升为默认、大 handler 重建和用 50/5 研究账改线上 10/3。新刀即使通过 A，也必须重新证明信息能传到冻结模型，再证明能在固定 10/3 兑现；不能用任何死亡路线的中间产物拼特征。

## 2. 冻结表

| 层 | 锁定值 / 禁令 |
|---|---|
| 当前 label | 只用 `Ref($close,-2)/Ref($close,-1)-1`；禁止换 label 或 horizon |
| 基线 pred | `8a061ea428e04bb3a199a485ade49d0e`；2026 `pred.pkl` 与 2025 同模型补分 CSV 只读，不覆盖、不回写；不读写 `55c5bf77` |
| 唯一候选 | `HIGH252_PROX_RANK`，严格按 §1.1 构造；禁止窗口、价格字段、方向、变换、阈值、lag、交互或 seed 网格 |
| 原始数据 | 只读与 `8a061ea4` 一致的冻结 qlib provider 快照及 `$close`；记录 provider 路径、快照指纹、交易日历指纹和代码 commit；A 后不得刷新数据 |
| 构造时点 | 特征日 `t` 只使用 `t` 及以前数据；固定 252 个市场日 close 全部有效，不扩窗、不填补、不使用 `t+1` 数据 |
| 构造宇宙 | 先按冻结市场日历逐股票算 `high252_prox`，再只在 `alpha158_cost_kdj_lgb / 8a061ea4` 冻结 handler 的当日索引与有效值交集上排一次截面秩；不得先在另一市场池 rank 再切 handler |
| 唯一 sidecar | 一次性导出覆盖 train/valid/test 的不可变 sidecar，至少保留 `(instrument, datetime)`、窗起止、有效 close 数、`high_close_252`、最高收盘价日期、`high252_prox`、`HIGH252_PROX_RANK` 与缺失原因；写 SHA-256 和行键摘要。A 只切片，B 只左连这一份，C 只认 B recorder 血缘中的同一 SHA-256 |
| 两窗 | A/B/C 统一为 2025 valid `2025-01-03~2025-12-31`、2026 OOS `2026-01-01~2026-09-14`；两窗均已被研究，不包装为新盲窗 |
| 训练 | A 全过后才可复制 `8a061ea4` 的 LGB 配置；唯一差异是向原 handler 帧左连一列 `HIGH252_PROX_RANK`；train 2020-2024、valid 2025、test 2026，seed、超参、早停、scaler、训练宇宙全冻结，涨停出池开、`DropLimitUpLearn` 关 |
| 组合 | B 全过后才可做 paired PortAna；只有 10/3，`hold_thresh=1`、top/bottom；buy-state、ST、年龄、5 日 15% 全关，止损、trail、止盈全关 |
| 尺子 | qlib `$close` 后复权 bin；买 5bp / 卖 15bp / 最低 5；拒单 0.095、不追买、整手向下；本金 1e8、`risk_degree=0.95`、基准 SH000300 |
| 禁止项 | 不扫任何参数或特征；不换树、月滚、per-fold scaler、20/3、50/5 PortAna、15% 关闸默认或大 handler 重建；不把 DSEM、BETA、MAXRET、Amihud、CYQ、winratio 中间产物并入本刀 |
| 线上 | 全程仍为 `8a061ea4` + 10/3；即使全链成功也只得到候选标签，不自动替换 pred、特征或线上参数 |

## 3. A/B/C 有序门

### 3.1 A 门：跨窗条件信息门；禁止重训与 PortAna

先从冻结 provider 快照一次性构造唯一 sidecar。导出器可以为 2020 起始日读取恰好 251 个前置市场交易日用于热身，但只输出冻结 handler 键；不得读取 label，也不得在 A 通过后重算历史。

数据门：

- 每个 `(instrument, datetime)` 的 252 日窗口边界、有效 close 数、最高收盘价及其日期、比例和截面成员必须可复算；最高值并列时仅为审计记录保留最早日期，不参与特征值或排序破 tie。
- sidecar 必须通过列集、唯一键、日期范围、provider/日历/sidecar hash、行键摘要、随机抽样复算和时点检查。
- A/B 重叠键上的 `HIGH252_PROX_RANK` 必须逐值一致；任何 hash、成员集合或数值不一致均为 `H52_DATA_INVALID`。
- 2025、2026 的共同样本覆盖率均须 `>=98%`。分母是冻结 handler 当日有限 score 行，分子是其中 score、当前 label 与候选列均有限的行；另报上市历史不足、close 非法或窗口不完整等缺失原因。覆盖不足即停止，不得放宽为 `min_periods`、可变窗或“上市以来高点”。
- feature day `t` 与 score/label 按同一 `(instrument, datetime)` 键对齐；禁止 `pred_minus_one`、成交日偏移或使用 `t+1` 数据。

信息量定义：每个特征日，在 score、label、`HIGH252_PROX_RANK` 均有限且 `n>=4` 的共同样本上，令 `s=rank_pct(score)`、`h=HIGH252_PROX_RANK`、`y=rank_pct(label)`；分别做 `h ~ 1+s` 与 `y ~ 1+s`，取两组残差的 Pearson 相关，定义当日 **H52 partial RankIC**。残差化只用于信息门；候选训练列仍只能是 sidecar 中的 `HIGH252_PROX_RANK`，不得另造“H52 对 score 残差”训练列。

每窗报告 mean、median、ICIR、有效/退化日数与原因、共同股票数中位数及覆盖率；2026 按自然季度报告 mean H52 partial RankIC。对逐日 IC 做 5 交易日 moving-block bootstrap，固定 10,000 次、seed `20260918`，报告 95% CI。

**A 门全过条件**：数据门通过；2025、2026 mean H52 partial RankIC 均 `>0`；2026 的 95% CI 下界 `>0`；2026 不得多数季度为负，也不得只靠一个季度为正。未全过立即按 §4 裁决，B/C 取消。

### 3.2 B 门：只加一列重训，再做模型信号门

A 全过后才允许建立一个新 recorder：

- 对照仍是现成 `8a061ea4`，不得重训或覆盖。
- 候选只复制其冻结训练配置，在现成 handler 帧按 `(instrument, datetime)` 左连同一 sidecar 的 `HIGH252_PROX_RANK`；不得同时加入 raw `high252_prox`、`high_close_252`、距高点天数、突破指示、缺失指示、其他窗口或任何死亡路线特征。
- 少量缺失只沿用现网的 `RobustZScoreNorm` 后 `Fillna(0)` 链，不得删股票、换宇宙或另拟 scaler。
- 只导出候选 2025 valid 和 2026 test 分数到新目录。在两窗共同样本上，以当前 label 比较候选与基线的日 RankIC、Top10Spread 和 `ΔRankIC` 的同口径 bootstrap CI。Top10Spread 固定为等权 Top10 减共同宇宙等权，禁止换成 Top10-Bottom10；此时仍不得跑组合。

**B 门全过条件**：候选在 2025、2026 均同时满足 `RankIC(candidate)>RankIC(8a)` 与 `Top10Spread(candidate)>Top10Spread(8a)`；2026 `ΔRankIC` 的 95% CI 下界 `>0`；2026 不得多数季度为负或单季驱动。未全过立即停止，C 取消。

### 3.3 C 门：最后才做固定 10/3 paired PortAna

B 全过后，才允许对基线 pred 与候选 pred 做两窗配对 PortAna：

- 两臂唯一上游差异必须是 `HIGH252_PROX_RANK` 一列；输入 hash、组合、成交、费用、闸和窗口全部冻结。
- C 使用各臂全宇宙 pred，不用 A/B 的共同有限样本重定义组合宇宙。
- 每窗报告末值、区间收益、扣费年化超额、最大回撤、换手与费用；报告 2026 自然季度 `ΔNetReturn`，并对 2026 配对日收益差做同样 5 日、10,000 次、seed `20260918` 的 bootstrap CI。

**C 门全过条件**：2025、2026 均 `ΔNetReturn>0` 且扣费年化超额排序候选高于基线；2026 `ΔNetReturn` 的 95% CI 下界 `>0`；2026 `majority_negative=false` 且 `single_quarter_driven=false`。

三门的 2026 季度口径统一：保留截至 9 月 14 日的不完整 Q3；`majority_negative = 负增量季度数 / 季度数 > 50%`；`single_quarter_driven = 全窗增量 > 0 且正增量季度数 <= 1`。A 的增量是 H52 partial RankIC，B 是候选减基线的 RankIC/Top10Spread，C 是 locked-cost `ΔNetReturn`，不得混写。

## 4. 成功标签 / 失败瀑布

一次合规执行最终必须且只能产生下表中的**一个**终态标签。A/B 的“通过”只记 gate boolean，不另打中间成功标签；裁决按优先级自上而下，命中即停止，所以成功标签与所有失败标签互斥。

| 优先级 | 唯一终态标签 | 命中条件 | 停手动作 |
|---:|---|---|---|
| 1 | `H52_DATA_INVALID` | 任一数据、时点、覆盖、公式复算、hash、行键或配置隔离门失败 | 停；只允许修实现错误后按原协议复跑，不得放宽完整窗、改价格字段或窗口 |
| 2 | `H52_CONDITIONAL_FLIP` | A 中 2025/2026 mean partial RankIC 反号，或 2026 多数季度为负 | 停；不翻方向、不挑季度、不换价格锚定义 |
| 3 | `H52_CONDITIONAL_NO_EDGE` | 未命中 1/2，但任一窗均值 `<=0`、2026 CI 下界 `<=0`、单季驱动或任一 A 信息门不过 | 停；不改窗口、完整性、方向或变换 |
| 4 | `H52_MODEL_NO_TRANSFER` | A 过而 B 任一窗 RankIC/Top10Spread 不同时胜基线，或 2026 CI/季度门不过 | 停；不加 raw 比例、第二列、交互、异 seed 或新树 |
| 5 | `H52_PORTANA_FLIP` | A/B 过而 C 的两窗 locked-cost `ΔNetReturn` 反号，或 2026 多数季度为负 | 停；不改 10/3、成本、闸、卖出或窗口 |
| 6 | `H52_PORTANA_NO_EDGE` | 未命中 1-5，但 C 的 2026 CI 下界 `<=0`、单季驱动或任一 C 门不过 | 停；不转扫宽度、`n_drop`、阈值或 50/5 |
| 7 | `H52_FEATURE_CANDIDATE` | A、B、C 全部通过 | 只登记候选；不自动改线上，是否需要新盲窗/实盘观察另立任务 |

程序崩溃、资源不足等运行错误不是研究 verdict；修复只能恢复本页冻结语义。任一研究失败标签一旦命中，T5-H52A1 收工，禁止滑成 `lookback x anchor-definition x direction x transform x seed x model` 网格。

## 5. 实现接口草案（本轮禁止执行）

以下只定义未来实现 PR 的接口形状。**当前 PR 不得创建这些脚本、不得导出 sidecar、不得计算 IC/RankIC、不得重训、不得跑 PortAna/BT。**脚本名不代表仓库中已经存在实现。所有阶段对既存输出目录都必须 fail-closed，不得删除、清空或复用旧目录。

### 5.1 唯一 sidecar + A 门

```powershell
$py = "D:/anaconda3/envs/vanna312/python.exe"
$out = "exports/analysis/t5_h52a1_20260918"

& $py -u my_scripts/export_high252_prox_sidecar.py `
  --experiment alpha158_cost_kdj_lgb `
  --recorder-id 8a061ea428e04bb3a199a485ade49d0e `
  --handler-index-source recorder-handler `
  --provider-uri "C:/Users/wangc/.qlib/qlib_data/my_data" `
  --freeze-provider-snapshot --close-field "`$close" `
  --lookback-market-days 252 --require-complete-window `
  --anchor highest-close --ratio current-close-over-anchor `
  --no-window-extension --no-close-imputation `
  --rank-method average --rank-pct pandas-pct-true `
  --feature-name HIGH252_PROX_RANK `
  --emit-source-qc --emit-hash-and-key-digest `
  --out-dir "$out/sidecar" --fail-if-out-exists

$sidecarSha256 = "<SIDECAR_SHA256_EMITTED_BY_EXPORT_MANIFEST>"

& $py -u my_scripts/diag_conditional_information.py `
  --experiment alpha158_cost_kdj_lgb `
  --recorder-id 8a061ea428e04bb3a199a485ade49d0e `
  --pred-2025 my_scripts/预测结果_8a061ea4_2025valid.csv `
  --sidecar "$out/sidecar/HIGH252_PROX_RANK.parquet" `
  --sidecar-manifest "$out/sidecar/manifest.json" `
  --sidecar-sha256 $sidecarSha256 --verify-key-digest `
  --feature HIGH252_PROX_RANK --control-score `
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
  --sidecar "$out/sidecar/HIGH252_PROX_RANK.parquet" `
  --sidecar-sha256 $sidecarSha256 --verify-key-digest `
  --only-extra-feature HIGH252_PROX_RANK `
  --train 2020-01-01:2024-12-31 --valid 2025-01-01:2025-12-31 `
  --test 2026-01-01:2026-09-14 --no-portana `
  --out-dir "$out/model" --fail-if-out-exists

& $py -u my_scripts/diag_pred_pair.py `
  --control-recorder 8a061ea428e04bb3a199a485ade49d0e `
  --candidate-recorder <H52_RECORDER_ID> `
  --control-pred-2025 my_scripts/预测结果_8a061ea4_2025valid.csv `
  --candidate-pred-2025 "$out/model/pred_2025.csv" `
  --label "Ref(`$close,-2)/Ref(`$close,-1)-1" --topk 10 `
  --top10-spread-vs common-universe-equal-weight `
  --window 2025-01-03:2025-12-31 `
  --window 2026-01-01:2026-09-14 `
  --block-days 5 --bootstrap-reps 10000 --seed 20260918 `
  --out-dir "$out/pred_pair" --fail-if-out-exists
```

`<H52_RECORDER_ID>` 只能是本次单列候选训练新建的 recorder，并须记录 sidecar SHA-256、行键摘要、列名单及相对 `8a061ea4` 的配置 diff；无法证明唯一变量隔离时拒绝运行。

### 5.3 C 门：固定 10/3 paired PortAna

```powershell
& $py -u my_scripts/portana_pred_pair.py `
  --control-recorder 8a061ea428e04bb3a199a485ade49d0e `
  --candidate-recorder <H52_RECORDER_ID> `
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
| 线上导向 10/3 账 | 固定当前 label 与 `8a061ea4` 时，`HIGH252_PROX_RANK` 能否依次通过两窗信息门、模型门和固定 10/3 兑现门 | 即使全过也不能直接替换线上 pred/特征；2025 valid 不得写成可外推年化；2025/2026 NAV 不相加、不相乘 |
| 50/5 研究账 | 本刀不产生新 50/5 结果，只保留历史分账 | 不跑 50/5 PortAna；不用 50/5 历史 NAV、超额、过滤、止损或宽度结果选方向、选窗口、定阈值或证明 H52A1 对 10/3 有效 |

最终立场：**DSV1 两窗均值同为正而 2026 CI 穿 0，是证据不足后的停止，不是翻 DSEM、改窗口、改分母或换 total/upside volatility 的邀请，也不授权返回 BETA、MAXRET、Amihud、CYQ、winratio、horizon 或 score-exit。下一刀只给 `HIGH252_PROX_RANK` 这个一年价格锚一次“先跨窗条件信息、后单列重训与模型信号、再固定 10/3 PortAna”的证伪机会；任一门失败，整把刀停止。**
