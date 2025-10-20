import multiprocessing
import logging

from timeit import default_timer as timer
from loguru import logger
import pandas as pd  # 导入pandas库进行数据处理
import qlib
from qlib.config import REG_CN
from qlib.contrib.data.handler import Alpha158
from qlib.contrib.evaluate import risk_analysis
from qlib.contrib.model import LGBModel
from qlib.contrib.report.analysis_position import report_graph
from qlib.utils import init_instance_by_config, flatten_dict
from qlib.workflow import R
from qlib.data.dataset import DatasetH
from qlib.contrib.strategy import TopkDropoutStrategy
from qlib.workflow.record_temp import SignalRecord, SigAnaRecord, PortAnaRecord
from qlib.contrib.report import analysis_model, analysis_position
from qlib.data import D  # 导入数据模块
from custom_handler import Alpha158CostKDJ
from custom_ops import SMA

from pprint import pprint
from custom_utils import pprint_position_report, analyze_position_by_date, generate_position_report, \
    pprint_risk_analysis

if __name__ == '__main__':
    multiprocessing.freeze_support() # 添加这一行，特别是在 Windows 上打包时可能有帮助

    print(qlib.__version__)  # 如果能够打印出版本号，说明安装成功

    start = timer()

    logger.remove(0)
    logger.add("ht.log")

    qlib.init(
        # 数据存储路径
        provider_uri = "~/.qlib/qlib_data/cn_data",  # target_dir
        # 中国市场
        region=REG_CN,
        # QLib 使用 Redis 进行缓存和锁机制,如果 Redis 连接失败，QLib 会自动降级为不使用缓存，这可能会影响性能但不会导致程序错误。
        redis_host='127.0.0.1',
        redis_port=6379,
        redis_password='123456',
        redis_task_db=1,  # Redis 数据库编号
        custom_ops=[SMA],
        # 配置实验管理器，用于跟踪和管理实验结果
        exp_manager={
            "class": "MLflowExpManager",
            "module_path": "qlib.workflow.expm",
            "kwargs": {
                "uri": "mlruns",
                "default_exp_name": "MyExperiment",
            }
        },
        # 设置日志级别，控制输出信息的详细程度：常用的日志级别有 DEBUG、INFO、WARNING、ERROR，级别从低到高，级别越低输出信息越详细。
        # logging_level=logging.DEBUG
        logging_level=logging.INFO
    )

    start_time = "2023-01-01"
    end_time = "2025-07-31"

    # 定义策略相关的市场和分析基准
    market = "csi300"
    benchmark = "SH000300"  # 设置业绩比较基准为沪深300指数代码

    exp_name = "alpha158_cost_kdj_lgb"

    signal_cols = ["COST_K", "COST_D", "COST_J"]

    # 定义数据处理器配置，指定数据获取的时间范围、训练集时间区间和投资标的
    data_handler_config = {
        "start_time": start_time,  # 整体数据开始时间
        "end_time": end_time,  # 整体数据结束时间
        "fit_start_time": start_time,  # 特征计算起始时间（通常与start_time一致）
        "fit_end_time": "2023-12-31",  # 特征计算结束时间（训练集截止时间）
        # "cost_window": 250,  # 特征计算结束时间（训练集截止时间）
        "infer_processors": [
                {"class": "RobustZScoreNorm", "kwargs": {"fields_group": "feature", "clip_outlier": True}}],  # 特征计算结束时间（训练集截止时间）
        "learn_processors": [{"class": "DropnaLabel"}],  # 特征计算结束时间（训练集截止时间）
        "instruments": market,  # 投资标的，这里使用前面定义的market（csi300）
        # "include_alpha158": True,  # 若仅需自定义因子，可设为 False 以加速
    }

    # handler = Alpha158CostKDJ(**data_handler_config)
    handler = Alpha158(**data_handler_config)

    # 定义任务配置字典，包含模型和数据集的详细配置
    task = {
        "model": {  # 模型配置部分
            "class": "LGBModel",  # 使用LightGBM模型,除了 LightGBM，QLib 还支持 XGBoost、CatBoost、MLP 等多种模型
            "module_path": "qlib.contrib.model.gbdt",  # 模型所在的模块路径
            "kwargs": {  # 传递给模型构造函数的参数（LightGBM的超参数）,LGBModel 是对 LightGBM 的封装，它实现了 QLib 的模型接口，能够与其他组件无缝集成
                "loss": "mse",  # 损失函数为均方误差
                "colsample_bytree": 0.8879,  # 构建每棵树时列采样比例
                "learning_rate": 0.0421,  # 学习率
                "subsample": 0.8789,  # 样本采样比例
                "lambda_l1": 205.6999,  # L1正则化系数
                "lambda_l2": 580.9768,  # L2正则化系数
                "max_depth": 8,  # 树的最大深度
                "num_leaves": 210,  # 树的叶子数
                "num_threads": 20,  # 并行线程数
                # "features": ["COST_J"],
            },
        },
        "dataset": {  # 数据集配置部分
            "class": "DatasetH",  # 使用DatasetH数据集类,负责将数据划分为训练集、验证集和测试集，并提供数据加载接口
            "module_path": "qlib.data.dataset",  # 数据集所在的模块路径
            "kwargs": {  # 传递给数据集构造函数的参数
                "handler": handler
                # {  # 数据处理器配置
                #     "class": "Alpha158CostKDJ",  # 使用Alpha158特征集,一个预定义的数据处理器，它实现了 158 个常用的 Alpha 因子
                #     "module_path": "custom_handler",  # 数据处理器所在模块路径
                #     "kwargs": data_handler_config,  # 使用前面定义的data_handler_config
                # }
                ,
                "segments": {  # 定义数据集的分段（训练集、验证集、测试集）
                    "train": (start_time, "2023-12-31"),  # 训练集时间范围
                    "valid": ("2024-01-01", "2024-12-31"),  # 验证集时间范围
                    "test": ("2025-01-01", end_time),  # 测试集时间范围
                },
            },
        },
    }

    # 验证数据加载
    data = handler.fetch(col_set="feature")
    print(data.head(10))
    available_cols = [col for col in signal_cols if col in data.columns]
    logger.info(f"可用信号列: {available_cols}")
    print(data[available_cols].head(10))

    model = init_instance_by_config(task["model"])  # 根据model配置创建模型实例
    print(u'根据model配置创建模型实例', timer() - start)
    dataset = init_instance_by_config(task["dataset"])  # 根据dataset配置创建数据集实例
    print(u'根据dataset配置创建数据集实例', timer() - start)

    # 定义投资组合分析（回测）的配置
    port_analysis_config = {
        "executor": {  # 回测执行器配置,负责模拟交易执行过程，计算交易成本和投资组合收益。
            "class": "SimulatorExecutor",  # 使用模拟执行器
            "module_path": "qlib.backtest.executor",  # 执行器所在模块路径
            "kwargs": {  # 执行器参数
                "time_per_step": "day",  # 回测的时间步长为一天
                "generate_portfolio_metrics": True,  # 生成投资组合指标
            },
        },
        "strategy": {  # 交易策略配置
            "class": "TopkDropoutStrategy",  # 使用TopK丢弃策略,一个简单但有效的策略，它每天选择模型预测分数最高的 50 只股票，并剔除其中 5 只持仓最久的股票
            "module_path": "qlib.contrib.strategy.signal_strategy",  # 策略所在模块路径
            "kwargs": {  # 策略参数
                "model": model,  # 使用的预测模型
                "dataset": dataset,  # 使用的数据集
                "topk": 10,  # 选择信号最强的50只股票
                "n_drop": 3,  # 每次调仓时丢弃排名最后5只股票
            },
        },
        "backtest": {  # 回测参数配置
            "start_time": "2025-01-01",  # 回测开始时间（与测试集一致）
            "end_time": end_time,  # 回测结束时间（与测试集一致）
            "account": 100000000,  # 初始资金金额（1亿元）
            "benchmark": benchmark,  # 业绩比较基准（沪深300指数）
            "exchange_kwargs": {  # 交易所模拟参数（交易规则）
                "freq": "day",  # 交易频率为日频
                "limit_threshold": 0.095,  # 涨跌幅限制阈值（9.5%）
                "deal_price": "close",  # 交易价格使用收盘价
                "open_cost": 0.0005,  # 开仓（买入）手续费率（万分之五）
                "close_cost": 0.0015,  # 平仓（卖出）手续费率（千分之1.5）
                "min_cost": 5,  # 最低手续费（5元）
            },
        },
    }

    """
    支持两种策略模式：
    模型驱动：用 COST_J 作为特征训练 LGB
    信号驱动：直接用 MAIRU == 1 选股
    """

    r_start = timer()
    rid = None
    with R.start(experiment_name=exp_name):
        R.log_params(**flatten_dict(task))  # 将任务配置参数扁平化后记录到实验中，便于追踪
        model.fit(dataset)  # 在训练集上训练模型，并在验证集上进行验证
        R.save_objects(trained_model=model)  # 将训练好的模型保存到当前实验记录中

        rid = R.get_recorder().id  # 获取当前实验记录器的ID，用于后续检索

        # 生成预测信号
        recorder = R.get_recorder()
        sr = SignalRecord(model, dataset, recorder)
        sr.generate()

        # 执行回测并生成分析报告
        par = PortAnaRecord(recorder, port_analysis_config, "day")  # 传入记录器、回测配置和时间频率
        par.generate()

        pred_df = recorder.load_object("pred.pkl")  # 预测结果
        print("预测结果")
        print(pred_df.head(10))

        report_normal_df = recorder.load_object("portfolio_analysis/report_normal_1day.pkl")  # 普通报告
        print("普通报告")
        print(report_normal_df.head(10))

        returns = report_normal_df["return"]
        benchmark_returns = report_normal_df["bench"]

        # 风险分析
        analysis_result = risk_analysis(returns)
        print("=== 风险绩效分析结果 ===")
        pprint_risk_analysis(analysis_result)

        # benchmark风险分析
        analysis_result = risk_analysis(benchmark_returns)
        print("=== benchmark风险绩效分析结果 ===")
        pprint_risk_analysis(analysis_result)

        positions_dict = recorder.load_object("portfolio_analysis/positions_normal_1day.pkl")  # 持仓记录
        print("持仓记录")
        # 分析最近交易日的持仓
        pprint_position_report(positions_dict)
        # 分析最近交易日的持仓
        analyze_position_by_date(positions_dict)
        # 生成报告
        generate_position_report(positions_dict)

        analysis_df = recorder.load_object("portfolio_analysis/port_analysis_1day.pkl")  # 分析报告
        print("分析报告")
        print(analysis_df.head(10))

        figures = analysis_position.report_graph(report_normal_df, show_notebook=False)
        print(
            "展示回测净值可视化结果(不扣费、扣费和基准净值；不扣费净值最大回撤；扣费净值最大回撤；不扣费和扣费超额收益净值；换手率；不扣费超额收益最大回撤；扣费超额收益最大回撤)",
            timer() - start)
        for i, fig in enumerate(figures):
            fig.show()

        figures = analysis_position.risk_analysis_graph(analysis_df, report_normal_df, show_notebook=False)
        print("生成风险分析图表可视化结果(年化收益率\波动率\信息比率\最大回撤)", timer() - start)
        for i, fig in enumerate(figures):
            fig.show()

        data_df = dataset.prepare(segments='test', col_set=['feature', 'label'])
        print(data_df.head(10))
        feature_df = data_df['feature']
        label_df = data_df['label']
        print("feature_df结果head")
        print(feature_df.head(10))
        print("label_df结果head")
        print(label_df.head(10))
        print("pred_df结果head")
        print(pred_df.head(10))

        label_df = dataset.prepare("test", col_set="label")
        label_df.columns = ['label']
        pred_label = pd.concat([label_df, pred_df], axis=1, sort=True).reindex(label_df.index)
        print("pred_label结果head")
        print(pred_label.head(10))

        figures = analysis_position.score_ic_graph(pred_label, show_notebook=False)
        print("AI模型预测个股收益的IC和Rank IC值可视化结果", timer() - start)
        for i, fig in enumerate(figures):
            # 如果你在支持 Plotly 的环境中（如 Dash 或某些 IDE），也可以直接显示
            fig.show()

    # 打印完成信息
    print("策略回测完成！", rid, timer() - r_start)

    print("✅ 训练与回测完成！")

    """
    在Qlib中，pred.pkl文件保存了模型在测试集上生成的预测结果，其核心字段包括时间戳、股票代码以及模型给出的预测分数。这个文件是连接模型预测与后续回测分析的关键输出。
    预测分数：这是文件中最核心的数值。模型会为每一个股票在每一个交易日期预测一个代表其未来潜力的分数。
    一般而言，分数越高，表示模型认为该股票在未来时间段内的预期收益也越高。这个分数是后续构建投资组合（如买入高分股票、卖出低分股票）的直接依据
    分数含义：预测分数的具体含义取决于模型训练时使用的标签（label）。如果标签是未来收益率，那么预测分数就直接与预期收益率相关
    
    在 Qlib 中，dataset.prepare(segments='test', col_set=['feature', 'label'])的 label表示机器学习模型要预测的目标变量。
    具体到量化投资场景，label通常是未来某个时间段的收益率或其他能够衡量投资回报的指标。
    
    标签在量化投资中的具体含义
    在 Qlib 的框架中，label是监督学习的核心组成部分，它代表了模型需要学习和预测的金融目标。
    
    常见的 label定义包括：
    未来收益率：最常用的标签，计算为 (未来N日价格 - 当前价格) / 当前价格，模型的目标是预测股票未来的价格走势
    涨跌分类：将未来收益率转化为分类问题，例如设定阈值将股票分为"上涨"和"下跌"两类
    相对排名：根据未来收益率对股票进行排名，用于构建投资组合
    
    特征与标签的关系
    在 Qlib 的数据集中，col_set=['feature', 'label']表示同时获取特征和标签数据：
    特征（feature）：描述股票当前状态的各种指标，如价格、成交量、技术指标等，作为模型的输入变量
    标签（label）：基于未来数据计算的目标值，作为模型训练时的监督信号
    
    标签在模型训练中的作用
    当使用 segments='test'参数时，Qlib 会准备测试集的数据，其中标签用于评估模型在未见数据上的表现。通过比较模型预测的标签值与真实的标签值，可以评估模型的预测准确性。
    需要注意的是，在实际的量化策略中，标签的定义直接影响模型的学习目标和最终的交易性能，因此需要谨慎设计以避免未来函数和保证实际可交易性。
    
    """