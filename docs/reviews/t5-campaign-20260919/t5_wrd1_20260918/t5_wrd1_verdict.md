# T5-WRD1 Verdict

- **最终标签**: `WINRATIO_GAP_MODEL_NO_TRANSFER`
- **停在**: B 门（模型信号门）；**未跑 C / PortAna / BT**
- **线上**: 未改 pred `8a061ea4`，未改 10/3

## 冻结输入

| 项 | 值 |
|---|---|
| 刀法 tip | `397c904`（PR #78 docs） |
| 实现 worktree | `D:\PycharmProjects\wt-myquant-pr78-t5-wrd1` @ `397c904` |
| CYQ parquet | `E:\stock_data\cyq_winner_ratio\t5_cyq1_2020_2026_20260917.parquet` |
| CYQ SHA-256 | `d167d27916920ea7c49a3f0cb2202de2bb64b7a4425a7852de64f0b278c88a34`（校验 OK，未重算） |
| sidecar | `...\exports\analysis\t5_wrd1_20260918\sidecar\BROKER_WR_GAP.parquet` |
| sidecar SHA-256 | `34453f4679ded0ba8233c16eee33c916e87d5eecca16fee15c7e5173424a6d65` |
| 控制 recorder | `8a061ea428e04bb3a199a485ade49d0e`（只读） |
| 候选 recorder | `5ef339db2fdc4f56815edf78d17e3017`（exp `alpha158_cost_kdj_lgb__t5_wrd1`，early-stop 233） |

## A 门（过）

| 窗 | mean WR-gap partial RankIC | 2026 CI |
|---|---:|---|
| 2025 valid | +0.017519 | — |
| 2026 OOS | +0.017242 | [+0.003146, +0.031243] |

覆盖与数据门通过；`A_GATE_PASS`。

## B 门（不过 → 终态）

共同样本上相对 `8a061ea4`：

| 窗 | RankIC ctrl→cand | Top10Spread ctrl→cand | ΔRankIC 95% CI |
|---|---|---|---|
| 2025 | 0.053079 → **0.053340**（胜） | 0.022765 → **0.024317**（胜） | — |
| 2026 | 0.029973 → **0.030642**（胜） | 0.014869 → **0.014529**（负，败） | [**-0.000645**, +0.002185]（下沿≤0，败） |

失败原因（预注册）：
1. 2026 Top10Spread 未同时高于基线
2. 2026 ΔRankIC bootstrap CI 下界 ≤ 0

按 §4 打 **`WINRATIO_GAP_MODEL_NO_TRANSFER`**；禁止加 raw `$winratio`、第二列、交互、异 seed 或扫参；C 取消。

## 产物路径

- A: `...\t5_wrd1_20260918\information\`
- sidecar: `...\t5_wrd1_20260918\sidecar\`
- B model: `...\t5_wrd1_20260918\model\`
- B pred_pair: `...\t5_wrd1_20260918\pred_pair\`
- 本文件: `...\t5_wrd1_20260918\t5_wrd1_verdict.md`
