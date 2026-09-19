# T5-MXR1 Verdict

- **最终标签**: `MAXRET_MODEL_NO_TRANSFER`
- **停在**: B 门（模型信号门）；**未跑 C PortAna / BT**
- **线上**: 未改 pred `8a061ea4`，未改 10/3

## 冻结输入

| 项 | 值 |
|---|---|
| 刀法 tip | `112faf4`（PR #80 docs；full `112faf4a67663239e1059e4974cf43b087b106f8`） |
| 实现 worktree | `D:\PycharmProjects\wt-myquant-pr80-t5-mxr1` @ `feat/t5-mxr1-impl` on tip `112faf4` + 本刀脚本 |
| sidecar | `exports\analysis\t5_mxr1_20260918\sidecar\MAXRET20_ANTI_RANK.parquet` |
| sidecar SHA-256 | `27320f8b7f6de3854802f97325f682039732470ce387f21bc9cd6c3083b7b348` |
| key digest | `e2b051e973df6c23f74d06cd0d9791c91253197fe05adaaf5de2531945c6432c` |
| provider | `C:\Users\wangc\.qlib\qlib_data\my_data` |
| calendar SHA-256 | `9e07c43e1fcb0f8031c150712f9675dadb5392dfa4b40ed1cdc162075399cdc6`（`2020-01-02`～`2026-09-15`，1626 日） |
| 控制 recorder | `8a061ea428e04bb3a199a485ade49d0e`（只读） |
| 候选 recorder | `d03e8ffcb6d14668b4d6fc2b192bc8c7`（实验 `alpha158_cost_kdj_lgb__t5_mxr1`；新实验，未回写 `8a061ea4`） |
| 标签 | `Ref($close,-2)/Ref($close,-1)-1`（未改） |
| 唯一特征 | `MAXRET20_ANTI_RANK` = 20 个市场交易日 close-to-close 简单收益 `r=close_d/close_{d-1}-1` 的 `maxret20=max(r)`，再对 **`-maxret20`** 在冻结 handler 当日 ∩ 有效 maxret20 上 `rank(method="average", pct=True)`；**先 max 再乘 -1**，未用 `$amount`/`$volume`、未翻成 `MAXRET20_RANK` |

## 数据门（过）

- sidecar 7,699,616 行 / 5,587 票 / 1,625 日；有限秩 7,546,804。
- 抽样 16 行独立复算 maxret20 通过；3 日截面秩 `rank(-maxret20)` 复算 `max_abs_diff=0`；时点检查通过。
- 缺失以 `incomplete_window` 为主（152,812；冻结日历从 2020-01-02 起，禁止向更早日期补点）。
- 2025 覆盖 99.00%（1,272,031 / 1,284,876）；2026 覆盖 98.24%（902,061 / 918,193）；均 `>=98%`。
- 2025/2026 缺失分解：close 行 0/0；20 日完整性 11,874 / 9,955。

## A 门（过）

MAXRET partial RankIC（控制冻结 score 截面秩；残差 Pearson；n>=4）：

| 窗 | mean | median | ICIR | 有效日 | 共同股票数中位数 | 2026 95% CI |
|---|---:|---:|---:|---:|---:|---|
| 2025 valid | **+0.044092** | +0.051352 | 0.2662 | 242 | 5279 | — |
| 2026 OOS | **+0.038542** | +0.046601 | 0.1767 | 169 | 5347 | **[+0.004456, +0.073341]** |

2026 自然季度 mean MAXRET partial RankIC（保留不完整 Q3 至 9-14）：

| 季度 | mean | 日数 |
|---|---:|---:|
| 2026Q1 | +0.048652 | 56 |
| 2026Q2 | -0.005858 | 60 |
| 2026Q3 | +0.078124 | 53 |

- 两窗 mean 均 `>0`（未反号）。
- 2026 CI 下界 `+0.004456 > 0`。
- `majority_negative=false`，`single_quarter_driven=false`（季度门过）。
- A 全过，允许只加 `MAXRET20_ANTI_RANK` 一列重训。

## B 门（不过 → 终态）

对照 `8a061ea4`，候选 `d03e8ffc`；共同样本日 RankIC 与 Top10Spread（等权 Top10 减共同宇宙等权，非 Top-Bottom）；2026 `ΔRankIC` moving-block bootstrap（5 日、10,000 次、seed `20260918`）。

| 窗 | RankIC 对照 | RankIC 候选 | ΔRankIC | Top10 对照 | Top10 候选 | ΔTop10 | 2026 ΔRankIC 95% CI |
|---|---:|---:|---:|---:|---:|---:|---|
| 2025 valid | 0.053079 | 0.053129 | **+0.000051** | 0.005374 | 0.005322 | **-0.000053** | — |
| 2026 OOS | 0.029973 | 0.030435 | **+0.000463** | 0.000473 | 0.000966 | **+0.000492** | **[-0.000556, +0.001459]** |

2026 自然季度 mean ΔRankIC：

| 季度 | mean ΔRankIC |
|---|---:|
| 2026Q1 | -0.000122 |
| 2026Q2 | +0.000607 |
| 2026Q3 | +0.000918 |

- 2025：RankIC 候选略胜（过），**Top10Spread 候选未胜对照（不过）**。
- 2026：RankIC 与 Top10Spread 均候选胜（过）；季度门 `majority_negative=false`、`single_quarter_driven=false`（过）。
- **2026 ΔRankIC CI 下界 -0.000556 `<= 0`（不过）。**

B 要求两窗同时 `RankIC(candidate)>RankIC(8a)` 且 `Top10Spread(candidate)>Top10Spread(8a)`，且 2026 CI 下界 `>0`。未全过。按 §4 优先级 4 打 **`MAXRET_MODEL_NO_TRANSFER`**。禁止加 raw `maxret20`、第二列、交互、异 seed 或新树；C 取消。

## 未做

- 未跑 `portana_pred_pair` / BT，未改 10/3。
- 未改线上 pred `8a061ea4`，未碰 `55c5bf77`。
- 未扫 lookback / 方向 / 变换 / seed / 宽度 / `n_drop`。
- sidecar 只导出一次；A 只切片，B 只左连同一 SHA。

## 产物路径

- sidecar: `D:\PycharmProjects\wt-myquant-pr80-t5-mxr1\exports\analysis\t5_mxr1_20260918\sidecar\`
- A: `D:\PycharmProjects\wt-myquant-pr80-t5-mxr1\exports\analysis\t5_mxr1_20260918\information\`
- B 训练: `D:\PycharmProjects\wt-myquant-pr80-t5-mxr1\exports\analysis\t5_mxr1_20260918\model\`
- B 配对: `D:\PycharmProjects\wt-myquant-pr80-t5-mxr1\exports\analysis\t5_mxr1_20260918\pred_pair\`
- 2026 基线 pred 只读副本: `D:\PycharmProjects\wt-myquant-pr80-t5-mxr1\exports\analysis\t5_mxr1_20260918\control_pred_2026_8a061ea4.csv`
- 本文件: `D:\PycharmProjects\wt-myquant-pr80-t5-mxr1\exports\analysis\t5_mxr1_20260918\t5_mxr1_verdict.md`
