# QL16：旧 L2 A/B 已合状态回写

本片只修正 MyQuant 两页的状态漂移。旧任务书正文保留，路线图的“L2 未开工”改为 A/B 的已合事实；QL16/P20 均未关闭。

## 原域证据

| 片 | 已合证据 | 合法结论 |
|---|---|---|
| A | 1.3 [#1024](https://github.com/baiyibing/OSkhQuant1.3/pull/1024)，merge `6fceccc64f45919476c14aa4322046e66b142a3e`，2026-09-14 05:41:45 UTC；[冻结 run-record](https://github.com/baiyibing/OSkhQuant1.3/blob/6fceccc64f45919476c14aa4322046e66b142a3e/docs/run-records/2026-09-14-l2-a-lebs-csv-v5-smoke.md) | 20260303–20260908 的历史 LEBS csv_v5 冒烟，131 日名单加载；不产生策略结论 |
| B | 1.3 [#1025](https://github.com/baiyibing/OSkhQuant1.3/pull/1025)，merge `1ee04a9be370640053800713c12f7bee48d7d730`，2026-09-14 06:06:01 UTC；[冻结 run-record](https://github.com/baiyibing/OSkhQuant1.3/blob/1ee04a9be370640053800713c12f7bee48d7d730/docs/run-records/2026-09-14-l2-b-csv-v5-reconcile.md)及[四维统计](https://github.com/baiyibing/OSkhQuant1.3/blob/1ee04a9be370640053800713c12f7bee48d7d730/docs/backtest/reports/l2_reconcile_pred_v5/reconcile-four-dims.json) | 名单 131/131 一致；reason、可卖股和涨跌停保留原报告的差异与归因，记录差异清单后合法关门；不代表两引擎规则完全一致 |

B 的限制继续有效：BT 日线无强制卖与 LEBS 合成 14:50 时钟不同，front/none 与暖机不同，涨停 skip/chase 不同，不足一手补单也不同。本次不重跑历史湖、不重新签收当前引擎，不以净值或 reason 匹配率定 C 门。

## 未关闭边界

C 晋升门数值及 D 旧 csv_v5 研究晋升线保留或归档仍待人裁。当前 v653/turtle paper 属于不同策略的验收，不能替代旧 D。旧任务书的 D 命令不是本次运行授权；不复活已退役 csv-live。

本次只完成本仓 E 的状态回写部分，不宣称 1.3 / BT 的 E 或整个 QL16/P20 完成。这里的“L2”是 2026-09-13 研究名单晋升线，不是 BT 的离线 `l2_analytics/`，也不是新的执行后端。

## 验证与发表

[facts.json](facts.json) 记录固定 PR/head/merge、原域 Git LF 哈希、四维统计与保留边界。[validation.json](validation.json) 记录原任务书字节保留、路线图单句修改、UTF-8 / NUL / 链接 / diff 检查；[publication-sha256.json](publication-sha256.json) 为 Git LF 发表哈希（不自包含）。文档片无生产代码、默认值或数据变化，不重跑模型或宿主；独立固定 head Grok 复核及 canonical CI 由合入线验收。
