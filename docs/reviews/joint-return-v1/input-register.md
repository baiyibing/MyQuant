# Joint return v1 输入登记

本刀只在 GrokBot 做 MQ control-only P-BASE data-free。以下“已核实”指固定仓库文本存在，不表示原始数据在本机或 4090 可读。用户已澄清原始 10/3 未上线、从未实盘，仅有回测；不存在线上原始意图包，不再要求 live frozen_original intents。未知 URI/hash/覆盖逐项标 `INPUT_BLOCKED`，不搜索湖、不新预测、不由已成交持仓补造失败订单。

## 2026-09-20 瘦合同裁定（覆盖下方历史全量依赖）

工作基线 origin/master=`7e94891a9b5b79010cbe2f293515ac3f1e5bb08f`（含 #94）。用户回执：4090 当前分数原料只有 date/instrument/score，anti/universe/labels 与 sessions/initial_state/pref 未齐。当前不宣称这些真实文件已补齐；解除的是 P-BASE 对后置 anti 链的依赖。

| 项 | P-BASE control_only | 后置臂 / 验证 |
|---|---|---|
| control pred | 固定原 recorder；只消费 control，保留全部键。三列原料可用显式 control-metadata 补来源/逐日可得时点，URI/双 hash 入 merge 回执 | 不重训、不重预测；原始来源/PIT/覆盖仍须宿主核验 |
| candidate universe | 不需要；candidate_present 省略/null，不从 control 名单伪造 | full / P-REF-anti INPUT_BLOCKED |
| anti_rank / anti_available_at | 不需要，不计算 anti 中位数 | P-CHASE、弱信号/anti 依赖臂 INPUT_BLOCKED；不重建 sidecar |
| labels / pref | 不需要；pref 明确省略，pref_check NOT_RUN | P-REF-anti NOT_RUN；恢复 full 保留原 expected/hash/两窗门禁 |
| 研究 initial_state | 允许显式选定研究现金空仓，不需要线上/历史持仓；仍必须提供文件与输入锁 | 不自动给金额，不从 PortAna/账户/旧缓存补仓 |
| 研究 sessions | 规则生成器需逐日价格/映射/资格/时钟/事件声明；显式 JSON 合同已有，无湖依赖 | 缺真实价格/资格仍局部 INPUT_BLOCKED；不能造值。已有合法 plans 则 freeze 不另需 sessions |
| P-BASE plans / portfolio | 单臂每日计划，50/5 默认，20/3、10/3 可配；三段 frozen 后独立通过组合约束 | 本地状态 PORTFOLIO_CONSTRAINTS_PASS，execution NOT_RUN；不是收益通过 |
| Mode B / BT / 实际指标 | 不属于 MQ 瘦入口依赖 | INPUT_BLOCKED / NOT_RUN；实际换手、回撤、净超额待执行/估值证据，不能用 RankIC 代替 |

宿主最小用法及三列来源声明见 [交接清单 §0](host-frozen-snapshot-checklist.md)。各阶段 scope_status 分列记账；顶层真实 input_status 保留上游来源待核验含义，不再把 anti/universe/labels/pref 缺失扩成 P-BASE 本地链阻断。

## 全量来源登记与历史依据

代码基线、白名单与 serialization 见 [contract](contract.md)；旧派工记录为 [联合计划](../2026-09-19-joint-return-implementation-plan.md)，本次用户澄清及修订合同优先。新 MQ 实施基线 `4e4368b274ada2e27da5902f7420aa5a8ae5950c`，BT `1049b904bdd818dbb79f51f1830a008c8f83b141`；旧计划 MQ 基线仅溯源，不替换用户令。生产/特征/pred/线上 10/3 配置/Mode A/B、δ1/δ2 既有实现及 sibling 均只读。研究默认 50/5（仓内实验积累最多），20/3、10/3 可切换；不据此声称有线上程序在运行。

| 输入 / 证据 | 已知来源与值 | 状态 / 影响 / 后续责任 |
|---|---|---|
| MQ-EXP、F-R* | [实验计划](../2026-09-19-next-portfolio-execution-plan.md)、联合计划 §6 | 文本已核实；旧研究 10/3 硬锁和索取 live 原始包已由用户澄清替代；本次白名单见修订 contract §1 |
| MQ-PREF | [REPORT](../t5-campaign-20260919/t5_mxr1_20260918/pseudo1_top10_constrain_20260919/REPORT.md) | 文本已核实；T0/T1 排序、中位数等号、回填/放宽、Top10Spread；不是成交 PnL |
| MQ-PJSON | [summary](../t5-campaign-20260919/t5_mxr1_20260918/pseudo1_top10_constrain_20260919/summary.json) | 文本及 raw/canonical hashes 已核实（见 contract §1）；窗口、统计设置与 recorder 来源 |
| 原始 control pred | recorder `8a061ea428e04bb3a199a485ade49d0e`，原始 URI/文件 hash/覆盖包未找到 | INPUT_BLOCKED：P-REF 与真实组合；后续 MQ 输入负责人只读定位 |
| candidate 宇宙 | `d03e8ffcb6d14668b4d6fc2b192bc8c7`，对齐快照未找到 | INPUT_BLOCKED：共同宇宙复核；禁止取候选 score 排序 |
| 原 anti-rank sidecar | 预期 hash `27320f8b7f6de3854802f97325f682039732470ce387f21bc9cd6c3083b7b348` | INPUT_BLOCKED：文件/时点/覆盖未核验；不新造 sidecar，不 residual 叠回 |
| label / 真实完整日历 | 原式与两窗见 MQ-PJSON；原始逐行数据未找到 | INPUT_BLOCKED：真实 P-REF；日历 242/170、可用 Top10 242/169 来自旧文本，不能替代本次核验 |
| 原 P-REF bootstrap 生成源码 / 全统计口径 | 原报告记录 block=5/reps=10000/seed=20260919；新入口覆盖横截面、RankIC、bootstrap、月季度表并明确规范 | INPUT_BLOCKED：真实复核须数值与原生成/缺失语义对齐；不得反写旧值或调容差凑绿 |
| 回测规则意图（替代不存在的 live 原始包） | `joint_return_rule_intents.py`，source=backtest_rule_intents，rule_version=topk-dropout-reference-v1 | 适配已实现；50/5 默认，20/3、10/3 可配，双臂独立参考递推。**不存在 live 原包不是 blocker**；真实运行仅待下列规则输入/来源齐备，不用 PortAna 倒推。 |
| TopkDropout 配置及逐日资格 | 仓内 replay_2025_st_age_vs_15.py（50/5）、replay_10n3_two_year.py（10/3）；基础 Qlib top/bottom 核心已按固定 commit 核对 | 输入模式已定义：topk/n_drop 可配；hold_thresh/risk_degree/资格规则、逐只布尔判定/原因/可得时点仍须显式提供。缺列 INPUT_BLOCKED，不猜 ST/年龄/涨幅。 |
| scores 合并 | `joint_return_merge_scores.py` 以显式共同宇宙逐键核验 control/anti/label | 已实现；缺列/缺共同键 INPUT_BLOCKED，不 inner join、不换 candidate score、不重新预测；额外键完整留账。真实导出 URI/hash/时点待核验。 |
| 旧导出入口 | `my_scripts/export_positions_trades.py` 持仓；`my_scripts/export_next_day_pool.py` 默认 50/5，可预测 | 只读来源线索；不是本链输入，不调用 |
| 研究初始现金/持仓、holding_days、参考 marks | 允许显式研究现金空仓起点；非空初态须数量/lot/instance/持有交易日数 | INPUT_BLOCKED：研究资金/价格/时点来源未给；不要求线上账户，不继承旧现金池，不把合成金额当真实参数。 |
| score/anti 发布时点、证券映射 | 原始可用时间、映射版本未给 | INPUT_BLOCKED：因果 M-LAG 与数量转换；后续 MQ/BT 联合核验 |
| 研究费用 / 生效到期时间 | P4/P5真实费率、最低费、订单时点来源未给 | INPUT_BLOCKED：真实订单/净额；合同已固定有限生命周期枚举，合成显式零费/最低费不作真实推荐 |
| none 日线/分钟、session、交易日历 | 旧 BT 缓存名/业务窗只有历史出处 | INPUT_BLOCKED：BT R1/R6；不证明新码集覆盖，不按旧窗自动截取 |
| 4090 新码集缓存 manifest | 路径/hash/码集/日期/单位/warmup 未找到完整包 | INPUT_BLOCKED：宿主执行；cache miss 应退回，不扫湖重建 |
| 公司行动事件 / PIT / 数量因子 | δ2 文本说明范围，真实映射包未给 | INPUT_BLOCKED / SEMANTICS_BLOCKED：受影响配对；本 MQ v1 非空事件拒绝，不能漏事件后标绿 |
| PIT 行业 / size | 分类、市值定义、时点/文件 hash 未给 | INPUT_BLOCKED：R3，对 MQ R1 合成无依赖；不借此扩臂 |
| benchmark 与 P6 判断预算 | 主基准同 fill P-BASE 已定义；市场指数/独立窗/支持阈值未给 | INPUT_BLOCKED：收益判断，所有新收益待实测 |
| BT E-R5、NP2 适用性 | 正确性轨道尚需明确分钟主研究面的经济证据 | SEMANTICS_BLOCKED：可交易净收益解释；本刀不跑 NP2、不重开 δ1/δ2 |
| 4090 执行人与资源清单 | 后续由 4090 + Cursor Grok 4.6 执行，具体缓存、上限、回执未齐 | INPUT_BLOCKED：R6；本刀不连接、不运行 4090、不嵌套 Codex |

真实窗口不能从旧脚本继承：P-REF 原窗 2025-01-03～2025-12-31、2026-01-01～2026-09-14；旧 BT 2025-10-23～2026-09-09 仅覆盖线索。新链交集须新码集 metadata 证明，超范围保留“不可测”，不删失败日凑配对。当前新链真实状态统一 `NOT_RUN`。

P1–P7 在本刀的落实：P1 已由用户令明确只做 R0/MQ R1；P2 已按用户澄清改为确定性回测规则生成+独立状态 hash；规则默认 50/5，支持 20/3、10/3；P3 只允许原 anti-chase 的记录式放宽，无 R2/R3 参数；P4 生命周期枚举钉合同、具体真实时间仍缺；P5 合成冻结 share/100 股新买/旧 lot 退出/commission-only，真实费用与公司行动仍缺；P6 不判断收益；P7 只做 GrokBot 合成，无宿主授权包。

后续补输入必须记录 URI、原字节 hash、规范内容 hash、覆盖日期/证券/行数/缺失原因、版本、发布时间、价域与数量单位、核验人及核验时点。不能仅把状态改成绿色，本次已明确登记回测规则适配版本和与 Qlib 的参考约束差异；不得称为线上原始意图，不再索取不存在的 live 包。

2026-09-20 MQ 显式拼装入口与 recorder READY 回执的适用边界见 [回测规则 freeze 交接清单](host-frozen-snapshot-checklist.md)；真实 scores/资格/研究初态/参考价/可得时点、PIT/ε/τ 与 BT Mode B 缺口仍逐项阻塞；旧“缺原始 10/3 live 包”条目已撤销。
