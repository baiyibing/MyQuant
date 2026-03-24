import multiprocessing
import atexit
import logging
import os
import copy

from timeit import default_timer as timer


from loguru import logger
import pandas as pd  # 导入pandas库进行数据处理
import qlib
from qlib.config import REG_CN
from qlib.contrib.data.handler import Alpha158
from qlib.contrib.evaluate import risk_analysis
from qlib.contrib.model import LGBModel
from qlib.contrib.report.analysis_position import report_graph
from qlib.data.filter import ExpressionDFilter, NameDFilter
from qlib.utils import init_instance_by_config, flatten_dict
from qlib.workflow import R
from qlib.data.dataset import DatasetH
from qlib.contrib.strategy import TopkDropoutStrategy
from qlib.workflow.record_temp import SignalRecord, SigAnaRecord, PortAnaRecord
from qlib.contrib.report import analysis_model, analysis_position
from qlib.data import D  # 导入数据模块
from custom_handler import Alpha158CostKDJ
from custom_filter import UnifiedLimitUpFilter
from custom_ops import SMA
import plotly.graph_objects as go

from pprint import pprint
from custom_utils import pprint_position_report, analyze_position_by_date, generate_position_report, \
    pprint_risk_analysis, TimerRecorder, set_global_timer_recorder


def verify_limit_up_filter(filtered_handler, unfiltered_handler, segments):
    """验证 UnifiedLimitUpFilter 是否在 train/valid/test 三段生效。"""
    filtered_df = filtered_handler.fetch(col_set="feature")
    unfiltered_df = unfiltered_handler.fetch(col_set="feature")

    if "LIMIT_STATUS" not in filtered_df.columns or "LIMIT_STATUS" not in unfiltered_df.columns:
        raise ValueError("验证失败：缺少 LIMIT_STATUS 列，请确认 include_lz=True 且 $zhangting 字段可用。")

    print("\n=== Verify UnifiedLimitUpFilter (train/valid/test) ===")
    for seg_name, (seg_start, seg_end) in segments.items():
        base_seg = unfiltered_df.loc[(slice(seg_start, seg_end), slice(None)), :]
        filtered_seg = filtered_df.loc[(slice(seg_start, seg_end), slice(None)), :]

        base_rows = len(base_seg)
        filtered_rows = len(filtered_seg)
        removed_rows = base_rows - filtered_rows
        removed_ratio = (removed_rows / base_rows) if base_rows else 0.0

        base_limit_cnt = int((base_seg["LIMIT_STATUS"] == 1).sum())
        filtered_limit_cnt = int((filtered_seg["LIMIT_STATUS"] == 1).sum())

        print(
            f"[{seg_name}] rows(before/after)={base_rows}/{filtered_rows}, "
            f"removed={removed_rows} ({removed_ratio:.2%}), "
            f"limit_status_1(before/after)={base_limit_cnt}/{filtered_limit_cnt}"
        )

        if filtered_limit_cnt > 0:
            raise ValueError(
                f"验证失败：{seg_name} 分段过滤后仍存在 LIMIT_STATUS==1 样本（{filtered_limit_cnt} 条）。"
            )
        if base_limit_cnt > 0 and removed_rows <= 0:
            raise ValueError(
                f"验证失败：{seg_name} 分段存在涨停样本（{base_limit_cnt} 条），但过滤前后样本数无减少。"
            )

    print("✅ UnifiedLimitUpFilter 验证通过：train/valid/test 均已生效。\n")

if __name__ == '__main__':
    multiprocessing.freeze_support() # 添加这一行，特别是在 Windows 上打包时可能有帮助

    print(qlib.__version__)  # 如果能够打印出版本号，说明安装成功

    start = timer()
    t_rec = TimerRecorder()
    # Make recorder visible to other modules in the same process (strategy/handler timing).
    set_global_timer_recorder(t_rec)
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    exp_name = None
    timing_path = None

    logger.remove(0)

    # logger.add("Filter.log", filter=lambda record: record["function"].startswith("_filter_stocks_by_return_threshold"))
    # logger.add("Filter.log", filter=lambda record: "custom_strategy:" in record["message"])

    logger.add("Filter.log", filter=lambda record: record["module"] == "custom_strategy")
    logger.add("orders.log", filter=lambda record: record["module"] != "custom_strategy")
    # logger.add("orders.log", filter=lambda record: record["module"] == "qlib.backtest.position")
    # logger.add(
    #     "logs/custom_strategy_{time:YYYY-MM-DD}.log",
    #     format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {extra[name]}:{function}:{line} - {message}",
    #     filter=lambda record: record["extra"].get("name") == "custom_strategy",
    #     level="INFO",
    #     rotation="00:00",  # 每天午夜轮转
    #     retention="30 days",
    #     compression="zip",
    #     encoding="utf-8"
    # )
    #
    # # 其他日志的文件处理器
    # logger.add(
    #     "orders.log",
    #     filter=lambda record: record["extra"].get("name") != "custom_strategy"
    # )

    qlib.init(
        # 数据存储路径
        provider_uri = "~/.qlib/qlib_data/my_data",  # target_dir
        # 中国市场
        region=REG_CN,
        kernels=16,
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

    # 显示所有行
    pd.set_option('display.max_rows', None)
    # 显示所有列
    pd.set_option('display.max_columns', None)
    # 设置列宽，确保长文本完整显示
    pd.set_option('display.max_colwidth', None)
    # 设置显示宽度，防止自动换行
    pd.set_option('display.width', None)

    start_time="2026-01-01"
    end_time="2026-03-23"

    fit_start_time=start_time
    fit_end_time="2026-01-31"

    valid_start_time="2026-02-01"
    valid_end_time="2026-02-28"

    test_start_time="2026-03-01"
    test_end_time=end_time

    # 2. 定义动态过滤规则：排除过去5日涨幅超过10%的股票
    # 注意：表达式中的 $close 等字段需要确保在你的数据中存在
    # f"""
    # (
    #     ($close - Ref($close,5)) / Ref($close,5) < -0.10 &
    #     ($high - $low)/$close < 0.05 &
    #     (EMA($close,12) > EMA($close,26))
    # )
    # """
    # expression_rule = "(Ref($close, 0) / Ref($close, 5) - 1) <= 0.10"

    # 要排除的股票代码列表
    exclude_stocks = ['SZ000004', 'SZ000430', 'SZ000488', 'SZ000504', 'SZ000518', 'SZ000595', 'SZ000608', 'SZ000609', 'SZ000615', 'SZ000638', 'SZ000656', 'SZ000668', 'SZ000669', 'SZ000691', 'SZ000697', 'SZ000698', 'SZ000711', 'SZ000736', 'SZ000752', 'SZ000793', 'SZ000820', 'SZ000903', 'SZ000908', 'SZ000909', 'SZ000929', 'SZ000972', 'SZ001270', 'SZ002005', 'SZ002024', 'SZ002047', 'SZ002058', 'SZ002076', 'SZ002122', 'SZ002168', 'SZ002197', 'SZ002199', 'SZ002200', 'SZ002211', 'SZ002214', 'SZ002231', 'SZ002253', 'SZ002289', 'SZ002305', 'SZ002306', 'SZ002388', 'SZ002425', 'SZ002485', 'SZ002496', 'SZ002528', 'SZ002529', 'SZ002569', 'SZ002581', 'SZ002586', 'SZ002592', 'SZ002620', 'SZ002630', 'SZ002647', 'SZ002650', 'SZ002656', 'SZ002693', 'SZ002713', 'SZ002717', 'SZ002742', 'SZ002762', 'SZ002789', 'SZ002808', 'SZ002816', 'SZ002822', 'SZ002848', 'SZ002868', 'SZ002872', 'SZ002898', 'SZ003004', 'SZ003032', 'SZ300020', 'SZ300029', 'SZ300044', 'SZ300052', 'SZ300093', 'SZ300096', 'SZ300097', 'SZ300125', 'SZ300137', 'SZ300147', 'SZ300152', 'SZ300159', 'SZ300165', 'SZ300167', 'SZ300175', 'SZ300198', 'SZ300205', 'SZ300211', 'SZ300225', 'SZ300237', 'SZ300268', 'SZ300301', 'SZ300311', 'SZ300313', 'SZ300326', 'SZ300338', 'SZ300343', 'SZ300344', 'SZ300366', 'SZ300376', 'SZ300379', 'SZ300391', 'SZ300419', 'SZ300462', 'SZ300472', 'SZ300477', 'SZ300506', 'SZ300527', 'SZ300555', 'SZ300561', 'SZ300716', 'SZ300899', 'SZ301288', 'SH600107', 'SH600130', 'SH600136', 'SH600165', 'SH600169', 'SH600193', 'SH600200', 'SH600228', 'SH600238', 'SH600243', 'SH600265', 'SH600289', 'SH600355', 'SH600358', 'SH600360', 'SH600365', 'SH600381', 'SH600421', 'SH600525', 'SH600568', 'SH600599', 'SH600608', 'SH600624', 'SH600636', 'SH600696', 'SH600735', 'SH600753', 'SH600777', 'SH600892', 'SH603007', 'SH603021', 'SH603261', 'SH603268', 'SH603377', 'SH603388', 'SH603389', 'SH603398', 'SH603517', 'SH603557', 'SH603559', 'SH603580', 'SH603595', 'SH603721', 'SH603789', 'SH603813', 'SH603825', 'SH603828', 'SH603838', 'SH603843', 'SH603869', 'SH605081', 'SH605199', 'SH688053', 'SH688076', 'SH688184', 'SH688287', 'SH688511', 'SH688646', 'BJ920305', 'BJ920680']
    # exclude_stocks = ['SZ000004', 'SZ000430', 'SZ000488']

    # 创建排除表达式
    # 这里使用NotIn操作来排除特定股票
    exclude_filter = NameDFilter(name_rule_re='^(?!(' + '|'.join(exclude_stocks) + ')).*$')  # 正则排除

    # 创建表达式过滤器
    # exclude_filter = ExpressionDFilter(rule_expression=exclude_expression)

    expression_rule = f"""
    (
        ($close - Ref($close,5)) / Ref($close,5) < -0.10
    )
    """
    dynamic_filter = ExpressionDFilter(rule_expression=expression_rule)

    # === 阶段2：动态涨停过滤（核心新增）===
    # 这是关键：在DataHandler中配置，自动作用于Train/Valid/Test
    limit_up_filter = UnifiedLimitUpFilter(
        use_field="$zhangting",  # 使用您数据中的涨停标记
        limit_pct=0.095,  # 主板阈值，科创板需0.19
        keep=False  # False=剔除涨停股票
    )

    # 定义策略相关的市场和分析基准
    # market = "all"
    # market = "csi300"

    benchmark = "SH601727"  # 设置业绩比较基准为沪深300指数代码
    # market = ['SH600000','SH600010','SH600028','SH600025','SH600019','SH600900','SH600941','SZ300059','SZ300124','SZ300274']

    exp_name = "alpha158_cost_kdj_lgb"
    timing_path = os.path.join(base_dir, f"timing_custom_train_backtest_{exp_name}.json")

    def _dump_timing_on_exit():
        # Ensure we always persist timing nodes, even if the run crashes mid-way.
        try:
            _path = timing_path or os.path.join(base_dir, "timing_custom_train_backtest_unknown.json")
            t_rec.dump_json(_path, extra={"exp_name": exp_name})
            print(f"=== Timing saved: {_path} ===")
        except Exception as e:
            print(f"Failed to dump timing json: {e}")

    atexit.register(_dump_timing_on_exit)

    signal_cols = ["COST_K", "COST_D", "COST_J", "MAIRU_SIGNAL","ZHANGTING"]

    # 定义数据处理器配置，指定数据获取的时间范围、训练集时间区间和投资标的
    data_handler_config = {
        "start_time": start_time,  # 整体数据开始时间
        "end_time": end_time,  # 整体数据结束时间
        "fit_start_time": fit_start_time,  # 特征计算起始时间（通常与start_time一致）
        "fit_end_time": fit_end_time,  # 特征计算结束时间（训练集截止时间）
        # "cost_window": 250,  # 特征计算结束时间（训练集截止时间）
        # "infer_processors": [
        #         {"class": "RobustZScoreNorm", "kwargs": {"fields_group": "feature", "clip_outlier": True}}],  # 特征计算结束时间（训练集截止时间）
        # "learn_processors": [{"class": "DropnaLabel"}],  # 特征计算结束时间（训练集截止时间）
        "infer_processors": [
            {"class": "ProcessInf"},
            {"class": "RobustZScoreNorm", "kwargs": {"fields_group": "feature"}},
            {"class": "Fillna", "kwargs": {"method": "ffill"}}
        ],
        # `filter_pipe` is not None, but it will not be used with `instruments` as list
        # "instruments": filtered_instruments,  # 投资标的，这里使用前面定义的market（csi300）
        "instruments": "all",  # 关键：不要用 list
        "include_alpha158": True,  # 若仅需自定义因子，可设为 False 以加速
        "include_cost_kdj": True,
        "include_signal": False,
        "include_lz": True,
        "filter_pipe":[exclude_filter,limit_up_filter]
    }

    print("[debug] before handler_init(filtered)", flush=True)
    with t_rec.timer("handler_init"):
        handler = Alpha158CostKDJ(**data_handler_config)
    print("[debug] after handler_init(filtered)", flush=True)
    # handler = Alpha158(**data_handler_config) #  **运算符将字典展开为关键字参数

    # 构建“无涨停过滤”对照 handler：仅保留 exclude_filter，用于验证前后差异
    no_limit_filter_config = copy.deepcopy(data_handler_config)
    no_limit_filter_config["filter_pipe"] = [exclude_filter]
    print("[debug] before handler_init(no_limit_filter)", flush=True)
    with t_rec.timer("handler_init_no_limit_filter"):
        handler_no_limit_filter = Alpha158CostKDJ(**no_limit_filter_config)
    print("[debug] after handler_init(no_limit_filter)", flush=True)

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
                "handler": handler,
                # {  # 数据处理器配置
                #     "class": "Alpha158CostKDJ",  # 使用Alpha158特征集,一个预定义的数据处理器，它实现了 158 个常用的 Alpha 因子
                #     "module_path": "custom_handler",  # 数据处理器所在模块路径
                #     # "kwargs": data_handler_config,  # 使用前面定义的data_handler_config
                #     # "class": "Alpha158",  # 使用Alpha158特征集,一个预定义的数据处理器，它实现了 158 个常用的 Alpha 因子
                #     # "module_path": "qlib.contrib.data.handler",  # 数据处理器所在模块路径
                #     "kwargs": data_handler_config,  # 使用前面定义的data_handler_config
                # },
                "segments": {  # 定义数据集的分段（训练集、验证集、测试集）
                    "train": (fit_start_time, fit_end_time),  # 训练集时间范围，用于模型训练。
                    "valid": (valid_start_time, valid_end_time),  # 验证集时间范围，用于调参、早停等。
                    "test": (test_start_time, test_end_time),  # 测试集时间范围，用于最终回测评估。
                },
            },
        },
    }

    # 验证数据加载
    with t_rec.timer("handler_fetch_feature"):
        data = handler.fetch(col_set="feature")

    print(data.head(10))
    #                            KMID      KLEN  ...    COST_D    COST_J
    # datetime   instrument                      ...
    # 2023-01-03 SH600000   -0.298624 -0.706633  ... -0.085372 -0.023536
    #            SH600009   -1.546573  0.264609  ...       NaN       NaN
    #            SH600010    0.475908 -0.207787  ... -0.688093 -0.629647
    #            SH600011    2.071525  3.000000  ... -0.203372  0.317179
    #            SH600015    0.238334 -1.020868  ...  0.510582  0.613794
    #            SH600016   -0.318746 -1.018924  ... -0.211149 -0.147461
    #            SH600018    0.099265 -0.398185  ... -0.363264 -0.186470
    #            SH600019    0.358459 -0.619303  ... -0.132547 -0.161108
    #            SH600025    1.410132  0.216171  ...  0.223375  0.598955
    #            SH600028    0.429478 -0.831903  ...  1.067183  1.107931
    #
    # [10 rows x 161 columns]
    print(f"所有feature列: {data.columns}")
    all_features = data.columns
    available_cols = [col for col in signal_cols if col in data.columns]
    print(f"可用信号列: {available_cols}")
    print(data[available_cols].head(10))
    # 2023-01-03 SH600000   -0.066754 -0.085372 -0.023536
    #            SH600009         NaN       NaN       NaN
    #            SH600010   -0.671162 -0.688093 -0.629647
    #            SH600011   -0.030015 -0.203372  0.317179
    #            SH600015    0.543704  0.510582  0.613794
    #            SH600016   -0.192020 -0.211149 -0.147461
    #            SH600018   -0.306091 -0.363264 -0.186470
    #            SH600019   -0.144487 -0.132547 -0.161108
    #            SH600025    0.348180  0.223375  0.598955
    #            SH600028    1.079720  1.067183  1.107931

    with t_rec.timer("model_init"):
        model = init_instance_by_config(task["model"])  # 根据model配置创建模型实例
    print(u'根据model配置创建模型实例', timer() - start)
    print("[debug] before dataset_init", flush=True)
    with t_rec.timer("dataset_init"):
        dataset = init_instance_by_config(task["dataset"])  # 根据dataset配置创建数据集实例
    print("[debug] after dataset_init", flush=True)
    print(u'根据dataset配置创建数据集实例', timer() - start)

    # 训练前强制验证过滤器是否真正生效，失败则中断
    print("[debug] before verify_limit_up_filter", flush=True)
    verify_limit_up_filter(
        filtered_handler=handler,
        unfiltered_handler=handler_no_limit_filter,
        segments=task["dataset"]["kwargs"]["segments"],
    )
    print("[debug] after verify_limit_up_filter", flush=True)

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
            # "class": "TopkDropoutStrategyWithFilter",  # 使用TopK丢弃策略,一个简单但有效的策略，它每天选择模型预测分数最高的 50 只股票，并剔除其中 5 只持仓最久的股票
            # "module_path": "custom_strategy",  # 策略所在模块路径
            "kwargs": {  # 策略参数
                "model": model,  # 使用的预测模型
                "dataset": dataset,  # 使用的数据集
                "topk": 10,  # 选择信号最强的50只股票
                "n_drop": 3,  # 每次调仓时丢弃排名最后5只股票
                "hold_thresh": 1,  # 最小持有1天
                # timing_interval_steps 仅适用于 custom_strategy.TopkDropoutStrategyWithFilter，勿传给 qlib TopkDropoutStrategy
            },
        },
        "backtest": {  # 回测参数配置
            "start_time": test_start_time,  # 回测开始时间（与测试集一致）
            "end_time": test_end_time,  # 回测结束时间（与测试集一致）
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

    recorder_path = None
    r_start = timer()
    rid = None
    with R.start(experiment_name=exp_name):
        R.log_params(**flatten_dict(task))  # 将任务配置参数扁平化后记录到实验中，便于追踪
        print("[debug] before model.fit", flush=True)
        with t_rec.timer("model_fit"):
            model.fit(dataset)  # 方法根据数据集对模型进行训练，这个过程会生成模型参数和训练指标 在训练集上训练模型，并在验证集上进行验证
        print("[debug] after model.fit", flush=True)
        R.save_objects(trained_model=model)  # 将训练好的模型保存到当前实验记录中
        # 保存的模型可以通过 recorder.load_object("trained_model")在后续流程（如回测阶段）中重新加载使用，确保模型的一致性和可复用性

        rid = R.get_recorder().id  # 获取当前实验记录器的ID，用于后续检索

        # 5. 特征重要性分析与选择
        # 获取特征重要性（新版本QLib模型通常内置该方法）
        # 方式一：直接使用模型提供的 `feature_importance` (如果可用)
        if hasattr(model, 'feature_importance'):
            feat_imp = model.feature_importance()
        else:
            # 方式二：使用模型训练器中的特征重要性（适用于某些版本）
            # 注意：具体方法可能因版本而异，请查阅官方文档
            try:
                feat_imp = model.get_feature_importance()
            except:
                # 方式三：回退方案 - 基于训练数据手动计算（近似）
                # 此方法可能计算较慢，且为近似值
                print(
                    "Warning: Using fallback method for feature importance. Check Qlib documentation for the recommended way.")
                # 此处可能需要根据实际模型类型调整获取方式
                feat_imp = None

        print(f"直接使用模型提供的 `feature_importance` (如果可用)")
        print(feat_imp)
        # Column_17     103
        # Column_1       95
        # Column_178     89
        # Column_175     80
        # Column_27      77

        # 将特征重要性转换为Series并按降序排序
        feat_imp_series = feat_imp.sort_values(ascending=False)

        # 选择前K个最重要的特征
        selected_features = feat_imp_series.index.tolist()
        print(f"将特征重要性转换为Series并按降序排序:")
        print(selected_features)

        selected_features_name = []
        for col in selected_features:
            parts = col.split('_') # Column_17
            if parts:
                number = int(parts[-1])
                selected_features_name.append(all_features[number])
        print(f"重要的特征列名对应的特征名")
        print(selected_features_name)

        K = 50
        # 6. (可选) 可视化特征重要性
        top_features = feat_imp_series.head(K)
        top_features_name = pd.Series(selected_features_name)
        top_features_name=top_features_name.head(K)

        # 创建水平条形图
        feature_importance_fig = go.Figure()

        # 添加条形图轨迹
        feature_importance_fig.add_trace(go.Bar(
            y=top_features_name.values,
            # y=top_features.index.tolist(),
            x=top_features.values,
            orientation='h',
            marker=dict(
                color=top_features.values,
                colorscale='Viridis',
                showscale=True,
                colorbar=dict(title="重要性分数")
            ),
            hovertemplate='<b>%{y}</b><br>重要性: %{x:.4f}<extra></extra>'
        ))

        # 更新布局
        feature_importance_fig.update_layout(
            title=dict(
                text=f'Top {K} 特征重要性',
                x=0.5,
                xanchor='center'
            ),
            xaxis_title='重要性分数',
            yaxis_title='特征名称',
            height=600 + K * 10,  # 动态调整高度以适应特征数量
            template='plotly_white',
            showlegend=False
        )

        # 调整y轴顺序，使最重要的特征在顶部
        feature_importance_fig.update_yaxes(autorange="reversed")

        feature_importance_fig.show()

        # 7. 使用筛选后的特征重新训练模型（可选但推荐）
        # 可以创建一个新的Handler或Dataset，仅包含选定的特征
        # 例如，可以修改handler的配置，只包含selected_features
        # 然后重新训练模型，可能会获得更好的性能或更快的训练速度

        # 生成预测信号
        recorder = R.get_recorder()

        sr = SignalRecord(model, dataset, recorder)
        with t_rec.timer("SignalRecord.generate"):
            sr.generate()
        # 执行 sr.generate()后，生成的预测信号会保存到记录器的工件（artifacts）中，主要包括：
        #   预测分数文件：保存每个股票在每个时间点的预测分数
        # [record_temp.py:198] - Signal record 'pred.pkl' has been saved as the artifact of the Experiment 963122733822150836
        # 'The following are prediction results of the LGBModel model.'
        #                           score
        # datetime   instrument
        # 2025-01-02 SH600000   -0.000373
        #            SH600009   -0.000373
        #            SH600010   -0.000373
        #            SH600011   -0.000373
        #            SH600015   -0.000373

        pred_df = recorder.load_object("pred.pkl")  # 预测结果
        print("预测结果head")
        print(pred_df.head(10))

        pred_df.to_csv('预测结果.csv', encoding='utf-8')
        # 预测结果
        #                           score
        # datetime   instrument
        # 2025-01-02 SH600000   -0.000373
        #            SH600009   -0.000373
        #            SH600010   -0.000373
        #            SH600011   -0.000373
        #            SH600015   -0.000373
        #            SH600016   -0.000373
        #            SH600018   -0.000373
        #            SH600019   -0.000373
        #            SH600023   -0.000373
        #            SH600025   -0.000373
        print("预测结果tail")
        print(pred_df.tail(10))

        # SigAnaRecord（信号分析记录器）专门用于评估预测信号的质量。
        # 其工作原理是加载通过SignalRecord生成的预测结果（pred.pkl）和真实标签（label.pkl），然后计算一系列量化指标来评估预测信号的准确性和有效性。
        # 该分析过程是量化研究中的标准步骤，帮助研究人员判断模型预测信号是否具有实际投资价值。
        # 创建信号分析记录
        sar = SigAnaRecord(recorder)
        # 执行信号分析
        with t_rec.timer("SigAnaRecord.generate"):
            sar.generate()
        # 在 Qlib 中，sig_analysis.pkl文件是由 SigAnaRecord组件在您调用其 generate()方法后自动生成的，并默认保存在当前实验的 记录器（Recorder） 对应的目录下
        # sig_analysis.pkl文件包含了 SigAnaRecord对模型预测信号进行分析后得出的关键量化指标。这些指标是评估策略预测有效性的核心。
        # 通常，该文件会保存一个字典（Dictionary）形式的数据，其中可能包括：
        # IC (Information Coefficient)：预测值与未来实际收益率的相关系数，衡量预测的线性相关性。
        # ICIR (Information Coefficient Information Ratio)：IC的均值与标准差的比率，衡量IC的稳定性和显著性。
        # Rank IC：预测值的排名与未来实际收益率排名的相关系数。
        # 还可能包含其他分析结果，如各时间段的IC序列等。

        # 查看信号分析报告 LoadObjectError: No such file or directory
        # signal_ic_metrics = recorder.load_object("sig_analysis/ic.pkl")
        # signal_ric_metrics = recorder.load_object("sig_analysis/ric.pkl")
        print("信号分析报告")
        # 查看数据结构
        # pprint(signal_ic_metrics)
        # 查看数据结构
        # pprint(signal_ric_metrics)

        # 执行回测并生成分析报告
        # PortAnaRecord 是 QLib 工作流中的组合分析记录器，它通过三个关键参数初始化：
        #   recorder 是之前实验记录器的实例，用于获取已训练的模型model和数据集dataset；
        #   port_analysis_config 是包含策略、执行器和回测参数的配置字典；
        #   day则指定了回测的频率为日级别

        par = PortAnaRecord(recorder, port_analysis_config, "day")  # 传入记录器、回测配置和时间频率
        with t_rec.timer("PortAnaRecord.generate"):
            par.generate()  # 系统会基于配置启动完整的回测流程，包括初始化投资组合、模拟每日交易、计算持仓价值，并最终生成收益率、波动率、夏普比率、最大回撤等指标的分析报告


        # 'The following are analysis results of benchmark return(1day).'
        #                        risk
        # mean               0.000297
        # std                0.009591
        # annualized_return  0.070800
        # information_ratio  0.478475
        # max_drawdown      -0.108001
        # 'The following are analysis results of the excess return without cost(1day).'
        #                        risk
        # mean               0.000512
        # std                0.007390
        # annualized_return  0.121823
        # information_ratio  1.068579
        # max_drawdown      -0.049597
        # 'The following are analysis results of the excess return with cost(1day).'
        #                        risk
        # mean               0.000329
        # std                0.007401
        # annualized_return  0.078281
        # information_ratio  0.685570
        # max_drawdown      -0.057426
        # 'The following are analysis results of indicators(1day).'
        #      value
        # ffr    1.0
        # pa     0.0
        # pos    0.0
        """
        在 Qlib 中，调用 par.generate()生成的回测分析报告默认会保存到本地，主要通过 Qlib 的工作流记录系统进行管理
        报告保存位置与内容
        回测完成后，生成的分析报告和相关数据会以 Python pickle 文件（.pkl格式）的形式，保存在您当前运行的“实验”所对应的记录器中。您可以通过以下步骤获取这些报告：
        获取记录器：首先需要获取执行回测的那个记录器对象。
        加载报告文件：使用记录器的 load_object方法加载特定的报告文件。
        以下是生成的主要分析报告文件及其含义：
        report_normal_1day.pkl：这是核心的每日组合表现报告。它是一个 DataFrame，包含了投资组合每天的关键指标，例如：
            return：投资组合的日收益率
            cost：交易成本
            bench：基准（如沪深300）的日收益率
            turnover：换手率
        positions_normal_1day.pkl：此文件保存了每日详细的持仓信息，包括现金、每个持仓的股票代码、数量、市值、权重等。
        port_analysis_1day.pkl：此文件包含风险分析结果，如计算出的夏普比率、最大回撤等风险指标
        """

        report_normal_df = recorder.load_object("portfolio_analysis/report_normal_1day.pkl")  # 普通报告
        print("普通报告")
        print(report_normal_df.head(10))
        #                  account        return  total_turnover  turnover     total_cost      cost         value          cash     bench
        # datetime
        # 2025-01-02  1.000000e+08  0.000000e+00    0.000000e+00  0.000000       0.000000  0.000000  0.000000e+00  1.000000e+08 -0.029101
        # 2025-01-03  9.995250e+07 -6.184564e-17    9.499240e+07  0.949924   47496.200661  0.000475  9.499240e+07  4.960102e+06 -0.011842
        # 2025-01-06  9.977200e+07 -1.599917e-03    1.177013e+08  0.227197   68087.926556  0.000206  9.906677e+07  7.052291e+05 -0.001640
        # 2025-01-07  9.963182e+07 -1.132319e-03    1.448909e+08  0.272517   95293.228832  0.000273  9.892239e+07  7.094250e+05  0.007201
        # 2025-01-08  9.962876e+07  2.424084e-04    1.720861e+08  0.272957  122502.487049  0.000273  9.891853e+07  7.102330e+05 -0.001815
        # 2025-01-09  9.825507e+07 -1.351865e-02    1.989188e+08  0.269327  149344.902865  0.000269  9.755221e+07  7.028590e+05 -0.002465
        # 2025-01-10  9.710504e+07 -1.143511e-02    2.253884e+08  0.269397  175822.280388  0.000269  9.641307e+07  6.919667e+05 -0.012540
        # 2025-01-13  9.683369e+07 -2.517667e-03    2.522351e+08  0.276471  202686.771864  0.000277  9.613312e+07  7.005769e+05 -0.002671
        # 2025-01-14  9.919015e+07  2.462459e-02    2.802384e+08  0.289189  230718.374729  0.000289  9.846085e+07  7.293065e+05  0.026334
        # 2025-01-15  9.939273e+07  2.323229e-03    3.080876e+08  0.280766  258580.614262  0.000281  9.866534e+07  7.273911e+05 -0.006415
        returns = report_normal_df["return"]
        benchmark_returns = report_normal_df["bench"]

        # 风险分析
        analysis_result = risk_analysis(returns)
        print("=== 风险绩效分析结果 ===")
        pprint_risk_analysis(analysis_result)
        # === 风险绩效分析结果 ===
        # risk: mean                 0.000809
        # std                  0.009135
        # annualized_return    0.192622
        # information_ratio    1.366866
        # max_drawdown        -0.071131
        # Name: risk, dtype: float64

        # benchmark风险分析
        analysis_result = risk_analysis(benchmark_returns)
        print("=== benchmark风险绩效分析结果 ===")
        pprint_risk_analysis(analysis_result)
        # === benchmark风险绩效分析结果 ===
        # risk: mean                 0.000297
        # std                  0.009591
        # annualized_return    0.070800
        # information_ratio    0.478475
        # max_drawdown        -0.108001
        # Name: risk, dtype: float64

        # 计算超额收益的风险指标
        analysis_result = risk_analysis(report_normal_df["return"] - report_normal_df["bench"])
        print("=== 超额收益的风险指标 ===")
        pprint_risk_analysis(analysis_result)
        # === 超额收益的风险指标 ===
        # risk: mean                 0.000512
        # std                  0.007390
        # annualized_return    0.121823
        # information_ratio    1.068579
        # max_drawdown        -0.049597
        # Name: risk, dtype: float64

        positions = recorder.load_object("portfolio_analysis/positions_normal_1day.pkl")  # 持仓记录
        print("持仓记录")
        # 分析最近交易日的持仓
        pprint_position_report(positions)
        # 分析最近交易日的持仓
        analyze_position_by_date(positions)
        # 生成报告
        position_dict = {str(key): value for key, value in positions.items()}
        generate_position_report(position_dict)

        analysis_df = recorder.load_object("portfolio_analysis/port_analysis_1day.pkl")  # 分析报告
        print("分析报告")
        print(analysis_df.head(10))
        #                                                   risk
        # excess_return_without_cost mean               0.000512
        #                            std                0.007390
        #                            annualized_return  0.121823
        #                            information_ratio  1.068579
        #                            max_drawdown      -0.049597
        # excess_return_with_cost    mean               0.000329
        #                            std                0.007401
        #                            annualized_return  0.078281
        #                            information_ratio  0.685570
        #                            max_drawdown      -0.057426

        figures = analysis_position.report_graph(report_df=report_normal_df, show_notebook=False)
        print(
            "展示回测净值可视化结果(不扣费、扣费和基准净值；不扣费净值最大回撤；扣费净值最大回撤；不扣费和扣费超额收益净值；换手率；不扣费超额收益最大回撤；扣费超额收益最大回撤)",
            timer() - start)
        for i, fig in enumerate(figures):
            fig.show()

        figures = analysis_position.risk_analysis_graph(analysis_df=analysis_df, report_normal_df=report_normal_df,
                                                        show_notebook=False)
        print("生成风险分析图表可视化结果(年化收益率\波动率\信息比率\最大回撤)", timer() - start)
        for i, fig in enumerate(figures):
            fig.show()

        with t_rec.timer("dataset_prepare_test_feature_label"):
            data_df = dataset.prepare(segments='test', col_set=['feature', 'label'])
        print(data_df.head(10))
        #                         feature            ...               label
        #                            KMID      KLEN  ...    COST_J    LABEL0
        # datetime   instrument                      ...
        # 2025-01-02 SH600000   -1.094309  1.112157  ...  1.419466  0.008949
        #            SH600009   -1.885474  1.238996  ...       NaN  0.000000
        #            SH600010   -1.844725  1.732232  ...  0.256333  0.011371
        #            SH600011   -2.143927  1.458528  ... -0.898165 -0.002981
        #            SH600015   -2.509159  1.886665  ...  1.472711  0.001351
        #            SH600016   -2.171542  1.984429  ...  1.141696  0.004983
        #            SH600018   -1.323347  0.981285  ...  0.583204 -0.006141
        #            SH600019   -0.624932 -0.027884  ...  1.010373  0.004384
        #            SH600023   -2.076626  1.375968  ...  0.017027 -0.011719
        #            SH600025   -1.655245  1.014867  ... -0.275800 -0.001794
        #
        # [10 rows x 162 columns]
        feature_df = data_df['feature']
        label_df = data_df['label']

        print("feature_df结果head")
        print(feature_df.head(10))
        #                            KMID      KLEN  ...    COST_D    COST_J
        # datetime   instrument                      ...
        # 2025-01-02 SH600000   -1.094309  1.112157  ...  1.337797  1.419466
        #            SH600009   -1.885474  1.238996  ...       NaN       NaN
        #            SH600010   -1.844725  1.732232  ...  0.529145  0.256333
        #            SH600011   -2.143927  1.458528  ... -0.687459 -0.898165
        #            SH600015   -2.509159  1.886665  ...  1.588773  1.472711
        #            SH600016   -2.171542  1.984429  ...  1.224480  1.141696
        #            SH600018   -1.323347  0.981285  ...  0.534174  0.583204
        #            SH600019   -0.624932 -0.027884  ...  1.044818  1.010373
        #            SH600023   -2.076626  1.375968  ...  0.207711  0.017027
        #            SH600025   -1.655245  1.014867  ... -0.070628 -0.275800
        #
        # [10 rows x 161 columns]
        print("label_df结果head")
        print(label_df.head(10))
        #                          LABEL0
        # datetime   instrument
        # 2025-01-02 SH600000    0.008949
        #            SH600009    0.000000
        #            SH600010    0.011371
        #            SH600011   -0.002981
        #            SH600015    0.001351
        #            SH600016    0.004983
        #            SH600018   -0.006141
        #            SH600019    0.004384
        #            SH600023   -0.011719
        #            SH600025   -0.001794
        print("pred_df结果head")
        print(pred_df.head(10))
        # pred_df结果head
        #                           score
        # datetime   instrument
        # 2025-01-02 SH600000   -0.000373
        #            SH600009   -0.000373
        #            SH600010   -0.000373
        #            SH600011   -0.000373
        #            SH600015   -0.000373
        #            SH600016   -0.000373
        #            SH600018   -0.000373
        #            SH600019   -0.000373
        #            SH600023   -0.000373
        #            SH600025   -0.000373
        label_df = dataset.prepare("test", col_set="label")
        label_df.columns = ['label']
        pred_label = pd.concat([label_df, pred_df], axis=1, sort=True).reindex(label_df.index)
        print("pred_label结果head")
        print(pred_label.head(10))
        pred_label.to_csv('预测结果和真实标签.csv', encoding='utf-8')
        #                           label     score
        # datetime   instrument
        # 2025-01-02 SH600000    0.008949 -0.000373
        #            SH600009    0.000000 -0.000373
        #            SH600010    0.011371 -0.000373
        #            SH600011   -0.002981 -0.000373
        #            SH600015    0.001351 -0.000373
        #            SH600016    0.004983 -0.000373
        #            SH600018   -0.006141 -0.000373
        #            SH600019    0.004384 -0.000373
        #            SH600023   -0.011719 -0.000373
        #            SH600025   -0.001794 -0.000373

        # 假设 pred_label 是一个DataFrame，包含模型的预测得分（'score'）和真实收益率（'label'）
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