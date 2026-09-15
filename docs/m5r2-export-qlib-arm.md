# M5 二轮任务 2：导出 Qlib 臂（名单源 A）

**阶段机（eng-perf P1-5）**：`predict_extended|train → pred 产物 → export_daily_pool / sweep_ranking --pred-from`。后两段只读 pred，禁止再付 handler_init。

前置：宿主跑通 `my_scripts/predict_extended.py`，得到 `预测结果_ext.csv`
（约 128 个交易日 pred；VM 不跑 ~25min handler_init）。

## 命令（as-of / topk 锁死）

```bash
python my_scripts/export_daily_pool.py --pred my_scripts/预测结果_ext.csv \
    --out-dir exports/m5r2_pred_topn10_20260302_20260908
```

约定：

- `--asof` 缺省即 `pred_minus_one`（**不重开**）
- `--topk` 缺省即 `10`（**不加 topk 臂**——那是 M3-B 维度，混入会污染 M5 归因）
- export manifest 由 `export_daily_pool` 自动落（M4-C）
- 验收：导出天数 = pred 交易日数 − 1（首日无前日 pred）；池 CSV 字节契约测试已有

常量见 `my_scripts/predict_extended.py`：`M5R2_EXPORT_OUT_DIR` /
`M5R2_EXPORT_TOPK` / `M5R2_EXPORT_ASOF`。

## 宿主仍欠

1. 一次 live `predict_extended`（~25min）→ `预测结果_ext.csv`
2. 上列 export
3. 任务 3（backtrader 仓三源对照）另会话
