# T5-DSV1 Verdict

- **最终标签**: `DSEM_CONDITIONAL_NO_EDGE`
- **停在**: A 门（跨窗条件信息门）；**未跑 B 重训 / C PortAna / BT**
- **线上**: 未改 pred `8a061ea4`，未改 10/3

## 冻结输入

| 项 | 值 |
|---|---|
| 刀法 tip | `2e64556`（PR #82 docs；full `2e64556a22a623b13826d4664f88b6ea35f715cb`） |
| 实现 worktree | `D:\PycharmProjects\wt-myquant-pr82-t5-dsv1` @ `feat/t5-dsv1-impl` on tip `2e64556` + 本刀脚本 |
| sidecar | `exports\analysis\t5_dsv1_20260918\sidecar\DSEM20_ANTI_RANK.parquet` |
| sidecar SHA-256 | `dc9fe981bba49c3e61910bd155bb3d674d56919a902b13244e351b06e26498d1` |
| key digest | `e2b051e973df6c23f74d06cd0d9791c91253197fe05adaaf5de2531945c6432c` |
| provider | `C:\Users\wangc\.qlib\qlib_data\my_data` |
| calendar SHA-256 | `9e07c43e1fcb0f8031c150712f9675dadb5392dfa4b40ed1cdc162075399cdc6`（`2020-01-02`～`2026-09-15`，1626 日） |
| 控制 recorder | `8a061ea428e04bb3a199a485ade49d0e`（只读；未回写） |
| 标签 | `Ref($close,-2)/Ref($close,-1)-1`（未改） |
| 唯一特征 | `DSEM20_ANTI_RANK`：冻结 `$close` close-to-close 简单收益 `r=close/close_prev-1`，`down=min(r,0)`，固定 20 个市场日 `t-19..t`（21 个 close 全部有限且 `>0`），`dsem20=sqrt(mean(down^2))` 分母固定 20（正收益日 down=0 并进均方；全窗无负收益时 `dsem20=0` 为有效值）。再对 **`-dsem20`** 在冻结 handler 当日 ∩ 有效 dsem20 上 `rank(method="average", pct=True)`；**先算 dsem20 再乘 -1**。未用 19 作分母、未按负收益日平均、未 `1-rank(x)`、未在 A 子样本重 rank。 |

## 数据门（过）

- sidecar 7,699,616 行 / 5,587 票 / 1,625 日；有限秩 7,546,804。`dsem20=0` 保留为有效值 25 行（未改成缺失）。
- 抽样 16 行独立复算 `dsem20` 通过；3 日截面秩 `rank(-dsem20)` 复算 `max_abs_diff=0`；时点检查通过；A 未在子样本上重 rank。
- 未插值、未 ffill、未用 0 补原始收益、未向 `t-20` 之前扩窗。冻结日历从 2020-01-02 起，2020 起始日无更早热身日（`lookback_available=0`），禁止发明更早交易日。
- 全 sidecar 缺失：`incomplete_window` 85,654；`not_enough_history` 67,158。
- 2025 覆盖 99.00%（1,272,031 / 1,284,876）；2026 覆盖 98.24%（902,061 / 918,193）；均 `>=98%`。
- 2025/2026 缺失分解：close 非法行 0/0；不完整 20 日窗 11,874 / 9,955。

## A 门（不过 → 终态）

DSEM partial RankIC（控制冻结 score 截面秩；残差 Pearson；n>=4；残差化只用于 A）：

| 窗 | mean | median | ICIR | 有效日 | 共同股票数中位数 | 95% CI |
|---|---:|---:|---:|---:|---:|---|
| 2025 valid | **+0.020675** | +0.029931 | +0.0987 | 242 | 5279 | [−0.002302, +0.047721]（A 不要求 2025 CI） |
| 2026 OOS | **+0.030425** | +0.043169 | +0.1221 | 169 | 5347 | **[−0.008751, +0.070781]** |

2026 自然季度 mean DSEM partial RankIC（保留不完整 Q3 至 9-14）：

| 季度 | mean | 日数 |
|---|---:|---:|
| 2026Q1 | +0.043237 | 56 |
| 2026Q2 | −0.005431 | 60 |
| 2026Q3 | +0.057479 | 53 |

- 数据门过（S0=true）。
- 两窗 mean 均 `>0`（未反号）；2026 `majority_negative=false`，`single_quarter_driven=false`（季度门本身过）。
- **2026 CI 下界 −0.008751 `<= 0`，信息门不过。**

未命中 `DSEM_DATA_INVALID` / `DSEM_CONDITIONAL_FLIP`。按 §4 优先级 3 打 **`DSEM_CONDITIONAL_NO_EDGE`**。禁止改窗口、分母、方向或变换。B/C 取消。

## 未做

- 未跑 `train_sidecar_feature_arm` / `diag_pred_pair` / `portana_pred_pair` / BT，未改 10/3。
- 未改线上 pred `8a061ea4`，未碰 `55c5bf77`。
- 未扫 lookback / 分母 / 方向 / total-upside vol / Sortino / 阈值 / seed / 宽度 / `n_drop` / 新树。
- sidecar 只导出一次；A 只切片。未在 A 过后再导（避免 `DSEM_DATA_INVALID`）。

## 产物路径

- sidecar: `D:\PycharmProjects\wt-myquant-pr82-t5-dsv1\exports\analysis\t5_dsv1_20260918\sidecar\`
- A: `D:\PycharmProjects\wt-myquant-pr82-t5-dsv1\exports\analysis\t5_dsv1_20260918\information\`
- 2026 基线 pred 只读副本: `D:\PycharmProjects\wt-myquant-pr82-t5-dsv1\exports\analysis\t5_dsv1_20260918\control_pred_2026.csv`
- 本文件: `D:\PycharmProjects\wt-myquant-pr82-t5-dsv1\exports\analysis\t5_dsv1_20260918\t5_dsv1_verdict.md`
