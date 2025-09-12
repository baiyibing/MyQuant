import multiprocessing
import qlib
import logging
from qlib.data import D
from qlib.data.filter import NameDFilter
from qlib.constant import REG_CN    # 中国市场

# 数据检索 API

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
    # 首先需要确认你当前安装的 qlib版本中，qlib.data模块是否确实提供了 get_price函数。
    import qlib.data
    print(dir(qlib.data))   # 查看qlib.data模块所有可用的属性
    # 在输出列表中仔细查找是否有 get_price。如果找不到，说明该函数在当前版本的 qlib.data模块中可能不存在或已更名
    # from qlib.data import get_price
    # # 获取沪深 300 指数成分股的行情数据
    # df = get_price(
    #     instruments='csi300',
    #     start_time='2010-01-01',
    #     end_time='2020-12-31',
    #     fields=['open', 'close', 'high', 'low', 'volume'],
    #     freq='day'
    # )
    # print(df.head())

    # 获取沪深300指数成分股列表
    instruments = D.instruments('csi300')
    stock_list = D.list_instruments(instruments=instruments, as_list=True)[:10]  # 获取前10只股票作为示例

    # 使用 D.features 获取行情数据
    df = D.features(
        instruments=stock_list,  # 股票列表
        fields=['$open', '$close', '$high', '$low', '$volume'],  # 字段前需要加 $ 符号
        start_time='2010-01-01',
        end_time='2020-12-31',
        freq='day'
    )

    print(df.head())