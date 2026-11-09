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

同日 Human 澄清：回测策略的条件组合、参数、交易日映射和实验名单导出可归 BT。
策略 9/10/11/13 与 App ∩ Qlib 的回测专用名单脚本保留 BT，不作为迁出欠账；
Qlib 模型预测仍由 MyQuant 提供，不要求所有名单都由本仓生成。

公共计算按同一口径只保留一份权威实现，多个仓经同一 API/包复用，不复制、vendor
或另写等价实现。当前已迁出的筹码/TR 核由本包共享。若后续归并到 infra，整项
迁移并删除旧实现，只留必要转发；不同研究变体须显式参数化或标明方法/版本。
同一共享组件内部可维护参考实现与 Rust/Numba 加速后端，须共用合同并做数值对拍；
消费者调用同一组件，不各自维护一套后端副本。

`myquant-research-factors` 只安装 `myquant_factors`。Notebook、训练工作流、
Qlib handler 和模型配置不随包安装给 BT。BT 通过固定源码提交依赖本包，
只保留 import 转发及宿主路径、reader 生命周期、时钟与门禁适配。
包内禁止反向导入 BT、读取相邻 BT 源码或提供缺依赖时的本地副本。

独立运行研究工具安装 `.[analysis,research]`，研究读侧的 DuckDB 保持 `2.0.0` 钉；
infra 仍从显式选定的源码/制品安装。BT 安装基础包并沿用自身依赖清单。

独立研究入口需要显式设置 `OSKH_SOURCE_PARQUET_ROOT`、`OSKH_DATA_ROOT`；
直接导入研究脚本时另设 `MYQUANT_RESEARCH_ROOT`。原有显式研究参数与
数值规则保留；迁移没有授权重跑训练、读写真实行情湖或发布新名单。

Rust 构建在 `myquant_factors/rust/turnover-resist` 内执行
`cargo build --locked --release`。桥接层可通过 `TURNOVER_RESIST_EXE`
消费显式指定的产物，也支持 `CARGO_TARGET_DIR`。BT 不再留 Rust 源码。
纯 Python 数值测试和无数据的 Rust 编译检查由 MyQuant CI 承担。
