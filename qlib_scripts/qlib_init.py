# https://www.wuzao.com/qlib/tutorial/introduction
import qlib
print(qlib.__version__)  # 如果能够打印出版本号，说明安装成功

import logging
from qlib.data import D
from qlib.data.filter import NameDFilter
from qlib.constant import REG_CN    # 中国市场
import logging
# python scripts/get_data.py qlib_data --target_dir ~/.qlib/qlib_data/cn_data --region cn
# 下载会报错，元宝建议从https://github.com/chenditc/investment_data/releases/latest/download/qlib_bin.tar.gz下载解压到~/.qlib/qlib_data/cn_data

# qlib.init(provider_uri='~/.qlib/qlib_data/cn_data', region=REG_CN)    ~ 表示当前用户的“home”目录

# qlib.init(provider_uri='./.qlib/qlib_data/cn_data', region=REG_CN)
qlib.init(
    # 数据存储路径,自定义数据存储路径
    provider_uri='E:/PycharmProjects/MyQuant/.qlib/qlib_data/cn_data',
    # 市场区域，支持qlib.constant.REG_CN（中国）和qlib.constant.REG_US（美国）
    region=REG_CN,
    # QLib 使用 Redis 进行缓存和锁机制,如果 Redis 连接失败，QLib 会自动降级为不使用缓存，这可能会影响性能但不会导致程序错误。
    redis_host='127.0.0.1',
    redis_port=6379,
    redis_password='123456',
    # 配置实验管理器，用于跟踪和管理实验结果，实验管理配置，支持自定义实验管理器（如MLflow）
    exp_manager={
        "class": "MLflowExpManager",
        "module_path": "qlib.workflow.expm",
        "kwargs": {
            "uri": "mlruns",
            "default_exp_name": "MyExperiment",
        }
    # mongo：MongoDB配置，用于任务管理，可选，用于任务管理高性能存储
    # kernels：计算特征时使用的进程数
    },
    # 设置日志级别，控制输出信息的详细程度：常用的日志级别有 DEBUG、INFO、WARNING、ERROR，级别从低到高，级别越低输出信息越详细。
    logging_level=logging.INFO
    # redis={
    #     "host": "localhost",  # 若Redis在远程服务器，请填写服务器IP
    #     "port": 6379,
    #     "password": "123456",  # 请替换为你的实际密码
    #     "db": 1
    # }
)

# 初始化完成后，可以通过以下方式验证是否成功：如果能够成功输出交易日历和股票列表，说明初始化成功。

# 获取交易日历
calendar = D.calendar()
print(f"交易日历长度: {len(calendar)}")
print(f"最近5个交易日: {calendar[-5:]}")

# 获取股票列表
instruments = D.instruments(market='csi300')
stock_list = D.list_instruments(instruments=instruments, as_list=True)
print(f"CSI300成分股数量: {len(stock_list)}")
print(f"部分成分股: {stock_list[:5]}")


# 数据健康检查
# 为确保数据质量，QLib 提供了数据健康检查工具，可以检查数据是否存在缺失、异常波动等问题：
# 检查日线数据
# python scripts/check_data_health.py check_data --qlib_dir ~/.qlib/qlib_data/cn_data   ~ 表示linux当前用户的“home”目录
# python scripts/check_data_health.py check_data --qlib_dir ./.qlib/qlib_data/cn_data
# python scripts/check_data_health.py check_data --qlib_dir E:/PycharmProjects/MyQuant/.qlib/qlib_data/cn_data
# 检查1分钟线数据
# python scripts/check_data_health.py check_data --qlib_dir ~/.qlib/qlib_data/cn_data_1min --freq 1min
# 可以通过参数调整检查阈值：
# python scripts/check_data_health.py check_data --qlib_dir ~/.qlib/qlib_data/cn_data --missing_data_num 300 --large_step_threshold_price 20
# --missing_data_num：允许的最大缺失数据量
# --large_step_threshold_price：价格最大允许波动阈值
# --large_step_threshold_volume：成交量最大允许波动阈值


# 运行错误：使用python -m pdb qlib/workflow/cli.py启动调试模式，定位问题

# 获取默认时间段的日线日历
calendar = D.calendar()
print(f"总交易日数: {len(calendar)}")
print(f"日期范围: {calendar[0]} 至 {calendar[-1]}")

# 获取指定时间段的日历
custom_calendar = D.calendar(start_time='2020-01-01', end_time='2020-12-31')
print(f"2020年交易日数: {len(custom_calendar)}")

# 获取所有股票
all_instruments = D.instruments(market='all')
all_stocks = D.list_instruments(instruments=all_instruments, as_list=True)
print(f"所有股票数量: {len(all_stocks)}")

# 按股票代码筛选
name_filter = NameDFilter(name_rule_re='SH[0-9]{4}55')  # 筛选代码以SH开头且后四位为数字，第五位为5的股票
filtered_instruments = D.instruments(market='csi300', filter_pipe=[name_filter])
filtered_stocks = D.list_instruments(instruments=filtered_instruments, as_list=True)
print(f"筛选后的股票: {filtered_stocks}")

# 目前qlib使用的三方维护的qlib数据，数据每日更新，修改地址中的日期即可获取最新数据，有兴趣可以看一下investment_data这个开源项目
# https://github.com/chenditc/investment_data

# 1 Qlib 是做什么的？
# 想象一下构建一个量化策略的完整流程：
#   数据获取与处理：获取股票的量价数据、财务数据等，并进行清洗、对齐、标准化。
#   因子挖掘 (Alpha Seeking)：利用数据构建各种因子（features），比如计算 5 日均线、动量指标等，希望能找到对未来股价有预测能力的信号（Alpha）。
#   模型训练：使用机器学习或深度学习模型（如 LightGBM, LSTM）来学习因子和未来收益率之间的关系，从而得到一个预测模型。
#   组合构建：根据模型的预测分数，决定买入哪些股票、卖出哪些股票，以及各自的仓位。
#   回测与分析：在历史数据上模拟交易过程，评估策略的夏普比率、最大回撤、年化收益等指标。
# Qlib 的目标就是将这整个流程 标准化、自动化、可复现。它提供了一整套工具链，覆盖了从数据到回测的每一个环节。

# 2 Qlib的模型架构
# Qlib框架将模型架构分为几个层次，从数据接口开始，到特征工程，最后是模型训练与评估。这种分层设计的目的是将数据处理和模型开发解耦，使得开发者能够专注于特定层次的开发，而不必了解其他层次的细节。
# 数据接口层：该层作为最底层，负责与外部数据源进行交互，加载和预处理数据，为上层的特征工程提供所需的数据。
# 特征工程层：这一层是Qlib框架的核心之一，负责提取和构建有意义的特征来描述数据，对原始数据进行转换和增强。
# 模型训练与评估层：在前两层的基础上，这一层关注的是将特征工程的成果应用到模型训练和评估中。它提供了一系列算法和工具，用于构建、训练、验证以及测试机器学习模型。

# 3 Qlib主要核心组件
# 数据准备（Data Preparation）下载和准备公开数据集，支持多市场（如中国市场）。数据由爬虫脚本采集，存储于本地。为后续模型训练和回测提供统一标准的数据接口。
#   数据层为模型提供输入
# 模型（Model）Qlib内置多种预测模型，如LightGBM、MLP等，也支持用户自定义模型集成。模型负责根据数据训练预测因子（alpha）。包含多种机器学习模型实现（GBDT、神经网络等）和风险模型（结构化协方差、收缩估计等）
#   模型生成预测信号，向工作流层提供预测
# 工作流管理（Workflow）通过配置文件或代码定义完整的量化研究流程，包括数据加载、模型训练、信号生成、回测及结果分析。其中，qrun 是自动化运行工具，支持一键执行整个流程。
#   工作流层协调模型训练、回测和强化学习任务
# 回测（Backtest）提供模拟交易环境，支持多种策略执行和绩效评估指标计算。回测结果包括收益率、风险指标、信息比率等。
#   回测和强化学习层模拟交易执行和策略优化
# 结果分析（Report）提供丰富的图形化报表和指标分析，帮助用户理解模型表现和策略效果。
# 实验记录（Recorder）负责实验过程数据的记录和管理，支持结果复现和对比。
#   实验管理组件负责记录和管理实验数据。

# 4 Qlib中的数据处理流
# Qlib的数据处理流程是其设计思想的集中体现，它利用一系列预定义的数据管道来完成数据的清洗、标准化、归一化等操作。
# 数据在经过处理后，将被加载到内存中供模型使用。这些数据管道是可配置的，并且易于扩展，使得Qlib能够适应不同的数据和模型需求。
#   qlib.data数据加载：使用Qlib提供的数据接口组件，能够将数据从本地或远程数据源中加载到内存中。
#   预处理：包括数据清洗、标准化、归一化等操作，是数据工程的重要一环。
#   qlib.features特征工程：在预处理的基础上，对数据进行更深层次的特征提取和转换。
#   模型应用：最后，将处理好的数据输入到qlib.modeling模型训练与qlib.workflow评估流程中进行最终的模型构建和评估。

# 5 Qlib官方示例模型的主要功能涵盖了从数据预处理到模型训练，再到最终结果预测的整个流程。具体来说，这些模型通常包含以下功能：
#   数据清洗与预处理：通过算法处理缺失值、异常值和数据标准化等问题。
#   特征工程：挖掘并选取对预测模型最有用的特征变量。
#   模型训练：利用历史数据训练模型，并进行交叉验证。
#   模型评估：使用验证集评估模型性能，包括诸如准确率、召回率和F1分数等指标。
#   预测与部署：将训练好的模型应用于新数据，进行未来市场走势的预测。

# 6 源码模块讲解
# qlib.data - 数据层,提供一个高效、统一的数据存储和访问接口。数据处理模块，包括数据客户端、数据集、缓存、存储和数据操作
# qlib/data/client.py: 作用：提供统一接口访问底层金融数据。主要类：DataClient，负责数据加载、缓存和查询。
# qlib/data/data.py: 定义了核心的数据加载逻辑和 D 对象。
# qlib/data/cache.py: 实现了表达式计算结果的缓存机制，是性能的关键。
# qlib/data/dataset/handler.py: 处理数据预处理，如数据标准化、缺失值填充等。
# 理解数据流：重点看数据是如何从 D.features() 流出，经过 DataHandler 处理，送入 Dataset，最后被模型使用的
# Dataset 数据集构建模块，包括数据集基类、处理器、加载器、存储等，支持数据预处理、分段、采样等功能。构建依赖 DataHandler 和 Processor 进行数据预处理。
#   handler.py：数据处理器，管理数据的加载、预处理及分段。
#   loader.py：数据加载器，从底层数据源加载原始数据。
#   processor.py：数据处理器，实现各种数据转换和标准化方法。
#   storage.py：数据存储接口及实现，支持不同存储格式。
#   utils.py：工具函数，辅助数据处理。

# qlib.workflow - 工作流管理,管理和记录整个量化实验流程，确保实验的 可复现性。管理量化研究工作流，如实验管理、任务调度、在线策略等
# qlib/workflow/cli.py 工作流命令行入口 - 提供命令行工具qrun，自动运行量化研究工作流（数据准备、模型训练、回测、评估）main()：解析命令行参数，加载配置文件，启动工作流
# qlib/workflow/recorder.py: Recorder 类的实现，负责实验的启动、记录和结束。
# qlib/workflow/exp.py: 实验管理器，用于管理多个 Recorder 实例。
# R 是 workflow 模块的核心。当你运行一个实验时，Recorder 会自动记录下所有的配置、模型文件、预测结果和回测报告。每个实验都会有一个唯一的 ID，方便你日后回溯、比较不同实验的结果。
# Qlib 强烈推荐使用 YAML 配置文件来定义整个工作流（用什么数据、什么模型、什么策略、回测参数等）。这使得实验设置一目了然，并且易于分享和修改。
# qlib.workflow.Recorder 是如何根据 YAML 配置，一步步调用 task（模型训练）和 port_analysis_config（回测）的。

# qlib.contrib -AI 模型和因子库,提供一个即插即用的模型库和因子库，降低用户的使用门槛。社区贡献的模型、策略、数据处理器、调优器、报告分析、在线服务等扩展组件。
# qlib/contrib/model/: 存放了各种已经集成好的机器学习/深度学习模型。例如 lightgbm.py, gru.py, transformer.py 等。这些模型都遵循 Qlib 定义的统一接口，可以被工作流无缝调用。
# qlib/contrib/meta/: 包含了一些高阶的应用，比如自动因子挖掘 (AutoML) 等。
# qlib/contrib/evaluate.py: 包含了一些常用的因子评价函数，如计算 IC (Information Coefficient)、Rank IC 等。

# qlib.strategy - 策略层 将模型的预测分数（Alpha）转化为实际的交易决策（仓位），实现交易逻辑
# 定义了策略的基类 BaseStrategy。
# qlib/strategy/strategy.py:提供了常见的策略实现，如 TopkDropoutStrategy（买入预测分数最高的 K 支股票，并控制换手率）。

# qlib.backtest 回测引擎,模拟历史交易，评估策略表现。回测框架，包含账户管理、策略执行、报告生成等
# qlib/backtest/backtest.py: 高层次的回测接口。
# qlib/backtest/executor.py: 实际执行交易逻辑的执行器。
# qlib/backtest/analyser.py: 用于分析回测结果并生成报告。

# qlib.model 模型相关代码，包括训练器、风险模型、解释器等。模型训练和风险模型实现，支持多种机器学习模型和解释模块
#   模型训练 - qlib/model/trainer.py
#   作用：封装模型训练流程，支持多种机器学习模型。
#   提供灵活的训练控制接口，支持早停、日志记录等。
# qlib.utils 工具函数集合，辅助文件操作、时间处理、并行计算、序列化等
# qlib.rl ：强化学习相关模块，包含环境、策略、训练器等，支持基于RL的策略开发和训练
# run/：运行时相关脚本和初始化。

# examples/ 示例代码目录，包含多种模型和工作流、高频数据处理的示例，方便用户学习和快速上手。包含丰富的示例代码和benchmark，涵盖多种模型和工作流配置，便于用户快速上手
#   示例工作流 - examples/workflow_by_code.py
#   作用：演示如何通过代码构建自定义量化研究工作流。
#   结构清晰，包含数据准备、模型训练、回测和结果分析。
# scripts/ 辅助脚本，如数据获取、数据校验等。提供数据采集工具和辅助脚本，方便用户准备和更新数据集。
# docs/ 文档目录，包含安装、使用、组件介绍、FAQ等文档
# tests/ 测试代码，确保项目质量

# 7 qlib典型使用流程
# 从 examples 开始不要直接扎进 qlib 核心代码。先找一个简单的例子，比如 examples/workflow_config_lightgbm_Alpha158.yaml，然后用调试器（如 VS Code 的 debugger）跟着 qrun 命令走一遍。
# 7.1 准备数据
# 运行 scripts/get_data.sh 脚本。
# 这个脚本会下载 A 股市场的历史日线数据，并将其转换为 Qlib 高效的 .bin 格式。

# 7.2 编写配置文件 (YAML)
# 在 examples/ 目录下，你会找到很多 workflow_config_*.yaml 文件。这是一个典型的配置文件，定义了整个实验。
# data_handler_config: 配置数据预处理，比如使用哪些因子、如何标准化、如何处理标签（label，即预测目标）。
# task: 定义了模型和训练参数。
# model: 指定使用哪个模型，例如 LightGBM。
# dataset: 定义训练集、验证集、测试集的时间范围。
# port_analysis_config: 配置投资组合分析（回测）。
# strategy: 指定使用哪种交易策略，例如 TopkDropoutStrategy。
# backtest: 配置回测参数，如交易成本。

# 7.3 运行实验
# 在终端运行命令：qrun examples/workflow_config_lightgbm_Alpha158.yaml
# qrun 是 Qlib 提供的命令行工具。它会解析 YAML 文件，然后调用 qlib.workflow 启动一个 Recorder，依次执行数据处理、模型训练、预测和回测。

# 7.4 分析结果
# 实验结束后，所有的结果都被保存在 mlruns 目录中（这是 MLflow 的格式，Qlib 集成了它来做实验管理）。
# 你可以查看生成的 recorder 对象，或者直接查看目录下的回测报告（portfolio_analysis.pkl）、模型文件（model.pkl）等。

# 8 qlib工作流程
# 8.1 环境准备
# 安装依赖（numpy, cython等），安装Qlib库。
# 准备数据集，下载公开数据。
# 8.1 定义研究任务
# 通过配置文件或代码初始化模型和数据集。
# 8.2 训练模型
# 使用准备好的数据训练模型，生成预测信号。
# 8.4 信号生成与分析
# 基于模型输出生成交易信号，进行信号质量分析。
# 8.5 回测执行
# 使用模拟账户和策略执行回测，计算绩效指标。
# 8.6 结果展示
# 通过图形化报表展示回测和信号分析结果。
# 8.7 迭代优化
# 用户可自定义模型、策略或数据，重复流程优化投资策略。