# T5-H52A1 Verdict

- **最终标签**: `H52_DATA_INVALID`
- **停在**: A 门数据覆盖（跨窗条件信息门）；**未跑 B 重训 / C PortAna / BT**
- **线上**: 未改 pred `8a061ea4`，未改 10/3

## 冻结输入

| 项 | 值 |
|---|---|
| 刀法 tip | `6d6593f`（PR #83 docs；full `6d6593f393cf4e62ee38f33db121a3ca5c3eabbf`） |
| 实现 worktree | `D:\PycharmProjects\wt-myquant-pr83-t5-h52a1` @ `feat/t5-h52a1-impl` on tip `6d6593f` + 本刀脚本 |
| sidecar | `exports\analysis\t5_h52a1_20260918\sidecar\HIGH252_PROX_RANK.parquet` |
| sidecar SHA-256 | `215c78b34c936457354f926ab46958666d874946ef9b13258d0ae745898a8acb` |
| key digest | `e2b051e973df6c23f74d06cd0d9791c91253197fe05adaaf5de2531945c6432c` |
| provider | `C:\Users\wangc\.qlib\qlib_data\my_data` |
| calendar SHA-256 | `9e07c43e1fcb0f8031c150712f9675dadb5392dfa4b40ed1cdc162075399cdc6`（`2020-01-02`～`2026-09-15`，1626 日） |
| 控制 recorder | `8a061ea428e04bb3a199a485ade49d0e`（只读；未回写） |
| 标签 | `Ref($close,-2)/Ref($close,-1)-1`（未改） |
| 唯一特征 | `HIGH252_PROX_RANK`：冻结 `$close`，`high_close_252=max(close[d], d=t-251..t)` 共 252 个市场交易日（含 `t`），全部有限且 `>0`；`high252_prox=close[t]/high_close_252`（合法 `0<prox<=1`，越界不截断）；再对 **high252_prox 本身** 在冻结 handler 当日 ∩ 有效 prox 上 `rank(method="average", pct=True)`。**不乘 −1**。最高收盘价并列只为审计保留最早日期，不参与特征值或破 tie。未用 `$high`、未取最大单日收益、未把 252 改成 250 / 可变窗 / 上市以来高点。 |

## 数据门（不过 → 终态）

- sidecar 7,699,616 行 / 5,587 票 / 1,625 日；有限秩 5,906,671。
- 抽样 16 行独立复算 `high252_prox` / `high_close_252` / 最高日 通过；3 日截面秩 `rank(high252_prox)` 复算 `max_abs_diff=0`；时点检查通过；A 未在子样本上重 rank。
- 未插值、未 ffill、未扩窗、未 `min_periods`。冻结日历从 2020-01-02 起，2020 起始日无更早热身日（`lookback_available=0`，禁止发明更早交易日）；只允许恰好 251 个前置市场日，本快照没有这些日。
- 全 sidecar 缺失：`not_enough_history` 914,100；`incomplete_window` 878,845。
- **2025 覆盖 91.02%**（1,169,512 / 1,284,876）；**2026 覆盖 88.30%**（810,769 / 918,193）；均 **`< 98%`**。
- 2025/2026 缺失分解：close 非法行 0/0；不完整 252 日窗 114,615 / 102,055（全部 `incomplete_window`）。分母是冻结 handler 当日有限 score 行。

覆盖不足即停止。未放宽完整窗、未改成可变窗 / `min_periods` / 「上市以来高点」、未换 `$high` 或 250 日。

## A 信息量（覆盖不过，不用于改标签）

H52 partial RankIC（控制冻结 score 截面秩；残差 Pearson；n>=4；残差化只用于 A）在覆盖失败样本上的数字，**不授权翻方向或进 B**：

| 窗 | mean | median | ICIR | 有效日 | 共同股票数中位数 | 95% CI |
|---|---:|---:|---:|---:|---:|---|
| 2025 valid | −0.024097 | −0.023345 | −0.1825 | 242 | 4829 | [−0.039560, −0.007026] |
| 2026 OOS | +0.000370 | +0.001529 | +0.0024 | 169 | 4800 | [−0.025080, +0.024624] |

2026 自然季度 mean H52 partial RankIC（保留不完整 Q3 至 9-14）：

| 季度 | mean | 日数 |
|---|---:|---:|
| 2026Q1 | +0.008228 | 56 |
| 2026Q2 | +0.036284 | 60 |
| 2026Q3 | −0.048588 | 53 |

- 数据门不过（S0=false）。按 §4 优先级 1 打 **`H52_DATA_INVALID`**，不再进入 `H52_CONDITIONAL_FLIP` / `H52_CONDITIONAL_NO_EDGE`。
- B/C 取消。禁止改窗口、完整性、价格字段、方向或变换。

## 未做

- 未跑 `train_sidecar_feature_arm` / `diag_pred_pair` / `portana_pred_pair` / BT，未改 10/3。
- 未改线上 pred `8a061ea4`，未碰 `55c5bf77`。
- 未扫 lookback / 250 vs 252 / 方向 / `$high` / MAXRET / 阈值 / seed / 宽度 / `n_drop` / 新树。
- sidecar 只导出一次；A 只切片。未在 A 过后再导（避免二次 `H52_DATA_INVALID`）。

## 产物路径

- sidecar: `D:\PycharmProjects\wt-myquant-pr83-t5-h52a1\exports\analysis\t5_h52a1_20260918\sidecar\`
- A: `D:\PycharmProjects\wt-myquant-pr83-t5-h52a1\exports\analysis\t5_h52a1_20260918\information\`
- 2026 基线 pred 只读副本: `D:\PycharmProjects\wt-myquant-pr83-t5-h52a1\exports\analysis\t5_h52a1_20260918\control_pred_2026.csv`
- 本文件: `D:\PycharmProjects\wt-myquant-pr83-t5-h52a1\exports\analysis\t5_h52a1_20260918\t5_h52a1_verdict.md`
