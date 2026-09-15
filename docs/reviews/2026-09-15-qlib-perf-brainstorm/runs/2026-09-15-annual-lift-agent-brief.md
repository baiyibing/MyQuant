# Agent 施工单 · MyQuant 研究年化再抬一截（2026-09-15）

**目标**：在本仓把研究侧年化/超额再抬一截（出表、出诊断、必要时写小脚本）。**不是**改线上默认、不是谈上线。  
**终裁**：`docs/reviews/2026-09-15-qlib-perf-brainstorm/SYNTHESIS-r2-live.md`  
**本机根目录**：`D:\PycharmProjects\MyQuant`（Windows newtest_4090）

---

## 今日已有锚点（勿重训除非本单要求）

| 臂 | topk/n_drop | recorder | manifest | 分析包 |
|----|-------------|----------|----------|--------|
| A | 10/3 | `907edbfbd9ae48b0b5d8828626ec4476` | `manifests/train_20260915T061116Z.json` | `exports/analysis/907edbfbd9ae48b0b5d8828626ec4476/` |
| B（主） | **50/5** | `8a061ea428e04bb3a199a485ade49d0e` | `manifests/train_20260915T055308Z.json` | `exports/analysis/8a061ea428e04bb3a199a485ade49d0e/` |

- 窗：`test=2026-01-01:2026-09-14`；`buy_state_filter_on=false`，`exclude_filter_on=false`（买资/排除关）；`limit_up_filter_on=true`
- 用户报 qlib 默认超额：10/3 **+3.0%**，50/5 **+11.8%**（方向：宽名单更好）
- **两趟是不同 train/recorder**（git tip 也不同）→ **禁止**当「同 pred 宽度扫」；正式宽度因果要用**同一 pred** 重扫或只用 B 的 pred 做下游

优先用 **B（50/5）** 的 `pred.pkl` 做诊断。

---

## 派工顺序（可并行的已标）

### 工单 1 · P0-3 有效秩深（主，先做）

**谁跑**：任意能读写本机 MyQuant 的 coding agent  
**做什么**：

1. 从 recorder `8a061ea4…` 加载 `pred.pkl`（及需要的 label/次日收益）。
2. 对每个交易日：按 score 降序，在**当时可交易/未排除宇宙**上算：
   - 名义 `k_req=50`
   - 实际可填 `k_fill`
   - 若有 walk-down / 回填：回填只数、回填天数
   - `rank_max`（当日入选最深名义秩；定义写进表头）
3. 汇总：`rank_max` **P50/P90**、`k_fill<k_req` 日占比、回填天数分布。
4. 输出 CSV + 一页 Markdown 结论到：
   - `docs/reviews/2026-09-15-qlib-perf-brainstorm/runs/2026-09-15-p0-3-rank-depth-50n5.md`
   - 同目录放 `*.csv`

**成功判据**：

- 表能回答：「名义 50 时，有效宽度是否长期 ≪50？」
- 写出门检一句：若 `rank_max` P90>80 **或** 回填日占比>10% → 标记 `P1-5_WIDTH_SWEEP_DEFER`（宽度细扫降级）

**不要做**：改 topk 默认；开过滤默认；重训模型（除非 pred 缺失且无法从 recorder 取）。

---

### 工单 2 · P0-4 头部分段毒尾（与工单 1 同 pred，可同 PR）

**输入**：同一 `8a061ea4…` pred（禁止混用 10/3 recorder）

**做什么**：

按日把名单按预测秩切成 **1–10 / 11–20 / 21–50**（不足则标明），对每段报：

- 次日命中率（或等权次日收益）
- 相对等权超额（若可得）
- 负尾（最差分位 / 亏损贡献）
- 尽量拆：**新买入 vs 已持仓留存**（有 `positions_daily` / `trades_daily` 就拆；没有就注明缺）

可用已有分析包：

- `exports/analysis/8a061ea428e04bb3a199a485ade49d0e/{daily_picks,positions_daily,trades_daily,nav_daily,pnl_by_stock}.csv`

输出：

- `docs/reviews/2026-09-15-qlib-perf-brainstorm/runs/2026-09-15-p0-4-toxic-tail-50n5.md` + CSV

**成功判据**：明确一句「下一刀倾向 **加宽** / **改信号（头部毒）** / **换手/持仓路径**」；不得只报全池年化。

---

### 工单 3 · 三档成本补报（可与 1/2 并行）

**输入**：同一 50/5 pred / recorder `8a061ea4…`（或等价 PortAna 重跑，**不改策略参数**）

**做什么**：在**同一窗、同一名单逻辑**下报：

| 成本档 | open/close | 年化或超额 | 回撤 |
|--------|------------|------------|------|
| zero | 0/0 | | |
| qlib_default | 0.0005/0.0015 | | |
| realistic | 仓内现行 realistic 定义（写版本号） | | |

输出：`.../runs/2026-09-15-cost-tiers-50n5.md`

**成功判据**：三档同表；写清「研究档好看 ≠ 现实档」；若现实档相对 zero 缺口折合换手成本 >20% 年化，打标签 `COST_GAP_EXECUTION`（下一步做换手分解，**禁止**单窗拧 n_drop 救）。

可参考：`my_scripts/rebacktest_cost_tiers.py`。

---

### 工单 4 · 同 pred 宽度对照（可选，工单 1/2 后）

**目的**：补上「今日 10/3 vs 50/5 异 train」的洞。

**做法**：只用 **B 的 pred.pkl**，离线模拟 topk∈{10,20,30,50}×n_drop∈{3,5}（过滤状态与 B 一致），出超额表。  
**不要**再开两趟完整 handler_init 除非 pred 不够长。

输出：`.../runs/2026-09-15-same-pred-width-grid.md`

---

### 工单 5 · 弱/强窗预锁跑（工单 1–3 有结论后再派）

**参数冻结**：与 B 相同（50/5、过滤开关一致、成本三档都报）

| 窗 | 角色 | 段建议（可按仓内日历微调，但须写入报告） |
|----|------|------------------------------------------|
| 2025 全年或 HOST 指定验证段 | **弱窗** | 早停已见 valid → 证据降权 |
| 2026-04-01～2026-08-31 | **强窗** | OOS 向 |

**失败标签**（二选一写死）：`WINDOW_DEPENDENT` | `COST_STRUCTURE_UNSAVEABLE`

**成功**：强窗与今日窗同号同排序（相对 10/3 或相对零宽基线）；弱窗允许弱，但须标注「仅一强窗」。

---

## 全局禁止（研究抬年化时也禁止）

- 把今日 +11.8% 与旧过滤开 +9.1% **相加**讲故事（异 recorder）
- 单窗拧 n_drop/hold「救」现实档
- 下调 realistic 假设让策略转正
- 路径依赖逻辑塞进 Qlib
- 无声改成先滤后排当默认
- 为省事换 PyPI qlib / 改 kernels 冲吞吐（那是 eng-perf 另一册）

---

## 交付给 Host 的格式

每个工单结束时回一条：

1. 产物路径（md/csv）
2. 三句结论（秩深 / 毒尾归因 / 成本缺口）
3. **建议的下一刀**（加宽 | 改信号 | 换手分解 | 开多窗）+ 依据表单元格
4. 未做项与缺文件清单

---

## Host 一句话优先级

**先派工单 1+2（同 pred 50/5）→ 3 成本三档 → 再决定 4/5。**  
抬年化的杠杆在「看清亏在哪一段」，不在再开一趟异 seed 的 topk50。
