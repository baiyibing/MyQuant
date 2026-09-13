# 任务书：M3-D 实现片——截面行业/市值中性化 → TopN（中期计划收官）

- 日期：2026-09-13
- 上游：`docs/plan-midterm-m1m4m2m3-2026-09-13.md` §4 M3-D；行业源已复核（路线图 §0.2，`wind_crosscheck.json` 一致率 1.0）
- 约束沿用中期计划 §0（全量测试门槛，基线 **137 passed + 18 subtests**；host_env；CI 绿才合）
- 这是中期计划**最后一片**

---

## 定位（先钉死，防走样）

中性化只作用在**排序侧**：`pred 打分 → 截面中性化 → TopN → 导出`。
不动 label、不动特征、不动 infer 链、不动成交、不改 `--asof`、不改 topk 默认。
依据：路线图 §1.1「Qlib 里只变怎么排序、怎么出名单，不变成交」。

## 输入

| 项 | 来源 | 说明 |
|---|---|---|
| 行业映射 | `exports/m3d_industry/sw_l1_map.csv`（已入 git，wind 100% 复核） | 列 `code_qlib,code_gildata,name,sw_l1`；用 `code_qlib`（SZ300190 方言，与 pred 对齐）；31 个申万一级 |
| 市值 | **bin-16 现场推导**：`$close × $adfadfbasiccurhold` ≈ 自由流通市值 | 无外部市值源；取对数用。**必须过验证门**（见 M3D-B） |
| pred | 现有两份：`预测结果.csv`（16 日三月窗）/ `预测结果_ext.csv`（132 日长窗） | 宿主持有，测试用 fixture |

## 切片

| 片 | 内容 | 验收 |
|---|---|---|
| M3D-A | `my_scripts/ranking_neutralize.py` 纯模块：① `industry_demean(scores, sw_l1)`——按日截面、行业内去均值（行业缺映射的样本保留原分并计数）② `size_residual(scores, log_float_cap)`——按日截面 OLS 回归取残差（NaN 市值样本保留原分）③ `industry_size_neutral` 组合（先行业后市值或正交一次，实现者定并注释）；`--method industry/size/both` | 合成 fixture 单测：已知构造下残差行业均值≈0 / 与规模相关≈0；缺映射/NaN 旁路计数正确；方言转换（SZ300190↔映射表）单测 |
| M3D-B | 市值推导验证门 `verify_float_cap()`：NaN 率 <1%；**秩合理性**——推导市值与 `$amount` 的日截面秩相关中位数 > 0.5（流通市值与成交额强相关是常识锚）；对照若干已知大盘股（如 600519）排名靠前 | 单测（fixture 构造强相关/弱相关两组，验证门放行/拒绝）；不过门则 size 方法标 blocked 保留 industry 方法 |
| M3D-C | 导出接线：`export_daily_pool.py` 增 `--industry-map <csv>` `--neutralize industry|size|both`（缺省**不开**，现行为完全不变）；中性化在 TopN 截取**之前**；产物字节契约不变（LF/裸六位），export manifest 的 config 记录中性化方法 | 契约测试扩一例中性化路径；缺省路径回归不变 |
| M3D-D（宿主） | 两窗实跑对比：三月窗 + 长窗，各出 raw vs industry vs size vs both 四列名单——对比表（与 raw Top10 的日重叠率、名单月度换手变化、命中率/IR 借 sweep 指标口径） | 宿主跑完回写路线图 §0.2 |

## 判读纪律（预锁，防事后挑方法）

1. **映射是当前时点分类**，回贴历史窗存在幸存者/重分类偏差——排序实验可接受，结论措辞必须带此脚注；不引入「点时行业史」的伪造精确
2. 中性化是否被采纳 = **两窗同向**（三月经、长窗也经，或反之）：单窗改进不算数（M3-C/OOS 双重教训）
3. 预期管理：TopN=10 下，中性化只有当 pred 在少数行业高度集中时才会实质换名单——**先量集中度再谈效果**；若日重叠率 >80%，结论就是「中性化不改变本模型名单」，同样是有效终点
4. 禁止说法：「中性化后模型更强」（未过两窗门）、「该改 topk」、任何 NAV 判优

## 明确不做

- 不动 label/特征/infer/成交/as-of/topk 默认；不造点时行业史；不接外部市值源（M3D-B 过不了门就 blocked，不硬凑）
