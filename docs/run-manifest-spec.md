# run-manifest 契约（myquant.run-manifest/1）

- 日期：2026-09-13
- 仓：MyQuant（信号厂）。MyQuant-backtrader / OSkhQuant1.3 **本仓不改**；后续 BT 对齐读本契约即可。
- 实现：`my_scripts/run_manifest.py`

## 目标

一次 train / export / refresh 跑完后留下可追溯 JSON：用了哪版代码、哪份配置、哪段日历、哪些产物（MD5）、耗时节点。判优仍只看 IC/IR/名单命中率，**不用** PortAna NAV。

## 文件约定

- JSON，**UTF-8 无 BOM**
- 主键路径：`manifests/<stage>_<UTC>.json`（UTC = `YYYYMMDDTHHMMSSZ`）
- 可选副本：写在产物目录旁（pred / 导出池旁）

## Schema

```json
{
  "schema": "myquant.run-manifest/1",
  "stage": "train | export | refresh",
  "git_commit": "<startup HEAD sha or UNKNOWN>",
  "git_branch": "<optional; startup branch>",
  "git_dirty": false,
  "created_utc": "2026-09-13T01:02:03Z",
  "config": {
    "key": "value",
    "config_hash": "sha256(canonical json of config without config_hash)"
  },
  "data": {
    "calendar_first": "YYYY-MM-DD",
    "calendar_last": "YYYY-MM-DD",
    "calendar_days": 0,
    "calendar_md5": "optional"
  },
  "artifacts": [
    {"path": "相对或文件名", "md5": "32-hex lowercase", "rows": 0}
  ],
  "timings": {
    "total_seconds": 0,
    "nodes": [{"name": "handler_init", "seconds": 0}]
  }
}
```

### 字段说明

| 字段 | 要求 |
|------|------|
| `schema` | 必须精确等于 `myquant.run-manifest/1` |
| `stage` | 仅 `train` / `export` / `refresh` |
| `git_commit` | **启动时** HEAD（handler_init 前一次 `capture_git_provenance`）；勿在收尾再读 |
| `git_branch` / `git_dirty` | 可选；同一次启动快照。加字段不 bump schema |
| `config.config_hash` | 对去掉自身后的 config 做 canonical JSON（`sort_keys`、无空白）再 sha256 |
| `artifacts[].md5` | 文件字节 MD5，小写 32 hex |
| `artifacts[].rows` | 可选；可知行数时填写 |

### stage 建议 config 键

- **train**：`exp_name`, `segments`, `topk`, `n_drop`, `benchmark`, …
- **export**：`asof`（默认锁 `pred_minus_one`）, `topk`, `pred`, `out_dir`, `output_file_count`
- **refresh**：编排参数摘要（max_workers=8 等；禁 dump_update）

## 接入点（本仓）

| stage | 入口 |
|-------|------|
| train | `custom_train_backtest.py` → `write_train_manifest` |
| export | `export_daily_pool.py` → `write_export_manifest` |
| refresh | 后续可挂 `refresh_mydata.py`（本片未强制） |

## 非目标

- 不重开 as-of；不改池 CSV 字节契约（LF、无 BOM、裸六位）
- 不在本仓改 MyQuant-backtrader 代码
