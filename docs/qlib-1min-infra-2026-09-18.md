# qlib 1min 基础设施（2026-09-18）

日频 `~/.qlib/qlib_data/my_data` **不动**。1min 单独放在 `~/.qlib/qlib_data/my_data_1min`（C 盘，和日频并列）。Handler 缓存仍在 D。

操作手册：`my_docs/提示词-qlib-1min-bin刷新.md`。

## 数据从哪来

本机分钟湖：

- 股票 `E:\stock_data\stock\period=1m\dividend_type=none`（不复权，满日约 241 根，缺 13:00）
- 指数 `E:\stock_data\index\period=1m\dividend_type=none`（覆盖短于个股；`899001_BJ` 可能空）

```
qlib_scripts/stage_1min_from_lake.py   股票+指数湖 → staging parquet
qlib_scripts/dump_bin.py dump_all --freq=1min
  （日历只从 sz000001/sh000300 等锚点并集，禁止每只回传 10 万 Timestamp）
qlib_scripts/refresh_mydata_1min.py    日常增量 / --rebuild
qlib_scripts/build_mydata_1min.py      首次冒烟（默认 20 只 + SH000300）
```

已有 `my_data_1min` 只追加新分钟，不要对短窗口 `dump_all`（会截短日历），不要 `dump_update`。

```text
D:\anaconda3\envs\vanna312\python.exe -u qlib_scripts/refresh_mydata_1min.py
D:\anaconda3\envs\vanna312\python.exe qlib_scripts/build_mydata_1min.py
```

## 训练预测什么

官方 highfreq 例子（`qlib-dev/examples/highfreq`）是：

| 项 | 官方 | 本仓冒烟默认 |
|---|---|---|
| 特征 | Alpha158，窗口单位变成**分钟** | 8 个轻量：MA5/10/20/60、STD20、量比、K 线幅度 |
| 标签 | `Ref($close,-2)/Ref($close,-1)-1`（未来 **2 分钟**收益） | 同官方；`--label-horizon 30` 改成约半小时 |
| 模型 | `HFLGBModel` 二分类涨跌 | `LGBModel` 回归（方便看 IC） |
| 宇宙 | csi300 | dump 进去的 `all` |
| 回测 | 另有嵌套高频执行框架 | **不做**；成交仍走 BT 分钟湖 |

```text
D:\anaconda3\envs\vanna312\python.exe my_scripts/train_1min_smoke.py
D:\anaconda3\envs\vanna312\python.exe my_scripts/train_1min_smoke.py --label-horizon 30
```

预测写到 `exports/1min_smoke/预测结果_1min_h2.csv`，不覆盖 `8a061ea4` / `55c5bf77`。

想用满 Alpha158 分钟窗：`custom_handler_1min.Alpha158Min`（158 个因子，窗口是分钟不是天）。

## 和日频 / BT 的关系

- 日频训练、TopK、PortAna 仍只读 `my_data`。
- BT 分钟成交已经在跑，不依赖这套 bins。
- 以后要用 qlib 分钟信号：在 1min 上 train/predict，再聚合成日名单交给 BT。
