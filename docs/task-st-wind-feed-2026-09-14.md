# 任务书：ST 历史 PIT 数据集（Wind × Kimi datasource → F 湖 → MyQuant 消费）

- 日期：2026-09-14
- 背景：zcode 的 QMT 逐码采集方案因速度不可行（~0.5s/只，单日全市场 46 分钟）被停止；本方案改用 **Kimi datasource 的 Wind 接口**批量获取 A 股 ST 实施/撤销历史，构建本地 PIT 数据集。
- 状态：已验证 Wind `wind_get_financial_data` 可返回：
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

## 日常更新

- 每周一次全量刷新（56×2 次调用）
- 或每日盘后对当日有 ST 公告的股票增量更新（需配合公告源，先以周刷新为主）

## 消费端任务（MyQuant）

1. `build_tradable_universe.py` 增加 `--st-daily-file`：读取 `st_daily.parquet`，按 as-of 日期过滤当日 ST
2. `buy_eligibility.py` 的 `BuyEligibilityFilter` 支持从每日矩阵加载 `st_codes_of_date`
3. 训练/回测统一使用 PIT ST 过滤，替代静态 177 只黑名单
4. 保留静态黑名单作为 fallback（无数据日或新增未覆盖股票）

## 纪律与注记

- 三件套落地前，本 PR 的开关实验按静态近似先跑；落地后重跑对比
- 数据消费规则：日期 T 的过滤只能用 `trade_date <= T` 的数据，禁止前视
- 额度敏感：全市场一次约 112 次计费调用；建议分阶段提交进度
