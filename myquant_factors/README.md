# 因子实现归属

2026-11-09 用户裁定：BT 不再作为因子算法 SSOT。本包先接收原 BT
筹码分布、换手系数、TR、价格带和周线 MACD 背离实现，包含 Rust 源码。
原来的研究扫描、IC/效果验证、抽样诊断和 TR 研究入口也迁入
`research/`；命令入口在 `my_scripts/factor_research/`，迁移清单见
`examples/chip_research/entrypoint-migration.json`。

MyQuant 负责因子定义、计算实验、效果验证、Qlib 训练和信号导出。
infra 负责数据采集、清洗、聚合和对消费者交付的因子数据产制。
是否转为 infra 数据产品按交付职责判断，不按“成熟”或消费者数量判断。
本次先归并实现，不启用批量产制或调度；已经在 infra 的 CYQ feeder、
TR Store IO、行情读取和股本/复权数据处理继续调用 infra。

`myquant-research-factors` 只安装 `myquant_factors`。Notebook、训练工作流、
Qlib handler 和模型配置不随包安装给 BT。BT 通过固定源码提交依赖本包，
只保留 import 转发及宿主路径、reader 生命周期、时钟与门禁适配。
包内禁止反向导入 BT、读取相邻 BT 源码或提供缺依赖时的本地副本。

独立研究入口需要显式设置 `OSKH_SOURCE_PARQUET_ROOT`、`OSKH_DATA_ROOT`；
直接导入研究脚本时另设 `MYQUANT_RESEARCH_ROOT`。原有显式研究参数与
数值规则保留；迁移没有授权重跑训练、读写真实行情湖或发布新名单。

Rust 构建在 `myquant_factors/rust/turnover-resist` 内执行
`cargo build --locked --release`。桥接层可通过 `TURNOVER_RESIST_EXE`
消费显式指定的产物，也支持 `CARGO_TARGET_DIR`。BT 不再留 Rust 源码。
纯 Python 数值测试和无数据的 Rust 编译检查由 MyQuant CI 承担。
