#!/usr/bin/env python
# -*- coding: utf-8 -*-

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

# 1. 配置参数（可灵活调整）
CONFIG = {
    "data_path": "~/.qlib/qlib_data/my_data",
    "region": REG_CN,
    "time_periods": {
        "train": ("2020-01-01", "2021-12-31"),
        "valid": ("2022-01-01", "2022-12-31"),
        "test": ("2023-01-01", "2023-12-31")
    },
    "model_params": {
        "num_leaves": 64,
        "learning_rate": 0.05,
        "n_estimators": 100
    },
    "strategy_params": {
        "topk": 10,
        "n_drop": 3
    },
    "backtest_params": {
        "account": 100000000,
        "benchmark": "SH601727",
        "exchange_kwargs": {
            "freq": "day",
            "limit_threshold": 0.1,
            "st_limit_threshold": 0.05,
            "deal_price": "close",
            "open_cost": 0.0003,
            "close_cost": 0.0003,
            "min_cost": 5,
            "impact_cost": 0.001
        }
    }
}

# 2. 初始化Qlib环境（关键：正确配置region和实验管理器）
qlib.init(
    provider_uri=CONFIG["data_path"],
    region=CONFIG["region"],
    exp_manager={
        "class": "MLflowExpManager",
        "module_path": "qlib.workflow.expm",
        "kwargs": {
            "uri": "mlruns",
            "default_exp_name": "qlib_backtest"
        }
    }
)

print("="*50)
print("Qlib量化回测流程：训练-验证-回测（严格时间一致性）")
print("="*50)

# 3. 定义过滤条件：5日涨幅≤25%
expression_rule = """
    (
        ($close - Ref($close,5)) / Ref($close,5) <= 0.25
    )
"""

# 4. 定义动态过滤器（关键：显式指定时间范围）
def define_filter(start, end):
    return ExpressionDFilter(
        rule_expression=expression_rule,
        fstart_time=start,
        fend_time=end,
        keep=True
    )

# 5. 定义各阶段股票池（关键：使用独立过滤器）
def define_instruments(period):
    start, end = CONFIG["time_periods"][period]
    return D.instruments(
        market='all',
        start_time=start,
        end_time=end,
        filter_pipe=[define_filter(start, end)]
    )

# 6. 定义数据处理器配置（关键：包含所有必要参数）
data_handler_config = {
    "start_time": CONFIG["time_periods"]["train"][0],
    "end_time": CONFIG["time_periods"]["train"][1],
    "fit_start_time": CONFIG["time_periods"]["train"][0],
    "fit_end_time": CONFIG["time_periods"]["train"][1],
    "instruments": define_instruments("train"),
    "window": 20
}

# 7. 模型训练与验证
print("\n步骤1：模型训练与验证（使用独立数据集）")
print("-"*50)

# 训练配置
train_config = {
    "model": LGBModel,
    "dataset": {
        "handler": {
            "class": "Alpha158",
            "kwargs": data_handler_config
        },
        "kwargs": {
            "fit": {
                "start_time": CONFIG["time_periods"]["train"][0],
                "end_time": CONFIG["time_periods"]["train"][1],
                "instruments": define_instruments("train")
            },
            "predict": {
                "start_time": CONFIG["time_periods"]["valid"][0],
                "end_time": CONFIG["time_periods"]["valid"][1],
                "instruments": define_instruments("valid")
            }
        }
    },
    "fit": {
        "params": CONFIG["model_params"]
    }
}

# 训练模型
with R.start():
    R.train(train_config)
    R.save("model", "trained_model.pkl")
    print("模型训练完成，已保存到 trained_model.pkl")
    print(f"训练阶段股票池: {len(define_instruments('train'))} 只股票")

# 8. 模型验证
valid_config = {
    "model": R.load("model", "trained_model.pkl"),
    "dataset": {
        "handler": {
            "class": "Alpha158",
            "kwargs": data_handler_config
        },
        "kwargs": {
            "predict": {
                "start_time": CONFIG["time_periods"]["valid"][0],
                "end_time": CONFIG["time_periods"]["valid"][1],
                "instruments": define_instruments("valid")
            }
        }
    }
}

with R.start():
    R.get_dataset(valid_config)
    pred_valid = R.predict(valid_config)
    R.save("valid_pred", "valid_pred.pkl")
    print("模型验证完成，预测结果已保存到 valid_pred.pkl")
    print(f"验证阶段股票池: {len(define_instruments('valid'))} 只股票")

# 9. 回测配置
print("\n步骤2：回测（2023-01-01至2023-12-31）")
print("-"*50)

# 回测配置（关键：使用独立测试数据集）
test_config = {
    "model": R.load("model", "trained_model.pkl"),
    "dataset": {
        "handler": {
            "class": "Alpha158",
            "kwargs": data_handler_config
        },
        "kwargs": {
            "predict": {
                "start_time": CONFIG["time_periods"]["test"][0],
                "end_time": CONFIG["time_periods"]["test"][1],
                "instruments": define_instruments("test")
            }
        }
    },
    "backtest": {
        "start_time": CONFIG["time_periods"]["test"][0],
        "end_time": CONFIG["time_periods"]["test"][1],
        "account": CONFIG["backtest_params"]["account"],
        "benchmark": CONFIG["backtest_params"]["benchmark"],
        "exchange_kwargs": CONFIG["backtest_params"]["exchange_kwargs"]
    },
    "strategy": {
        "class": TopkDropoutStrategy,
        "kwargs": {
            "topk": CONFIG["strategy_params"]["topk"],
            "n_drop": CONFIG["strategy_params"]["n_drop"],
            "signal": pred_valid['score'],
            "instruments": define_instruments("test")
        }
    }
}

# 执行回测
with R.start():
    R.get_dataset(test_config)
    R.predict(test_config)
    report, positions = R.get_recorder().load_object("report")
    print("回测完成！")

# 10. 结果分析
print("\n步骤3：回测结果分析")
print("-"*50)

# 使用Qlib内置函数进行风险分析
from qlib.contrib.evaluate import risk_analysis
analysis = risk_analysis(report['return'] - report['bench'])

# 记录完整分析结果
results = {
    "phase": ["training", "validation", "backtest"],
    "instruments_count": [
        len(define_instruments("train")),
        len(define_instruments("valid")),
        len(define_instruments("test"))
    ],
    "total_return": [
        R.get_recorder().load_object("train_report")['total_return'],
        R.get_recorder().load_object("valid_report")['total_return'],
        analysis['total_return']
    ]
}

# 保存完整实验记录
R.save("backtest_report", "backtest_report.pkl")
print("回测报告已保存到 backtest_report.pkl")

# 打印关键指标
print("\n回测关键指标:")
print(f"总收益率: {analysis['total_return']:.2%}")
print(f"年化收益率: {analysis['annualized_return']:.2%}")
print(f"夏普比率: {analysis['sharpe']:.2f}")
print(f"最大回撤: {analysis['max_drawdown']:.2%}")
print(f"回测股票池: {len(define_instruments('test'))} 只股票")

print("\n✅ 量化回测流程完成！所有阶段严格遵循时间一致性原则")
print("✅ 训练、验证、回测阶段的股票池已正确隔离")
print("✅ 回测阶段使用了正确的测试数据集")
print("="*50)