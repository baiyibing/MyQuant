# 任务书：ST 名称 + 上市日期 + 获利盘三件套数据集（QMT 采集 → F 湖 → MyQuant 消费）

- 日期：2026-09-14
- 背景：全市场长窗实验（`docs/qlib-fullmarket-longwindow-report-2026-09-14.md`）新增四个买入
  过滤开关，其中 ST 名单与上市日期目前用静态近似（`train_wiring.EXCLUDE_STOCKS_DEFAULT`
  177 只 + all.txt 起始日），盈筹率用时间无权 Quantile 近似。探明：
  - F 湖**无** ST 名称/上市日期数据集（`OSkhQuant1.3/oskh_core/board_limit.py` 自述 "no name feed"）
  - 采集通道现成：`hkcodex_miniqmt.get_stock_chinese_name(codes, day=历史日)` 支持 as-of；
    `_ST_RISK_NAME_RE` 正则已在 `scratch_verify_st2.py` 用例验证（全角＊/SST/退市/XD 排除）；
    上市日期在 `get_instrument_detail`（OpenDate 字段）
  - F 湖已有 `vendor_qmt_winner_chips.parquet`（winner_ratio=QMT 获利盘比例），但仅
    2026-03-18~27 八个交易日全量 + 09-08 零星 3 行，**采集已中断**；且有脏值（-1.0 / 2.95）
- 分工：采集端 = **OSkhQuant1.3**（QMT 依赖在其侧）；消费端 = MyQuant（开关已就位，接线为辅）

## 数据集设计（F 湖 vendor 风格，原子分区）

### 1. `F:/stock_data/vendor_qmt_st_names/date=YYYYMMDD/data.parquet`

| 列 | 类型 | 说明 |
|---|---|---|
| stock_code | str | 规范形 `000001.SZ`（对齐 vendor_qmt_winner_chips） |
| name | str | as-of 当日证券简称（QMT 原文） |
| is_st_risk | bool | `_ST_RISK_NAME_RE` 判定（*ST/ST/S ST/SST/退市整理/退） |
| st_kind | str | 命中类别（`st` / `star_st` / `sst` / `delist` / 空串） |
| asof_day | str | 名称的历史基准日 `YYYYMMDD`（正常=当日；回填=历史日） |
| pulled_at_utc / client_ver / source | | 沿用 vendor_qmt_winner_chips 既有约定 |

每日全量一行一股（~5580 行），**as-of 当日收盘名称**（非最新名——PIT 语义关键）。

### 2. `F:/stock_data/vendor_qmt_instrument_meta/data.parquet`（低频全量覆盖）

| 列 | 说明 |
|---|---|
| stock_code / name | 同上 |
| open_date | 上市日期 `YYYYMMDD`（get_instrument_detail OpenDate） |
| instrument_status | QMT 状态字段原文 |
| pulled_at_utc | |

每周刷新一次即可（上市日期不变）。

## 采集端任务（OSkhQuant1.3）

1. 新脚本 `scripts/data/pull_vendor_qmt_st_names.py`：仿 `pull_vendor_qmt_metrics.py`
   结构——全市场代码清单 → `get_stock_chinese_name(codes, day=T)` → 正则判别 → 原子落盘；
   `--day YYYYMMDD` 支持历史回填，`--asof-today` 为日常入口
2. `pull_vendor_qmt_instrument_meta.py`：全市场 detail 一次拉齐 open_date（低频）
3. **回填**：利用 day= 历史 as-of，补 2020-01 ~ 2026-09 每周五一个采样点（~350 个交易日
   快照，PIT 评估够用；winner_chips 如需回填另行评估 QMT 历史接口能力）
4. **日常更新**：每个交易日 15:10 定时跑当日快照；失败重试与告警对齐仓内既有 drill 风格
5. winner_chips 恢复日常采集（同管道），落盘前加清洗：winner_ratio ∉ [0,1] → 置 NaN +
   quality_flag（负值/超 1 疑似 QMT 对无历史成交股的哨兵值，先标记不清数）

### 验收

- [ ] 连续 3 个交易日快照齐全、行数≈全市场股数、原子写无半文件
- [ ] 回填快照抽查：戴帽/摘帽股在帽期前后 is_st_risk 翻转正确（例：真实 ST 变动案例 ≥2）
- [ ] open_date 抽查 5 只与交易所公告一致
- [ ] winner_chips 新数据全部 ∈[0,1] 或带 quality_flag

## 消费端任务（MyQuant，本 PR 开关已就位后的接线增强）

1. `build_tradable_universe.py --st-file`：接 `vendor_qmt_st_names` 最新 asof 的
   is_st_risk 名单（替代静态 177 只）；`--listing-file`：接 open_date（替代 all.txt
   起始日近似，消除"2019-12 上市被当老股"误差）
2. `buy_eligibility` 盈筹率精确化（开关①升级）：优先读
   `vendor_qmt_winner_chips.winner_ratio`（清洗后）；Quantile 近似降级为无数据日的回退；
   两口径差异进报告注记
3. 回测 PIT 消费规则：日期 T 的过滤用 `asof_day <= T` 的最近快照（禁止用未来快照）

## 判读与纪律

- 三件套落地前，本 PR 的开关实验按静态近似先跑（结论标注局限）；落地后重跑一轮对比
  静态/真值两版差异，差异显著则修正此前结论
- 不因数据升级改动 topk/线上默认（预锁纪律不变）
