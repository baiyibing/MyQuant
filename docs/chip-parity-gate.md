# M2-C：筹码 parity 晋升门

- 日期：2026-09-13
- 依赖：`docs/chip-parity-map.md`（M2-A）、`my_scripts/chip_parity_check.py`（M2-B）
- 当前映射结论：**不可比** → 本门在「真分布 COST 同构落地并改写映射为可比」之前保持 **closed / blocked**

---

## 1. 触发事件（何时必须跑）

在以下任一事件发生前，若策略 / handler **消费筹码量**（bin 筹码字段、COST_*、或未来真分布因子）并拟晋升 **Paper**：

1. 首次把筹码相关特征或信号纳入 Paper 候选配置；
2. 变更 COST / cyq / 筹码 bin 字段的定义、窗口、复权或数据源；
3. 路线图或中期计划要求重开 M2 数值门（映射表从不可比改为可比之后）。

**不触发**：纯 Alpha158 / 非筹码特征的日常训练与导出；M3 ranking-only 且未使用筹码量时。

日常 CI **不**强制本门（晋升门，不是每日红灯）。

---

## 2. 通过标准

| 条件 | 要求 |
|------|------|
| 映射 | `docs/chip-parity-map.md` 中 `MAPPING_CONCLUSION=` 为 **可比**（或英文 `comparable`），且逐量行标明可比对象 |
| 窗口 / 宇宙 | 默认 2026-03-02~03-23；固定 8 标的（含 `600000` / `300190` / `920014`）；变更须同步改 map 与 golden meta |
| 数值 | `chip_parity_check.py` 对每个可比量相对误差 ≤ `--rtol`（默认 `1e-4`）；不一致 **exit 1** |
| 归档 | 将当次报告写入 `docs/chip-parity-report-<YYYY-MM-DD>.md`（见 §3） |

若映射仍为 **不可比**：

- 比较器 live 模式 exit 0 并打印 `not comparable`（**不算**数值通过）；
- **不得**宣称「跨仓筹码已对齐」；
- Paper 晋升若依赖筹码量 → **blocked**，直至映射改写 + 数值门通过；
- 允许归档一份「closed as 不可比」报告（本波已写，见下节）。

---

## 3. 结果归档路径

```
docs/chip-parity-report-<date>.md
```

建议最小章节：触发原因、git SHA（本仓 + BT）、映射结论、rtol、符号/窗口、逐量表或「不可比关闭」说明、CLI 原文摘要。

本波归档：`docs/chip-parity-report-2026-09-13.md`（M2 因不可比关闭）。

---

## 4. 推荐命令

```bash
# 映射仍为不可比时：应 exit 0 且报告 not comparable
/workspace/vanna312/bin/python my_scripts/chip_parity_check.py \
  --bt-repo /workspace/MyQuant-backtrader

# 将来映射改为可比且具备两侧数值后：
/workspace/vanna312/bin/python my_scripts/chip_parity_check.py \
  --bt-repo /workspace/MyQuant-backtrader \
  --myquant-values-json path/to/mq.json \
  --bt-values-json path/to/bt.json \
  --rtol 1e-4 \
  --report-out /tmp/chip-parity-out.txt
```

Harness 单测（注入 fake bt）：`pytest my_tests/test_chip_parity_check.py`。
