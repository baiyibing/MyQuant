# 提示词：L2 A 片贯通冒烟交接（给 OSkhQuant1.3 仓会话）

> 上游：MyQuant 仓 `docs/plan-l2-pipeline-2026-09-13.md`（PR #30 已合）A 片。
> 本文件 = 可直接粘贴给 1.3 侧会话的交接说明。侦察事实均对源核过（2026-09-13 晚）。

## 任务

把 LEBS csv 族的 `--pool-dir` 指向**研究侧契约名单目录**，同窗跑通一轮——验证「名单 → trade_decision → LEBS」管道贯通。这是 L2 的第一片，只验管道，不产结论。

## 名单源（只读，勿改勿拷）

首选：`E:\PycharmProjects\MyQuant\exports\m5r2_pred_topn10_20260302_20260908\`
- 131 个 `YYYYMMDD.csv`（20260303~20260908 全窗无缺日）、每文件 10 码、裸六位、LF 无 BOM
- 它是模型名单（晋升链的目标源），比 hand 快照（129 日，缺 20260525/20260605）更适合首冒烟

## 命令草案（以 1.3 侧实际入口/环境为准，参数名已对过 `backtest/lebs/cli.py`）

```bash
python -m backtest.lebs \
  --strategy csv_v5 \
  --pool-dir "E:/PycharmProjects/MyQuant/exports/m5r2_pred_topn10_20260302_20260908" \
  --start 20260303 --end 20260908 --freq 1d \
  --cash 1000000 --track pessimistic \
  --out docs/backtest/reports/l2_smoke_pred_v5
```

冒烟用哪个 csv_vN 都行（管道验证不挑规则）；建议 csv_v5，原因见下。

## 两个必须知道的侦察结论

1. **csv 族只有 v1~v5，没有 v6/v8**（`CSV_STRATEGY_BY_PRESET` 实读）。因此 **B 片对账版本锁定 csv_v5 ↔ BT 仓 version5 策略书**（两边都有实现，避免规则错配）；v6/v8 parity 以后再说
2. CLI 帮助里 csv_vN 标注 "retired"（当前 paper 双胞胎是 turtle）——**L2 复活 csv 族作研究名单对账道，与 turtle paper 并行不冲突，别动 `lebs/turtle/` 与 `capital.py`**

## 验收（照计划书 A 片）

- [ ] LEBS 报告落 `--out` 目录
- [ ] 名单加载率 = 131/131 天全被读（缺日=当日不买，非失败；本目录无缺日）
- [ ] 无引擎级异常；遇数据缺口按 fail-closed 行为**记录**（哪个代码哪天缺什么），不硬修
- [ ] 回报格式：报告路径 + 四个数（跑的天数 / 买入笔数 / 卖出笔数 / 名单加载率），净值数字不进结论

## 边界

不改 MyQuant / MyQuant-backtrader 任何代码；名单目录只读；preset 参数保持缺省（对账参数对齐留给 B 片统一）；发现契约不兼容先停下回报，不单方面改解析。
