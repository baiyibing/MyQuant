from qlib.data.dataset.loader import QlibDataLoader  # 导入基础数据加载器类

class Alpha360DL(QlibDataLoader):
    """数据加载器，用于生成Alpha360因子数据集，提供过去60天的标准化价格和成交量数据[4](@ref)"""

    def __init__(self, config=None, **kwargs):
        # 初始化配置：默认使用get_feature_config返回的特征字段，允许用户通过config参数扩展或覆盖配置
        _config = {
            "feature": self.get_feature_config(),  # 核心特征配置
        }
        if config is not None:
            _config.update(config)  # 合并用户自定义配置
        super().__init__(config=_config, **kwargs)  # 调用父类初始化方法

    @staticmethod
    def get_feature_config():
        # 生成Alpha360因子配置：包含60个时间点的价格和成交量数据，全部用最新值标准化[4](@ref)
        fields = []  # 存储QLib表达式（如"Ref($close, 59)/$close"）
        names = []   # 存储对应字段名（如"CLOSE59"）

        # 生成滞后59天到当前时刻的收盘价标准化序列（除以最新收盘价）
        for i in range(59, 0, -1):  # 从59天前到1天前
            fields += ["Ref($close, %d)/$close" % i]  # 引用i天前的收盘价并标准化
            names += ["CLOSE%d" % i]  # 字段命名，如CLOSE59, CLOSE58...
        fields += ["$close/$close"]  # 当前收盘价自身标准化（结果为1）
        names += ["CLOSE0"]  # 当前时刻字段

        # 同样的逻辑生成开盘价、最高价、最低价、VWAP和成交量的标准化序列
        for i in range(59, 0, -1):
            fields += ["Ref($open, %d)/$close" % i]  # 开盘价相对最新收盘价的比值
            names += ["OPEN%d" % i]
        fields += ["$open/$close"]
        names += ["OPEN0"]

        for i in range(59, 0, -1):
            fields += ["Ref($high, %d)/$close" % i]  # 最高价标准化
            names += ["HIGH%d" % i]
        fields += ["$high/$close"]
        names += ["HIGH0"]

        for i in range(59, 0, -1):
            fields += ["Ref($low, %d)/$close" % i]  # 最低价标准化
            names += ["LOW%d" % i]
        fields += ["$low/$close"]
        names += ["LOW0"]

        for i in range(59, 0, -1):
            fields += ["Ref($vwap, %d)/$close" % i]  # 成交量加权均价标准化
            names += ["VWAP%d" % i]
        fields += ["$vwap/$close"]
        names += ["VWAP0"]

        for i in range(59, 0, -1):
            # 成交量标准化（加1e-12防止除零错误）
            fields += ["Ref($volume, %d)/($volume+1e-12)" % i]
            names += ["VOLUME%d" % i]
        fields += ["$volume/($volume+1e-12)"]
        names += ["VOLUME0"]

        return fields, names  # 返回表达式和字段名列表，供父类解析计算[4](@ref)