# MyQuant + MyQuant-backtrader 联合收益实施计划

> **状态：v0.1 / docs-only / implementation plan。目标：提高净收益研究产能。** 本次只交付本文与文档 PR；下述代码、data-free pins、宿主核验和实验均为后续派工，未在本任务执行。
> **IMPLEMENTATION_BASE_MQ：`0cfd91b834bd941682d5824fdf8a85b19d890a88`**。
> **IMPLEMENTATION_BASE_BT：`1049b904bdd818dbb79f51f1830a008c8f83b141`**。
> **冻结：online pred `8a061ea4`、线上及离线对照 10/3、主模型与特征定义；禁止重训。** 冻结特征研发一周，研究输出不写回线上。
> **机器分工：Codex@GrokBotVM；跑数@4090。** Codex 只在 Grok Bot 虚拟机；4090 物理机没有 Codex。文档、后续编码及 data-free 门禁在 GrokBot；重数仅在前置齐备后交给 4090 的宿主执行人。本任务不连接 4090 开跑、不读湖、不嵌套启动 Codex。
> **与 MyQuant #89 的关系：实现层跟进。** #89 的组合臂 / fill 矩阵与证据边界保持；本文补充接口、代码落点、依赖、验收、责任和派工门槛，不把 experiment plan 改写成已完成实验。

## 1. 单行范围

以冻结 `8a061ea4` / 10/3 为输入，交付“只读组合约束 → 固定意图 → 分钟成交情景 → 换手 / 回撤 / 净超额台账”的隔离研究链实施清单，生产撮合、特征、线上配置和既有判决均不变。

## 2. Why now：信息有、组合没

**先别再开新特征刀。** 这两天的证据已经很清楚：MAXRET、WRD1 在 A 门有一点条件信息，进入已有强 LGB 后却未稳定传到 B 门。继续“再加一列”很难抬净收益；按用户给定的战略，业内提高净收益的主战场通常在组合、风险、成本和成交。本计划据此分配研究产能，不把行业经验或诊断结果写成已验证的收益。

本轮是**「信息有、组合没」**：单因子有条件信息，但没有已验证的组合改善。**MAXRET 伤头、WRD1 伤底**：前者在验证窗换入近期大涨股而损害头部；后者在样本外主要是底部收益上升拖累冻结 Top−Bottom，不能解释为同一种头部失败。主模型不动；两项 residual 直接叠回均被判为“削弱”，不再另开一门 LGB。来源为 MQ-SUM、MQ-PREF、MQ-PJSON，见 §2.1。

三条线并行，组合优先：

1. **组合与约束（最优先）**：同一信号、更干净的持仓；研究行业 / 市值主动暴露中性、换手上限、禁止追近端大涨、尾部暴露。MAXRET 伪1支持头部机制，但 CI 跨零，不能承诺净收益提升。
2. **成本与成交**：已有分钟 Mode B；先落实“同信号、不同成交假设”，量化冲击、涨跌停、能否成交、未成交及止损路径对净收益的影响。既有宿主网格不能替代新信号实测。
3. **信号怎么用**：弱信息只作组合过滤、降权或否决；首片使用已有 anti-rank，WRD1 暂保留头尾诊断，不照搬 MAXRET 规则，不叠回 score。

明确不建议：再扫新特征刀；为过 B 扫 seed / 窗口 / 方向；动线上 10/3；没过组合层就用 PortAna 当真钱结论。本计划全程不调用 PortAna / Exchange。

| 既有判决 / 结论 | 本实施计划如何承接 |
|---|---|
| 无 `FEATURE_CANDIDATE` | 不安排特征晋级、重训或上线切片 |
| `MAXRET_MODEL_NO_TRANSFER` | 保留 B 门终态；P-CHASE 是组合用途，不是复活模型 |
| `WINRATIO_GAP_MODEL_NO_TRANSFER` | 保留 Top−Bottom 原口径；不以头部减宇宙替换原 B 门 |
| `H52_DATA_INVALID` | 数据失败不改成新方向候选 |
| `AMIHUD_CONDITIONAL_NO_EDGE`、`CYQ_CONDITIONAL_NO_EDGE`、`DSTR_CONDITIONAL_NO_EDGE`、`DSEM_CONDITIONAL_NO_EDGE`、`BETA_CONDITIONAL_FLIP` | 停点不变；不借本计划重开特征 |
| MAXRET 伪1机制支持、WRD1 伪1部分支持；两项 residual 伪2“削弱” | 只用于确定过滤与诊断优先级，不当作成交 PnL |

已合入“七条下一步”的逐条落地：停新刀→F-R2；信息有、组合没→本节；组合优先→R1/R2/R3；成本成交→R1/R4；弱信息过滤→R1；不扫 seed/窗、不动线上、不用 PortAna 真钱化→F-R2/F-R10；冻结一周、只看换手/回撤/净超额→§8 与 R5/R6。七条复核记录见 MQ-NEXT7。

### 2.1 已核实来源与版本边界

MQ 路径相对 MyQuant；BT 路径相对 MyQuant-backtrader。以下来源均已用本地文件或 `git show <固定 SHA>:<路径>` 核实。BT 文件名先经固定树枚举再读取；链接固定到 BT 基线，避免依赖本机 symlink。

| 标签 | 已核实路径 | 采用范围 |
|---|---|---|
| MQ-SUM | [docs/reviews/2026-09-19-t5-campaign-summary.md](2026-09-19-t5-campaign-summary.md) | T5 终态、机制解释、三条主线 |
| MQ-NEXT7 | [docs/reviews/2026-09-19-t5-campaign-summary.GROK-NEXT.md](2026-09-19-t5-campaign-summary.GROK-NEXT.md) | 已合入七条下一步覆盖记录 |
| MQ-EXP | [docs/reviews/2026-09-19-next-portfolio-execution-plan.md](2026-09-19-next-portfolio-execution-plan.md) | #89：P-*、M-*、输入与验收定义 |
| MQ-PREF | [docs/reviews/t5-campaign-20260919/t5_mxr1_20260918/pseudo1_top10_constrain_20260919/REPORT.md](t5-campaign-20260919/t5_mxr1_20260918/pseudo1_top10_constrain_20260919/REPORT.md) | T0/T1 排序、严格中位数条件、回填、放宽 |
| MQ-PJSON | [docs/reviews/t5-campaign-20260919/t5_mxr1_20260918/pseudo1_top10_constrain_20260919/summary.json](t5-campaign-20260919/t5_mxr1_20260918/pseudo1_top10_constrain_20260919/summary.json) | recorder、sidecar hash、窗口、标签、冻结统计规格 |
| BT-CLOCK | [docs/backtest/plan-industry-align-refactor-2026-09-18.md](https://github.com/baiyibing/MyQuant-backtrader/blob/1049b904bdd818dbb79f51f1830a008c8f83b141/docs/backtest/plan-industry-align-refactor-2026-09-18.md) | #112 已实施的命名 / pins；P1/P2/P4 不重开 |
| BT-FORK | [docs/backtest/plan-industry-align-next-2026-09-19.md](https://github.com/baiyibing/MyQuant-backtrader/blob/1049b904bdd818dbb79f51f1830a008c8f83b141/docs/backtest/plan-industry-align-next-2026-09-19.md) | 门未拦截 ≠ 已成交；书/v7 分叉 |
| BT-FEE | [docs/backtest/plan-industry-align-p3-fees-2026-09-19.md](https://github.com/baiyibing/MyQuant-backtrader/blob/1049b904bdd818dbb79f51f1830a008c8f83b141/docs/backtest/plan-industry-align-p3-fees-2026-09-19.md) | δ1 已有费率合同、收费粒度、研究费率边界 |
| BT-EXDIV | [docs/backtest/plan-industry-align-p3-d2-exdiv-2026-09-19.md](https://github.com/baiyibing/MyQuant-backtrader/blob/1049b904bdd818dbb79f51f1830a008c8f83b141/docs/backtest/plan-industry-align-p3-d2-exdiv-2026-09-19.md) | δ2 A→B→C 运行记录、除权残留和 PIT 未证 |
| BT-ENGINE | [docs/backtest/engine-ashare-correctness.md](https://github.com/baiyibing/MyQuant-backtrader/blob/1049b904bdd818dbb79f51f1830a008c8f83b141/docs/backtest/engine-ashare-correctness.md) | E-R1–E-R6、费率、时钟、价格域与已知局限 |
| BT-MPLAN | [docs/backtest/plan-unified-exit-modeb-2026-09-17.md](https://github.com/baiyibing/MyQuant-backtrader/blob/1049b904bdd818dbb79f51f1830a008c8f83b141/docs/backtest/plan-unified-exit-modeb-2026-09-17.md) | Q39 open/close、Mode B 自有除权模型 |
| BT-MHOST | [docs/backtest/unified-exit-modeb-host-note-2026-09-17.md](https://github.com/baiyibing/MyQuant-backtrader/blob/1049b904bdd818dbb79f51f1830a008c8f83b141/docs/backtest/unified-exit-modeb-host-note-2026-09-17.md) | 既有 Q39 E 已跑；不挪用历史收益 |
| BT-MRUN | [docs/backtest/host-runbook-unified-exit-modeb-2026-09-17.md](https://github.com/baiyibing/MyQuant-backtrader/blob/1049b904bdd818dbb79f51f1830a008c8f83b141/docs/backtest/host-runbook-unified-exit-modeb-2026-09-17.md) | 缓存、session、覆盖、未平仓、宿主回执 |
| BT-MHAND | [docs/backtest/handoff-unified-exit-modeb-codex-impl-2026-09-17.md](https://github.com/baiyibing/MyQuant-backtrader/blob/1049b904bdd818dbb79f51f1830a008c8f83b141/docs/backtest/handoff-unified-exit-modeb-codex-impl-2026-09-17.md) | 已有 A–D 交付与 Q7/Q36/Q37/Q38；旧 E 待办是历史阶段 |

**本机核查差异**：MQ HEAD 等于 IMPLEMENTATION_BASE_MQ，提交说明为合入 #89。BT sibling 工作目录 HEAD 为 `41f3d11a34c665cc8a21b3e1d351b9e06b0466b5`，不是指定基线；指定的 `1049b904bdd818dbb79f51f1830a008c8f83b141` 对象存在，提交说明为合入 #123。本文的 BT 事实按该固定对象读取，不 checkout / pull / 修改 sibling。各旧计划自己的实施基线只解释旧切片，不替换本文两仓基线。

BT-MHOST / BT-MPLAN 头部确认 Q39 E 已完成；BT-MHAND 与 runbook 部分正文仍留早期“未执行”。本文采用有完成证据的状态，也不把历史 E 视为 `8a061ea4` 已测。BT-FORK 内历史命令示例的 SHA 与头部不同，后续不照抄其旧基线赋值。

## 3. 仓库分工与跨仓信号契约

### 3.1 谁交什么，现有入口缺什么

| 责任 | 交付 | 对净收益研究的作用 |
|---|---|---|
| MQ 组合实施负责人（具体执行人待派） | 只读输入清单、冻结 10/3 原始意图、离线约束名单 / 权重、暴露 / 可行性台账 | 先证明“同一分数如何形成持仓”，隔离组合选择与执行影响 |
| BT 分钟实施负责人（具体执行人待派） | 固定意图的因果成交适配、订单生命周期、费用 / 现金 / 持仓对账、fill 情景 | 识别净超额是否被成本、延迟、未成交吞掉 |
| 联合验收负责人（任务派工时指定） | 同一 contract hash、配对键、指标定义、失败标签、固定产物索引 | 两仓各自绿不能替代跨仓串联通过 |
| 4090 宿主执行人（待派；无 Codex） | 只读快照核验、有限清单执行、日志及回执 | 只运行已交付的研究入口，不现场选参或改代码 |

MQ 已核实 [my_scripts/replay_10n3_two_year.py](../../my_scripts/replay_10n3_two_year.py) 使用同一 recorder，但调用 `backtest_daily`；[my_scripts/export_positions_trades.py](../../my_scripts/export_positions_trades.py) 默认读取既有 PortAna 持仓，不能把已成交持仓当原始订单意图。[my_scripts/export_next_day_pool.py](../../my_scripts/export_next_day_pool.py) 声明收盘分到次日，默认 50/5，且可重新预测；不能直接把默认 CLI 当本计划 10/3 冻结导出。上述文件仅供核对来源，本次及后续链均不运行其回测 / 预测分支。

BT 已核实 `backtest/research/unified_exit_modeb.py`、`scripts/research/run_unified_exit_modeb.py` 存在；当前接口以名单实例与卖出规则网格为中心，不能声称已支持 #89 的任意固定意图、有限现金、部分成交和延迟配对。`_result` / `build_daily_equity` 使用 Mode A 常量佣金；**CSV 书/v7 的 δ1 fee-wiring 通过，不等于 Mode B 费用已接同一接口。** R1 要补隔离研究适配层及自己的接线证明，冻结既有模块；不能直接运行冠军网格冒充本任务。

### 3.2 contract v1：先固化字节，再交付意图

以下 schema 是**拟实施接口**，尚无新文件 / CLI。文件内容由 R0 定义，R1 实现读写及拒绝逻辑。哈希采用规范排序、固定 UTF-8 序列化后 SHA-256；原文件字节 hash 与规范内容 hash 分列。不能只比较 recorder 短 ID。

| 对象 | 必需字段 / 不变量 | 缺失或漂移时 |
|---|---|---|
| `manifest.json` | schema_version、两仓代码 SHA、两个实施基线、contract_hash、pred 完整 recorder ID、各输入 URI / hash / 覆盖、生成时点、窗口、日历 / Asia/Shanghai、价格域、10/3 配置与资格闸门、费用 / 风险预算 / 初始现金持仓、估值与 benchmark 版本 | `INPUT_BLOCKED`；不回落最近 recorder、不按默认配置补值 |
| `scores` | 日期、instrument、score、score_available_at、来源版本；原值保留；排序 `score desc, instrument asc, mergesort` | 重复键、时点不明、score 改写即拒绝 |
| `intents` | arm_id、intent_id、instance/lot_id、instrument 映射、decision_at、available_at、side、目标权重及原始目标数量、数量单位、数量转换参考价 / 时点、reason、参考状态 hash、订单生效 / 失效 / 重试政策 | BT 不得重新选票、重算原始目标数量或向前移动信号 |
| `reference_state` | 每个组合臂独立递推的现金 / 持仓、漂移权重、原始卖买计划；有原生止损才存参考 cost/peak 和触发事件 | 禁止用各 fill 情景的实际成本重新生成信号；无原生止损则标 N/A，不引入 Mode B 冠军规则 |
| `execution_ledger` | 每条意图各情景的订单状态、合法执行时点、成交价量、费用、未成交量 / 原因、剩余订单、实际现金持仓、可卖股数、最后估值日期 / 陈旧标记 | 卖出不超可卖持仓，买入不超含费现金；未成交不等于删除意图 |
| `metrics` | 组合臂 / fill 情景 / 窗口 / 月份、分母、净 NAV 与 benchmark、换手、回撤、净超额、覆盖 / 缺失 / 不可行、语义限定 | 缺产物或定义则“待实测 / 不可判”，禁止用标签价差填 PnL |

完整对照 recorder 是 MQ-PJSON 的 `8a061ea428e04bb3a199a485ade49d0e`。sidecar 预期 SHA-256 为 `27320f8b7f6de3854802f97325f682039732470ce387f21bc9cd6c3083b7b348`，只用于核验已有 `MAXRET20_ANTI_RANK`；候选 recorder 仅按 P-REF 共同宇宙对齐，不参与排序。**原始 pred 快照、冻结 10/3 意图快照、PIT 行业 / size 快照、4090 新信号码集缓存 manifest：本次只读材料中未找到可直接派工的完整包，待补。** 旧报告里的机器路径是出处线索，不代表本机或 4090 已可读。本任务不搜索湖或补造数据。

“同信号”只在**同一组合臂的 fill 配对内部**成立；组内 intent hash、目标数量、参考触发、费用与资金基数一致。跨 P-BASE / P-CHASE 的变化属于组合效应。先将目标权重按同一参考状态转为意图数量，再由各情景实际现金 / 可卖持仓裁剪成交并记原因，不让成交结果反向改变意图。

公司行动另存数量单位转换记录：跨除权的未完成订单必须以共同事件换算到当前股数单位，保留原始数量与转换因子；映射不可证则停止相关配对。参考数量不因 fill 调整，合法公司行动换算不伪装为选股变化。Mode B 的 shares÷k 允许小数持仓、现金红利不入账；整手新买、零股退出及未成交单位须经 P5 固定，不能以股份缩放宣称真实总回报守恒。

### 3.3 指标先定，收益不预填

| 指标 | 实施定义 / 验收用途 |
|---|---|
| 目标换手 | 沿用 #89：`0.5 × Σ abs(w_target − w_pre_drift)`，包含现金；相同估值时点，初始建仓单列；伪1 的名单 turnover / Jaccard 不替代资金换手 |
| 实际换手 | 每日 `0.5 × (买入成交金额 + 卖出成交金额) / 调仓前净资产`，另列双边金额、费用、现金和未成交；分母非正即停止收益计算 |
| 回撤 | 同一完整日历上净 NAV 的 `max(1 − NAV_t / running_max(NAV))`；比较 `ΔMDD = 处理 − 对照`，正值为恶化；未平仓含估值，不能仅算已平仓单 |
| 净超额 | 主 benchmark 为同 fill / 同资金口径的冻结 P-BASE；`R_net = NAV_end / NAV_start − 1`，`ΔR_net = R_net(处理) − R_net(P-BASE)`。另报同一日历逐日净收益差与配对不确定性；不把差序列直接冒称可投资 NAV |
| 市场基准与中性基准 | 行业 / size 中性用共同宇宙等权主动暴露；它不是已成交的收益基准。市场指数收益只在 P6 锁定指数、分红域和版本后单列，不把旧脚本默认指数自动继承 |
| 成本前后 | 净 NAV 从实际现金 / 持仓和一次扣费产生。配对内费用固定；滑点通过成交价进入，不能再扣一次。相同成交路径下的费用加回仅是会计归因，不等于无费用重跑（费用会影响现金资格） |
| 尾部与执行 | 预先定义低 anti-rank 权重、行业集中、size 尾部；成交率同时报订单数 / 数量口径，意图全集为分母；缺码、缺分钟、停牌、现金不足、部分成交、过期与陈旧估值均保留 |

新链收益、成交率、滑点、Sharpe 一律**待实测**。初期只宣称“冻结研究费用及公司行动假设下的净超额”；δ1 代理佣金不是完整真实税费，Mode B 股份缩放不是现金分红账本。外推为可交易或真钱收益须另有证据，本计划不授予上线资格。

## 4. 实施切片：7 刀，按依赖派工

编号 `R0–R6` 是本联合实施计划；`P-* / M-*` 沿用 #89；`δ*` 专指 BT industry-align；本文人裁 `P1–P7` 与旧计划局部 P* 不混用。每刀单独可审查、可回退；跨仓刀分成 MQ / BT 两个提交或 PR，通过 contract_hash 绑定，未齐备不宣称端到端完成。

估时为**人工工作量**：S≤1 人日，M=2–3 人日，L=4–5 人日；不含评审、外部数据等待或 4090 实测时间。这里的“可立即开工”指**后续派工就绪度**，本次授权仍只有文档与 PR，不在本 PR 写代码或运行测试。

依赖：`R0 → R1 → R2 → R3`；`R1 → R4`；`R1 → R5 → R6`。R5/R6 的首批只验收 R1 最小矩阵，后续才接 R2/R3/R4，故首周不必做完整菜单。

**路径约定**：下述所有 `joint_return_*` 新代码 / tests / 文档及 `joint-return-v1/` 产物均为**拟新增，当前未实现**。这是明确落点，不是已存在脚本或结果引用；未来 PR 须核名后落盘，运行前必须把占位 `<run_id>` 换成实际不可覆盖目录。

### R0 — 固化输入、契约与验收账本

| 项 | 派工定义 |
|---|---|
| 所属仓 / 责任 | MQ 主责，BT 校验接口；联合验收负责人收口 |
| 前置 / 输入冻结 | 本文两仓基线、MQ-EXP 与全部 F-R*；原始数据缺口逐项登记，先用合成样例定义 schema |
| 动作 / 产出路径 | MQ 拟新增 `docs/reviews/joint-return-v1/contract.md`、`input-register.md`、`acceptance.md`；定义 §3 字段、排序/hash、10/3 来源、有限参数、订单生命周期与状态码；列出后续两仓白名单与完整代码基线 |
| 验收 | 字段、单位、数量转换、时点、来源、缺失处理均有定义；不能定位的数据明确 `INPUT_BLOCKED`；七条主轴到切片逐项映射；可用纯合成样例手工核对，不读真实数据 |
| Non-goals | 不补 pred、不推断线上资格闸门、不写训练/回测实现、不照抄旧宿主现金池与窗口 |
| 映射 | 全部 P-* / M-* 的协议前置；继承 δ1/δ2 边界，不重做它们 |
| 估时 / 立即开工 / 机器 | **S；可立即派文档刀**；GrokBot。数据定位由后续宿主任务补，不能把缺口标绿 |

### R1 — 最小纵向链：P-BASE / P-CHASE → M-REF / M-LAG

| 项 | 派工定义 |
|---|---|
| 所属仓 / 责任 | MQ 组合负责人 + BT 分钟负责人；一个联合验收点 |
| 前置 / 输入冻结 | R0 合同固定；P1–P5 中与本刀有关的实现选择落实；真实数据未齐仍可做 data-free 部分。冻结原始 10/3、score、既有 anti-rank、参考状态、费用与订单有效期 |
| 动作 / 产出路径 | MQ 拟新增 `my_scripts/joint_return_contract.py`、`my_scripts/joint_return_portfolio.py`、`tests/test_joint_return_portfolio.py`；BT 拟新增 `backtest/research/joint_return_replay.py`、`scripts/research/run_joint_return_replay.py`、`tests/test_joint_return_replay.py`。实现显式快照输入、P-REF 复核入口、P-BASE/P-CHASE 意图输出、隔离的 M-REF/M-LAG 消费与最小台账；不接既有生产入口 |
| 组合动作 | 先实现 P-REF 原样复核；持仓链再只约束 10/3 原始换入：anti-rank 严格低于当日 T0 中位数跳过，按 score 回填，按原规则记录放宽。保留未获准调出的旧仓；各臂独立递推，不每日整体换成 T1 |
| 成交动作 | M-REF 标明理想化参考；M-LAG 从 `available_at` 之后首个合法分钟 open 开始。同根 close 事件不能倒填该根 open；T+1、跌停次日重评、停牌、到期缺分钟与期末 mark 固定；不得给 10/3 添 r2 / Livermore 止损 |
| 产物路径 | 拟 MQ `exports/analysis/joint-return-v1/<run_id>/manifest.json`、`intents.csv`、`constraints.csv`、`pref_check.json`；BT `backtest_output/joint-return-v1/<run_id>/orders.csv`、`fills.csv`、`daily_nav.csv`、`summary.json`。数字仅未来宿主保留，不入库 |
| 验收 | 合成 pin：ties / 中位数等号 / 回填不足 / 旧仓延续；契约 round-trip 不丢意图；信号发布时间与 session 端点；买入日禁卖、涨跌停/无 bar、现金不足/超卖拒绝、费用只扣一次、期末 mark 非 SELL；公司行动数量单位显式。实际运行前 P-REF 按 MQ-PJSON 原口径及预定容差复核。最小 summary 必含 §3.3 换手 / 回撤 / 净超额字段，合成手算通过，真实值待实测 |
| Non-goals | 不运行现有 PortAna 重放或 Mode B 冠军网格；不改生产 ledger / scanner / Mode B；不增加新止损、WRD1 过滤或残差叠回；本刀不做完整压力矩阵 |
| 映射 | P-REF / P-BASE / P-CHASE；M-REF / M-LAG；Q39 / Q7 / Q36 / Q29；δ1/δ2 只作边界对照 |
| 估时 / 立即开工 / 机器 | **L；R0 与相关派工决定落定后开，当前不编码**；GrokBot 编码/data-free，重数仅交 4090 |

若从已知快照无法恢复原始 10/3 意图，R1 必须报阻塞，不能从 PortAna 最终持仓倒推已失败订单。若已有快照不存在，后续单独核对冻结规则后才能实现仅生成意图的确定性适配；不能偷偷调用旧回测补齐。

### R2 — 换手预算与 anti-chase 联合约束

| 项 | 派工定义 |
|---|---|
| 所属仓 / 前置 | MQ；R1 组合状态递推与合同通过，P3 的 `τ` / 数值容差先登记 |
| 输入冻结 / 动作 | P-BASE 与原始 10/3 不变；按 §3.3 约束目标换手，先 P-TURN 再 P-CHASE-TURN；保留现金、未执行意图及旧仓，初始建仓独立报告 |
| 产出路径 | 扩展拟 `my_scripts/joint_return_portfolio.py`、`tests/test_joint_return_portfolio.py`；拟 `exports/analysis/joint-return-v1/<run_id>/turnover.csv`、`constraints.csv`、`intents.csv` |
| 验收 | 合成 pin：价格漂移不等于交易、现金项不可省、初建不隐去、约束冲突显式失败；τ 不被暗放宽。未来报告目标/实际换手、净费用、ΔMDD、ΔR_net，不以换手下降单项判收益成功 |
| Non-goals / 映射 | 不改 10/3 为低频配置、不扫 τ、不按分钟结果反选预算；P-TURN / P-CHASE-TURN |
| 估时 / 立即开工 / 机器 | **M；不抢首批，R1 后派**；GrokBot/data-free，4090/真实评估 |

### R3 — 行业 / 市值中性与尾部暴露

| 项 | 派工定义 |
|---|---|
| 所属仓 / 前置 | MQ；R1/R2、PIT 行业/size 来源及 P3 风险预算。缺 PIT 只阻塞本刀，不阻塞 R1 |
| 输入冻结 / 动作 | 不残差化 score；相对共同宇宙等权，按股票总敞口缩放基准，现金另列。拟固定目标 `min Σ(w − w_base_target)^2`（股票及现金等权项），约束含非负、预算和各臂风险上限；求解器/精度/确定性排序在 P3 登记。先 P-IND / P-SIZE，再 P-NEUTRAL / P-NEUTRAL-TURN，最后 P-ALL；尾部先报告低于当日 T0 anti-rank 中位数的持仓权重之和及行业集中度，新增尾部预算须登记而非另开特征 |
| 产出路径 | 扩展拟 `my_scripts/joint_return_portfolio.py`、其 tests；拟 `exports/analysis/joint-return-v1/<run_id>/exposures.csv`、`infeasible.csv`、`intents.csv` |
| 验收 | 合成可行/不可行样例与容差边界；10 只候选不足以中性时照报；不增加票数、不做空、不靠现金冒充中性。联合臂组成项均通过；暴露 / 尾部改善与换手 / ΔMDD / ΔR_net 并列 |
| Non-goals / 映射 | 不扫行业版本、市值定义或窗口；不新增 tail 因子；不把“保留旧仓”记成约束成功。映射 P-IND / P-SIZE / P-NEUTRAL / P-NEUTRAL-TURN / P-ALL；尾部约束属 #89 风险预算细化，具体公式未登记前不执行 |
| 估时 / 立即开工 / 机器 | **L；后置，数据缺口尚未关闭**；GrokBot/data-free，4090/真实评估 |

### R4 — 成交敏感性与成本穿透

| 项 | 派工定义 |
|---|---|
| 所属仓 / 前置 | BT；R1 的同意图配对通过；P4 参数及 P5 经济/数量语义固定。R2/R3 非前置，可先用 P-BASE / P-CHASE |
| 输入冻结 / 动作 | 每个组合臂以 M-LAG 为因果基线；逐次加入 M-DELAY、M-NOFILL，再按证据加入 M-PRICE、M-PARTIAL，单项通过才组合。固定费用表和意图，仅 fill 与派生现金持仓变化；费用参与现金资格检查，不能仅事后扣费 |
| 产出路径 | 扩展拟 BT `backtest/research/joint_return_replay.py`、`tests/test_joint_return_replay.py`；拟 `backtest_output/joint-return-v1/<run_id>/fill_attribution.csv`、`orders.csv`、`fills.csv`、`summary.json` |
| 验收 | 合成 pin：同 signal hash、合法延迟、不利方向价格及合法价域、部分成交余量、过期/反向意图冲突、不同 lot 可卖资格、交易顺序/现金守恒；全意图分母报告成交与未成交。逐项归因执行差额、费用、实际换手、ΔMDD / ΔR_net；新参数无数据来源则该项 `INPUT_BLOCKED` |
| Non-goals / 映射 | 不扫冲击/参与率找最高收益；不改 Mode B 原库、book/v7、δ1 默认或印花记账；不把分钟 OHLCV 当排队证据。M-DELAY / M-PRICE / M-PARTIAL / M-NOFILL / M-COMBINED；M-PARTIAL 仅隔离研究假设，不表示 δ5 生产参与率上限已实施 |
| 估时 / 立即开工 / 机器 | **L；R1 后派，先延迟/未成交，价格/参与率缺证据可分别停**；GrokBot/data-free，4090/真实评估 |

### R5 — 联合归因、可比性与报告封装

| 项 | 派工定义 |
|---|---|
| 所属仓 / 前置 | MQ 汇总，BT 提供完整台账；R1 最小 summary 即可先开；R2/R3/R4 按已交付臂增量接入 |
| 输入冻结 / 动作 | 冻结 metric_version、完整日历、资金基数、benchmark、费用域与样本；组内看 fill 效应，跨组看组合效应；原窗口 / 月度、行业 / size / 流动性分层缺输入就明确不可得，不静默删行 |
| 产出路径 | MQ 拟新增 `my_scripts/joint_return_report.py`、`tests/test_joint_return_report.py`；未来轻量报告 `docs/reviews/joint-return-v1/<run_id>-REPORT.md`；数字汇总留拟 `exports/analysis/joint-return-v1/<run_id>/paired_metrics.csv`、`verdict.json` |
| 验收 | 从 fills→cash/positions→NAV→metrics 可复算；合成手算净额、回撤、换手与处理−对照一致；覆盖 / 不可行 / 公司行动污染单列。必须区分“实现通过”“可比性通过”“收益待实测/无支持/有待外部验证线索”；RankIC 不参与晋级 |
| Non-goals / 映射 | 不拼 Mode A/B NAV、不把历史宿主收益移植、不用已见 OOS 选参、不补 Sharpe 数字；汇总全部已交付 P-* / M-*；δ2 经济残留作为资格门 |
| 估时 / 立即开工 / 机器 | **M；R1 后可先做最小报告，不等完整矩阵**；GrokBot/data-free，4090/计算重表，GrokBot/回执文档 |

### R6 — 封装宿主清单与一次有限执行回执

| 项 | 派工定义 |
|---|---|
| 所属仓 / 前置 | 联合验收负责人出包、4090 宿主执行人接单；R0/R1/R5 通过，§8.2 所有必填齐备。R2/R3/R4 只有进入当次清单才成为依赖 |
| 输入冻结 / 动作 | 两仓实际代码 SHA、contract/input hashes、限定 P×M 清单、参数 / 窗口 / 预算、缓存码集/版本固定；先 manifest-only 核验，再受限 smoke，后同版本有限清单；任何重试保留 run_id/父运行与原因 |
| 产出路径 | MQ 拟 `docs/reviews/joint-return-v1/host-handoff.md`、`<run_id>-RECEIPT.md`；数值留 §R1 两仓独立研究目录，绝不覆盖既有 Q39 目录 |
| 验收 | 文档阶段：命令来自实现后真实 `--help` 与合成验收，不虚构参数；宿主阶段：实际 tip、hash、机器、日志、exit code、耗时/内存、覆盖和全部状态写回，失败也有回执。所有收益字段仍以真实产物为准；未运行写 `NOT_RUN` |
| Non-goals / 映射 | 本任务不执行；不在 4090 启动/安装 Codex；不补湖、不重建缓存、不跑旧默认网格、不现场修代码；映射 #89 两层执行前置、BT-MRUN 的宿主留证方式 |
| 估时 / 立即开工 / 机器 | **S（派工封装）；实际跑数耗时待实测，不估 GPU 加速**；当前不可开跑；GrokBot/文档与门禁，4090/获派后重数 |

## 5. 人裁表 P*：现有授权与后续必填分开

当前用户已授权**本篇 docs-only 计划、commit、push、PR**，不为这些动作再次求确认。下表用于后续实现派工；本文推荐值不是已获得的生产行为授权。旧 BT 的 P1/P2/P4、δ1/δ2 已裁 A 保持，不重问、不重开。

| ID | 决策 / 推荐 | 当前状态与只阻塞什么 |
|---|---|---|
| **P1** | 首周只 R0+R1：先冻结合同，再做 P-BASE/P-CHASE × M-REF/M-LAG 的最小链；主模型不动 | 战略已由用户指定；后续代码实施与具体执行人尚待派工。本 PR 只写实施清单 |
| **P2** | 10/3 原始规则、初始持仓现金、信号可用时点按真实冻结快照；推荐因果 M-LAG 为主、M-REF 仅理想参考 | 来源 / 时点证据待补；阻塞真实输入及可交易解释，合成契约可先做。不得把默认 50/5 或旧 11 亿现金池带入 |
| **P3** | 行业 `ε_ind`、size `ε_size`、换手 `τ`、尾部预算、求解容差与不可行处理由风险依据一次登记 | 数值待登记；仅阻塞对应 R2/R3 臂，不阻塞首批 anti-chase。仅原 P-REF 允许规则内回填放宽，其余无隐含放宽 |
| **P4** | 延迟、订单有效期/重试/冲突优先级、合法 session、滑点/冲击与参与率参数及证据一次固定 | 生命周期阻塞 R1；敏感参数各阻塞 R4 对应项。推荐先做可核实延迟/保守未成交，禁止看到收益后挑分钟或阈值 |
| **P5** | 研究费用、收费粒度、公司行动和整手/零股语义明确注册；推荐继承 Mode B 研究近似并标范围 | 不假定 CSV δ1 或 Mode B 单模块已闭合新适配账本；真实费用/公司行动来源待补。需要改生产默认或完整红利账本时另案，当前不改 |
| **P6** | 主判看同 fill 的 P-BASE 净超额、换手及回撤；运行前固定支持阈值、可接受回撤/换手预算、不确定性方法、独立检验窗 | 未登记则只能输出工程 / 历史诊断，不判收益晋级；既有 OOS 已观察，不冒充盲测。市场指数只作另表，基准版本待补 |
| **P7** | 4090 执行人、资源上限、缓存只读清单及缺失停止政策；推荐任一必需项缺失即退回缺口单 | 首周默认不直接开跑；完成 §8.2 的可审查包后才能派工。无 4090 Codex，不嵌套代理 |

## 6. 硬锁 F-R*（联合计划局部编号）

| ID | 硬锁 / 可核验方式 |
|---|---|
| **F-R1** | 本次变更白名单只有 `docs/reviews/2026-09-19-joint-return-implementation-plan.md`（可选 INDEX 本次未创建）；两仓代码 / tests / 配置 / 数据均不改；事实包和旧总结只读 |
| **F-R2** | pred `8a061ea4`、10/3、模型和特征冻结；不重训、不新增特征/sidecar、不做 residual 叠回，不扫 seed / 窗 / 方向为 B 翻案；特征研发冻结一周 |
| **F-R3** | 本任务不跑回测、训练、湖、宿主网格、NP2；后续 data-free 仅在 GrokBot 的受控环境。4090 仅执行人跑已封装任务，禁嵌套 Codex |
| **F-R4** | 两仓基线固定为头部 40 位 SHA；后续另分支登记实际基线/代码 SHA，若变更须核差与重新验收受影响合同，不能用移动 master 或现算 merge-base 偷换 |
| **F-R5** | 不改生产撮合、Mode A/B 原实现、书/v7、读取器、缓存、特征与在线导出；后续仅独立研究入口。旧 P1/P2/P4 和 δ3/δ4/δ5 不因本计划自动获准 |
| **F-R6** | 同组固定 signal/intent hash、原始目标数量、触发参考、费用与初始资金；仅 fill 假设改变。各情景守现金 / T+1 可卖量，真实 fill 不反馈改信号 |
| **F-R7** | 可得时点早于合法成交；none 日线 / 分钟域一致；close 事件不倒填同根 open。Q39 不恢复 H/L；Q7 跌停次日重评；Q36 缺分钟顺延；N 按市场交易日，期末 mark 不是 SELL |
| **F-R8** | 门未拦截 ≠ 成交；全意图分母、失败日、缺失日、不可行日、滞留持仓均保留；各组合臂沿时间独立递推；不删困难样本、不扩 10 只、不暗放宽风险约束 |
| **F-R9** | δ1 commission-only 代理费率不等于真实税费；不加第二印花行、不 import live fee policy。δ2 书/v7 cost/peak 与 Mode B shares÷k 分开，现金红利 / PIT / 错域残留不宣称已修复 |
| **F-R10** | 不复活 PortAna/Exchange、Cerebro、Rolling、LEBS/live；不拼 Mode A/B 收益；oracle 仅事后上界，不优化为可交易策略；T5 标签与原指标口径不改 |
| **F-R11** | 参数、样本、费用、窗口和判断标准在看新增收益前固定；历史 OOS 标为已观察。门禁通过仅代表实现或可比性，不代表产生净收益增益；所有新数字待实测 |
| **F-R12** | 新真实产物宿主独立目录、不入 Git、不覆盖旧缓存 / 报告；日志及文件 hash 可追溯；文本 UTF-8 无 BOM、NUL=0，提交差异及引用路径必查 |

### 后续 data-free 门禁如何复用

以下 BT 既有路径均已在 IMPLEMENTATION_BASE_BT 固定树核实；**本次未运行**。未来在受控 Python 3.12 环境，用仓库 AGENTS 指定的显式解释器、`not production and not benchmark` 范围运行受影响合同，不隐式用系统 Python。记录实际 HEAD、命令、exit code、收集数与 skip，不能挪用历史 passed 数。

| 门禁集合 | 已存在的 BT 路径 | 对新链的证明限度 |
|---|---|---|
| Q39 / 除权 / 聚合 | `tests/test_unified_exit_modeb_exit.py`、`tests/test_unified_exit_modeb_exdiv.py`、`tests/test_unified_exit_modeb_aggregate.py` | 既有语义回归；不代替拟 `test_joint_return_replay.py` 的固定意图 / 资金接线测 |
| 费用与 import 边界 | `tests/test_ashare_fees.py`、`tests/test_ashare_fee_wiring.py`、`tests/test_ashare_simulate_import_fence.py` | 保护 δ1 与固定热路径围栏，不证明新 Mode B 账本已接通 |
| 交易 / 公司行动边界 | `tests/test_ashare_session.py`、`tests/test_ashare_simulate_predicates.py`、`tests/test_exdiv_map.py`、`tests/test_exdiv_refprice_engines.py` | as-built pins；经济残留/PIT 未证仍是限制，不改旧测试凑绿 |
| 仓库级合同 | `scripts/gates/verify_oskh_data_contract.py`、`scripts/gates/verify_data_path_ssot.py`、`scripts/gates/verify_no_hardcoded_machine_paths.py`、`scripts/gates/verify_tr_bridge_import_ssot.py` | 路径及边界门；不是收益或真实成交证据 |

未来各 PR 同时审计 base→HEAD、未暂存、暂存、未跟踪路径；既有生产文件零 diff，新增研究文件只能在已登记白名单。新测试要覆盖接口失败和经济不变量，不把“无真实数据可跑”当全部测试通过。

## 7. 与 industry-align 并行：局部阻塞，限制结论

收益研究不等待正确性长尾全部清零；正确性也不替代收益研究。R0/R1 的契约、组合算法、合成配对与报告实现可先做；真实数据中碰到某类残留，只阻塞受影响情景或结论层，不默默排除样本继续报赢。

| industry-align 轨道 | 本文基线状态 / 不重做项 | 联合收益轨道消费方式 / 停止边界 |
|---|---|---|
| fill clock / fill gates | 已有命名与 as-built 分叉；14:57 标签不证明交易所撮合；书/v7 的未知档位、ST、零量行为不同 | R1 明确所用路径并钉“资格 vs fill”；不把 v7 fail-open 移植为成交保证，不等待统一全部引擎 |
| P3 δ1 fees | 已有默认/覆写/floor/现金资格与边界合同 | R1/R4 自己证明新适配的费用接线和扣费粒度；既有研究费率不包装成真实税费。真实费用缺口阻塞真实净收益外推，不阻塞合成账本 |
| P3 δ2 exdiv | docs + pins 已验收；E-R6 仅参考价；书/v7 未增股/无现金红利；因子恢复日错域、停牌漏事件、原始 PIT 未证仍在 | R1 保留 Mode B 自有模型且 pin 数量/资金域。原始因子时点或域无法证明，相关真实配对为 `SEMANTICS_BLOCKED`；可报告带明确限制的历史近似，不授予收益晋级 |
| δ3 ST PIT / δ4 `limits=None` | 保持后置；不借本任务统一政策 | 若新链消费到非 PIT ST 或未知档位，完整记录并阻塞受影响的可交易解释；无需等这些改造才写 R0 或跑合成向量 |
| δ5 participation cap | 生产 cap 仍后置 | R4 的 M-PARTIAL 是隔离、预注册的研究假设；单位 / 证据不够则该情景停，M-LAG/M-DELAY 的合格部分仍可交付 |
| P1 / P2 / P4 | 14:57 行为、旧 trades 新列、touch↔mark 改造继续挂起 | 新研究台账不改旧 trades schema；新情景不回写生产扫描器；确需改生产时退出本计划、另开范围 |

BT-ENGINE 的 E-R5 重开条件包含“分钟链成为主研究面”等，本战略已触及该类研究方向。**不能因 δ2 pins 通过就宣布 E-R5 已解除。** R0 登记此依赖，R6 派真实净收益结论前，由正确性轨道完成适用性判定与所需 NP2 / 公司行动证据；本任务不跑 NP2。若尚未闭合，仍可完成 R1 合成链与 P-REF / 约束诊断，真实收益只留为受限历史研究，不标可交易支持。

不得在看过结果后删除除权 / ST / 缺分钟股票重算“干净净超额”。预注册的分层诊断可以做，但意图全集、受影响权重与日期仍保留；若完整资金路径不可对账，则完整期净超额为不可判，不能用一个事后子集替代。

## 8. 第一周派工与 4090 最小实验清单

### 8.1 只开 1–2 刀时怎么选

**只开一刀：R0。开两刀：R0 + R1。** 组合优先体现在 R1 的处理是已有分数的 anti-chase 约束；分钟配对一开始就串进最小链，避免组合标签改善到最后才发现不可成交。R2 换手预算紧随其后；R3 中性化资料缺失不能占满首周；R4 不展开滑点/参与率大矩阵。

| 时间 / 执行者 | 交付与结束条件 |
|---|---|
| 第 1 天：GrokBot，联合负责人 | R0 合同、输入缺口、相关 P*、来源与冻结表定稿；缺真实数据照报，不妨碍合成实现准备 |
| 第 2–5 天：GrokBot，MQ+BT 负责人 | R1 两仓独立研究实现与 data-free pins，使用一个冻结合同。先 MQ P-BASE/P-CHASE，再 BT M-REF/M-LAG；首周容量不足就停在已验收接口，不压缩门禁换取跑数 |
| 周末检查：联合负责人 | R1 最小台账能否从意图一路对账到净 NAV；R5 报告封装与 R6 清单准备度排下一步。首周不承诺真实收益或重数完成 |

R5/R6 的核验尚未完成时，只有 R0/R1 两刀完成也**不能**直接交 4090。特征研发冻结以联合任务启动日计一周，结束复核本链产能与缺口，不因负收益马上改回扫新刀。

| 状态 | 成功 / 失败 / 停止条件 | 后续动作 |
|---|---|---|
| `IMPLEMENTATION_PASS` | contract 一致、data-free pins 与完整资金/持仓对账通过、生产零 diff，最小链可复现 | 可准备宿主清单；这不是收益 PASS |
| `INPUT_BLOCKED` | 缺 pred/意图来源、时点、PIT、费用、参数或新码集缓存元信息 | 退回具体缺口；未依赖该数据的合成工作继续，不补湖或现场预测 |
| `PAIR_INVALID` / `SEMANTICS_BLOCKED` | signal hash 漂移、前视、价格域混用、现金/股数不守恒、删失败日、不可行伪装成功，或经济语义无法解释 | 立即停该配对；不进入收益排名，不用换窗/seed修饰 |
| `NO_RETURN_SUPPORT` | 实测在预登记预算和 P6 标准下无净超额支持、回撤/换手超预算，或改善仅来自理想化 M-REF | 如实报告负结果，停止扩臂；不调整阈值后在同窗重判 |
| `HISTORICAL_DIAGNOSTIC_ONLY` | 有数字但 P6 独立窗/阈值未齐，或费用/公司行动只支持历史近似 | 只交研究诊断；不判可交易增益 |
| `RETURN_RESEARCH_SUPPORTED` | 真实可追溯产物通过 P6 预注册净超额、不确定性、回撤/换手预算及因果/经济门禁 | 仅晋级下一轮独立研究验证；绝不改 pred/10/3、不上线 |

### 8.2 “最小实验清单”交给 4090 的前置条件（本任务不跑）

以下条目全部是后续 R6 的**必填交接项**；未齐不得把本篇当执行命令。当前新链状态统一 `NOT_RUN`。

1. **实现版本**：MQ/BT 两个实际提交 SHA、实施基线、PR 与评审范围、contract/metric 版本、只改独立研究入口的冻结证明；不存在“在 4090 再让 Codex 补代码”。
2. **验收记录**：R1 及最小版 R5 data-free pins 的实际结果、逐条必需 pin、合成端到端手算对账、真实 `--help`；不得直接复用旧宿主网格命令。P-REF 数值复核的容差/统计设置先登记。
3. **信号包**：冻结完整 recorder / score 文件 hash、10/3 原始意图与资格规则、可用时间、初始资金/持仓、已有 anti-rank hash、证券映射、参考数量转换、订单有效期/冲突规则；不得只给一个股票名单 CSV。
4. **窗口与覆盖**：P-REF 原窗为 MQ-PJSON 的 2025-01-03～2025-12-31、2026-01-01～2026-09-14。已有 BT-MRUN 业务窗为 2025-10-23～2026-09-09，只提供覆盖线索；新链准确交集须由新信号码集与 metadata 证明后固定。超范围写不可测，不延长窗口、不丢意图；P-REF 原窗复核不足即不得标复核通过。
5. **数据包**：none 日线/分钟、市场日历、公司行动事件及 PIT/域证据的只读 resolver/版本；缓存 parquet+meta 的路径、hash、码集与日期覆盖、warmup、单位/session。旧 `minute_none_20251013_20260909` key 仅说明旧缓存命名，**不证明覆盖 MQ 的新码集**；未命中则停止并回报，不自动扫湖建缓存。
6. **有限矩阵**：P-REF 单列诊断；首批仅 `P-BASE × {M-REF,M-LAG}` 与 `P-CHASE × {M-REF,M-LAG}`。M-REF 不具备因果时点时仅列理想化诊断，净超额主判断用两臂 M-LAG。R2/R4 未交付不填入任务；不得顺手跑 P-ALL、冠军族或全参数网格。
7. **费用与判定**：共同研究费率/粒度、资金基数、除权/零股处理、净超额和回撤/换手预算、P6 独立窗与统计规则均填写并冻结；尚无数值依据就标诊断任务，不能空白视为 PASS。BT E-R5 适用性及需另案关闭的经济问题有明确状态。
8. **机器与资源**：指定 4090 宿主执行人、受控解释器、代码路径、输入只读路径、独立输出路径、任务时间/内存上限、退出码与 UTF-8 日志保留。4090 是机器选择，不承诺 GPU 加速；不得安装/启动 Codex。
9. **运行顺序与停止**：先只读 manifest/metadata 检查，不启动湖加载；通过后按预登记小样本 smoke 检查串联，再一次有限矩阵。cache miss、时点不明、域不明、超资源、hash变化或对账失败立即停；禁止下载/补名单/重建缓存/现场改参数。
10. **回执**：实际代码/输入 hash、运行命令、起止时间、资源与 exit code、意图全集覆盖、缺失/失败原因、台账及完整指标路径；无论正负均回传轻量报告。实测换手、回撤、净超额及成交数据来自这些产物，未生成的字段写“待实测”。

首批因 anti-rank / 原始意图缺失而停时，可交付输入缺口与合成链验收；不得另选一个更容易出正收益的组合臂顶替。冻结特征、组合优先、同信号成交敏感性的主轴保持。

## 9. 本次文档交付验收

- 只新增主文；Git diff 无训练、撮合、特征、配置、测试或数据改动；本地 `.sibling-MyQuant-backtrader` 是已有只读导航 symlink，不加入提交。
- 两仓 40 位基线对象可解析；BT 引用按固定树核实，既有源码/测试/门禁路径与拟新增落点明确区分；找不到的输入已标“未找到，待补”。
- UTF-8 无 BOM、NUL=0，whitespace 检查通过；新收益、成交率、滑点、Sharpe 没有预填；本任务没有运行测试、回测、湖或宿主命令。
- commit / push / PR 只发布文档；本次文档验收不标 R0–R6 实现或收益通过，也不以历史 BT 测试数替代新链验收。

## 10. Changelog

- **v0.1（2026-09-19）**：基于固定 MQ / BT 基线，将 T5 总结及七条下一步、#89 组合/Mode B 实验计划落为 R0–R6 七刀。新增跨仓固定意图合同、数量/时点/成本对账、P* 与 F-R*、industry-align 局部阻塞规则、首周 R0+R1 排序及 4090 最小清单前置。记录 sibling HEAD 与指定 BT 对象差异、旧宿主完成状态和未找到的真实输入；仅文档，无实验结果、代码或生产变更。
