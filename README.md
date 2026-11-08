# MyQuant

基于 [Microsoft Qlib](https://github.com/microsoft/qlib) 的 A 股量化研究项目。

从 2025 年 9 月第一次跑通 Qlib demo 开始，逐步演进到自定义数据、自定义因子与策略、滚动训练与回测的完整流程。这个仓库记录了整个学习与研究过程，包括踩过的坑（见 `my_docs/` 笔记）。

本仓覆盖基于 Qlib 的完整量化研究链路：特征与策略研究、训练、预测打分、回测、成本敏感性实验、收益分析和信号导出。可以使用 Qlib 的全部组件，包括 `PortAnaRecord`、`Exchange`、executor 和策略组件；相关训练与 replay 脚本属于本仓研究能力。

仓库边界按职责划分：通用量化数据采集与产制归 MyQuant-infra；Qlib 研究与回测归本仓；MyQuant-backtrader 维护其自身回测引擎与研究流程；OSkhQuant1.3 承担实盘执行与真栈验收；通用工程协作归 grok-bot-ops。使用成交模拟、费用或收益计算本身不构成迁出依据。2026-11-08 用户澄清后，历史文档中的“Qlib PortAna/Exchange 停用”表述不再作为本仓边界约束。

## 目录结构

```
MyQuant/
├── qlib_scripts/   # 实验脚本：LightGBM + Alpha158 变体工作流、滚动训练/预测/回测等
├── my_scripts/     # 自定义扩展：DataHandler（KDJ、$volume 与有效流通盘等特征）、
│                   # 涨停/涨幅过滤策略（TopkDropoutStrategy 扩展）、工具函数
├── my_tests/       # 测试
├── tests/          # 合同与回归测试
├── docs/           # 设计、计划与验证文档
├── configs/        # 研究与模型配置
├── manifests/      # 运行与导出清单
├── .github/workflows/ci.yml  # CI 工作流
└── my_docs/        # 学习笔记与问题记录
```

## 环境搭建

Python 3.12（conda）。Qlib 采用源码 editable 方式安装，便于调试与阅读源码：

```bash
git clone https://github.com/microsoft/qlib.git qlib-dev
cd qlib-dev
pip install -e .
```

将 `MyQuant-infra` 源码放在本仓的同级目录，然后在 MyQuant 根目录安装依赖：

```bash
pip install -r requirements.txt
```

`requirements.txt` 以 editable 方式引用相邻的 infra 源码，本仓直接运行研究脚本。Qlib 仍使用上述源码安装。infra 源码在其他位置时，将 requirements 中的对应路径改为实际 checkout。infra 的独立安装命令为：

```bash
pip install -e "/path/to/MyQuant-infra[qlib-data,st,data-validation]"
```

通用协作脚手架另需同级 `grok-bot-ops` 源码（或设置 `MYQUANT_OPS_ROOT`），直接读取其中的通用执行核，无需安装 ops 包。本仓保留研究模板和检查入口；流程见[研究验收与协作指针](docs/pipeline-collab-2026-09-13.md)。

## 数据准备

数据产制统一调用 [MyQuant-infra](https://github.com/baiyibing/MyQuant-infra)：

```bash
python -m myquant_infra.adapters.qlib_data --help
python -m myquant_infra.derived_data.cyq --help
```

日线、1min、ETF 的 staging/bin、PIT、CSV 校验、CYQ、ST 读侧、信号包契约与通用产物溯源均归 infra。本仓删除已迁出的实现及旧入口，后续直接导入 `myquant_infra` 或调用其 CLI。训练、模型、策略筛选、Qlib 回测、收益分析、实验计时和宿主环境配置留在本仓；不复制 infra 实现，也不在依赖缺失时退回本地副本。

infra CLI 要求显式输入、输出和保护目录；本仓 `data_root.py` 仅把宿主环境配置传给 infra 路径 API。日常操作见[日线刷新](my_docs/提示词-qlib-bin刷新.md)、[分钟刷新](my_docs/提示词-qlib-1min-bin刷新.md)和[指数修补](my_docs/提示词-指数数据修补.md)。历史研究文档中的旧脚本路径保留为当时的记录。数据文件不入库。

旧 ST 采集、CSV 扫描及行业原始响应加工脚本已删除，当前入口见[参考数据手册](my_docs/prompt-kimi-datasource-industry-harvest.md)。行业中性化的单表读取和代码转换复用 infra，Git 溯源与文件指纹也调用 infra；研究算法与实验元数据保留在本仓。

`my_scripts/build_tradable_universe.py` 保留本仓排除名单选择，产制调用 infra；运行时必须用 `--st-asof YYYY-MM-DD` 显式指定快照日期。

## 相关项目（L2 四仓分工）

| 仓 | 职责 |
|---|---|
| [MyQuant-infra](https://github.com/baiyibing/MyQuant-infra) | L2 数据处理（写侧 + 湖工具 + research 读侧探索脚手架） |
| **本仓** | L2 数据利用（`l2_signals/`：信号、定义卡、跨年验证、池导出） |
| [MyQuant-backtrader](https://github.com/baiyibing/MyQuant-backtrader) | 回测执行（stab_t1 等；跨引擎契约）。Cerebro 已于 2026-09-16 退役 |
| [grok-bot-ops](https://github.com/baiyibing/grok-bot-ops) | 全局配置与湖口径/历程文档；研究脚本已迁出 |

细则见 [`l2_signals/README.md`](l2_signals/README.md)。

## 免责声明

本项目仅用于量化研究与技术学习，不构成任何投资建议。

## 致谢与许可

- [Microsoft Qlib](https://github.com/microsoft/qlib)（MIT License）
- 本项目代码以 [MIT](LICENSE) 许可开源

## CI 源码访问

GitHub Actions 的完整研究测试使用两把独立的只读 SSH deploy key：在 `MyQuant-infra` 注册公钥、将私钥保存为本仓 Actions secret `MYQUANT_INFRA_READ_KEY`；在 `grok-bot-ops` 注册另一把公钥、将对应私钥保存为 `MYQUANT_OPS_READ_KEY`。两仓均不勾选写入权限。CI 通过 `actions/checkout` 的 `ssh-key` 读取相邻源码，设置 `persist-credentials: false`，不将凭据留给后续测试。本地继续读取相邻源码，无需这些 CI secret。缺少密钥时 CI 明确失败，不使用本地实现副本替代。

infra [#83](https://github.com/baiyibing/MyQuant-infra/pull/83) 与 ops [#182](https://github.com/baiyibing/grok-bot-ops/pull/182) 已合入各自默认分支，CI 直接读取其当前源码；联合收益纯离线测试独立运行。
