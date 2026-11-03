# P11：ETF E3/E4 本机验收

状态：**PASS，关闭固定历史窗口的隔离 provider E3/E4 冒烟验收**。实现提交 `3e4c992b444480071100fbd1fb9ea3f8717320c9`；后续仅整理回执。没有切换默认 provider，也没有策略收益或 paper/live 准入结论。

历史 E3 使用 2020-01-02～2026-10-13 窗口：1640 个交易日、`all=1629`、`etf_full=573`。本次重新核验全部 **11406** 个文件指纹，并对 SH510050、SH510300、SZ159915、SH518880 的 open/high/low/close/volume/amount/vwap 做完整窗口读回，均与冻结 staging 一致。[E3 复核](e3-revalidation.json)单列实时湖八个抽样文件在补数后的变化；不把这个冻结 provider 说成最新湖快照。

旧 E4 仅留下文本 IC，未保存逐行预测/标签。同时，[真实边界反例](boundary-before.json)确认训练、验证段末尾八条抽样标签使用了下一分段的价格；旧代码只在算 IC 时过滤，没有从拟合与 early stopping 输入排除。本次修正实际 DatasetH 边界，并检查真实 prepared learn 日期。旧 IC 0.0433548 保留为历史结果，未用于新验收。

| 分段 | 名义范围 | 实际 DatasetH 范围 | 有效预测/标签 | 独立复算 IC | Rank IC |
|---|---|---|---:|---:|---:|
| train | 2020-01-02～2024-12-31 | 2020-01-02～2024-12-27 | 583700 | 0.1954368703 | 0.1043681036 |
| valid | 2025-01-02～2025-12-31 | 2025-01-02～2025-12-29 | 137826 | 0.0520968728 | 0.0218612420 |
| test | 2026-01-05～2026-10-13 | 保持名义区间，验收排除跨界/未定义标签 | 104772 | 0.0435218051 | 0.0169925865 |

只跑一个 LightGBM，最多 80 轮，8 线程，early stopping 选中第 16 轮；[实际运行参数](invocation.json)直接读自本次 MLflow 记录。官方 Alpha158、标签 `Ref($close,-2)/Ref($close,-1)-1`、#107 已合入的宇宙及名义切分不变；特征处理器仍只在 2020～2024 拟合。指标是有限样本上的**合并 Pearson / Spearman**，不是逐日 IC 均值，不证明策略盈利。front 复权和末日筛选的研究偏差继续保留。

每段已保存逐行 prediction、raw label、边界/有限值/接受掩码及 SHA256。独立验证器没有复用生产 mask 函数，重新推导未来两个交易日、检查掩码、读取 Parquet 并复算三段样本数与指标；结果逐项一致。训练后再次核对 11406 个 provider 文件和受保护目录锚，均未变化。[宿主验收](acceptance.json)、[运行回执](run-receipt.json)、[IC 文本](ic_report.txt)。原始 Parquet、MLflow、provider 和 staging 仅保留本机，不入库。

`--write-acceptance-artifacts` 为显式开关，要求新的输出目录，并在训练前拒绝与股票/ETF provider 重叠的路径。写盘失败、有效样本不足或非有限 IC 不会生成 PASS 的单模型回执。多模型若部分成功仍可 exit 0，但 JSON 为 PARTIAL；读取方必须检查回执状态。

验证：四个受影响 ETF 测试文件 **34 passed**；仓库 CI 的六文件 data-staging 选择 **68 passed**；Ruff 通过。[方案复核](plan-review.json)在编码之前，[固定提交实现复核](implementation-review.json)与[宿主证据复核](evidence-review.json)均为 APPROVE。实际复核工具为 Claude Code CLI 2.1.317，沿用本机配置的 **GLM-5.3**，未冒称原生 Anthropic 模型。Pyright 不是 MyQuant 已配置门禁，额外探索调用因父工作树/导入解析范围失败，没有记为通过。

复现命令（使用本机约定的 vanna312；`<new-out>` 必须不存在）：

```text
python -m pytest -q tests/test_build_etf_qlib.py tests/test_etf_daily_qlib_offline_smoke.py tests/test_stage_1min_from_lake.py tests/test_stage_etf_daily_from_lake.py tests/test_train_etf_smoke.py tests/test_ql11_1min_increment_receipt_harness.py
python my_scripts/train_etf_smoke.py --qlib-dir <isolated>/my_data_etf --out-dir <new-out> --models lgb --num-boost-round 80 --write-acceptance-artifacts
```

本目录三个 `.py` 是该次本机审计脚本原件，依赖 [validation.json](validation.json) 记录的原 audit-root 相对布局，不是新的生产入口。`calendar.json` 是语义日历导出；原 provider、原始本地文件、运行时 CRLF 源码与发布 UTF-8/LF 文件分别记录 hash。[publication-sha256.json](publication-sha256.json) 只校验本目录发布字节。P12/QL11 真机分钟增量、后续模型比较及新窗口 provider 不由此关闭。
