# M3-C 特征实验（bin-16 only）

- 日期：2026-09-13
- 代码：`my_scripts/feature_experiments.py`
- 约束：仅用 bin 16 字段可算特征；NaN<1% 入围；单窗 IC / ICΔ；**不要求**本 PR 合入前全量重训

## 字段白名单

`adjclose amount basiccurhold adfadfbasiccurhold bigddx change close factor high low netcsfree open volddx volume vwap zhangting`

## 候选特征

| feature | 公式（近似） | 备注 |
|---------|--------------|------|
| turnover_approx | volume / (adfadfbasiccurhold+eps) | 换手近似 |
| turnover_resist_approx | sum_5(volume)/sum_20(volume) | **不是** BT cyq；M2 已判不可比 |
| amount_per_volume | amount/(volume+eps) | 流动性/均价代理 |
| volddx_zscore | rolling z-score($volddx)；warm-start=0 | 筹码流字段 |

## 合成窗结果（VM `--demo-synthetic`，非宿主真实 bin）

| feature | nan_rate | qualifies | ic | ic_delta |
|---------|----------|-----------|-----|----------|
| turnover_approx | 0 | True | ~0.27 | ~0.27 |
| turnover_resist_approx | 0 | True | ~0.08 | ~0.08 |
| amount_per_volume | 0 | True | ~-0.10 | ~-0.10 |
| volddx_zscore | 0 | True | ~0.00 | ~0.00 |

合成 label 与 turnover 相关，故 `turnover_approx` IC 为正属预期，**不能**外推为生产结论。

## 宿主待办

1. 用真实 `~/.qlib` bin 抽一窗跑 `run_feature_screen`
2. 入围特征再进 M3-B sweep / 合批重训看 IC/IR
