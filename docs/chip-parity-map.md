# M2-A：筹码量概念映射（MyQuant ↔ MyQuant-backtrader）

- 日期：2026-09-13
- 分支：`feat/m2-chip-parity`
- 对照仓：`/workspace/MyQuant-backtrader`（宿主机 `E:\PycharmProjects\MyQuant-backtrader`）
- **总结论：`MAPPING_CONCLUSION=不可比`**（无比对对象可做数值 golden；M2 合法关门）

> 哲学：Map first, align second。「不可比」是合法终点，不强迫数值一致。

---

## 1. 本仓（MyQuant）筹码相关对象

### 1.1 bin 预置字段（外部 CSV → `dump_bin`，本仓不计算）

来源：`docs/qlib-data-state-2026-09-13.md` / `qlib_scripts/custom.txt` 的
`--include_fields … netcsfree,basiccurhold,adfadfbasiccurhold,volddx,bigddx …`。

| 字段 | 定义（据命名与用法推断） | 单位 | 复权 | 窗口 | 本仓计算？ |
|------|--------------------------|------|------|------|------------|
| `$netcsfree` | 净流通盘 / 自由流通相关量（供应商导出） | 股或万股（源 CSV 口径；本仓未再换算） | 随源 CSV；非本仓后复权重算 | 逐日标量 | 否（只读 bin） |
| `$basiccurhold` | 基础当前持仓/流通盘类标量 | 同上 | 同上 | 逐日 | 否 |
| `$adfadfbasiccurhold` | `basiccurhold` 的调整/衍生版（命名保留源侧拼写） | 同上 | 同上 | 逐日 | 否 |
| `$volddx` | 量能 DDX 类资金流 | 源侧单位 | 源侧 | 逐日 | 否 |
| `$bigddx` | 大单 DDX | 源侧单位 | 源侧 | 逐日 | 否 |

特征层（`Alpha158CostKDJ`，`include_lz=True`）仅对这些字段做滚动标准化 / 比率（如 `VOLDDX_TX*`、`BIGDDX_R*`），**不重建筹码分布**。

### 1.2 COST 特征（通达信 COST 的 **Quantile 近似**，非分布 COST）

落点：`my_scripts/custom_handler.py` → `Alpha158CostKDJ`。

| 量 | 本仓定义 | 单位 | 复权 | 窗口 | 是否真筹码分布 |
|----|----------|------|------|------|----------------|
| L1 ≈ COST(0.01) | `Quantile($low, N, 0.0001)` | 价格 | 用 bin `$low`（与训练同源；非独立复权链） | `cost_window` 默认 **250** | **否** — 高低价分位数近似 |
| L2 ≈ COST(99.99) | `Quantile($high, N, 0.9999)` | 价格 | 同上 `$high` | 250 | **否** |
| L3 | `(close-L1)/(L2-L1)*100` | [0,100] 相对位置 | — | 派生 | — |
| COST_K / COST_D | `EMA(L3,5)` / `EMA(K,5)`（注释：近似通达信 `SMA(X,3,1)`） | 同 L3 | — | EMA span 5 | — |
| COST_J | `3*K-2*D` | 同 L3 | — | — | — |
| MAIRU_SIGNAL | J 上穿 K 且 J&lt;80（+ 可选均线过滤） | {0,2}/信号 | — | — | 信号，非筹码量 |

文档自证：`my_docs/KDJ的Qlib实现.md` 写明「方案二：简化近似」；生产 handler 走的就是方案二，**没有**接入 BT/`QuantsPlaybook` 的 `CYQ_COST`。

---

## 2. 对照仓（MyQuant-backtrader）筹码相关对象

### 2.1 `qlib_cost/`（研究脸：日线 OHLCV+换手 → 分布 → 因子）

| 对象 | 定义 | 单位 | 复权/输入 | 窗口 |
|------|------|------|-----------|------|
| `calc_dist_chips` | N 日三角/均匀/换手系数累积筹码分布 | 量在价格网格上 | 输入 `close,high,low,vol,turnover_rate`；价格网格 step=0.01；**调用方负责复权一致性** | 调用方 rolling N |
| `ChipFactor.get_winner(p)` | 价位 p 以下筹码占比 | [0,1] | 基于 cumpdf | N |
| `ChipFactor.get_cost(r)` | 累计获利比率 r 对应价位（真 · 通达信 COST 语义） | 价格 | 同上 | N |
| `get_cyqk_c` / CYQK_C_* | 收盘价下获利盘占比 | [0,1] | triang / uniform / turn_coeff | ops 的 N |
| `get_asr` / ASR_* | 收盘 ±10% 活跃筹码占比 | [0,1] | 同上 | N |
| `get_ckdw` / CKDW_* | (成本中位−min)/(max−min)，可 winsorize | [0,1] | 同上 | N |
| `get_prp` / PRP_* | close/平均成本 − 1 | 无量纲 | 同上 | N |

### 2.2 `backtest/chip_indicator.py` + `chip_algorithm.py`（Cerebro Indicator 路径）

输出同名四因子 `cyqk_c / asr / ckdw / prp`，算法与 `qlib_cost` 同源思路，但是 **另一份封装**（默认 period=80；MVP 曾用占位流通股本）。路线图已弃用 Cerebro 作产品引擎；本映射仍列出以免漏扫。

---

## 3. 逐量对照表

| # | MyQuant 量 | BT 候选 | 定义是否同构 | 单位 | 复权 | 窗口 | **可比？** | 说明 |
|---|------------|---------|--------------|------|------|------|------------|------|
| A | `$netcsfree` | （无） | — | — | — | — | **不可比** | BT 无同名/同义字段；无重建公式 |
| B | `$basiccurhold` | （无） | — | — | — | — | **不可比** | 同上 |
| C | `$adfadfbasiccurhold` | （无） | — | — | — | — | **不可比** | 同上；仅作本仓比率分母 |
| D | `$volddx` / `$bigddx` 及 LZ 滚动特征 | （无 cyq 对应） | — | — | — | — | **不可比** | 资金流字段 ≠ 筹码分布因子 |
| E | L1/L2 Quantile 近似 COST | `ChipFactor.get_cost(0.0001/0.9999)` | **否** | 皆价格 | 输入链不同 | 250 vs 调用 N（常 80） | **不可比** | 分位数高低价 ≠ 换手衰减分布分位 |
| F | COST_K/D/J | （无） | — | — | — | — | **不可比** | BT 无 COST-KDJ；且上游 L1/L2 已不可比 |
| G | （本仓无） | CYQK_C / ASR / CKDW / PRP | — | — | — | — | **不可比** | 本仓训练/导出路径未产出这些量 |
| H | （本仓无独立实现） | `backtest.chip_indicator` 四线 | — | — | — | — | **不可比** | 本仓无平行 Indicator |

---

## 4. 总判定

```
MAPPING_CONCLUSION=不可比
```

- **无比对对象**：没有任何一对 (本仓量, BT 量) 同时满足定义同构 + 单位一致 + 复权口径可对齐 + 窗口可对齐。
- 名字相近的「COST」是最大误导点：本仓是 `Quantile` 近似，BT 是 `cumpdf` 分位；**禁止**用数值逼近把二者判成「已对齐」。
- 因此 M2 **不进入**「强制数值 parity」阶段；M2-B 比较器仍交付（注入 fake bt 证明 harness），对真实映射 live 跑只报告「not comparable」并以 exit 0 结束。
- M2-C 晋升门：在映射仍为不可比期间，**不得**以「筹码量已跨仓对齐」为由晋升 Paper；若策略改用真分布 COST 并在本仓落地同构实现，须先改写本表为「可比」再开数值门。

---

## 5. 固定 golden 窗（供 M2-B 文档/夹具，非 live 对齐前提）

| 项 | 值 |
|----|-----|
| 窗口 | 2026-03-02 ~ 2026-03-23（与首轮 M5 / R0 同窗） |
| 标的（8） | `600000`, `300190`, `920014`(BJ), `000001`, `000858`, `601318`, `688981`, `301236` |
| 选取说明 | 前三只计划硬性要求；后五只覆盖主板/深市龙头/沪深300成分/科创板/创业板，便于将来若映射变可比时复用 |

