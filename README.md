# MyQuant

基于 [Microsoft Qlib](https://github.com/microsoft/qlib) 的 A 股量化研究项目。

从 2025 年 9 月第一次跑通 Qlib demo 开始，逐步演进到自定义数据、自定义因子与策略、滚动训练与回测的完整流程。这个仓库记录了整个学习与研究过程，包括踩过的坑（见 `my_docs/` 笔记）。

## 目录结构

```
MyQuant/
├── qlib_scripts/   # 数据准备与实验脚本：CSV 转 Qlib bin 格式（dump_bin.py）、
│                   # LightGBM + Alpha158 变体工作流、滚动训练/预测/回测等
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

其余依赖见 `requirements.txt`。

## 数据准备

自有 CSV 行情数据经 `qlib_scripts/dump_bin.py` 转换为 Qlib 二进制格式后使用。数据文件不入库。

## 相关项目

- [MyQuant-backtrader](https://github.com/baiyibing/MyQuant-backtrader) — 向量化研究回测（Cerebro 已于 2026-09-16 退役）；本仓库输出信号，不运行该回测账本。

## 免责声明

本项目仅用于量化研究与技术学习，不构成任何投资建议。

## 致谢与许可

- [Microsoft Qlib](https://github.com/microsoft/qlib)（MIT License）
- 本项目代码以 [MIT](LICENSE) 许可开源
