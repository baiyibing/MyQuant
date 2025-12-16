import multiprocessing
import logging
import os
from timeit import default_timer as timer

from loguru import logger
import pandas as pd
import qlib
from qlib.config import REG_CN
from qlib.utils import init_instance_by_config
from qlib.workflow import R
from qlib.data import D
from qlib.data.filter import ExpressionDFilter, NameDFilter
from custom_handler import Alpha158CostKDJ
from custom_ops import SMA
from custom_utils import pprint_position_report, analyze_position_by_date, generate_position_report, \
    pprint_risk_analysis
import plotly.graph_objects as go
from qlib.contrib.evaluate import risk_analysis
from qlib.contrib.report.analysis_position import report_graph
from qlib.workflow.record_temp import PortAnaRecord

if __name__ == '__main__':
    multiprocessing.freeze_support()

    print(qlib.__version__)

    start = timer()

    logger.remove(0)
    logger.add("backtest.log")

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

    # 从文件读取最后一个实验ID，或让用户输入
    rid = None
    exp_name = None
    try:
        with open("last_experiment_info.txt", 'r', encoding='utf-8') as f:
            content = f.read().strip()
            print(f"文件内容: {content}")

            # 检查文件格式是否符合预期
            if '=' in content:
                rid, exp_name = content.split('=', 1)  # 只分割一次，防止exp_name中有等号
                rid = rid.strip()
                exp_name = exp_name.strip()

                print(f"成功提取 - 实验ID: {rid}")
                print(f"成功提取 - 实验名称: {exp_name}")
            else:
                print(f"文件格式不正确，期望格式: rid=exp_name")

    except FileNotFoundError:
        print(f"错误: 找不到文件")
    except Exception as e:
        print(f"读取文件时发生错误: {e}")

    if not rid or not exp_name:
        print("错误: 未提供实验ID和名称")
        exit(1)

    # 获取实验记录器
    try:
        recorder = R.get_recorder(recorder_id=rid, experiment_name=exp_name)  # 根据rid获取训练记录器
        print(f"成功加载实验记录器: {rid}")
    except Exception as e:
        print(f"加载实验记录器失败: {e}")
        print("可用的实验记录:")
        try:
            experiments = R.list_experiments()
            for exp in experiments:
                print(f"实验: {exp}")
                recorders = R.list_recorders(experiment_name=exp)
                for rec in recorders:
                    print(f"  - 记录器ID: {rec}")
        except:
            pass
        exit(1)

    # 从recorder加载所有保存的对象
    try:
        model = recorder.load_object("trained_model")
        model_config = recorder.load_object("model_config")
        dataset_config = recorder.load_object("dataset_config")
        data_handler_config = recorder.load_object("data_handler_config")
        backtest_config = recorder.load_object("backtest_config")

        test_start_time = backtest_config["test_start_time"]
        test_end_time = backtest_config["test_end_time"]
        benchmark = backtest_config["benchmark"]

        print("成功加载训练好的模型和配置")
        print(f"回测时间段: {test_start_time} 至 {test_end_time}")
        print(f"基准: {benchmark}")

    except Exception as e:
        print(f"加载模型或配置失败: {e}")
        exit(1)

    # 重新创建数据集（使用测试时间段）
    dataset_config['kwargs']['segments'] = {
        'test': (test_start_time, test_end_time)
    }

    dataset = init_instance_by_config(dataset_config)
    print("数据集创建完成")

    # 回测配置
    port_analysis_config = {
        "executor": {
            "class": "SimulatorExecutor",
            "module_path": "qlib.backtest.executor",
            "kwargs": {
                "time_per_step": "day",
                "generate_portfolio_metrics": True,
            },
        },
        "strategy": {
            "class": "TopkDropoutStrategyWithFilter",
            "module_path": "custom_strategy",
            "kwargs": {
                "model": model,
                "dataset": dataset,
                "topk": 10,
                "n_drop": 3,
                "hold_thresh": 1
            },
        },
        "backtest": {
            "start_time": test_start_time,
            "end_time": test_end_time,
            "account": 100000000,
            "benchmark": benchmark,
            "exchange_kwargs": {
                "freq": "day",
                "limit_threshold": 0.095,
                "deal_price": "close",
                "open_cost": 0.0005,
                "close_cost": 0.0015,
                "min_cost": 5,
            },
        },
    }

    # 执行回测
    print("开始回测...")
    par = PortAnaRecord(recorder, port_analysis_config, "day")
    par.generate()
    print("回测完成")

    # 加载回测结果
    try:
        report_normal_df = recorder.load_object("portfolio_analysis/report_normal_1day.pkl")
        positions = recorder.load_object("portfolio_analysis/positions_normal_1day.pkl")
        analysis_df = recorder.load_object("portfolio_analysis/port_analysis_1day.pkl")

        print("成功加载回测结果")
    except Exception as e:
        print(f"加载回测结果失败: {e}")
        exit(1)

    # 分析结果
    print("\n=== 回测结果分析 ===")

    # 风险分析
    returns = report_normal_df["return"]
    benchmark_returns = report_normal_df["bench"]

    analysis_result = risk_analysis(returns)
    print("=== 组合风险绩效分析结果 ===")
    pprint_risk_analysis(analysis_result)

    analysis_result = risk_analysis(benchmark_returns)
    print("=== 基准风险绩效分析结果 ===")
    pprint_risk_analysis(analysis_result)

    # 超额收益分析
    analysis_result = risk_analysis(report_normal_df["return"] - report_normal_df["bench"])
    print("=== 超额收益风险指标 ===")
    pprint_risk_analysis(analysis_result)

    # 持仓分析
    print("\n=== 持仓分析 ===")
    analyze_position_by_date(positions)

    # 生成持仓报告
    position_dict = {str(key): value for key, value in positions.items()}
    generate_position_report(position_dict)

    # 可视化结果
    try:
        from qlib.contrib.report import analysis_position

        figures = analysis_position.report_graph(report_df=report_normal_df, show_notebook=False)
        print("生成回测净值图表")
        for i, fig in enumerate(figures):
            fig.write_image(f"backtest_chart_{i}.png")
            print(f"图表已保存为 backtest_chart_{i}.png")

        figures = analysis_position.risk_analysis_graph(analysis_df=analysis_df, report_normal_df=report_normal_df,
                                                        show_notebook=False)
        print("生成风险分析图表")
        for i, fig in enumerate(figures):
            fig.write_image(f"risk_analysis_chart_{i}.png")
            print(f"图表已保存为 risk_analysis_chart_{i}.png")

    except Exception as e:
        print(f"图表生成失败: {e}")

    # 保存详细结果到CSV
    report_normal_df.to_csv('backtest_results.csv', encoding='utf-8')
    print("回测结果已保存到 backtest_results.csv")

    print("\n✅ 回测完成！总耗时:", timer() - start)
    print(f"实验ID: {rid}")
    print(f"回测期间: {test_start_time} 至 {test_end_time}")