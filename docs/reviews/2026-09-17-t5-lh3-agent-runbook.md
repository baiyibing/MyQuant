# T5-LH3 标签持有期预检：执行 agent runbook

## 在哪跑

- 主机：`newtest_4090`（Windows）。
- 仓库：`D:\PycharmProjects\MyQuant`，先取得本 PR 分支/提交。
- Python：`D:/anaconda3/envs/vanna312/python.exe`；该环境须能 import `qlib`、`pandas`、`numpy`，并能读 `~/.qlib/qlib_data/my_data`。
- 性质：固定 pred 的只读信号预检；禁止重训、覆盖 pred、跑 PortAna/BT、扫闸或改线上。

PowerShell 一行命令：

```powershell
Set-Location D:\PycharmProjects\MyQuant; & D:/anaconda3/envs/vanna312/python.exe -u my_scripts/diag_label_horizon.py --experiment alpha158_cost_kdj_lgb --recorder-id 8a061ea428e04bb3a199a485ade49d0e --pred-2025 my_scripts/预测结果_8a061ea4_2025valid.csv --window 2025-01-03:2025-12-31 --window 2026-01-01:2026-09-14 --topk 10 --block-days 5 --bootstrap-reps 10000 --seed 20260917 --out-dir exports/analysis/annual_lift_label_h3_20260917
```

若 qlib 数据不在默认目录，只可追加 `--provider-uri <现有数据目录>`；不得借此扩大窗口或换数据口径。输出目录已有四个结果文件时脚本会拒绝覆盖，请先保留旧目录，再换一个全新的输出目录。

## 输入与输出约定

运行前只检查存在性，不生成或替换任何输入：

| 项 | Windows 路径/标识 | 约束 |
|---|---|---|
| 2026 pred | `D:\PycharmProjects\MyQuant\my_scripts\mlruns\*\8a061ea428e04bb3a199a485ade49d0e\artifacts\pred.pkl` | 由 experiment `alpha158_cost_kdj_lgb` / recorder `8a061ea428e04bb3a199a485ade49d0e` 只读加载 |
| 2025 valid pred | `D:\PycharmProjects\MyQuant\my_scripts\预测结果_8a061ea4_2025valid.csv` | 同一 `trained_model` 已补出的 CSV，只读 |
| close 数据 | `%USERPROFILE%\.qlib\qlib_data\my_data` | 须覆盖标签所需后续交易日；尾部不完整行由两臂共同删除，不单独扩窗 |
| 输出目录 | `D:\PycharmProjects\MyQuant\exports\analysis\annual_lift_label_h3_20260917` | 新目录，gitignore 内；不得复用或覆盖 pred/既有分析包 |

固定比较：对照 `Ref($close,-2)/Ref($close,-1)-1`，候选 `Ref($close,-4)/Ref($close,-1)-1`。脚本只接受固定 recorder、标签、Top10、5 日 block、10,000 次和 seed `20260917`；窗口可显式覆盖，但本工单只跑命令中的 2025 valid 与 2026 OOS。

成功运行会生成：

- `daily_metrics.csv`：共同样本的每日 RankIC、Top10 每日化信号差、两者增量及缺失率；
- `window_summary.json`：窗口/季度汇总、5 日 moving-block bootstrap CI、门检与 verdict；
- `window_summary.md`：便于直接贴回的汇总；
- `input_summary.json`：输入路径、hash、行数、有效日期、股票数中位数和缺失率。

## Verdict 与停手规则

- `LABEL_HORIZON_CANDIDATE`：S1 两窗候选 RankIC/Top10 信号差均为正，S2 两窗候选均胜对照，且 S3 的 2026 `ΔRankIC` 95% CI 下界大于 0、季度稳定性通过。只允许另行申请一次“只改标签”的配对重训；本次不重训、不回测、不改线上。
- `LABEL_HORIZON_FLIP`：S1/S2 任一方向或排序在 2025/2026 翻转。立即停止标签周期路线，禁止改扫 h=2/4/5/10，也禁止回到 2026 扫闸。
- `LABEL_HORIZON_NO_EDGE`：两窗方向一致但不满足全部成功门，或 S3/季度稳定性不过。按证据不足停止；禁止用单窗 PortAna/NAV 复活路线。

脚本报错属于操作失败，不得手写研究 verdict。贴回报错、`--help` 输出和输入存在性检查后停手；只允许修复缺文件/环境/路径，不得趁机改标签、窗口、bootstrap、horizon 或 2026 闸参数。

## 回报格式

向 PR 告主贴回以下内容：

1. 命令末行的完整 `verdict: ...`。
2. 2025、2026 各自的：有效日期数、股票数中位数、缺失率；control/candidate mean RankIC、`ΔRankIC`、其 95% CI；control/candidate mean Top10 每日化信号差。
3. 2026 每季 `ΔRankIC`、`ΔTop10`，以及 `majority_negative` / `single_quarter_driven`。
4. 四个原始结果文件（至少完整贴回 `window_summary.md`，并提供其余 CSV/JSON 的可取路径或压缩包）。
5. 确认一句：`未重训、未覆盖 pred、未跑 PortAna/BT、未扫闸、未改线上；线上仍为 10/3。`

无论 verdict 是什么，跑完即停，不追加任何 horizon、窗口、闸或组合回放。
