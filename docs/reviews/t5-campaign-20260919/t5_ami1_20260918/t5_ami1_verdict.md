# T5-AMI1 Verdict

- **最终标签**: `AMIHUD_CONDITIONAL_NO_EDGE`
- **停在**: A 门（跨窗条件信息门）；**未跑 B 重训 / C PortAna / BT**
- **线上**: 未改 pred `8a061ea4`，未改 10/3

## 冻结输入

| 项 | 值 |
|---|---|
| 刀法 tip | `b2b675c`（PR #79 docs；full `b2b675cf2be5411704bd46b45aaf3f3f9cf21cd0`） |
| 实现 worktree | `D:\PycharmProjects\wt-myquant-pr79-t5-ami1` @ `b2b675c` + 本刀脚本 |
| sidecar | `exports\analysis\t5_ami1_20260918\sidecar\AMIHUD20_RANK.parquet` |
| sidecar SHA-256 | `e5ec2bc7cba8e580cbc33e1253605f00166119f740542c699fdc6c4b4822746d` |
| key digest | `e2b051e973df6c23f74d06cd0d9791c91253197fe05adaaf5de2531945c6432c` |
| provider | `C:\Users\wangc\.qlib\qlib_data\my_data` |
| calendar SHA-256 | `9e07c43e1fcb0f8031c150712f9675dadb5392dfa4b40ed1cdc162075399cdc6`（`2020-01-02`～`2026-09-15`，1626 日） |
| 控制 recorder | `8a061ea428e04bb3a199a485ade49d0e`（只读） |
| 标签 | `Ref($close,-2)/Ref($close,-1)-1`（未改） |
| 唯一特征 | `AMIHUD20_RANK` = 20 个市场交易日 `mean(abs(close_d/close_{d-1}-1)/$amount)` 后，在冻结 handler 当日 ∩ 有效 impact20 上 `rank(method="average", pct=True)`；未乘 `-1` |

## 数据门（过）

- sidecar 7,699,616 行 / 5,587 票 / 1,625 日；有限秩 7,546,750。
- 抽样 16 行独立复算 impact20 通过；3 日截面秩复算 `max_abs_diff=0`；时点检查通过。
- 缺失以 `incomplete_window` 为主（152,830；冻结日历从 2020-01-02 起，禁止向更早日期补点），`amount_invalid|incomplete_window` 36。
- 2025 覆盖 99.00%（1,272,031 / 1,284,876）；2026 覆盖 98.24%（902,022 / 918,193）；均 `>=98%`。
- 2025/2026 缺失分解：close 行 0/0；amount 行 3/33；20 日完整性 11,875 / 10,008。

## A 门（不过 → 终态）

AMIHUD partial RankIC（控制冻结 score 截面秩；残差 Pearson；n>=4）：

| 窗 | mean | median | ICIR | 有效日 | 共同股票数中位数 | 2026 95% CI |
|---|---:|---:|---:|---:|---:|---|
| 2025 valid | **+0.018829** | +0.026892 | 0.1329 | 242 | 5279 | — |
| 2026 OOS | **+0.015922** | +0.016182 | 0.0921 | 169 | 5347 | **[-0.007202, +0.042791]** |

2026 自然季度 mean partial RankIC（保留不完整 Q3 至 9-14）：

| 季度 | mean | 日数 |
|---|---:|---:|
| 2026Q1 | +0.023597 | 56 |
| 2026Q2 | -0.024891 | 60 |
| 2026Q3 | +0.054015 | 53 |

- 两窗 mean 均 `>0`（未反号）。
- `majority_negative=false`，`single_quarter_driven=false`（季度门过）。
- **2026 moving-block bootstrap（5 日、10,000 次、seed `20260918`）CI 下界 -0.007202 `<= 0`。**

按 §4 优先级 3 打 **`AMIHUD_CONDITIONAL_NO_EDGE`**。禁止改 20 日窗、公式、方向或变换；B/C 取消。

## 未做

- 未重训、未新建 candidate recorder、未跑 `diag_pred_pair` / `portana_pred_pair`。
- 未改线上 pred `8a061ea4`，未改 10/3，未碰 `55c5bf77`。
- 未扫 lookback / 成交额归一 / 反向 / 阈值 / seed。

## 产物路径

- sidecar: `D:\PycharmProjects\wt-myquant-pr79-t5-ami1\exports\analysis\t5_ami1_20260918\sidecar\`
- A: `D:\PycharmProjects\wt-myquant-pr79-t5-ami1\exports\analysis\t5_ami1_20260918\information\`
- 2026 基线 pred 只读副本: `D:\PycharmProjects\wt-myquant-pr79-t5-ami1\exports\analysis\t5_ami1_20260918\control_pred_2026_8a061ea4.csv`
- 本文件: `D:\PycharmProjects\wt-myquant-pr79-t5-ami1\exports\analysis\t5_ami1_20260918\t5_ami1_verdict.md`
