# 筹码 parity 报告（2026-09-13）

- 仓库：MyQuant `feat/m2-chip-parity`
- 对照：MyQuant-backtrader `/workspace/MyQuant-backtrader`
- 窗口（文档约定）：2026-03-02 ~ 2026-03-23
- 标的（8）：600000, 300190, 920014, 000001, 000858, 601318, 688981, 301236
- rtol：1e-4（未启用数值比对）

## 结论

**M2 closed as 不可比。**

依据 `docs/chip-parity-map.md`：`MAPPING_CONCLUSION=不可比`。本仓 bin 筹码字段为供应商预置、COST_* 为高低价 Quantile 近似；BT `qlib_cost`/`cyq` 与 `backtest/chip_indicator` 为换手衰减分布因子。无同构可比对象，故不伪造数值相等，也不跑 live golden 对齐。

## 交付

| 片 | 状态 |
|----|------|
| M2-A 映射表 | 已合入本分支 |
| M2-B 比较器 + 注入单测 | harness 覆盖 agree/disagree；live → not comparable / exit 0 |
| M2-C 晋升门 | 见 `docs/chip-parity-gate.md`；本报告归档关闭 |

## Live golden

**未跑**（fixture-only / map-blocked）。将来映射改为可比后再产两侧数值 JSON 并重开本报告系列。
