# 复核：`docs/reviews/2026-09-19-t5-campaign-summary.md`

## 1. 总体判定

**`PASS_WITH_NITS`**

主文全部关键数字、标签、路径与冻结声明均可在事实包 `docs/reviews/t5-campaign-20260919/` 内逐项对上，未发现无来源数字、未发现四舍五入改写、未发现把伪实验或诊断口径当成正式判决。没有阻断问题。下列 4 条为非阻断 nit，其中 N1 建议修，其余为体例或事实包自身问题，不影响结论。

## 2. 复核者身份

- 我是 **cursor-agent**（CLI 版本 `2026.09.18-9a7762b`），本次选用模型为 **Claude Opus 5（thinking）**。
- 环境未暴露精确的 model-id 字符串（`env` 中无 model 变量），因此以上为所选模型名而非 API slug。
- 本次复核只读取事实包与主文，未重新计算任何实验统计量，未修改主文、事实包、非文档代码、线上 pred、10/3 或 MyQuant-backtrader。新增文件仅本文件。

## 3. 复核范围

| 项 | 内容 |
|---|---|
| worktree / 分支 | `/workspace/wt-myquant-t5-campaign-summary` @ `docs/t5-campaign-20260919` |
| 本地 HEAD | `2d33d68`（`docs: add Chinese T5 campaign summary from facts pack`，仅新增主文 118 行） |
| HEAD~1 | `ecde0f7`（`Add T5-CYQ1 lightweight facts to campaign bundle.`） |
| 被查文件 | `docs/reviews/2026-09-19-t5-campaign-summary.md` |
| 事实来源 | `docs/reviews/t5-campaign-20260919/` 下 52 个文件（`FACTS.json`、`SOURCE_INDEX.md`、`README.md`、`_bundle_meta.json` + 8 把刀目录） |
| 读过的来源 | 8 份 `t5_*_verdict.md`、`FACTS.json` 内全部 `verdicts`、MXR1/WRD1 各自 `pred_pair/verdict.json`、`b_diag_20260919/{REPORT.md,summary.json}`、`pseudo1_*/{REPORT.md,summary.json}`、`pseudo2_residual_blend_20260919/{REPORT.md,summary.json}` |
| 链接检查 | 主文 27 条唯一 markdown 链接全部解析到存在的文件（相对主文所在目录） |

## 4. 数字 / 标签 / 路径审计

约定：**来源**列为事实包根目录下的相对路径；**匹配**列 Y 表示与来源逐位一致（或与来源已有展示精度一致）。

### 4.1 冻结与范围

| 主文声明 | 来源 | 匹配 | 备注 |
|---|---|---|---|
| online pred `8a061ea4` / 10/3 全程未改 | `FACTS.json` → `online_pred="8a061ea4"`、`constraint="online pred and 10/3 untouched across campaign"` | Y | 8 份 verdict.md 亦各自写明「未改 pred `8a061ea4`，未改 10/3」 |
| 最终无 FEATURE_CANDIDATE | `FACTS.json` 全部 `verdicts` + 8 份 verdict.md | Y | 8 把刀终态无一为 FEATURE_CANDIDATE |
| 未进入 C / PortAna / BT | 各刀 verdict.md「未做」段 | Y | MXR1/WRD1 明示「未跑 C PortAna / BT」，其余明示「未跑 B 重训 / C PortAna / BT」 |
| 包内不含原始 parquet / 预测 CSV / mlruns | `README.md` → `Exclude: *.parquet, pred_*.csv, mlruns/` | Y | 磁盘核对：包内无 parquet / pred CSV |
| campaign tip SHA `ecde0f7`，分支 `docs/t5-campaign-20260919` | `git rev-parse HEAD~1` = `ecde0f76375676058bbd65dde1705d390915551b`；`git branch --show-current` | Y | 见 N1：SHA 正确，但「经本地 HEAD 核验」的措辞已过期 |
| 本次交付仅为本文，未改事实包 / 非文档代码 / 线上配置 | `git show --stat HEAD` 只含 `docs/reviews/2026-09-19-t5-campaign-summary.md` | Y | 工作区 `git status` 干净 |

### 4.2 逐刀结果表（A 门均值为 2025 valid / 2026 OOS，CI 为 2026 样本外 95% CI）

| 刀 | 主文数值与标签 | 来源 | 匹配 |
|---|---|---|---|
| AMI1 | `AMIHUD_CONDITIONAL_NO_EDGE`；+0.018829 / +0.015922；CI [-0.007202, +0.042791] | `t5_ami1_20260918/t5_ami1_verdict.md`（A 门表）；`FACTS.json` 原值 `0.018829194003947756` / `0.01592188154819158`，`ci_lower=-0.007202234111503954`、`ci_upper=0.04279090837809987` | Y |
| BETA1 | `BETA_CONDITIONAL_FLIP`；−0.003630 / +0.004667；CI [−0.029287, +0.042903] | `t5_beta1_20260918/t5_beta1_verdict.md`；`FACTS.json` `-0.0036300792515266225` / `0.004666792181534001`，CI `-0.029286564885777168` / `0.04290339310814517` | Y |
| CYQ1 | `CYQ_CONDITIONAL_NO_EDGE`；+0.032364 / +0.016444；CI [-0.005880, 0.037817] | `t5_cyq1_20260917/t5_cyq1_verdict.md`（表内即写 `[-0.005880, 0.037817]`）；`information/verdict.json` `0.03236437071515043` / `0.016444193098030725` | Y |
| DSTR1 | `DSTR_CONDITIONAL_NO_EDGE`；−0.002029 / −0.005503；CI [−0.020253, +0.008338] | `t5_dstr1_20260918/t5_dstr1_verdict.md`；`FACTS.json` `-0.002029412775406366` / `-0.00550280463831853`，CI `-0.02025279691183407` / `0.008338109436972848` | Y |
| DSV1 | `DSEM_CONDITIONAL_NO_EDGE`；+0.020675 / +0.030425；CI [−0.008751, +0.070781] | `t5_dsv1_20260918/t5_dsv1_verdict.md`；`FACTS.json` `0.020675282035367417` / `0.03042501448600329`，CI `-0.008750922930890623` / `0.07078142271601973` | Y |
| H52A1 | `H52_DATA_INVALID`；覆盖率 91.02% / 88.30%，低于 98% 门槛 | `t5_h52a1_20260918/t5_h52a1_verdict.md`：「2025 覆盖 91.02%（1,169,512 / 1,284,876）；2026 覆盖 88.30%（810,769 / 918,193）；均 `< 98%`」 | Y |
| MXR1 | `MAXRET_MODEL_NO_TRANSFER`；+0.044092 / +0.038542；CI [+0.004456, +0.073341] | `t5_mxr1_20260918/t5_mxr1_verdict.md`；`FACTS.json` `0.044092005053138` / `0.038541790010131145`，CI `0.004455550658482764` / `0.07334131619820311` | Y |
| WRD1 | `WINRATIO_GAP_MODEL_NO_TRANSFER`；+0.017519 / +0.017242；CI [+0.003146, +0.031243] | `t5_wrd1_20260918/t5_wrd1_verdict.md`；`FACTS.json` `0.017518829760563518` / `0.01724187938897852`，CI `0.0031464268748165676` / `0.031242693526731022` | Y |

停点定性同样可查：AMI1/BETA1/CYQ1/DSTR1/DSV1 均为「停 A、B/C 未跑」；H52A1 为「停 A 数据覆盖门」且 verdict.md 明写「覆盖不过，不用于改标签」，主文「信息量不用于改判」与之一致；MXR1「A 过、停 B，验证窗头部未胜 + 样本外 CI 跨零」对应 `pred_pair/verdict.json` 2025 `pass_top10=false`、2026 `pass_ci=false`；WRD1「样本外冻结 Top−Bottom 未胜 + CI 跨零」对应 2026 `pass_top10=false`、`pass_ci=false`。全部 Y。

主文「CYQ 的来源明确位于 `t5_cyq1_20260917/`，没有独立实现 worktree」对上 `FACTS.json` 的 `note_cyq`（"CYQ1 lived under main MyQuant exports/analysis (no separate wt-myquant-pr*-t5-cyq1 worktree on disk)."）与 `SOURCE_INDEX.md`（`worktree: D:\PycharmProjects\MyQuant` (main repo exports)）。Y。

### 4.3 冻结 B 门表

| 主文数值 | 来源字段 | 匹配 |
|---|---|---|
| MAXRET 2025 ΔRankIC `5.0768410642020034e-05`；ΔTop10 `-5.260264777101273e-05` | `t5_mxr1_20260918/pred_pair/verdict.json` → `windows[0].rankic_delta` / `top10_delta` | Y |
| MAXRET 2026 ΔRankIC `0.00046281734652085446`；ΔTop10 `0.0004921033324056564`；CI `[-0.0005562195993456413, 0.0014590946571083482]` | 同上 `windows[1].rankic_delta` / `top10_delta` / `delta_rankic_ci.lo,hi` | Y |
| WRD1 2025 ΔRankIC `0.00026165899706542817`；ΔTop−Bottom `0.0015516403008036875` | `t5_wrd1_20260918/pred_pair/verdict.json` → `windows[0]` | Y |
| WRD1 2026 ΔRankIC `0.0006696727179042773`；ΔTop−Bottom `-0.00034010738613822304`；CI `[-0.00064472672697206, 0.0021847408549700497]` | 同上 `windows[1]` | Y |
| MAXRET 冻结 Top10Spread = 等权 Top10 − 共同宇宙等权 | `pred_pair/verdict.json` `top10_spread_vs="common-universe-equal-weight"`；`b_diag_20260919/REPORT.md`「Top10Spread｜等权 Top10 − 共同宇宙等权；**禁止 Top-Bottom**」 | Y |
| WRD1 冻结 Top10Spread = Top−Bottom；头部减宇宙只作诊断 | `t5_wrd1_20260918/b_diag_20260919/REPORT.md`「冻结 B 门 Top10Spread｜**Top−Bottom**」「诊断 Top10Spread｜等权 Top10 − 共同宇宙等权；**禁止用诊断数字替换冻结门**」；`summary.json` `top10_spread_frozen_b_gate="top-minus-bottom"` | Y |
| 验证窗 CI 不参与否决（该列留空） | `t5_mxr1_20260918/t5_mxr1_verdict.md`「B 要求两窗同时…且 2026 CI 下界 `>0`」；`t5_wrd1_20260918/b_diag_20260919/REPORT.md` §4「2025 只要求 RankIC 与 Top10 同时高于对照；**季度/CI 只卡 2026**」 | Y |

### 4.4 B-diag 机制叙述

| 主文声明 | 来源 | 匹配 |
|---|---|---|
| MAXRET：LGB 用上了该列 | `t5_mxr1_20260918/b_diag_20260919/REPORT.md`「LGB **用上了** `MAXRET20_ANTI_RANK`」 | Y |
| MAXRET：验证窗换入票 anti-rank 更低、次日收益更差，头部偏向近期大涨股，报告据此列为失败机制 | 同上 §2–§3：2025 换入特征 0.130 < 换出 0.149；换入次日 label 0.00447 < 换出 0.00560（−11.3 bp）；两侧 Top10 落在特征左尾（≈0.19 vs 宇宙 0.50） | Y |
| WRD1：LGB 用上了该列，但候选头部没有明显偏向低 gap | `t5_wrd1_20260918/b_diag_20260919/REPORT.md`：换入 gap 分位 0.483 vs 换出 0.472；Top10 pct≈0.50（截面中位数） | Y |
| WRD1：样本外冻结价差恶化主要由底部收益上升解释；头部减宇宙点估计仍微正 | 同上 §3：Δ univ `+5.90e-5`，Δ Bottom10 `+3.99e-4`，恒等式 `+5.90e-5 − 3.99e-4 = −3.40e-4` 与冻结逐位闭合 | Y（另见 N3） |
| 主文未引用 B-diag 中的 gain 排名等数字 | — | Y（**恰当规避**，见 N3） |
| 「包内 B-diag summary.json 的部分重算汇总与 REPORT.md 明示的冻结口径对齐结果不同」，并声明 B 门数字用原始 verdict、机制用 REPORT、伪实验用各自 summary、不混用 | MXR1 `b_diag/summary.json` `recompute_vs_frozen`：2025 `d_top10_recomputed=2.83e-06` vs `d_top10_frozen=-5.26e-05`；WRD1 同字段 `d_top10_tb_recomputed=0.0014452336436605504` vs `frozen=0.0015516403008036875`（`abs_err≈1.06e-4`）。两份 REPORT.md 则称按冻结口径对齐后「逐位一致」 | Y — 这是主文对包内不一致的**如实披露**，处理方式正确 |

### 4.5 头尾部伪实验

| 主文数值 | 来源字段 | 匹配 |
|---|---|---|
| MAXRET 约束名单 2025 mean ΔTop10Spread `0.001105356788883118`，CI `[-0.000505627267395951, 0.0027925108272934636]` | `t5_mxr1_20260918/pseudo1_top10_constrain_20260919/summary.json` → `windows.2025_valid.d_top10` / `bootstrap.lo,hi` | Y |
| MAXRET 2026 `0.0003618171010832952`，CI `[-0.0021314959930410133, 0.0025806468553058056]` | 同上 `windows.2026_oos` | Y |
| 规则：从对照 score 名单出发，跳过 anti-rank 严格低于当日对照头部中位数的票，按预注册规则回填；候选分数只用于宇宙对齐，不参与约束名单排序 | `pseudo1_top10_constrain_20260919/REPORT.md` §0：「T0｜对照 score 降序…」「T1｜跳过 anti-rank **严格低于**当日 T0 中位数的票；凑不满则按 score 回填」「对照 / 候选（宇宙对齐，候选分数不参与 T1）」；`summary.json` `t1_rule` 同义 | Y |
| 「按预注册的验证窗均值符号门槛支持机制；CI 跨零，不称已证实；样本外只报告；`MAXRET_MODEL_NO_TRANSFER` 不变」 | 同上 REPORT §4：「预注册门槛只看均值符号，不另加显著性」「2026…不据此改 2025 结论」「终态标签仍是 `MAXRET_MODEL_NO_TRANSFER`」；`summary.json` `hypothesis_supported=true`、`cannot_overturn="MAXRET_MODEL_NO_TRANSFER"` | Y |
| WRD1 2025 mean ΔSpread_freeze `0.0008404026302215687`，CI `[-0.0003723261174108986, 0.002038561176656296]` | `t5_wrd1_20260918/pseudo1_bottom10_freeze_20260919/summary.json` → `windows.2025_valid.d_spread_freeze` | Y |
| WRD1 2026 `5.9027014336047265e-05`，CI `[-0.0016901782803940407, 0.0018420541322667456]` | 同上 `windows.2026_oos.d_spread_freeze` | Y |
| WRD1 样本外底部收益增量 `0.0003991343295229213` | 同上 `windows.2026_oos.d_bot_mean.mean` | Y（路径标注省略末级 `.mean`，见 N4） |
| 「冻结底部后的价差增量等于头部收益增量，也等于头部减共同宇宙等权的增量」 | 同上 `identity_freeze_eq_dtop_maxabs=0.0`、`identity_freeze_eq_univ_maxabs=0.0`，且 `d_spread_freeze = d_top10_univ = d_top_mean` 三者同值；REPORT §1 给出恒等式推导 | Y |
| 「正式判决仅为部分支持，`WINRATIO_GAP_MODEL_NO_TRANSFER` 不变」 | 同上 `decision.verdict="部分支持"`、`decision.cannot_overturn="WINRATIO_GAP_MODEL_NO_TRANSFER"` | Y |

### 4.6 残差直接叠回

| 主文数值 | 来源字段 | 匹配 |
|---|---|---|
| 主档 λ=0.5 | 两份 `pseudo2_residual_blend_20260919/summary.json` `primary_lambda=0.5`；REPORT「主档 λ｜`0.5`；敏感性 `[0.25, 0.5, 1.0]`」 | Y |
| 主头部指标为等权 Top10 − 共同宇宙等权，WRD1 不用 Top−Bottom 改写主判决 | 两份 summary `top10_spread_vs="common-universe-equal-weight"`；WRD1 REPORT「**禁止 Top−Bottom 作主指标**」，Top−Bottom 仅列于 §5 附录「不进判决」 | Y |
| MAXRET：2026 mean ΔRankIC `0.014050230142645477`；CI 下界 `-0.0035159157527491942`；2025 mean ΔTop10Spread `-0.0005372940310378816`；判决「削弱」 | `t5_mxr1_20260918/pseudo2_residual_blend_20260919/summary.json` → `decision.{d_rankic_2026,d_rankic_2026_ci_lo,d_top10_2025,verdict}` | Y |
| WRD1：`0.004059557472964878` / `-0.004245852320417678` / `-0.00021501339910444154`；判决「削弱」 | `t5_wrd1_20260918/pseudo2_residual_blend_20260919/summary.json` → 同名字段 | Y |
| 「抬高样本外排序增量的点估计，仍未满足排序 CI 与验证窗头部表现的联合条件」 | 两份 REPORT §3 支持门槛：λ=0.5 下 2026 mean(ΔRankIC)>0 **且 CI 下沿>0**，**同时** 2025 mean(ΔTop10Spread)≥0；两刀均在第二项失败 | Y |
| 「全部伪实验均未重训、未跑 PortAna / BT，也不能推翻原始 B 门终态」 | 4 份 summary：`no_retrain` / `no_portana` 均为真；`cannot_overturn` 分别为 `MAXRET_MODEL_NO_TRANSFER` / `WINRATIO_GAP_MODEL_NO_TRANSFER` | Y |

### 4.7 路径与附录

- 主文 27 条唯一链接全部命中磁盘文件；表内「来源」标签写作事实包根相对路径，链接 href 写作主文目录相对路径，主文已在表前显式说明这两套口径的差别 —— 与**复核规则 5**（关键数字需带相对来源标注）一致，逐行「来源」列覆盖该行全部数字与判决。
- 附录 8 个入口（事实包根、`FACTS.json`、`SOURCE_INDEX.md` + `README.md`、各刀 `t5_*_verdict.md` 与 `information/verdict.json`、CYQ `information/verdict.json`、MXR1/WRD1 `pred_pair/verdict.json`、B-diag 与伪实验）全部存在。8 把刀的 `information/verdict.json` 均在包内。
- 末段「早期文件中的『未开伪实验』只代表该文件写作阶段」可查：WRD1 `b_diag/summary.json` `no_pseudo_run=true`、两份 pseudo1 summary `no_pseudo2` 为真，而 pseudo2 报告与判决确已收录，`FACTS.json` 的 `followups` 亦列出 `pseudo2_residual_blend_20260919`。Y。

## 5. 结构清单（复核规则 3）

| 要求结构 | 主文位置 | 状态 |
|---|---|---|
| 一句话结论 | 首行加粗段 | 有 |
| 范围与冻结 | 「范围与冻结」节 | 有 |
| 逐刀表 | 「逐刀结果」节，8 行覆盖包内 8 把刀 | 有 |
| MAXRET / WRD1 的 B-diag + 伪实验 | 「MAXRET / WRD1：B-diag 与伪实验」节（冻结 B 门表 / B-diag 机制 / 头尾部伪实验 / 残差叠回） | 有 |
| 共同模式（A 有效，B 不迁移） | 「共同模式：A 有效，B 不迁移」节 | 有 |
| 下一步：组合约束 + 分钟成交；不再叠特征刀 | 「下一步」节三条 bullet，逐条齐备 | 有 |
| 附录路径 | 「附录：事实包与关键来源」表 | 有 |

**复核规则 4（冻结声明）**：主文「范围与冻结」首条即写「线上冻结：online pred `8a061ea4` / 10/3 全程未改」，次条写「最终无 FEATURE_CANDIDATE」，两项齐备且带来源。**通过**。

另外加分项（非必需但值得记录）：主文对「下一步」明确标注「是研究顺序建议，不是事实包已经验证的收益结论」，并写明事实包无成交率 / 滑点 / 收益提升数字、本文不填 —— 这正是本次复核最容易出问题的地方，主文主动设了边界。

## 6. Nit（非阻断）

**N1（建议修）— 「经本地 HEAD 核验」措辞已过期。**
主文写：「本次汇总使用的 campaign tip SHA：`ecde0f7` …这是任务指定并经本地 HEAD 核验的写作基点」。SHA 本身正确：`ecde0f7` 是事实包完整就位的最后一个 commit。但主文自身已在 `2d33d68` 提交，`ecde0f7` 现在是 `HEAD~1`；今天照字面去核 `git rev-parse HEAD` 的读者会拿到 `2d33d68`。建议改为「事实包 tip（本文提交前的 HEAD，现为 `HEAD~1`）」之类的表述。不影响任何数字。

**N2（体例）— 逐刀表 CI 的负号与正号写法不统一。**
AMI1 与 CYQ1 用 ASCII 连字符 `-`，BETA1 / DSTR1 / DSV1 用 Unicode 减号 `−`；CYQ1 上界 `0.037817` 未加 `+` 而其余行加了。两处都忠实于各自来源（CYQ1 verdict.md 原文即 `[-0.005880, 0.037817]`），属显示体例而非事实偏差，可不改。

**N3（事实包自身问题，主文已规避）— 包内 WRD1 诊断汇总与报告口径冲突。**
`t5_wrd1_20260918/b_diag_20260919/summary.json` 的 `windows.2026_oos.d_top10_univ = -8.998395008525463e-05`（负），而同目录 `REPORT.md` 与 `pseudo1_bottom10_freeze_20260919/summary.json` 给出 `+5.903e-05`（正）。主文「头部减宇宙的点估计仍微正」取自 REPORT，与 pseudo1 summary 一致，且主文在「来源差异处理」段已显式声明不混用这些字段、不声称包内诊断汇总全部一致 —— 处理正确。同类情况还有：MXR1 `b_diag/summary.json` 的 `feature_importance` 把 `Column_183` 列在 gain 第 4（559 / 36368 ≈ 1.54%），而其 `REPORT.md` §3 写「gain 占比 1.47%，第 9 / 184」；主文只说「报告确认 LGB 使用了该列」而不引排名或占比，正好避开了这处冲突。**建议后续修事实包，而非改主文。**

**N4（吹毛求疵）— 一处字段路径少一级。**
主文标注 WRD1 底部增量来源为 `windows.2026_oos.d_bot_mean`，实际值在 `windows.2026_oos.d_bot_mean.mean`。数值 `0.0003991343295229213` 无误。

**附带记录（与主文无关）**：`_bundle_meta.json` 的 `copied` 列出 48 个文件，其中 6 个 `daily_metrics.csv` 实际不在包内（磁盘与 git 均无）。主文从未引用这些 CSV，因此不影响任何声明，但事实包的自述与内容对不上，建议一并修。

## 7. 阻断问题

**无。**

具体地：未发现任何「事实包里查不到的数字」；未发现把诊断口径（univ-EW）当成 WRD1 冻结 B 门、或把冻结 TB 当成伪实验主判决的串口径；未发现用伪实验推翻终态标签；未发现擅自换算收益单位或改写精度；未发现下一步建议被写成已验证收益。

## 8. 结论

主文可以按现状交付。它做对的三件最关键的事：**一是**所有 B 门数字取自冻结 `pred_pair/verdict.json` 而非诊断重算，**二是**全程把 MAXRET 的 univ-EW 与 WRD1 的 Top−Bottom 两套口径分开陈述并声明绝对水平不可比，**三是**把包内 `summary.json` 与 `REPORT.md` 的不一致如实写进正文而不是悄悄选一边。四条 nit 中只有 N1 涉及主文措辞且属一行改动，N3 / 附带记录应回到事实包去修。

最终判定：**`PASS_WITH_NITS`**。

## Nits follow-up

- **N1 已关闭（作者自检）**：主文明确定义事实包 tip 为 `ecde0f7`，并与本文初次提交 `2d33d68` 区分，移除「经本地 HEAD 核验」的时效性措辞。
- **N4 已修正（作者自检）**：来源字段路径补全为 `windows.2026_oos.d_bot_mean.mean`，原数值保持不变。
- **核对方式**：通过 `git show` 核对上述固定提交及其父子关系；只读解析 WRD1 底部冻结伪实验的 `summary.json`，确认补全路径对应正文原值；检查 diff，确认仅修改主文上述两处并追加本节，未改实验数字、事实包（含 N3 相关 `summary.json`）、非 docs 文件、线上 pred 或 10/3。

## Grok nits verification

- **Verifier**: `cursor-agent` model `cursor-grok-4.6-xhigh`, ask/read-only (`--mode ask`).
- **Against tip**: nits commit `7a94b89`; facts-pack tip `ecde0f7`; summary first commit `2d33d68`.
- **VERDICT: PASS**
- **N1: CLOSED** — 主文已去掉「经本地 HEAD 核验」，并区分事实包 tip `ecde0f7` 与初次提交 `2d33d68`。
- **N4: CLOSED** — 来源路径已补全为 `windows.2026_oos.d_bot_mean.mean`，数值未改。
- **ONLINE_UNTOUCHED: YES** — online pred `8a061ea4` / 10/3 未动；未见 N3/`summary.json` 被改。

## 下一步补强 follow-up

**作者自检（非新增独立复核）：**主文「下一步」节首已标明「研究顺序建议，非事实包已验证收益结论」，覆盖要点 1–7：

1. 停止堆叠特征刀；说明两刀 A 有条件信息、进 LGB 未稳定迁移，再加一列难抬净收益，研究重心转向组合/风险/成本/成交。
2. 定性「信息有、组合没」及 MAXRET 伤头、WRD1 伤底，保留头底口径差异，安排三条线并行。
3. 组合约束最优先：只读输入 `8a061ea4`，覆盖行业/市值中性、换手上限、禁止追近端大涨（MAXRET 伪1机制支持）与尾部暴露控制。
4. 成本成交明确挂名 Mode B / MyQuant-backtrader，同信号对照冲击、涨跌停、能否成交和止损路径等成交假设。
5. residual 直接叠回已被削弱，主模型不动；弱信息用于过滤/降权/否决（如头部 anti-rank），不另开 LGB。
6. 明确不建议再扫刀、为过 B 扫 seed/窗、动线上 pred / 10/3，或没过组合层就把 PortAna 当真钱。
7. 单步建议为冻结特征研发约一周，输入 `8a061ea4` 开「组合约束+分钟成交」只读对照，以换手/回撤/净超额验收，不以 RankIC 验收。

核对范围：仅重写主文目标节并在本 REVIEW 末尾追加本节；保留原停止边界来源链接，未添加事实包没有的成交率、滑点或净超额数字，主文其余内容及 N1/N4 修正保持不变，未改事实包、已有实验数字、非 docs 文件或线上 pred / 10/3。
