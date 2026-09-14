# 任务书：ST 历史 PIT 数据集（Wind × Kimi datasource → F 湖 → MyQuant 消费）

- 日期：2026-09-14
- 背景：zcode 的 QMT 逐码采集方案因速度不可行（~0.5s/只，单日全市场 46 分钟）被停止；本方案改用 **Kimi datasource 的 Wind 接口**批量获取 A 股 ST 实施/撤销历史，构建本地 PIT 数据集。
- 状态：**深市 PIT 已落地**（交易所简称变更，不消耗 Kimi）。沪/京仍缺 14 个 Wind 实施批；额度恢复后只补这些。已验证 Wind `wind_get_financial_data` 可返回：
  - 实施 ST 后简称、实施 ST 前简称、实施 ST 日期、实施 ST 原因
  - 撤销日期、撤销 ST 后简称、撤销 ST 前简称

## 数据源

- **源**：`wind`（经 Kimi datasource MCP）
- **API**：`wind_get_financial_data`
- **问题串模板**：
  - 实施：`"code1.SZ、code2.SH…codeN.SZ的ST状态和历史戴帽摘帽时间"`
  - 撤销：`"code1.SZ、code2.SH…codeN.SZ的撤销风险警示和摘帽日期"`
- **批量大小**：100 只/问题最稳（与行业采集经验一致）
- **代码格式**：`000001.SZ / 600000.SH / 920000.BJ`

## 数据结构设计

### 1. 原始层（按批落盘 CSV，便于审计与重跑）

`F:/stock_data/vendor_wind_st_status/raw/`

- `st_implement_batch_0000.csv`：实施 ST 原始响应
- `st_revoke_batch_0000.csv`：撤销 ST 原始响应

### 2. 合并层（低频全量覆盖 parquet）

`F:/stock_data/vendor_wind_st_status/st_implement.parquet`

| 列 | 类型 | 说明 |
|---|---|---|
| code | str | `000001.SZ` 规范形 |
| name | str | 当前证券简称 |
| st_after_name | str | 实施 ST 后简称 |
| st_before_name | str | 实施 ST 前简称 |
| st_date | date | 实施 ST 日期 |
| reason | str | 实施 ST 原因 |
| pulled_at_utc | str | 采集时间 |
| source | str | `wind:kimi-datasource` |

`F:/stock_data/vendor_wind_st_status/st_revoke.parquet`

| 列 | 类型 | 说明 |
|---|---|---|
| code | str | `000001.SZ` |
| name | str | 当前证券简称 |
| revoke_date | date | 撤销日期 |
| after_revoke_name | str | 撤销后简称 |
| before_revoke_name | str | 撤销前简称 |
| pulled_at_utc | str | 采集时间 |
| source | str | `wind:kimi-datasource` |

### 3. 派生层

`F:/stock_data/vendor_wind_st_status/st_intervals.parquet`：ST 区间表

| 列 | 说明 |
|---|---|
| code | |
| name | 最新简称 |
| st_kind | `st` / `star_st` / `delist` / `other`（由简称/原因推断） |
| start_date | ST 生效日期 |
| end_date | 撤销日期（未撤销则为空） |
| reason | 实施原因 |

`F:/stock_data/vendor_wind_st_status/st_daily.parquet`：每日 ST 状态矩阵

| 列 | 说明 |
|---|---|
| trade_date | |
| code | |
| is_st | bool |
| st_kind | str / None |
| name | 当日简称（如可知） |

## 采集任务

1. **代码清单**：从 `~/.qlib/qlib_data/my_data/instruments/all.txt` 取全市场代码（5583 只）
2. **分批**：每批 100 只，约 56 批；每批分别问实施与撤销两个问题
3. **落盘**：原始 CSV 按 `raw/st_{implement,revoke}_batch_{NNNN}.csv` 保存
4. **合并**：脚本读取全部 CSV → `st_implement.parquet` / `st_revoke.parquet`
5. **派生**：
   - 按 code 合并实施/撤销记录，生成 `(code, start_date, end_date)` 区间
   - 对无撤销记录的最新 ST，end_date 留空
   - 展开交易日历生成 `st_daily.parquet`
6. **校验**：
   - 抽查已知 ST 股的区间与交易所公告一致（例：000504.SZ 2025-04-30 实施 *ST，2026-06-12 撤销）
   - 每日矩阵行数 = 交易日数 × 全市场代码数

## 日常更新（已改，不消耗 Kimi）

每周或每个交易日盘后在 **OSkhQuant1.3**（本机、无额度）：

```text
D:/anaconda3/envs/vanna312/python.exe -m oskh_data.vendor_wind_st pull-szse-namechange
D:/anaconda3/envs/vanna312/python.exe -m oskh_data.vendor_wind_st merge
```

本仓只读 `F:/stock_data/vendor_wind_st_status/st_daily.parquet`。

- 深市：深交所「简称变更」一张表覆盖全部 PIT 戴帽/摘帽
- 当前 ST：东财风险警示板快照；其中尚未被 PIT 覆盖的沪/京代码写入
  `snapshot_fallback_wind_codes`（质量等同静态黑名单，只补漏）
- 不要再对深市打 Wind 实施/撤销

## 2026-09-14 断点（Kimi 额度用尽后）

已落地（`F:/stock_data/vendor_wind_st_status/`）：

- 深交所简称变更 7479 行 → 实施 869 / 撤销 676；覆盖深市 A 股 3077 只
- Wind 实施批 42/56（0027/0028 已标空；缺 0035、0037、0044–0055，均为沪/京）
- Wind 撤销批 0/56（深市已不需要；沪/京摘帽约 43 只为 `unknown_end`，回退静态名单）
- `st_daily.parquet` 稀疏约 26 万行（日历 2020-01-02～2026-09-14），末日 ST ≈ 262 只
- 抽查：000504.SZ 2025-04-30 戴帽、2026-06-12 摘帽，与任务书用例一致

额度恢复后 **只补沪/京**（约 14 个实施问题串 + 对应撤销）：

- 实施缺批：`0035, 0037, 0044, 0045, 0046, 0047, 0048, 0049, 0050, 0051, 0052, 0053, 0054, 0055`
- 撤销：只跑上述批次的 `q_st_revoke_*.txt`（不要从 0000 全量重打）
- 0027/0028 不要重试
- 每批仍用 `wind` / `wind_get_financial_data`，`file_path` 指向
  `F:/stock_data/vendor_wind_st_status/raw/st_{implement,revoke}_batch_{NNNN}.csv`
- 遇到 403/额度立刻停；「没找到数据」写成仅表头的空 CSV
- 全部补完后再跑本机 `merge`

## 消费端任务（MyQuant）

1. `build_tradable_universe.py` 增加 `--st-daily-file`：读取 `st_daily.parquet`，按 as-of 日期过滤当日 ST
2. `buy_eligibility.py` 的 `BuyEligibilityFilter` 支持从每日矩阵加载 `st_codes_of_date`
3. 训练/回测统一使用 PIT ST 过滤，替代静态 177 只黑名单
4. 保留静态黑名单作为 fallback（无数据日或新增未覆盖股票）

## 纪律与注记

- 三件套落地前，本 PR 的开关实验按静态近似先跑；落地后重跑对比
- 数据消费规则：日期 T 的过滤只能用 `trade_date <= T` 的数据，禁止前视
- 额度敏感：全市场 Wind 一次约 112 次计费调用。深市已改交易所公开表，剩余约 14×2 次
- 消费：`rebacktest_cost_tiers.py --st-filter --st-daily-file F:/stock_data/vendor_wind_st_status/st_daily.parquet`

## 来源分目录（2026-09-14 起）

目录名必须等于来源，不要再把深交所 / 巨潮 / 东财写进 `vendor_wind_*`。

| 来源 | 根目录 | 状态 |
|---|---|---|
| Wind / Kimi | `F:/stock_data/vendor_wind_st_status/` | 旧批次与当前合并 PIT 仍在这里；不再往里塞新源 |
| 深交所简称变更 | 将来 `F:/stock_data/vendor_szse_st_status/` | 现文件暂在 wind 目录的 `raw/szse_namechange*.csv`；迁目录等下次 merge |
| 巨潮公告 | `F:/stock_data/vendor_cninfo_st_status/` | **1.3 仓库实施**，见下方交接 |
| 东财风险警示板 | 将来 `F:/stock_data/vendor_eastmoney_st_status/` | 现快照若有，也不要再叫 wind |
| 合并 PIT | 将来 `F:/stock_data/st_status/`（无 vendor 前缀） | **1.3 写出**；本仓与 backtrader 只读 |

**1.3 下载并写湖；本仓与 MyQuant-backtrader 只消费。** 不在本仓新写拉取或 merge。

巨潮回填交接（打开 1.3 的 agent 实施；本仓只读产物）：

`E:/PycharmProjects/OSkhQuant1.3/docs/engineering/handoff-cninfo-st-status-harvest-2026-09-14.md`

1.3 写 `vendor_cninfo_st_status/`，文件名带 `cninfo`。本仓用 `--st-daily-file` 指向 1.3 写好的消费文件，不再 merge。
