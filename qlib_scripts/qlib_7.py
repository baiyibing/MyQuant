import multiprocessing
import qlib
import logging
from qlib.data import D
from qlib.data.filter import NameDFilter
from qlib.constant import REG_CN    # 中国市场

# 常用数据处理器

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

    """
        from qlib.data.dataset.processor import ZScoreNorm, Fillna, DropnaProcessor
        from qlib.data.dataset.handler import DataHandlerLP

        # 定义处理器管道
        processors = [
            Fillna(fill_value=0),  # 用 0 填充缺失值
            ZScoreNorm(),  # Z 分数标准化
            DropnaProcessor()  # 删除仍然包含缺失值的样本
        ]

        # 创建数据处理器
        handler = DataHandlerLP(
            instruments='csi300',
            start_time='2010-01-01',
            end_time='2020-12-31',
            processors=processors,
            infer_processors=True
        )

        # 获取处理后的数据
        data = handler.fetch()
    """


    from qlib.data.dataset.handler import DataHandlerLP
    from qlib.data.dataset.processor import (
        RobustZScoreNorm,  # 对数据进行 Z 分数标准化
        CSZScoreNorm, # 使用CSZScoreNorm(截面标准化)代替普通的ZscoreNorm，更适合横截面金融数据
        MinMaxNorm, # 对数据进行最小-最大标准化
        Fillna,
        DropnaLabel,
        DropnaProcessor, # 删除包含缺失值的样本
        TanhProcess # TanhProcess可限制极端值
    )
    from qlib.data.dataset.loader import QlibDataLoader
    from qlib.constant import REG_CN

    # 初始化Qlib (必须步骤)
    # qlib.init(provider_uri="~/.qlib/qlib_data/cn_data", region=REG_CN)

    # 1. 创建数据加载器 (新版Qlib推荐显式定义)
    data_loader = QlibDataLoader(
        config={
            "feature": (  # 定义特征组
                ['$open', '$high', '$low', '$close', '$volume', '$factor'],  # 基础特征表达式
                ['open', 'high', 'low', 'close', 'volume', 'factor']  # 对应的特征名称
            )
        }
    )

    # 2. 定义处理器管道 (新版处理器分类更细致) 处理器现在分为shared_processors(共享)、learn_processors(训练)和infer_processors(推理)，更适合生产环境
    # shared_processors(共享)
    shared_processors = [
        Fillna(fill_value=0),  # 用0填充缺失值
    ]
    # learn_processors(训练)
    learn_processors = [
        DropnaLabel(),         # 删除标签缺失的数据
        CSZScoreNorm(),        # 截面Z分数标准化 (更适合金融数据)
    ]
    # infer_processors(推理)
    infer_processors = [
        RobustZScoreNorm(fit_start_time='2008-01-01',fit_end_time='2014-12-31'),    # 鲁棒Z分数标准化 (减少异常值影响)
    ]

    # 3. 创建数据处理器 (参数名称和结构有更新)
    handler = DataHandlerLP(
        instruments='csi300',           # 沪深300成分股
        start_time='2008-01-01',        # 开始时间
        end_time='2020-12-31',          # 结束时间
        data_loader=data_loader,        # 数据加载器
        shared_processors=shared_processors,  # 共享处理器
        learn_processors=learn_processors,     # 训练处理器
        infer_processors=infer_processors,     # 推理处理器
        process_type=DataHandlerLP.PTYPE_A,    # 追加处理模式
        drop_raw=False                  # 保留原始数据用于调试
    )

    # 4. 执行数据处理
    handler.fit_process_data()  # 新版推荐方法，一次性完成fit和处理

    # 5. 获取处理后的数据 (支持多种数据键)
    train_data = handler.fetch(data_key=DataHandlerLP.DK_L)  # 训练数据
    infer_data = handler.fetch(data_key=DataHandlerLP.DK_I)  # 推理数据
    all_data = handler.fetch()  # 所有数据

    print(f"训练数据形状: {train_data.shape}")
    print(f"推理数据形状: {infer_data.shape}")

    # 6. 增强功能：获取特征和标签信息
    feature_names = handler.get_cols("feature")  # 获取所有特征名称
    label_info = handler.fetch(col_set="label")   # 获取标签信息

    print(f"可用特征: {feature_names}")
    print(f"标签示例:\n{label_info.head()}")

    # 7. 性能优化建议（大数据集处理）
    handler.setup_data(enable_cache=True)  # 启用磁盘缓存
    handler.setup_data(init_type='fit_seq') # 序列化初始化减少内存占用

