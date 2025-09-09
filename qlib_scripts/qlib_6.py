# https://www.wuzao.com/qlib/tutorial/introduction
import multiprocessing
import qlib
import logging
from qlib.data import D
from qlib.data.filter import NameDFilter
from qlib.constant import REG_CN    # 中国市场

# python scripts/get_data.py qlib_data --target_dir ~/.qlib/qlib_data/cn_data --region cn
# 下载会报错，元宝建议从https://github.com/chenditc/investment_data/releases/latest/download/qlib_bin.tar.gz下载解压到~/.qlib/qlib_data/cn_data

# qlib.init(provider_uri='~/.qlib/qlib_data/cn_data', region=REG_CN)    ~ 表示当前用户的“home”目录

# qlib.init(provider_uri='./.qlib/qlib_data/cn_data', region=REG_CN)

# 初始化完成后，可以通过以下方式验证是否成功：如果能够成功输出交易日历和股票列表，说明初始化成功。

# ... 导入其他需要的模块

if __name__ == '__main__':
    multiprocessing.freeze_support() # 添加这一行，特别是在 Windows 上打包时可能有帮助

    print(qlib.__version__)  # 如果能够打印出版本号，说明安装成功

    qlib.init(
        # 数据存储路径
        provider_uri='E:/PycharmProjects/MyQuant/.qlib/qlib_data/cn_data',
        # 中国市场
        region=REG_CN,
        # QLib 使用 Redis 进行缓存和锁机制,如果 Redis 连接失败，QLib 会自动降级为不使用缓存，这可能会影响性能但不会导致程序错误。
        redis_host='127.0.0.1',
        redis_port=6379,
        redis_password='123456',
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
        logging_level=logging.INFO
        # redis={
        #     "host": "localhost",  # 若Redis在远程服务器，请填写服务器IP
        #     "port": 6379,
        #     "password": "123456",  # 请替换为你的实际密码
        #     "db": 1
        # }
    )

    from qlib.data.dataset.loader import QlibDataLoader

    # 定义要加载的字段
    fields = ['$open', '$close', '$high', '$low', '$volume']
    # loader = QlibDataLoader(fields=fields)

    data_loader_config = {
        "feature": (fields),
        # (表达式列表, 列名列表)
        # "label": (['$close'], ['CLOSE'])  # (表达式列表, 列名列表)
    }

    # 创建数据加载器
    loader = QlibDataLoader(data_loader_config)

    # 加载数据
    data = loader.load(instruments='csi300', start_time='2010-01-01', end_time='2020-12-31')

    print(f"特征数据形状: {data.shape}")
    print(data.head())