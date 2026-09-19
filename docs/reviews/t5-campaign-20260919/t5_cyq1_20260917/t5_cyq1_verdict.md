# T5-CYQ1 verdict

**最终标签**: `CYQ_CONDITIONAL_NO_EDGE`

**停在**: A 段条件信息门（未进入 B/C）

## 关键数字

| 窗 | mean CYQ partial RankIC | 95% CI (5日 block bootstrap, 10000, seed 20260917) | 行覆盖率 | 有效日 |
|---|---:|---|---:|---:|
| 2025 valid | +0.032364 | [0.018986, 0.043564] | 99.92% | 242 |
| 2026 OOS | +0.016444 | **[-0.005880, 0.037817]** | 99.31% | 169 |

- 两窗 mean 均为正，但 **2026 CI 下界 ≤ 0** → 按刀法 §5.2 记 `CYQ_CONDITIONAL_NO_EDGE`，停手。
- 不得进入加列训练 / PortAna，不得改 CYQ 口径复活。

## 输入

- CYQ parquet: `E:\stock_data\cyq_winner_ratio\t5_cyq1_2020_2026_20260917.parquet`
- SHA-256: `d167d27916920ea7c49a3f0cb2202de2bb64b7a4425a7852de64f0b278c88a34`
- 路径说明: 刀法写 F:，本机无 F:，经 qmt 确认改用 E:
- 基线 pred: `8a061ea428e04bb3a199a485ade49d0e`（只读）
- 刀法 tip: `f6be68c` (`docs/annual-lift-t5-remnant-after-sx0-flip`)
- A 脚本: `my_scripts/diag_cyq_increment.py`
- 产出目录: `D:\PycharmProjects\MyQuant\exports\analysis\t5_cyq1_information_20260917`

## 动作

按刀法：整把 T5-CYQ1 收工；不扫变体、不跑 BT、不改线上 10/3。
