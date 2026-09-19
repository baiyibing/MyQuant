**结论：本轮 T5 无 FEATURE_CANDIDATE；MAXRET 与 WRD1 的条件信息通过 A 门，但未稳定迁移到 B 门，下一步优先研究组合约束与分钟成交，不再叠加特征刀。**（终态依据：[FACTS.json](t5-campaign-20260919/FACTS.json)；下一步为本文建议。）

## 范围与冻结

本文只汇总只读事实包 [t5-campaign-20260919/](t5-campaign-20260919/)，覆盖包内全部刀及 MAXRET、WRD1 的 B-diag、头尾部伪实验和残差叠回伪实验。包内收录轻量 verdict、REPORT、summary 等材料，不含原始 parquet、预测 CSV 或 mlruns；本文不重新计算实验结果。（来源：[README.md](t5-campaign-20260919/README.md)、[SOURCE_INDEX.md](t5-campaign-20260919/SOURCE_INDEX.md)。）

- **线上冻结：online pred `8a061ea4` / 10/3 全程未改。**（来源：[FACTS.json](t5-campaign-20260919/FACTS.json) 的 `online_pred`、`constraint`。）
- **最终无 FEATURE_CANDIDATE**：各刀终态均为数据无效、条件信息未过门或模型未迁移；没有进入 C / PortAna / BT。（来源：[FACTS.json](t5-campaign-20260919/FACTS.json) 及下表逐刀 verdict。）
- **本次汇总使用的事实包 tip SHA：`ecde0f7`**，分支 `docs/t5-campaign-20260919`。该 SHA 固定标识本文采用的事实包版本；本文初次提交为 `2d33d68`。事实包 tip 不是各刀原始实验 tip，也不是实验统计量。
- 本次交付仅为本文；不修改事实包、非文档代码、线上配置或 MyQuant-backtrader。

以下来源标签均为**相对事实包根目录**的路径，链接从本文所在目录解析。表格“来源”列覆盖该行全部数字与判决；正文数字紧随来源。数字保留所引 JSON 原值或原报告已有精度，不另行换算收益单位、估算或加工舍入。

## 逐刀结果

下表 A 门均值依次为 **2025 valid / 2026 OOS**，CI 为样本外 **95% CI**；窗口、置信水平及展示精度均沿用各行来源。H52A1 优先按覆盖失败定性，信息量不用于改判。

| 刀 | 最终标签 | 停点与原因 | A 门关键证据 | 来源（本行全部数字与判决） |
|---|---|---|---|---|
| AMI1 / Amihud | `AMIHUD_CONDITIONAL_NO_EDGE` | 停 A；均值为正，但样本外 CI 跨零；B/C 未跑 | partial RankIC：+0.018829 / +0.015922；CI [-0.007202, +0.042791] | [t5_ami1_20260918/t5_ami1_verdict.md](t5-campaign-20260919/t5_ami1_20260918/t5_ami1_verdict.md) |
| BETA1 | `BETA_CONDITIONAL_FLIP` | 停 A；跨窗反号；B/C 未跑 | partial RankIC：−0.003630 / +0.004667；CI [−0.029287, +0.042903] | [t5_beta1_20260918/t5_beta1_verdict.md](t5-campaign-20260919/t5_beta1_20260918/t5_beta1_verdict.md) |
| CYQ1 | `CYQ_CONDITIONAL_NO_EDGE` | 停 A；均值为正，但样本外 CI 跨零；B/C 未跑 | partial RankIC：+0.032364 / +0.016444；CI [-0.005880, 0.037817] | [t5_cyq1_20260917/t5_cyq1_verdict.md](t5-campaign-20260919/t5_cyq1_20260917/t5_cyq1_verdict.md) |
| DSTR1 | `DSTR_CONDITIONAL_NO_EDGE` | 停 A；均值同为负，未命中反号标签；B/C 未跑 | partial RankIC：−0.002029 / −0.005503；CI [−0.020253, +0.008338] | [t5_dstr1_20260918/t5_dstr1_verdict.md](t5-campaign-20260919/t5_dstr1_20260918/t5_dstr1_verdict.md) |
| DSV1 / DSEM | `DSEM_CONDITIONAL_NO_EDGE` | 停 A；均值为正，但样本外 CI 跨零；B/C 未跑 | partial RankIC：+0.020675 / +0.030425；CI [−0.008751, +0.070781] | [t5_dsv1_20260918/t5_dsv1_verdict.md](t5-campaign-20260919/t5_dsv1_20260918/t5_dsv1_verdict.md) |
| H52A1 | `H52_DATA_INVALID` | 停 A 数据覆盖门；不得据诊断 IC 翻方向或进 B；B/C 未跑 | 覆盖率：91.02% / 88.30%，均低于 98% 门槛 | [t5_h52a1_20260918/t5_h52a1_verdict.md](t5-campaign-20260919/t5_h52a1_20260918/t5_h52a1_verdict.md) |
| MXR1 / MAXRET | `MAXRET_MODEL_NO_TRANSFER` | A 过、停 B；验证窗头部未胜，样本外 ΔRankIC CI 跨零；C 未跑 | partial RankIC：+0.044092 / +0.038542；CI [+0.004456, +0.073341] | [t5_mxr1_20260918/t5_mxr1_verdict.md](t5-campaign-20260919/t5_mxr1_20260918/t5_mxr1_verdict.md) |
| WRD1 / winratio-gap | `WINRATIO_GAP_MODEL_NO_TRANSFER` | A 过、停 B；样本外冻结 Top−Bottom 未胜，ΔRankIC CI 跨零；C 未跑 | partial RankIC：+0.017519 / +0.017242；CI [+0.003146, +0.031243] | [t5_wrd1_20260918/t5_wrd1_verdict.md](t5-campaign-20260919/t5_wrd1_20260918/t5_wrd1_verdict.md) |

CYQ 的来源明确位于 `t5_cyq1_20260917/`；原产物来自主 MyQuant 的分析目录，事实包没有为它假定独立实现 worktree。（来源：[SOURCE_INDEX.md](t5-campaign-20260919/SOURCE_INDEX.md)、[FACTS.json](t5-campaign-20260919/FACTS.json) 的 `note_cyq`。）

## MAXRET / WRD1：B-diag 与伪实验

### 冻结 B 门：先分清指标口径

MAXRET 的冻结 Top10Spread 是**等权 Top10 减共同宇宙等权**；WRD1 的冻结 Top10Spread 是 **Top−Bottom**。WRD1 的头部减宇宙指标只用于诊断，不能替换冻结 B 门；不同口径的绝对水平不直接比较。（来源：[t5_mxr1_20260918/b_diag_20260919/REPORT.md](t5-campaign-20260919/t5_mxr1_20260918/b_diag_20260919/REPORT.md)、[t5_wrd1_20260918/b_diag_20260919/REPORT.md](t5-campaign-20260919/t5_wrd1_20260918/b_diag_20260919/REPORT.md)。）

下表 Δ 均为候选减对照，直接摘录冻结 `pred_pair/verdict.json`。验证窗 CI 不参与否决，故该列留空；样本外列为冻结 ΔRankIC CI。

| 刀与窗口 | ΔRankIC | ΔTop10Spread（各自冻结口径） | 样本外 ΔRankIC CI | 来源（本行全部数字） |
|---|---:|---:|---|---|
| MAXRET / 2025 valid | 5.0768410642020034e-05 | -5.260264777101273e-05 | — | [t5_mxr1_20260918/pred_pair/verdict.json](t5-campaign-20260919/t5_mxr1_20260918/pred_pair/verdict.json) |
| MAXRET / 2026 OOS | 0.00046281734652085446 | 0.0004921033324056564 | [-0.0005562195993456413, 0.0014590946571083482] | [t5_mxr1_20260918/pred_pair/verdict.json](t5-campaign-20260919/t5_mxr1_20260918/pred_pair/verdict.json) |
| WRD1 / 2025 valid | 0.00026165899706542817 | 0.0015516403008036875 | — | [t5_wrd1_20260918/pred_pair/verdict.json](t5-campaign-20260919/t5_wrd1_20260918/pred_pair/verdict.json) |
| WRD1 / 2026 OOS | 0.0006696727179042773 | -0.00034010738613822304 | [-0.00064472672697206, 0.0021847408549700497] | [t5_wrd1_20260918/pred_pair/verdict.json](t5-campaign-20260919/t5_wrd1_20260918/pred_pair/verdict.json) |

因此，MAXRET 卡在验证窗头部表现与样本外排序增量的不确定性；WRD1 虽在验证窗同时改善排序与冻结价差，样本外仍被冻结价差及排序 CI 否决。均值微升不能替代完整门槛通过。（来源：上表各刀 `pred_pair/verdict.json`。）

### B-diag：特征被使用，但头尾部机制不同

**MAXRET：**报告确认 LGB 使用了该列。验证窗候选换入票的 anti-rank 更低、次日收益更差，头部进一步偏向近期大涨股；报告据此将头部换入方向列为失败机制。特征相对冻结 score 的条件信息，未转化为稳定的全模型排序与持仓改善。（来源：[t5_mxr1_20260918/b_diag_20260919/REPORT.md](t5-campaign-20260919/t5_mxr1_20260918/b_diag_20260919/REPORT.md)。）

**WRD1：**报告同样确认 LGB 使用了该列，但候选头部没有明显偏向低 gap。样本外冻结价差的恶化主要由候选底部收益上升解释；头部减宇宙的点估计仍微正。它与 MAXRET 的头部换入机制不同，不能直接照搬 MAXRET 的过滤规则。（来源：[t5_wrd1_20260918/b_diag_20260919/REPORT.md](t5-campaign-20260919/t5_wrd1_20260918/b_diag_20260919/REPORT.md)。）

**来源差异处理：**包内 B-diag `summary.json` 的部分重算汇总与 `REPORT.md` 明示的冻结口径对齐结果不同。本文的 B 门数字采用原始 verdict；机制解释按所引 REPORT，后续伪实验采用各自 summary，不混合这些字段，也不声称包内诊断汇总已全部一致。（核对路径：[t5_mxr1_20260918/b_diag_20260919/summary.json](t5-campaign-20260919/t5_mxr1_20260918/b_diag_20260919/summary.json)、[t5_wrd1_20260918/b_diag_20260919/summary.json](t5-campaign-20260919/t5_wrd1_20260918/b_diag_20260919/summary.json) 的 `recompute_vs_frozen`，及上引 REPORT。）

### 头尾部伪实验：机制得到有限支持

**MAXRET 头部约束：**从对照 score 名单出发，跳过 anti-rank 严格低于当日对照头部中位数的票，依预注册规则回填；候选分数只用于宇宙对齐，不参与约束名单的排序。（来源：[t5_mxr1_20260918/pseudo1_top10_constrain_20260919/REPORT.md](t5-campaign-20260919/t5_mxr1_20260918/pseudo1_top10_constrain_20260919/REPORT.md)。）

| 窗口 | 约束名单相对对照的 mean ΔTop10Spread | CI | 来源（本行全部数字） |
|---|---:|---|---|
| 2025 valid | 0.001105356788883118 | [-0.000505627267395951, 0.0027925108272934636] | [t5_mxr1_20260918/pseudo1_top10_constrain_20260919/summary.json](t5-campaign-20260919/t5_mxr1_20260918/pseudo1_top10_constrain_20260919/summary.json) |
| 2026 OOS | 0.0003618171010832952 | [-0.0021314959930410133, 0.0025806468553058056] | [t5_mxr1_20260918/pseudo1_top10_constrain_20260919/summary.json](t5-campaign-20260919/t5_mxr1_20260918/pseudo1_top10_constrain_20260919/summary.json) |

该实验按预注册的验证窗均值符号门槛，**支持头部换入方向解释**；CI 跨零，不能称为已证实的稳定增益。样本外只报告，不改变原判决；`MAXRET_MODEL_NO_TRANSFER` 保持不变。（来源：[t5_mxr1_20260918/pseudo1_top10_constrain_20260919/REPORT.md](t5-campaign-20260919/t5_mxr1_20260918/pseudo1_top10_constrain_20260919/REPORT.md)。）

**WRD1 底部冻结：**保留候选头部，将底部替换为对照底部，再计算 Top−Bottom。冻结底部后的价差增量等于头部收益增量，也等于头部减共同宇宙等权的增量。（来源：[t5_wrd1_20260918/pseudo1_bottom10_freeze_20260919/REPORT.md](t5-campaign-20260919/t5_wrd1_20260918/pseudo1_bottom10_freeze_20260919/REPORT.md)。）

| 窗口 | mean ΔSpread_freeze | CI | 来源（本行全部数字） |
|---|---:|---|---|
| 2025 valid | 0.0008404026302215687 | [-0.0003723261174108986, 0.002038561176656296] | [t5_wrd1_20260918/pseudo1_bottom10_freeze_20260919/summary.json](t5-campaign-20260919/t5_wrd1_20260918/pseudo1_bottom10_freeze_20260919/summary.json) |
| 2026 OOS | 5.9027014336047265e-05 | [-0.0016901782803940407, 0.0018420541322667456] | [t5_wrd1_20260918/pseudo1_bottom10_freeze_20260919/summary.json](t5-campaign-20260919/t5_wrd1_20260918/pseudo1_bottom10_freeze_20260919/summary.json) |

样本外底部收益增量为 **0.0003991343295229213**，与头部增量共同解释冻结价差为何转负；替换底部后点估计翻为非负，但 CI 仍跨零，正式判决仅为**部分支持**，`WINRATIO_GAP_MODEL_NO_TRANSFER` 不变。（来源：[t5_wrd1_20260918/pseudo1_bottom10_freeze_20260919/summary.json](t5-campaign-20260919/t5_wrd1_20260918/pseudo1_bottom10_freeze_20260919/summary.json) 的 `windows.2026_oos.d_bot_mean.mean`、`decision`。）

### 残差直接叠回：均判“削弱”

伪实验绕过 LGB，将当日特征对冻结 score 的 OLS 残差标准化后，直接叠回标准化 score。主档 **λ=0.5**；主头部指标均为等权 Top10 减共同宇宙等权，WRD1 不用 Top−Bottom 改写此处主判决。（来源：[t5_mxr1_20260918/pseudo2_residual_blend_20260919/REPORT.md](t5-campaign-20260919/t5_mxr1_20260918/pseudo2_residual_blend_20260919/REPORT.md)、[t5_wrd1_20260918/pseudo2_residual_blend_20260919/REPORT.md](t5-campaign-20260919/t5_wrd1_20260918/pseudo2_residual_blend_20260919/REPORT.md)。）

| 刀 | 2026 mean ΔRankIC | 2026 ΔRankIC CI 下界 | 2025 mean ΔTop10Spread | 正式判决 | 来源（本行全部数字与判决） |
|---|---:|---:|---:|---|---|
| MAXRET | 0.014050230142645477 | -0.0035159157527491942 | -0.0005372940310378816 | 削弱 | [t5_mxr1_20260918/pseudo2_residual_blend_20260919/summary.json](t5-campaign-20260919/t5_mxr1_20260918/pseudo2_residual_blend_20260919/summary.json) 的 `decision` |
| WRD1 | 0.004059557472964878 | -0.004245852320417678 | -0.00021501339910444154 | 削弱 | [t5_wrd1_20260918/pseudo2_residual_blend_20260919/summary.json](t5-campaign-20260919/t5_wrd1_20260918/pseudo2_residual_blend_20260919/summary.json) 的 `decision` |

直接叠回虽抬高样本外排序增量的点估计，仍未满足排序 CI 与验证窗头部表现的联合条件。这削弱了“只因 LGB 吸收信息，绕过树便可稳定迁移”的解释；敏感性档位不能替换主档结论。全部伪实验均未重训、未跑 PortAna / BT，也不能推翻各自原始 B 门终态。（来源：上表 summary 的 `decision`、`cannot_overturn`、`no_retrain`、`no_portana`，及前述头尾部伪实验 REPORT。）

## 共同模式：A 有效，B 不迁移

“A 有效”只适用于 MAXRET 与 WRD1，不能扩展到本轮所有特征。其余刀已经在覆盖、跨窗方向或条件信息不确定性上停止。（来源：[FACTS.json](t5-campaign-20260919/FACTS.json) 与逐刀结果表。）

A 门回答特征在控制既有 score 等条件后是否仍有残差信息；B 门回答加入 LGB 后，整体排序和冻结头部指标能否跨窗稳定改善。通过前者不等于通过后者。B-diag 表明模型使用了特征，伪实验又表明直接叠回仍有排序与头部表现之间的冲突，因此不能把失败简化成“模型漏用了特征”。（来源：[t5_mxr1_20260918/b_diag_20260919/REPORT.md](t5-campaign-20260919/t5_mxr1_20260918/b_diag_20260919/REPORT.md)、[t5_wrd1_20260918/b_diag_20260919/REPORT.md](t5-campaign-20260919/t5_wrd1_20260918/b_diag_20260919/REPORT.md) 及残差叠回结果表。）

头部约束的机制支持与底部冻结的部分支持，都属于诊断证据；尚无通过 C 门的组合或成交证据，不能升级为上线资格或已实现收益。（来源：各刀 verdict 与伪实验 REPORT；本文据此作出的证据边界判断。）

## 下一步：组合约束与分钟成交优先

**研究顺序建议，非事实包已验证收益结论。**

**停止继续堆叠特征刀，先别再开新刀。**MAXRET 与 WRD1 在 A 门有条件信息，进入 LGB 后却未稳定通过 B 门；据此判断，再加一列很难抬高净收益，应把研究重心转到业内的主战场：组合、风险、成本与成交。这里的净收益判断用于安排研究资源，事实包尚无组合或成交层的收益验证。（依据：[MAXRET verdict](t5-campaign-20260919/t5_mxr1_20260918/t5_mxr1_verdict.md)、[WRD1 verdict](t5-campaign-20260919/t5_wrd1_20260918/t5_wrd1_verdict.md)。）

本轮可定性为**「信息有、组合没」**：仅指上述两刀有条件信息，却没有已验证的组合改善；**MAXRET 伤头、WRD1 伤底**，前者是验证窗头部换入偏向近期大涨股，后者是样本外底部收益上升拖累冻结 Top−Bottom，不能误读为 WRD1 头部同样受损。下一步让以下三条线并行，而非无限挖刀。（机制来源：[MAXRET B-diag](t5-campaign-20260919/t5_mxr1_20260918/b_diag_20260919/REPORT.md)、[WRD1 B-diag](t5-campaign-20260919/t5_wrd1_20260918/b_diag_20260919/REPORT.md)。）

- **组合与约束（最优先）。**以现有线上 pred `8a061ea4` 为只读输入，只在研究组合层对照行业/市值中性、换手上限、禁止追近端大涨与控制尾部暴露；预注册约束规则、对照、冻结指标及停止条件。MAXRET 伪1为「禁止追近端大涨」提供头部机制支持，但 CI 跨零，仍是待验证线索；WRD1 应保持头部、底部与宇宙基准的口径分离，不照搬 anti-rank 过滤。（依据：[MAXRET 头部约束伪1](t5-campaign-20260919/t5_mxr1_20260918/pseudo1_top10_constrain_20260919/REPORT.md)、[WRD1 底部冻结伪1](t5-campaign-20260919/t5_wrd1_20260918/pseudo1_bottom10_freeze_20260919/REPORT.md)。）
- **成本与成交：Mode B / MyQuant-backtrader。**在独立的分钟成交研究方案中，固定同一信号，对照不同成交假设：市场冲击与滑点、涨跌停、能否成交及未成交处理、成交价格、止损触发与执行路径，并评估交易成本和换手影响。事实包没有这部分结果，本文不填写成交率、滑点或净超额数字；此处是后续研究安排。
- **信号怎么用。**residual 直接叠回的解释已被伪实验判为「削弱」，因此主模型不动，不再为弱信息另开一门 LGB；改为预注册过滤、降权或否决规则，例如在头部使用 anti-rank 约束，再检查组合与成交后的效果。这是待验证用法，不改变原始 B 门终态。（依据：[MAXRET 残差叠回判决](t5-campaign-20260919/t5_mxr1_20260918/pseudo2_residual_blend_20260919/summary.json)、[WRD1 残差叠回判决](t5-campaign-20260919/t5_wrd1_20260918/pseudo2_residual_blend_20260919/summary.json)。）

**不建议：**再扫特征刀、加列或交互；为过 B 扫 seed、窗口或方向；动线上 pred `8a061ea4` / 10/3；没过组合层就把 PortAna 当成真钱收益。保留现有终态，不用伪实验或事后更换指标复活失败候选；研究提案与线上冻结分开管理。

**若只选一步：**冻结特征研发约一周，以 `8a061ea4` 为只读输入，开「组合约束+分钟成交」对照，预注册对照规则与验收口径；验收看**换手、回撤、净超额，不是 RankIC**。这一步检验现有信号经组合与成交处理后的效果，不承诺收益提升。

上述优先级来自头尾部诊断与残差叠回结果的综合判断；原报告的停止边界见 [t5_mxr1_20260918/t5_mxr1_verdict.md](t5-campaign-20260919/t5_mxr1_20260918/t5_mxr1_verdict.md)、[t5_wrd1_20260918/t5_wrd1_verdict.md](t5-campaign-20260919/t5_wrd1_20260918/t5_wrd1_verdict.md)、[t5_dstr1_20260918/t5_dstr1_verdict.md](t5-campaign-20260919/t5_dstr1_20260918/t5_dstr1_verdict.md)。

## 附录：事实包与关键来源

| 用途 | 相对本文的入口 |
|---|---|
| 事实包根目录 | [t5-campaign-20260919/](t5-campaign-20260919/) |
| 汇总事实与线上冻结 | [t5-campaign-20260919/FACTS.json](t5-campaign-20260919/FACTS.json) |
| 来源映射与收录边界 | [t5-campaign-20260919/SOURCE_INDEX.md](t5-campaign-20260919/SOURCE_INDEX.md)、[t5-campaign-20260919/README.md](t5-campaign-20260919/README.md) |
| 全部刀的正式终态 | 逐刀结果表所链接的 `t5_*_verdict.md`；对应目录的 `information/verdict.json` |
| CYQ 条件信息判决 | [t5-campaign-20260919/t5_cyq1_20260917/information/verdict.json](t5-campaign-20260919/t5_cyq1_20260917/information/verdict.json) |
| MAXRET 冻结 B 门 | [t5-campaign-20260919/t5_mxr1_20260918/pred_pair/verdict.json](t5-campaign-20260919/t5_mxr1_20260918/pred_pair/verdict.json) |
| WRD1 冻结 B 门 | [t5-campaign-20260919/t5_wrd1_20260918/pred_pair/verdict.json](t5-campaign-20260919/t5_wrd1_20260918/pred_pair/verdict.json) |
| B-diag 与全部伪实验 | 正文逐项链接的 `b_diag_20260919/REPORT.md`、`b_diag_20260919/summary.json` 及各 `pseudo*/REPORT.md`、`pseudo*/summary.json` |

早期 B-diag 或头尾部伪实验文件中的“未开伪实验”描述仅代表该文件写作阶段；事实包已收录后续残差叠回的独立报告与判决，本文据这些后续文件汇总最终状态。（来源：[FACTS.json](t5-campaign-20260919/FACTS.json) 的 `followups` 及正文对应伪实验路径。）
