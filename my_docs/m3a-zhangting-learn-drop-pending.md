# M3-A 涨停剔除训练集：IC/IR 对比（宿主机待跑）

- 日期：2026-09-13
- 代码：`DropLimitUpLearn` / `drop_limit_up_rows`（learn-only；infer / `export_daily_pool` as-of **未改**）
- VM 约束：`handler_init` ~18min，本环境**不**跑 live 全量重训

## 待宿主机验收

1. 与基线同窗重训（合批验证 M4-B train manifest + 本片）
2. 对比表：IC / IR / 名单命中率（**不要**用 PortAna NAV 判优）
3. 将对比表与 train manifest 路径回写本节

## 占位对比表

| 配置 | IC | IR | 备注 |
|------|----|----|------|
| 基线（filter_pipe `$zhangting`，无 learn DropLimitUp） | _pending_ | _pending_ | 宿主机 |
| M3-A（+ learn DropLimitUpLearn） | _pending_ | _pending_ | 宿主机 |

## 说明

生产路径仍带 `filter_pipe` 涨停剔除，learn processor 为同语义的 learn 帧防御；导出池字节契约与 `pred_minus_one` as-of 保持锁定。
