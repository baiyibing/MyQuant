import multiprocessing
import logging
import os
from timeit import default_timer as timer

from loguru import logger
import pandas as pd
import qlib
from qlib.config import REG_CN
from qlib.utils import init_instance_by_config, flatten_dict
from qlib.workflow import R
from qlib.data import D
from qlib.data.filter import ExpressionDFilter, NameDFilter
from custom_handler import Alpha158CostKDJ
from custom_ops import SMA
from pprint import pprint

if __name__ == '__main__':
    multiprocessing.freeze_support()

    print(qlib.__version__)

    start = timer()

    logger.remove(0)
    logger.add("Filter.log", filter=lambda record: record["module"] == "custom_strategy")
    logger.add("orders.log", filter=lambda record: record["module"] != "custom_strategy")

    qlib.init(
        provider_uri="~/.qlib/qlib_data/my_data",
        region=REG_CN,
        kernels=16,
        redis_host='127.0.0.1',
        redis_port=6379,
        redis_password='123456',
        redis_task_db=1,
        custom_ops=[SMA],
        exp_manager={
            "class": "MLflowExpManager",
            "module_path": "qlib.workflow.expm",
            "kwargs": {
                "uri": "mlruns",
                "default_exp_name": "MyExperiment",
            }
        },
        logging_level=logging.INFO
    )

    pd.set_option('display.max_rows', None)
    pd.set_option('display.max_columns', None)
    pd.set_option('display.max_colwidth', None)
    pd.set_option('display.width', None)

    # 时间配置
    start_time = "2020-01-01"
    end_time = "2025-12-12"
    fit_start_time = start_time
    fit_end_time = "2023-12-31"
    valid_start_time = "2024-01-01"
    valid_end_time = "2024-12-31"
    test_start_time = "2025-01-01"
    test_end_time = end_time

    # 排除股票列表
    exclude_stocks = ['SZ000004', 'SZ000430', 'SZ000488', 'SZ000504', 'SZ000518', 'SZ000595', 'SZ000608', 'SZ000609',
                      'SZ000615', 'SZ000638', 'SZ000656', 'SZ000668', 'SZ000669', 'SZ000691', 'SZ000697', 'SZ000698',
                      'SZ000711', 'SZ000736', 'SZ000752', 'SZ000793', 'SZ000820', 'SZ000903', 'SZ000908', 'SZ000909',
                      'SZ000929', 'SZ000972', 'SZ001270', 'SZ002005', 'SZ002024', 'SZ002047', 'SZ002058', 'SZ002076',
                      'SZ002122', 'SZ002168', 'SZ002197', 'SZ002199', 'SZ002200', 'SZ002211', 'SZ002214', 'SZ002231',
                      'SZ002253', 'SZ002289', 'SZ002305', 'SZ002306', 'SZ002388', 'SZ002425', 'SZ002485', 'SZ002496',
                      'SZ002528', 'SZ002529', 'SZ002569', 'SZ002581', 'SZ002586', 'SZ002592', 'SZ002620', 'SZ002630',
                      'SZ002647', 'SZ002650', 'SZ002656', 'SZ002693', 'SZ002713', 'SZ002717', 'SZ002742', 'SZ002762',
                      'SZ002789', 'SZ002808', 'SZ002816', 'SZ002822', 'SZ002848', 'SZ002868', 'SZ002872', 'SZ002898',
                      'SZ003004', 'SZ003032', 'SZ300020', 'SZ300029', 'SZ300044', 'SZ300052', 'SZ300093', 'SZ300096',
                      'SZ300097', 'SZ300125', 'SZ300137', 'SZ300147', 'SZ300152', 'SZ300159', 'SZ300165', 'SZ300167',
                      'SZ300175', 'SZ300198', 'SZ300205', 'SZ300211', 'SZ300225', 'SZ300237', 'SZ300268', 'SZ300301',
                      'SZ300311', 'SZ300313', 'SZ300326', 'SZ300338', 'SZ300343', 'SZ300344', 'SZ300366', 'SZ300376',
                      'SZ300379', 'SZ300391', 'SZ300419', 'SZ300462', 'SZ300472', 'SZ300477', 'SZ300506', 'SZ300527',
                      'SZ300555', 'SZ300561', 'SZ300716', 'SZ300899', 'SZ301288', 'SH600107', 'SH600130', 'SH600136',
                      'SH600165', 'SH600169', 'SH600193', 'SH600200', 'SH600228', 'SH600238', 'SH600243', 'SH600265',
                      'SZ600289', 'SH600355', 'SH600358', 'SH600360', 'SH600365', 'SH600381', 'SH600421', 'SH600525',
                      'SH600568', 'SH600599', 'SH600608', 'SH600624', 'SH600636', 'SH600696', 'SH600735', 'SH600753',
                      'SH600777', 'SH600892', 'SH603007', 'SH603021', 'SH603261', 'SH603268', 'SH603377', 'SH603388',
                      'SH603389', 'SH603398', 'SH603517', 'SH603557', 'SH603559', 'SH603580', 'SH603595', 'SH603721',
                      'SH603789', 'SH603813', 'SH603825', 'SH603828', 'SH603838', 'SH603843', 'SH603869', 'SH605081',
                      'SH605199', 'SH688053', 'SH688076', 'SH688184', 'SH688287', 'SH688511', 'SH688646', 'BJ920305',
                      'BJ920680']

    exclude_filter_1 = NameDFilter(name_rule_re='^(?!(' + '|'.join(exclude_stocks[:11*8]) + ')).*$')

    exclude_filter_2 = NameDFilter(name_rule_re='^(?!(' + '|'.join(exclude_stocks[11*8+1:]) + ')).*$')

    expression_rule = """
    (
        ($close - Ref($close,5)) / Ref($close,5) < -0.10
    )
    """
    dynamic_filter = ExpressionDFilter(rule_expression=expression_rule)

    # 获取筛选后的股票列表
    filtered_instruments = D.instruments(market='all',
                                         start_time=start_time,
                                         end_time=end_time,
                                         filter_pipe=[exclude_filter_1,exclude_filter_2])

    benchmark = "SH601727"
    exp_name = "alpha158_cost_kdj_lgb"

    # 数据处理器配置
    data_handler_config = {
        "start_time": start_time,
        "end_time": end_time,
        "fit_start_time": fit_start_time,
        "fit_end_time": fit_end_time,
        "infer_processors": [
            {"class": "ProcessInf"},
            {"class": "RobustZScoreNorm", "kwargs": {"fields_group": "feature"}},
            {"class": "Fillna", "kwargs": {"method": "ffill"}}
        ],
        "instruments": filtered_instruments,
        "include_alpha158": True,
        "include_cost_kdj": True,
        "include_signal": False,
        "include_lz": True,
    }

    # 任务配置
    task = {
        "model": {
            "class": "LGBModel",
            "module_path": "qlib.contrib.model.gbdt",
            "kwargs": {
                "loss": "mse",
                "colsample_bytree": 0.8879,
                "learning_rate": 0.0421,
                "subsample": 0.8789,
                "lambda_l1": 205.6999,
                "lambda_l2": 580.9768,
                "max_depth": 8,
                "num_leaves": 210,
                "num_threads": 20,
            },
        },
        "dataset": {
            "class": "DatasetH",
            "module_path": "qlib.data.dataset",
            "kwargs": {
                "handler": {
                    "class": "Alpha158CostKDJ",
                    "module_path": "custom_handler",
                    "kwargs": data_handler_config,
                },
                "segments": {
                    "train": (fit_start_time, fit_end_time),
                    "valid": (valid_start_time, valid_end_time),
                    "test": (test_start_time, test_end_time),
                },
            },
        },
    }

    # 训练模型
    with R.start(experiment_name=exp_name):
        R.log_params(**flatten_dict(task))  # 将任务配置参数扁平化后记录到实验中，便于追踪

        # 创建模型和数据集实例
        model = init_instance_by_config(task["model"])
        dataset = init_instance_by_config(task["dataset"])

        print('开始训练模型...', timer() - start)
        model.fit(dataset)
        print('模型训练完成', timer() - start)

        # 保存模型和所有配置信息
        R.save_objects(
            trained_model=model,
            model_config=task["model"],
            dataset_config=task["dataset"],
            data_handler_config=data_handler_config,
            backtest_config={
                "test_start_time": test_start_time,
                "test_end_time": test_end_time,
                "benchmark": benchmark
            }
        )

        recorder = R.get_recorder()

        # 生成预测信号用于验证
        from qlib.workflow.record_temp import SignalRecord

        sr = SignalRecord(model, dataset, recorder)
        sr.generate()

        rid = recorder.id
        print(f"模型训练完成，实验ID: {rid}")

        # 将实验ID和实验名称写入文件
        with open(f"last_experiment_info_{start_time}_{end_time}.txt", "w") as f:
            f.write(f"{rid}={exp_name}\n")

    print("✅ 模型训练完成并保存！总耗时:", timer() - start)