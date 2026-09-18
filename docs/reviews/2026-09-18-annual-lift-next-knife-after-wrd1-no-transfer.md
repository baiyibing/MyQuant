# 2026-09-18 · annual-lift 下一刀（T5-WRD1 MODEL_NO_TRANSFER 之后）

**性质**：只预注册一把刀、有序门和互斥终态标签。本轮**不实现、不导数、不算 IC/RankIC、不重训、不跑 PortAna/BT、不改线上**。

**裁决**：选 **T5-AMI1：固定 20 交易日 Amihud 成交额价格冲击截面秩**，只允许一列 `AMIHUD20_RANK`。

**线上默认**：仍为 **10/3 LGB**；默认 pred 仍为 `8a061ea4`（recorder `8a061ea428e04bb3a199a485ade49d0e`），全程只读。

一句话刀法：**固定当前 label、`8a061ea4`、原 handler 宇宙和唯一 20 日公式，先检验高 Amihud 价格冲击是否在 2025/2026 对现有 score 有同向正的增量 RankIC；A 过才允许只加 `AMIHUD20_RANK` 一列重训，B 过才允许做固定 10/3 的配对 PortAna，任一门失败即停。**

## 0. 上一刀结果与新刀一句话

T5-WRD1 已在 `newtest_4090` 收工，最终标签是 **`WINRATIO_GAP_MODEL_NO_TRANSFER`**：

| 门 | 已知结果 | 裁决 |
|---|---|---|
| A 条件信息门 | 2025 mean partial RankIC `+0.0175`，交接未单列其 CI；2026 为 `+0.0172`，95% CI `[+0.0031, +0.0312]` | 过 |
| B 模型信号门 | 2026 Top10Spread 候选 `0.01453` < 基线 `0.01487`；2026 `ΔRankIC` CI 下沿 `-0.000645 <= 0` | 失败并停止 |
| C 组合门 | 未进入 | 未跑 PortAna/BT |

2025 RankIC/Top10 与 2026 RankIC 虽微胜基线，但不足以全过 B。该次执行未改 pred、未改线上 10/3，也未重算 CYQ。本页不为交接未提供的数字或 CI 补值。

**新刀一句话**：T5-AMI1 离开筹码/获利盘口径族，只问一个新问题：由后复权收盘变动相对人民币成交额定义的 20 日价格冲击，是否含有现有 score 尚未吸收的跨窗信息。

## 1. 为什么在 WRD1 B 门失败后选这把

### 1.1 WRD1 留下的约束

WRD1 说明“独立条件信息为正”不等于“加进树后能改善头部排序”。因此下一刀不能从 A 门直接跳到 NAV，也不能用另一个 winratio 变体追着已经失败的 B 门调参。T5-AMI1 保留同样严格的 A -> B -> C 顺序，但把假设切换到不使用 CYQ、`$winratio`、卖出或 label horizon 的成交额价格冲击维度。

唯一原始量按特征日 `t` 定义。对股票 `i`：

```text
r[i,d] = abs(close[i,d] / close[i,d-1] - 1)
impact20[i,t] = mean(r[i,d] / amount[i,d], d = t-19..t)
AMIHUD20_RANK[i,t] = rank_pct_cross_section(impact20[i,t])
```

- `close` 只用 qlib `$close` 后复权 bin，`amount` 只用同一 provider 快照的 `$amount`。
- `t-19..t` 是包含 `t` 的固定 20 个市场交易日；需要 21 个 close 点和 20 个正的 amount 点。任一点缺失、非有限、`close<=0` 或 `amount<=0`，当行特征缺失，禁止填造原始值。
- `rank_pct_cross_section` 固定为每日在冻结 handler 当日成员与有效 `impact20` 的交集上执行 `pandas.Series.rank(method="average", pct=True)`。数值越大表示产生同样绝对涨跌需要的人民币成交额越少，即价格冲击/非流动性越高。
- 方向预注册为“高冲击 -> 更高的次日预期收益”（非流动性溢价假设）。若数据显示负向，不得现场乘 `-1` 救援。

这是一个可证伪假设，而不是字段池筛选：只有一个 20 日窗、一种绝对收益/成交额公式、一种截面秩定义和一个方向。

### 1.2 不选相邻路线

| 路线 | 已有结论 | 本轮处理 |
|---|---|---|
| 精确 CYQ 网格 | free/1000 单列条件增量已是 `CYQ_CONDITIONAL_NO_EDGE` | 不重算 CYQ，不试 shares/window/threshold/feature/seed，T5-AMI1 不读 CYQ 文件 |
| winratio 残差网格 | WRD1 已是 `WINRATIO_GAP_MODEL_NO_TRANSFER` | 不试 raw `$winratio`、阈值、平滑、lag、交互、另一种残差、异 seed 或新树；T5-AMI1 公式不含 `$winratio` |
| 卖出/执行扫参 | `score<=0` 额外卖出已是 `SCORE_EXIT_FLIP`，2026 扫闸/止损/trail/止盈/宽度/`n_drop` 已封死 | 不改卖出、闸、宽度或成交；只有 B 过后才用原封不动的 10/3 检验兑现 |
| label / horizon | 已是 `LABEL_HORIZON_FLIP` | label 与 horizon 原样冻结，不开 h=2/4/5/10 |
| 换树/月滚/scaler/大 handler | 均已有停手结论 | 只复制 `8a061ea4` 配置并左连一列 sidecar；不重建特征池 |
| 旧 M3-C 特征池 | 四候选未入选，其中 `turnover_resist_approx` 已跨窗反号 | 不重开 turnover/DDX/amount-per-volume 菜单；只验证一列预注册的 Amihud 冲击秩 |

选它的核心理由是：WRD1 的信息在独立诊断中成立，但没有穿过现有树的头部排序门，继续挤压筹码口径只会形成同族网格。`AMIHUD20_RANK` 使用的是价格变动与人民币成交额的联合尺度，不使用获利盘水平、跨源口径差或执行参数。它若连 A 门都过不了，就用信息诊断的低成本结果直接停掉，不烧重训和 NAV。

## 2. 冻结表

| 层 | 锁定值 / 禁令 |
|---|---|
| 当前 label | 只用 `Ref($close,-2)/Ref($close,-1)-1`；禁止换 label 或 horizon |
| 基线 pred | `8a061ea428e04bb3a199a485ade49d0e`；2026 `pred.pkl` 与 2025 同模型补分 CSV 只读，不覆盖、不回写；不读写 `55c5bf77` |
| 唯一候选 | `AMIHUD20_RANK`，严格按 §1.1 构造；不试 5/10/60 日、EWMA、signed return、量/流通盘归一、log/winsorize、反向、阈值、分箱、lag 或交互 |
| 原始数据 | 只读同一冻结 qlib provider 快照的 `$close`/`$amount`；须记录 provider 路径、快照指纹、交易日历指纹与代码 commit，禁止 A 后刷新数据 |
| 构造时点 | 特征日 `t` 只用 `t` 及之前数据；用市场交易日历取固定 20 日，禁止在单股缺日时向更早日期“补足 20 点” |
| 构造宇宙 | 时序 `impact20` 先在冻结 provider 日历上计算，然后只在 `alpha158_cost_kdj_lgb / 8a061ea4` 冻结 handler 的当日索引与有效值交集上做一次截面 rank；不得先在全市场 rank 后再切 handler |
| 唯一 sidecar | 一次性导出覆盖 train/valid/test 的不可变 sidecar，至少保留 `(instrument, datetime)`、原始 `close/amount`、`impact20`、`AMIHUD20_RANK`、20 日有效性和缺失原因，并写 sidecar SHA-256 与行键摘要；A 只切片，B 只左连这一份，C 只认 B recorder 血缘中的同一 SHA-256 |
| 两窗 | A/B/C 统一为 2025 valid `2025-01-03~2025-12-31`、2026 OOS `2026-01-01~2026-09-14`；两窗均已被研究，不包装为新盲窗 |
| 训练 | A 全过后才可复制 `8a061ea4` 的 LGB 配置；唯一差异是向原 handler 帧左连一列 `AMIHUD20_RANK`；train 2020-2024、valid 2025、test 2026，seed/超参/早停/scaler/训练宇宙全冻结，涨停出池开、`DropLimitUpLearn` 关 |
| 组合 | B 全过后才可做 paired PortAna；只有 10/3，`hold_thresh=1`、top/bottom，buy-state/ST/年龄/5 日 15% 全关，止损/trail/止盈全关 |
| 尺子 | qlib `$close` 后复权 bin；买5bp/卖15bp/最低5；拒单0.095、不追买、整手向下；本金1e8、`risk_degree=0.95`、基准 SH000300 |
| 禁止项 | 不扫任何参数或特征；不换树、月滚、per-fold scaler、20/3、50/5 PortAna、15% 关闸默认或大 handler 重建；不用 WRD1/CYQ 中间产物做候选列 |
| 线上 | 全程仍为 `8a061ea4` + 10/3；即使全链成功也只得到候选标签，不自动替换 pred、特征或线上参数 |

## 3. A/B/C 有序门

### 3.1 A 门：跨窗条件信息门；禁止重训与 PortAna

先从冻结 provider 快照一次性构造唯一 sidecar。导出器必须先为 2020 起始日读取足够的前置交易日，但只输出冻结 handler 键；不得读取 label，也不得在 A 通过后重算历史。

数据门要求：

- 每个 `(instrument, datetime)` 的 20 日原始输入、截面成员与输出必须可复算；等值秩取 average，不得加股票代码破 tie。
- sidecar 必须通过列集、唯一键、日期范围、provider/日历/sidecar hash、行键摘要、随机抽样复算和时点检查。
- A/B 重叠键上的 `AMIHUD20_RANK` 必须逐值一致；任一 hash、成员集合或值不一致，都是 `AMIHUD_DATA_INVALID`。
- 2025、2026 的共同样本覆盖率均须 `>=98%`。分母是冻结 handler 当日有限 score 行，分子是其中 score、当前 label 和 `AMIHUD20_RANK` 均有限的行；同时报告 close/amount/20 日完整性各自造成的缺失。
- feature day `t` 与 score/label 以同一 `(instrument, datetime)` 键对齐，禁止 `pred_minus_one`、成交日偏移或使用 `t+1` 数据。

信息量定义：每个特征日，在 score、label、`AMIHUD20_RANK` 均有限且 `n>=4` 的共同样本上，令 `s=rank_pct(score)`、`a=AMIHUD20_RANK`、`y=rank_pct(label)`；分别做 `a ~ 1+s` 与 `y ~ 1+s`，取两组残差的 Pearson 相关，定义当日 **AMIHUD partial RankIC**。这里的残差化只是信息门的统计控制，候选训练列仍是 sidecar 中唯一的 `AMIHUD20_RANK`，不得另造“AMIHUD 对 score 残差”列。

每窗报告 mean、median、ICIR、有效/退化日数与原因、共同股票数中位数和覆盖率；2026 按自然季度报告 mean AMIHUD partial RankIC。对逐日 IC 做 5 交易日 moving-block bootstrap，固定 10,000 次、seed `20260918`，报告 95% CI。

**A 门全过条件**：数据门通过；2025 与 2026 mean AMIHUD partial RankIC 均 `>0`；2026 的 95% CI 下界 `>0`；2026 不得多数季度为负，也不得只靠一个季度为正。未全过立即按 §4 裁决，B/C 取消。

### 3.2 B 门：只加一列重训，再做模型信号门

A 全过后才允许建立一个新 recorder：

- 对照仍是现成 `8a061ea4`，不得重训或覆盖。
- 候选只复制其冻结训练配置，在现成 handler 帧按 `(instrument, datetime)` 左连同一 sidecar 的 `AMIHUD20_RANK`。不得同时加 raw `impact20`、缺失指示、CYQ/winratio 或其他衍生列。
- 少量缺失只按现网的 `RobustZScoreNorm` 后 `Fillna(0)` 链处理，不得删股票、换宇宙或另拟 scaler。
- 候选只导出 2025 valid 和 2026 test 分数到新目录。在两窗共同样本上，以当前 label 比较候选与基线的日 RankIC、Top10Spread 和 `ΔRankIC` 的同口径 bootstrap CI；Top10Spread 固定为等权 Top10 减共同宇宙等权，禁止换成 Top10-Bottom10。此时仍不得跑组合。

**B 门全过条件**：候选在 2025、2026 均同时满足 `RankIC(candidate)>RankIC(8a)` 与 `Top10Spread(candidate)>Top10Spread(8a)`；2026 `ΔRankIC` 的 95% CI 下界 `>0`；2026 不得多数季度为负或单季驱动。未全过立即停止，C 取消。

### 3.3 C 门：最后才做固定 10/3 paired PortAna

B 全过后，才允许对基线 pred 与候选 pred 做两窗配对 PortAna：

- 两臂唯一上游差异必须是 `AMIHUD20_RANK` 一列；输入 hash、组合、成交、费用、闸与窗口全部冻结。
- C 使用各臂全宇宙 pred，不以 A/B 的共同有限样本重定义组合宇宙。
- 每窗报告末值、区间收益、扣费年化超额、最大回撤、换手与费用；报告 2026 自然季度 `ΔNetReturn`，并对 2026 配对日收益差做同样 5 日、10,000 次、seed `20260918` 的 bootstrap CI。

**C 门全过条件**：2025、2026 均 `ΔNetReturn>0` 且扣费年化超额排序候选高于基线；2026 `ΔNetReturn` 的 95% CI 下界 `>0`；2026 `majority_negative=false` 且 `single_quarter_driven=false`。

三门的 2026 季度口径统一：保留截至 9 月 14 日的不完整 Q3；`majority_negative = 负增量季度数 / 季度数 > 50%`；`single_quarter_driven = 全窗增量 > 0 且正增量季度数 <= 1`。A 的增量是 AMIHUD partial RankIC，B 是候选减基线的 RankIC/Top10Spread，C 是 locked-cost `ΔNetReturn`，不得混写。

## 4. 成功标签 / 失败瀑布

一次合规执行最终必须且只能产生下表中的**一个**终态标签。A/B 的“通过”只记 gate boolean，不另打中间标签；成功标签与全部失败标签互斥，裁决按优先级自上而下结束。

| 优先级 | 唯一终态标签 | 命中条件 | 停手动作 |
|---:|---|---|---|
| 1 | `AMIHUD_DATA_INVALID` | 任一数据、时点、覆盖、公式复算、hash、行键或配置隔离门失败 | 停；只允许修实现错误后按原协议复跑，不得改数据源或公式 |
| 2 | `AMIHUD_CONDITIONAL_FLIP` | A 中 2025/2026 mean partial RankIC 反号，或 2026 多数季度为负 | 停；不翻方向、不挑季度、不换窗口 |
| 3 | `AMIHUD_CONDITIONAL_NO_EDGE` | 未命中 1/2，但 A 的 2026 CI 下界 `<=0`、单季驱动或任一 A 信息门不过 | 停；不改 20 日、公式、方向或变换方式 |
| 4 | `AMIHUD_MODEL_NO_TRANSFER` | A 过而 B 任一窗 RankIC/Top10Spread 不同时胜基线，或 2026 CI/季度门不过 | 停；不加 raw 列、第二列、交互、异 seed 或新树 |
| 5 | `AMIHUD_PORTANA_FLIP` | A/B 过而 C 的两窗 locked-cost `ΔNetReturn` 反号，或 2026 多数季度为负 | 停；不改 10/3、成本、闸、卖出或窗口 |
| 6 | `AMIHUD_PORTANA_NO_EDGE` | 未命中 1-5，但 C 的 2026 CI 下界 `<=0`、单季驱动或任一 C 门不过 | 停；不转扫宽度、`n_drop`、阈值或 50/5 |
| 7 | `AMIHUD_FEATURE_CANDIDATE` | A、B、C 全部通过 | 只登记候选；不自动改线上，是否需要新盲窗/实盘观察另立任务 |

程序崩溃、资源不足等运行错误不是研究 verdict；修复只能恢复本页固定语义。任一研究失败标签一旦命中，T5-AMI1 收工，禁止滑成 `lookback x transform x direction x threshold x seed x model` 网格。

## 5. 实现接口草案（本轮禁止执行）

以下只定义未来实现 PR 的接口形状。**当前 PR 不得创建这些脚本、不得导出 sidecar、不得计算 IC、不得重训、不得跑 PortAna/BT。**下列脚本是未来接口名，本轮不假定它们已存在。所有阶段对既存输出目录都必须 fail-closed，不得删除、清空或复用旧目录。

### 5.1 唯一 sidecar + A 门

```powershell
$py = "D:/anaconda3/envs/vanna312/python.exe"
$out = "exports/analysis/t5_ami1_20260918"

& $py -u my_scripts/export_amihud20_sidecar.py `
  --experiment alpha158_cost_kdj_lgb `
  --recorder-id 8a061ea428e04bb3a199a485ade49d0e `
  --handler-index-source recorder-handler `
  --provider-uri "C:/Users/wangc/.qlib/qlib_data/my_data" `
  --freeze-provider-snapshot `
  --close-field "`$close" --amount-field "`$amount" `
  --lookback-market-days 20 --require-complete-window `
  --impact abs-return-over-amount `
  --rank-method average --rank-pct pandas-pct-true `
  --feature-name AMIHUD20_RANK `
  --emit-source-qc --emit-hash-and-key-digest `
  --out-dir "$out/sidecar" --fail-if-out-exists

$sidecarSha256 = "<SIDECAR_SHA256_EMITTED_BY_EXPORT_MANIFEST>"

& $py -u my_scripts/diag_amihud_information.py `
  --experiment alpha158_cost_kdj_lgb `
  --recorder-id 8a061ea428e04bb3a199a485ade49d0e `
  --pred-2025 my_scripts/预测结果_8a061ea4_2025valid.csv `
  --sidecar "$out/sidecar/AMIHUD20_RANK.parquet" `
  --sidecar-manifest "$out/sidecar/manifest.json" `
  --sidecar-sha256 $sidecarSha256 --verify-key-digest `
  --feature AMIHUD20_RANK --control-score `
  --label "Ref(`$close,-2)/Ref(`$close,-1)-1" `
  --window 2025-01-03:2025-12-31 `
  --window 2026-01-01:2026-09-14 `
  --min-coverage 0.98 --block-days 5 --bootstrap-reps 10000 --seed 20260918 `
  --out-dir "$out/information" --fail-if-out-exists
```

导出端必须先冻结 provider/日历指纹，在原始时序上算固定 20 日 `impact20`，再于 recorder handler 当日有效交集上唯一一次 rank；诊断端只读 sidecar 存储值。数据门失败只能得到 `AMIHUD_DATA_INVALID`；A gate boolean 非全真时禁止执行后两段。

### 5.2 B 门：单列训练与信号诊断

```powershell
& $py -u my_scripts/train_sidecar_feature_arm.py `
  --clone-recorder 8a061ea428e04bb3a199a485ade49d0e `
  --sidecar "$out/sidecar/AMIHUD20_RANK.parquet" `
  --sidecar-sha256 $sidecarSha256 --verify-key-digest `
  --only-extra-feature AMIHUD20_RANK `
  --train 2020-01-01:2024-12-31 --valid 2025-01-01:2025-12-31 `
  --test 2026-01-01:2026-09-14 --no-portana `
  --out-dir "$out/model" --fail-if-out-exists

& $py -u my_scripts/diag_pred_pair.py `
  --control-recorder 8a061ea428e04bb3a199a485ade49d0e `
  --candidate-recorder <AMIHUD_RECORDER_ID> `
  --control-pred-2025 my_scripts/预测结果_8a061ea4_2025valid.csv `
  --candidate-pred-2025 "$out/model/pred_2025.csv" `
  --label "Ref(`$close,-2)/Ref(`$close,-1)-1" --topk 10 `
  --top10-spread-vs common-universe-equal-weight `
  --window 2025-01-03:2025-12-31 `
  --window 2026-01-01:2026-09-14 `
  --block-days 5 --bootstrap-reps 10000 --seed 20260918 `
  --out-dir "$out/pred_pair" --fail-if-out-exists
```

`<AMIHUD_RECORDER_ID>` 只能是这一次单列候选训练新建的 recorder。候选 recorder 必须记录 sidecar SHA-256、行键摘要、列名单与相对 `8a061ea4` 的配置 diff；不能证明唯一变量隔离时拒绝运行。

### 5.3 C 门：固定 10/3 paired PortAna

```powershell
& $py -u my_scripts/portana_pred_pair.py `
  --control-recorder 8a061ea428e04bb3a199a485ade49d0e `
  --candidate-recorder <AMIHUD_RECORDER_ID> `
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

C 不得重导 sidecar 或改训练配置，只能沿用 B recorder 记录的同一特征血缘。B 未全过时这段命令不得运行。

## 6. 10/3 与 50/5 永久分账

| 账 | 本刀允许回答 | 本刀禁止回答 |
|---|---|---|
| 线上导向 10/3 账 | 固定当前 label 与 `8a061ea4` 时，`AMIHUD20_RANK` 能否依次通过两窗信息门、模型门和固定 10/3 兑现门 | 即使全过也不能直接替换线上 pred/特征；2025 valid 不得写成可外推年化；2025/2026 NAV 不相加、不相乘 |
| 50/5 研究账 | 本刀不产生新 50/5 结果，只保留历史对齐与审计 | 不跑 50/5 PortAna；不用 50/5 历史 NAV、超额、过滤或止损峰值选方向、选参数或证明 T5-AMI1 对 10/3 有效 |

最终立场：**WRD1 已经证明 winratio 分歧的独立信息没有稳健转移到模型头部排序，所以不再修补筹码口径族。T5-AMI1 只给一个不使用 CYQ/winratio 的成交额价格冲击特征一次“先信息、后模型、再固定 10/3 组合”的证伪机会。它不是 CYQ 网格、winratio 残差网格、卖出补丁或 horizon 续跑；任一门失败，整把刀停止。**
