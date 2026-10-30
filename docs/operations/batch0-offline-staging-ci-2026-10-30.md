# 批次 0：ETF/分钟 staging 离线测试接入 CI

对应三仓统一计划 P01 / QL01、批次 0B（BT #539）。既有测试已合入，但原 CI 只显式执行 joint-return、my_tests 和涨停过滤测试，遗漏本轮五文件。

新增 `data-staging` 作业：Ubuntu / Python 3.12，安装 pytest、numpy、pandas、pyarrow，显式执行：

- `tests/test_build_etf_qlib.py`
- `tests/test_etf_daily_qlib_offline_smoke.py`
- `tests/test_stage_1min_from_lake.py`
- `tests/test_stage_etf_daily_from_lake.py`
- `tests/test_train_etf_smoke.py`

这些测试使用仓内 synthetic fixture 和临时目录；训练文件仅测试 IC/标签边界等函数。作业不安装 Qlib，不读取目标机 provider，不启动训练或写行情湖。真实 ETF E3/E4 继续按原计划验收。

本机 vanna312：以上五文件共 **28 passed**。由于工作树位于另一仓库下，本地用 `-c pyproject.toml --confcutdir .` 明确本仓测试边界；避免继承父仓的 pytest 临时目录设置。GitHub 作业在仓库根执行原始命令，无该嵌套目录因素。最终 CI 以本 PR 最新 head 的 `data-staging` 作业为准。

关闭步骤：此 PR 合入且新作业通过后，在 BT 统一索引追加仅覆盖 QL01 的回执；不关闭整个 P01。
