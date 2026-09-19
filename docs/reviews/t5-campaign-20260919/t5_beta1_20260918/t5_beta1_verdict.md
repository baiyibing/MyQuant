# T5-BETA1 Verdict

- **最终标签**: `BETA_CONDITIONAL_FLIP`
- **停在**: A 门（跨窗条件信息门）；**未跑 B 重训 / C PortAna / BT**
- **线上**: 未改 pred `8a061ea4`，未改 10/3

## 冻结输入

| 项 | 值 |
|---|---|
| 刀法 tip | `f75022e`（PR #81 docs；full `f75022e08b6a1b51ccc8b6d56629dcd6f6106d48`） |
| 实现 worktree | `D:\PycharmProjects\wt-myquant-pr81-t5-beta1` @ `feat/t5-beta1-impl` on tip `f75022e` + 本刀脚本 |
| sidecar | `exports\analysis\t5_beta1_20260918\sidecar\BETA60_ANTI_RANK.parquet` |
| sidecar SHA-256 | `2021a4393a5ddd8d2dff3cae82f127130d459a376d7a9c0610c0f07043dfd5c3` |
| key digest | `e2b051e973df6c23f74d06cd0d9791c91253197fe05adaaf5de2531945c6432c` |
| benchmark | 冻结快照 `SH000300`（未换 000300.SH / 510300 / 等权市场 / 截面均值） |
| benchmark digest | `874055a39bc479fd5228bb85149e6b0c9bb7ef010d372b5f25ecbaf9a44ec9bf`（A 门复算一致） |
| provider | `C:\Users\wangc\.qlib\qlib_data\my_data` |
| calendar SHA-256 | `9e07c43e1fcb0f8031c150712f9675dadb5392dfa4b40ed1cdc162075399cdc6`（`2020-01-02`～`2026-09-15`，1626 日） |
| 控制 recorder | `8a061ea428e04bb3a199a485ade49d0e`（只读；未回写） |
| 标签 | `Ref($close,-2)/Ref($close,-1)-1`（未改） |
| 唯一特征 | `BETA60_ANTI_RANK` = 固定 60 个市场交易日、股与 `SH000300` 同一冻结 `$close` 的 close-to-close 简单收益，带截距 OLS 斜率 `beta60`（窗内有效配对全部进回归，下限 40 不是「最近 40 个」），再对 **`-beta60`** 在冻结 handler 当日 ∩ 有效 beta60 上 `rank(method="average", pct=True)`；**先 OLS 再乘 -1**。未用 Alpha158 `BETA60`（价格对时间斜率），未对收益先取负再回归。 |

## 数据门（过）

- sidecar 7,699,616 行 / 5,587 票 / 1,625 日；有限秩 7,417,155。
- 抽样 16 行独立复算 `beta60` 通过；3 日截面秩 `rank(-beta60)` 复算 `max_abs_diff=0`；时点检查通过；A 未在子样本上重 rank。
- `SH000300` 对齐日历 1,625 日，缺日/非正 close = 0；未插值、未 ffill、未用 0 补收益、未向 `t-60` 之前扩窗。
- 缺失：`not_enough_history` 206,157（冻结日历从 2020-01-02 起，禁止更早补点）；`insufficient_valid_pairs` 76,304。
- 2025 覆盖 99.56%（1,279,173 / 1,284,876）；2026 覆盖 98.82%（907,395 / 918,193）；均 `>=98%`。
- 2025/2026 缺失分解：close 非法行 0/0；有效配对不足 4,705 / 4,585。

## A 门（不过 → 终态）

BETA partial RankIC（控制冻结 score 截面秩；残差 Pearson；n>=4）：

| 窗 | mean | median | ICIR | 有效日 | 共同股票数中位数 | 2026 95% CI |
|---|---:|---:|---:|---:|---:|---|
| 2025 valid | **−0.003630** | −0.019013 | −0.0170 | 242 | 5308.5 | — |
| 2026 OOS | **+0.004667** | +0.006605 | +0.0194 | 169 | 5372 | **[−0.029287, +0.042903]** |

2026 自然季度 mean BETA partial RankIC（保留不完整 Q3 至 9-14）：

| 季度 | mean | 日数 |
|---|---:|---:|
| 2026Q1 | +0.011179 | 56 |
| 2026Q2 | −0.040246 | 60 |
| 2026Q3 | +0.048631 | 53 |

- 数据门过；2026 `majority_negative=false`，`single_quarter_driven=false`（季度门本身过）。
- **2025 mean < 0 而 2026 mean > 0，两窗反号。**
- 2026 CI 下界 −0.029287 `<= 0`（信息门亦不过，但优先级低于反号）。

按 §4 优先级 2 打 **`BETA_CONDITIONAL_FLIP`**。禁止翻方向、挑季度、换 beta 定义 / 窗口 / 基准 / 最小样本。B/C 取消。

## 未做

- 未跑 `train_sidecar_feature_arm` / `diag_pred_pair` / `portana_pred_pair` / BT，未改 10/3。
- 未改线上 pred `8a061ea4`，未碰 `55c5bf77`。
- 未扫 lookback / 基准 / 无截距 / 对数收益 / rolling corr / 下行 beta / 方向 / 变换 / seed / 宽度 / `n_drop`。
- sidecar 只导出一次；A 只切片。未在 A 过后再导（避免 `BETA_DATA_INVALID`）。

## 产物路径

- sidecar: `D:\PycharmProjects\wt-myquant-pr81-t5-beta1\exports\analysis\t5_beta1_20260918\sidecar\`
- A: `D:\PycharmProjects\wt-myquant-pr81-t5-beta1\exports\analysis\t5_beta1_20260918\information\`
- 2026 基线 pred 只读副本: `D:\PycharmProjects\wt-myquant-pr81-t5-beta1\exports\analysis\t5_beta1_20260918\control_pred_2026_8a061ea4.csv`
- 本文件: `D:\PycharmProjects\wt-myquant-pr81-t5-beta1\exports\analysis\t5_beta1_20260918\t5_beta1_verdict.md`
