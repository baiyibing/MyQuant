from pathlib import Path
from typing import Union
import logging
from qlib.constant import REG_CN
from qlib.contrib.rolling.base import Rolling
from loguru import logger
from custom_ops import SMA

# from qlib.tests.data import GetData
# import fire
# from qlib import auto_init

DIRNAME = Path(__file__).absolute().resolve().parent
CONF_LIST = [
    DIRNAME / "workflow_config_linear_Alpha158.yaml",
    DIRNAME / "workflow_config_lightgbm_Alpha158.yaml",
    DIRNAME / "workflow_config_linear_Alpha158_no_valid.yaml",
    DIRNAME / "workflow_config_linear_Alpha158_baostock.yaml",
    DIRNAME / "workflow_config_lightgbm_Alpha158_lz.yaml",
    DIRNAME / "workflow_config_lightgbm_Alpha158_20.yaml",
]




class RollingBenchmark(Rolling):

    def __init__(self,
                 conf_path: Union[str, Path] = None,
                 horizon=20,
                 **kwargs) -> None:

        print('conf_path', conf_path)
        super().__init__(conf_path=conf_path, horizon=horizon, **kwargs)




if __name__ == "__main__":
    logger.remove(0)
    logger.add("orders.log")
    #####################################
    # 0 删除缓存数据集handler pkl文件
    #####################################
    import os
    from os import listdir
    pkl_path = os.path.dirname(__file__)  # 当前文件所在的目录
    for file_name in listdir(pkl_path):
        if file_name.endswith('.pkl'):
            os.remove(pkl_path + '/' + file_name)

    ###################################
    # 1 滚动训练与预测
    ###################################
    import qlib
    exp_name = "combine"  # 合并预测结果pred.pkl存放mlflow实验名
    rb = RollingBenchmark(
        conf_path=CONF_LIST[4],
        step=20,  # 滚动步长，每隔20天滚动训练一次，它也决定了每滚测试集长度为20天
        horizon=20,  # 收益率预测期长度
        exp_name=exp_name)  # 最终合并预测结果所在实验名

    config_dict = rb._raw_conf()  # 配置字典
    print(config_dict)
    print('provider_uri',config_dict["qlib_init"]["provider_uri"])

    # 初始化qlib
    # qlib.init(provider_uri=config_dict["qlib_init"]["provider_uri"],
    #           region=config_dict["qlib_init"]["region"])

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
        # exp_manager={
        #     "class": "MLflowExpManager",
        #     "module_path": "qlib.workflow.expm",
        #     "kwargs": {
        #         "uri": "mlruns",
        #         "default_exp_name": "MyExperiment",
        #     }
        # },
        # 设置日志级别，控制输出信息的详细程度：常用的日志级别有 DEBUG、INFO、WARNING、ERROR，级别从低到高，级别越低输出信息越详细。
        logging_level=logging.DEBUG
        # logging_level=logging.INFO
    )

    # 滚动训练与预测
    rb._train_rolling_tasks()

    #################################
    # 2 滚动预测结果合并成大预测结果：每步小测试期预测结果合并成大测试期预测结果
    #################################
    rb._ens_rolling()
    # 打印合并后预测结果文件所在实验id，实验名和记录id
    print('experiment_id', rb._experiment_id, 'exp_name', exp_name, 'rid',
          rb._rid)

    #################################
    # 3 qlib信号分析与回测：在大测试期里执行信号分析与回测
    #################################
    # 回测:记录信号分析结果（如IC等）和回测结果（如仓位情况等）
    rb._update_rolling_rec()

    # 打印合并后预测结果文件所在实验id，实验名和记录id。回测结果也在此实验和记录id下。
    print('experiment_id', rb._experiment_id, 'exp_name', exp_name, 'rid',
          rb._rid)
