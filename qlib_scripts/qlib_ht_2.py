import multiprocessing
import logging

from timeit import default_timer as timer

from astropy.extern.ply.ctokens import t_STRING
from loguru import logger

import qlib  # 导入Qlib核心库
import pandas as pd  # 导入pandas库进行数据处理
from qlib.constant import REG_CN  # 导入中国区域常量
from qlib.utils import init_instance_by_config, flatten_dict  # 导入根据配置初始化实例和扁平化字典的工具函数
from qlib.workflow import R  # 导入工作流管理模块，用于实验记录和管理
from qlib.workflow.record_temp import SignalRecord, PortAnaRecord  # 导入生成信号和组合分析记录的工具类

from tdx_ops import SMA

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

    print(u'qlib.init', timer() - start)

    # 定义策略相关的市场和分析基准
    market = "csi300"  # 设置股票池为沪深300指数成分股
    benchmark = "SH000300"  # 设置业绩比较基准为沪深300指数代码

    # 定义数据处理器配置，指定数据获取的时间范围、训练集时间区间和投资标的
    data_handler_config = {
        "start_time": "2008-01-01",  # 整体数据开始时间
        "end_time": "2020-08-01",  # 整体数据结束时间
        "fit_start_time": "2008-01-01",  # 特征计算起始时间（通常与start_time一致）
        "fit_end_time": "2014-12-31",  # 特征计算结束时间（训练集截止时间）
        "instruments": market,  # 投资标的，这里使用前面定义的market（csi300）
    }

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
            },
        },
        "dataset": {  # 数据集配置部分
            "class": "DatasetH",  # 使用DatasetH数据集类,负责将数据划分为训练集、验证集和测试集，并提供数据加载接口
            "module_path": "qlib.data.dataset",  # 数据集所在的模块路径
            "kwargs": {  # 传递给数据集构造函数的参数
                "handler": {  # 数据处理器配置
                    "class": "Alpha158",  # 使用Alpha158特征集,一个预定义的数据处理器，它实现了 158 个常用的 Alpha 因子
                    "module_path": "qlib.contrib.data.handler",  # 数据处理器所在模块路径
                    "kwargs": data_handler_config,  # 使用前面定义的data_handler_config
                },
                "segments": {  # 定义数据集的分段（训练集、验证集、测试集）
                    "train": ("2008-01-01", "2014-12-31"),  # 训练集时间范围
                    "valid": ("2015-01-01", "2016-12-31"),  # 验证集时间范围
                    "test": ("2017-01-01", "2020-08-01"),  # 测试集时间范围
                },
            },
        },
    }

    # 通过配置动态初始化模型和数据集实例
    # QLib 采用了基于配置的设计理念，几乎所有组件都可以通过配置字典来定义。init_instance_by_config() 函数则负责将这些配置字典转换为实际的对象实例：
    # 这种设计有几个好处：首先，它使得组件的定义更加灵活，可以通过修改配置而不是代码来改变组件行为；其次，它便于序列化和存储实验配置，有利于实验的可复现性。
    model = init_instance_by_config(task["model"])  # 根据model配置创建模型实例
    print(u'根据model配置创建模型实例', timer() - start)
    dataset = init_instance_by_config(task["dataset"])  # 根据dataset配置创建数据集实例
    print(u'根据dataset配置创建数据集实例', timer() - start)

    t_start = timer()

    rid = None

    # 开始一个名为"train_model"的实验工作流，用于组织模型训练过程[6](@ref)
    with R.start(experiment_name="train_model"):
        R.log_params(**flatten_dict(task))  # 将任务配置参数扁平化后记录到实验中，便于追踪
        model.fit(dataset)  # 在训练集上训练模型，并在验证集上进行验证
        R.save_objects(trained_model=model)  # 将训练好的模型保存到当前实验记录中
        rid = R.get_recorder().id  # 获取当前实验记录器的ID，用于后续检索

    print(u'模型训练完成', rid,timer() - t_start)


