# T5-DSTR1 verdict

**唯一终态标签：`DSTR_CONDITIONAL_NO_EDGE`（优先级 3）**

A 数据门通过；两窗 mean DSTR partial RankIC 均为负且 2026 CI 下界 ≤ 0。未命中反号/多数季度为负，因此不是 `DSTR_CONDITIONAL_FLIP`。按 §4 停止，**未进入 B/C**。未改上限、收益符号、变换、阈值，未翻成追跌势或上涨 streak，未缩成 3 日。

线上仍为 **10/3 LGB**；默认 pred 仍为 **`8a061ea4`**（recorder `8a061ea428e04bb3a199a485ade49d0e`）。全程只读，未回写 recorder，未碰 `55c5bf77`。

## Freeze / provenance

| 项 | 值 |
|---|---|
| 文档 tip commit | `9df060fbf02e634139401137047835c501601727`（PR #87） |
| 实现分支 | `feat/t5-dstr1-impl` |
| 实验 | `alpha158_cost_kdj_lgb` |
| 对照 recorder | `8a061ea428e04bb3a199a485ade49d0e`（只读） |
| handler pickle | `D:\qlib_handler_cache\handler_86d82e09280b20b8.pkl`（只读） |
| provider | `C:\Users\wangc\.qlib\qlib_data\my_data` |
| calendar SHA-256 | `9e07c43e1fcb0f8031c150712f9675dadb5392dfa4b40ed1cdc162075399cdc6`（2020-01-02～2026-09-15，1626 个市场日） |
| 标签 | `Ref($close,-2)/Ref($close,-1)-1` |
| 唯一特征 | `DOWNSTREAK5_RANK`（对 **downstreak5 本身** `rank(method="average", pct=True)`，不乘 −1） |
| 方向（预注册，未现场翻转） | `DOWNSTREAK5_RANK` 越高 → 下一持有期反转收益越高 |

## Sidecar（只建一次）

| 项 | 值 |
|---|---|
| 路径 | `exports/analysis/t5_dstr1_20260918/sidecar/DOWNSTREAK5_RANK.parquet` |
| SHA-256 | `1a116595502b897bc1eddeead5d2b3c6d0ec3f390511c3b02427526aae75a706` |
| key digest | `e2b051e973df6c23f74d06cd0d9791c91253197fe05adaaf5de2531945c6432c` |
| 行数 / 有限秩 | 7,699,616 / 7,662,438 |
| 热身 | 为 2020-01-02 请求恰好 5 个前置市场日；冻结日历无更早日期，`lookback_available=0`，`raw_start=2020-01-02`（未扩窗、未读 t+1） |
| 公式 QC | 16 行抽样复算通过；3 日截面秩 `max_abs_diff=0`；`neg_bitmap` 前缀与 `downstreak5` 一致；交错阴阳行 streak ≠ 下跌天数（非 CNTN5）；`r[t]>=0` 时 streak=0（空积未当成 1） |
| downstreak5 分布（有限行） | 0: 3,821,401；1: 1,967,345；2: 964,736；3: 481,710；4: 229,321；5: 197,925 |
| 缺失 | `close_invalid\|incomplete_window` 19,762；`not_enough_history` 17,416（2020 日历开头） |

A 只切片该 sidecar；B/C 未跑，因此没有第二次导出。

2026 基线 pred 只读导出到 `exports/analysis/t5_dstr1_20260918/control_pred_2026.csv`（n=918,193），未回写 recorder。

## A 门

共同样本覆盖率分母 = 冻结 handler 当日 score 有限行。Bootstrap：5 日 moving-block，10,000 次，seed `20260918`。残差化只用于 A；未在 A 子样本上重 rank。

| 窗 | 覆盖率 | 分子/分母 | mean partial RankIC | median | ICIR | 有效日 | 中位共同股票数 | 2026 95% CI |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| 2025-01-03～2025-12-31 | 99.70% | 1,281,046 / 1,284,876 | −0.002029 | +0.002256 | −0.020641 | 242 | 5314 | CI [−0.013080, +0.008482]（非门控） |
| 2026-01-01～2026-09-14 | 99.08% | 909,715 / 918,193 | −0.005503 | −0.005274 | −0.047633 | 169 | 5388 | **[−0.020253, +0.008338]**，下界 ≤ 0 |

2025 缺失 2,832 行、2026 缺失 2,252 行，原因均为 `close_invalid|incomplete_window`（非法 close / 6-close 窗不完整）。无退化日。

### 2026 自然季度（含不完整 Q3 至 9-14）

| 季度 | n_days | mean partial RankIC |
|---|---:|---:|
| 2026Q1 | 56 | +0.004779 |
| 2026Q2 | 60 | +0.006218 |
| 2026Q3 | 53 | −0.029635 |

- `majority_negative = false`（1/3 季度为负，未 >50%）
- `single_quarter_driven = false`（全窗增量 < 0，不满足“全窗 >0 且正季度 ≤1”）
- 两窗 mean **同号且均为负**，不是反号，故不是 `DSTR_CONDITIONAL_FLIP`

### A 门布尔

- 数据 / 覆盖 / 公式 / hash / 行键：通过（S0=true）
- 两窗 mean > 0：失败
- 2026 CI 下界 > 0：失败
- 2026 季度门：通过
- **S1_pass = false → 停**

## B 门

未跑。没有新 recorder、没有候选 pred、没有 RankIC/Top10Spread 对比。

## C 门

未跑。没有 PortAna / BT。线上 10/3 未改。

## 停止动作

T5-DSTR1 收工。禁止滑成 streak-side × cap × transform × seed × model 网格，也不得回到 H52 / DSEM / BETA / MAXRET / Amihud / CYQ / winratio / horizon / score-exit。
