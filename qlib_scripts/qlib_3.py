# https://www.wuzao.com/qlib/tutorial/introduction
import multiprocessing

import qlib
from qlib.constant import REG_CN
from qlib.utils import exists_qlib_data

if __name__ == '__main__':
    multiprocessing.freeze_support() # 添加这一行，特别是在 Windows 上打包时可能有帮助

    print(qlib.__version__)  # 如果能够打印出版本号，说明安装成功

    # 数据存储路径
    provider_uri = 'E:/PycharmProjects/MyQuant/.qlib/qlib_data/cn_data'

    # 检查数据是否存在，如果不存在则下载
    if not exists_qlib_data(provider_uri):
        print(f"Qlib 数据不存在，正在下载到 {provider_uri}")
        from qlib.tests.data import GetData

        GetData().qlib_data(target_dir=provider_uri, region=REG_CN)

    # 初始化 QLib
    qlib.init(provider_uri=provider_uri, region=REG_CN)
    print("QLib 初始化成功！")
