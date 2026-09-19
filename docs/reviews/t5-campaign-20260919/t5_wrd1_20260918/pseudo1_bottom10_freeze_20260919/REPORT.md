# T5-WRD1 伪实验1：Bottom10 冻结

**结论先行：** 判决 **部分支持「否决来自底部而非头部」**。把候选 Bottom10 换成对照 Bottom10 后，2026 冻结口径 Top−Bottom 从 **−3.401e-4 翻到 +5.903e-5**，点估计非负且好于原候选；但 moving-block bootstrap 95% CI **[−1.690e-3, +1.842e-3]** 下沿穿零，达不到全额支持。2025 mean(ΔSpread_freeze)=**+8.404e-4** ≥ 0。恒等式 ΔSpread_freeze = ΔTop = univ-EW ΔTop10。本实验**不能推翻** `WINRATIO_GAP_MODEL_NO_TRANSFER`（未重训）。

未改线上 pred `8a061ea4` / 10/3，未跑 C，未开伪实验2。

---

## 0. 范围与对齐

| 项 | 值 |
|---|---|
| worktree / tip | `wt-myquant-pr78-t5-wrd1` @ `397c904` |
| 对照 / 候选 | `8a061ea4` / `5ef339db`（只读） |
| sidecar SHA-256 | `34453f4679ded0ba8233c16eee33c916e87d5eecca16fee15c7e5173424a6d65` |
| 标签 | `Ref($close,-2)/Ref($close,-1)-1` |
| 冻结口径 | Top−Bottom（`mean(T)−mean(B)`，与 B 门 pred_pair 一致） |
| 伪实验组合 | 每日 `T_cand` 保留，`B` 强制换成 `B_ctrl` |
| ties | score 降序 + instrument 字典序，`kind=mergesort`；禁止随机 |
| 窗 | 2025-01-03～12-31（242 日）；2026-01-01～09-14（169 日；标签全空日不进） |
| bootstrap | block=5，reps=10000，seed=`20260919` |

对齐检查：B 门 `sort_values(score)` 口径下 2025/2026 ΔSpread_cand 与 `pred_pair/verdict.json` **逐位一致**（style_err=0）。预注册 lex 破并列后日均 Δ 绝对差 4.1e-11 / 7.1e-11（第 k 名无并列，`n_at_kth=1`）。univ-EW ΔTop10=+5.903e-05 vs B-diag ≈+5.90e-05；ΔBottom=+3.991e-04 vs ≈+4.0e-04。

## 1. 预注册定义

共同宇宙 = 对照与候选 score 的 inner join（与 B 门 `pred_pair` 同一套样本；标签缺失不先删票，取 mean 时 skipna）。每日：

- `Spread_ctrl = mean(label|T_ctrl) − mean(label|B_ctrl)`
- `Spread_cand = mean(label|T_cand) − mean(label|B_cand)`
- `Spread_freeze = mean(label|T_cand) − mean(label|B_ctrl)`
- `ΔSpread_cand = Spread_cand − Spread_ctrl`（应复现冻结 B 门）
- `ΔSpread_freeze = Spread_freeze − Spread_ctrl = mean(T_cand) − mean(T_ctrl)`
- 诊断：`Top10_univ = mean(T) − mean(universe)`，不改判决

恒等式：`Δ(Top−Bottom) = ΔTop − ΔBottom`。冻结底部后 `ΔSpread_freeze = ΔTop`，与 univ-EW ΔTop10 同值（宇宙项相消）。

## 2. 窗口结果

| 窗 | n日 | Spread_ctrl | Spread_cand | Spread_freeze | ΔSpread_cand | ΔSpread_freeze | univ-EW ΔTop10 | ΔBottom |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2025 | 242 | +2.277e-02 | +2.432e-02 | +2.361e-02 | +1.552e-03 | +8.404e-04 | +8.404e-04 | -7.112e-04 |
| 2026 | 169 | +1.487e-02 | +1.453e-02 | +1.493e-02 | -3.401e-04 | +5.903e-05 | +5.903e-05 | +3.991e-04 |

### Bootstrap（moving-block，block=5，reps=10000，seed=20260919）

| 窗 | 序列 | 点估计 | CI 2.5% | CI 97.5% |
|---|---|---:|---:|---:|
| 2025 | `d_spread_freeze` | +8.404e-04 | -3.723e-04 | +2.039e-03 |
| 2025 | `d_spread_cand` | +1.552e-03 | -2.334e-04 | +3.435e-03 |
| 2025 | `d_top10_univ` | +8.404e-04 | -3.723e-04 | +2.039e-03 |
| 2025 | `d_bot_mean` | -7.112e-04 | -2.127e-03 | +5.918e-04 |
| 2026 | `d_spread_freeze` | +5.903e-05 | -1.690e-03 | +1.842e-03 |
| 2026 | `d_spread_cand` | -3.401e-04 | -2.901e-03 | +2.286e-03 |
| 2026 | `d_top10_univ` | +5.903e-05 | -1.690e-03 | +1.842e-03 |
| 2026 | `d_bot_mean` | +3.991e-04 | -1.559e-03 | +2.280e-03 |

### 底部重叠（对照 vs 候选 Bottom10）

2025 日均 Jaccard=0.783、重叠=8.71/10；2026 Jaccard=0.734、重叠=8.40/10。底部并非几乎相同，强制替换会改 spread。

### 季度 mean(ΔSpread_freeze) / mean(ΔSpread_cand)

| 季 | ΔSpread_freeze | ΔSpread_cand | ΔBottom |
|---|---:|---:|---:|
| 2025Q1 | +3.214e-03 | +4.946e-03 | -1.732e-03 |
| 2025Q2 | +1.162e-03 | +3.583e-03 | -2.421e-03 |
| 2025Q3 | -4.383e-05 | -1.169e-03 | +1.126e-03 |
| 2025Q4 | -7.241e-04 | -6.547e-04 | -6.940e-05 |
| 2026Q1 | -8.120e-04 | -2.698e-03 | +1.886e-03 |
| 2026Q2 | -5.545e-04 | +1.964e-04 | -7.509e-04 |
| 2026Q3 | +1.674e-03 | +1.544e-03 | +1.297e-04 |

2026 月度 mean：

| 月 | ΔSpread_freeze | ΔSpread_cand | ΔBottom |
|---|---:|---:|---:|
| 2026-01 | -6.741e-04 | -2.490e-03 | +1.816e-03 |
| 2026-02 | -2.832e-03 | -9.432e-03 | +6.600e-03 |
| 2026-03 | +3.480e-04 | +1.398e-03 | -1.050e-03 |
| 2026-04 | -1.120e-03 | -1.831e-03 | +7.112e-04 |
| 2026-05 | -2.570e-03 | -2.867e-03 | +2.968e-04 |
| 2026-06 | +1.739e-03 | +4.850e-03 | -3.111e-03 |
| 2026-07 | +3.294e-03 | +4.753e-03 | -1.459e-03 |
| 2026-08 | +1.139e-03 | -1.762e-03 | +2.900e-03 |
| 2026-09 | -1.217e-03 | +1.058e-03 | -2.274e-03 |

## 3. 判决（门槛未改）

- **支持「否决来自底部而非头部」**：2026 mean(ΔSpread_freeze)>0，且明显好于冻结 ΔSpread_cand（至少翻到非负）；同时 2025 mean(ΔSpread_freeze)≥0 或不少于 ΔSpread_cand。
- **部分支持**：2026 均值翻非负但 CI 下沿≤0，或相对 ΔSpread_cand 改善有限。
- **削弱**：2026 mean(ΔSpread_freeze)≤mean(ΔSpread_cand) 或仍显著为负。

**本刀：部分支持。** 2026 点估计翻非负（+5.903e-5 > 0，且优于冻结 −3.401e-4），2025 同步为正；CI 下沿 −1.690e-3 ≤ 0，不能声称显著好于对照。

检查清单：2026 翻非负=True；好于候选=True；2025 不差=True；CI 下沿>0=False；仍显著为负=False。

机制与 B-diag 闭合：2026 Δ(Top−Bottom)=ΔTop−ΔBottom = +5.90e-5 − 3.99e-4 = **−3.40e-4**。冻结底部等于只留 ΔTop，所以点估计回到 univ-EW 微胜；2 月仍是头部拖累（ΔSpread_freeze **−2.83e-3**），但 2 月原候选 TB 的 **−9.43e-3** 里大部分是 ΔBottom **+6.60e-3**。点估计支持「冻结否决来自底部口径」，推断强度被全窗噪声限制。

冻结终态不变：`WINRATIO_GAP_MODEL_NO_TRANSFER`。伪实验只解释 B 门 Top−Bottom 翻负的机制，不构成过 B / 进 C 的证据。未开伪实验2。

## 4. 产物

目录：`D:\PycharmProjects\wt-myquant-pr78-t5-wrd1\exports\analysis\t5_wrd1_20260918\pseudo1_bottom10_freeze_20260919`

- `REPORT.md`（本文件）
- `daily_metrics.csv`
- `summary.json`

