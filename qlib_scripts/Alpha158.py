# 导入基础类，AlphaBase 是 QLib 中公式化因子的基类，提供因子计算的基础结构[1](@ref)
from datafeed import AlphaBase

# 定义 Alpha158 因子类，继承自 AlphaBase
class Alpha158(AlphaBase):

    # 定义获取因子字段和名称的方法，返回两个列表：因子表达式列表和对应的因子名称列表
    def get_fields_names(self):
        # 注释中列出的是示例因子名称，实际代码中会动态生成
        # ['CORD30', 'STD30', 'CORR5', 'RESI10', 'CORD60', 'STD5', 'LOW0',
        # 'WVMA30', 'RESI5', 'ROC5', 'KSFT', 'STD20', 'RSV5', 'STD60', 'KLEN']
        fields = []  # 初始化空列表，用于存储因子表达式（公式）
        names = []   # 初始化空列表，用于存储因子名称

        # ============ K线（KBar）相关因子 ============
        # 基于开盘价(open)、最高价(high)、最低价(low)、收盘价(close)计算K线形态因子
        fields += [
            "(close-open)/open",  # KMID: 标准化价格变化，衡量涨跌幅
            "(high-low)/open",     # KLEN: 标准化波动幅度，衡量K线长度
            "(close-open)/(high-low+1e-12)",  # KMID2: 价格变化占波动幅度的比例，避免除零
            "(high-greater(open, close))/open",  # KUP: 上影线长度标准化
            "(high-greater(open, close))/(high-low+1e-12)",  # KUP2: 上影线占波动幅度比例
            "(less(open, close)-low)/open",  # KLOW: 下影线长度标准化
            "(less(open, close)-low)/(high-low+1e-12)",  # KLOW2: 下影线占波动幅度比例
            "(2*close-high-low)/open",  # KSFT: 重心偏移标准化
            "(2*close-high-low)/(high-low+1e-12)",  # KSFT2: 重心偏移占波动幅度比例
        ]
        names += [
            "KMID",    # 中间价格变化
            "KLEN",    # K线长度
            "KMID2",   # 标准化中间价格变化
            "KUP",     # 上影线强度
            "KUP2",    # 标准化上影线强度
            "KLOW",    # 下影线强度
            "KLOW2",   # 标准化下影线强度
            "KSFT",    # 价格重心偏移
            "KSFT2",   # 标准化价格重心偏移
        ]

        # ============ 价格相对变化因子 ============
        feature = ["OPEN", "HIGH", "LOW", "CLOSE"]  # 价格字段
        windows = range(5)  # 时间窗口：0到4期（当期和滞后4期）
        for field in feature:
            field = field.lower()  # 字段名转为小写以匹配数据格式
            # 生成当前期和滞后期的价格相对收盘价的比例（例如：OPEN0/close, shift(OPEN,1)/close）
            fields += ["shift(%s, %d)/close" % (field, d) if d != 0 else "%s/close" % field for d in windows]
            names += [field.upper() + str(d) for d in windows]  # 名称如：OPEN0, OPEN1, ..., HIGH0, HIGH1, ...

        # ============ 成交量相对变化因子 ============
        # 生成当前期和滞后期的成交量相对比例（标准化成交量变化）
        fields += ["shift(volume, %d)/(volume+1e-12)" % d if d != 0 else "volume/(volume+1e-12)" for d in windows]
        names += ["VOLUME" + str(d) for d in windows]  # 名称如：VOLUME0, VOLUME1, ...

        # ============ 滚动窗口技术指标因子 ============
        windows = [5, 10, 20, 30, 60]  # 定义多个滚动窗口（5日至60日）

        # 1. 收益率因子（Rate of Change, ROC）
        fields += ["shift(close, %d)/close" % d for d in windows]  # d期前价格与当前收盘价的比例
        names += ["ROC%d" % d for d in windows]  # 名称如：ROC5, ROC10, ...

        # 2. 移动平均因子（Moving Average, MA）
        fields += ["mean(close, %d)/close" % d for d in windows]  # d期收盘价均值与当前价格的比例
        names += ["MA%d" % d for d in windows]  # 名称如：MA5, MA10, ...

        # 3. 价格波动率因子（Standard Deviation, STD）
        fields += ["std(close, %d)/close" % d for d in windows]  # d期收盘价标准差与当前价格的比例
        names += ["STD%d" % d for d in windows]  # 名称如：STD5, STD10, ...

        # 4. 滚动窗口内最高价/最低价因子
        fields += ["max(high, %d)/close" % d for d in windows]  # d期内最高价与当前价格的比例
        names += ["MAX%d" % d for d in windows]  # 名称如：MAX5, MAX10, ...
        fields += ["min(low, %d)/close" % d for d in windows]  # d期内最低价与当前价格的比例
        names += ["MIN%d" % d for d in windows]  # 名称如：MIN5, MIN10, ...

        # 5. 分位数因子（Quantile）
        fields += ["quantile(close, %d, 0.8)/close" % d for d in windows]  # d期收盘价80%分位数与当前价格的比例
        names += ["QTLU%d" % d for d in windows]  # 上分位数因子
        fields += ["quantile(close, %d, 0.2)/close" % d for d in windows]  # d期收盘价20%分位数与当前价格的比例
        names += ["QTLD%d" % d for d in windows]  # 下分位数因子

        # 6. 随机震荡因子（Relative Strength Value, RSV）
        fields += ["(close-min(low, %d))/(max(high, %d)-min(low, %d)+1e-12)" % (d, d, d) for d in windows]
        names += ["RSV%d" % d for d in windows]  # 名称如：RSV5, RSV10, ...（类似KDJ中的RSV）

        # 7. 极值点位置因子
        fields += ["idxmax(high, %d)/%d" % (d, d) for d in windows]  # d期内最高价出现位置的标准化索引
        names += ["IMAX%d" % d for d in windows]  # 最高点位置因子
        fields += ["idxmin(low, %d)/%d" % (d, d) for d in windows]  # d期内最低价出现位置的标准化索引
        names += ["IMIN%d" % d for d in windows]  # 最低点位置因子
        fields += ["(idxmax(high, %d)-idxmin(low, %d))/%d" % (d, d, d) for d in windows]  # 高低点位置差
        names += ["IMXD%d" % d for d in windows]  # 极值点距离因子

        # 8. 量价相关性因子
        fields += ["corr(close, log(volume+1), %d)" % d for d in windows]  # d期收盘价与成交量对数的相关系数
        names += ["CORR%d" % d for d in windows]  # 名称如：CORR5, CORR10, ...
        fields += ["corr(close/shift(close,1), log(volume/shift(volume, 1)+1), %d)" % d for d in windows]  # 收益率与成交量变化率的相关系数
        names += ["CORD%d" % d for d in windows]  # 名称如：CORD5, CORD10, ...

        # 9. 价格方向统计因子
        fields += ["mean(close>shift(close, 1), %d)" % d for d in windows]  # d期内价格上涨天数占比
        names += ["CNTP%d" % d for d in windows]  # 正变化计数因子
        fields += ["mean(close<shift(close, 1), %d)" % d for d in windows]  # d期内价格下跌天数占比
        names += ["CNTN%d" % d for d in windows]  # 负变化计数因子
        fields += ["mean(close>shift(close, 1), %d)-mean(close<shift(close, 1), %d)" % (d, d) for d in windows]  # 多空方向净差值
        names += ["CNTD%d" % d for d in windows]  # 净方向因子

        # 10. 价格变化强度因子
        fields += [
            "sum(greater(close-shift(close, 1), 0), %d)/(sum(Abs(close-shift(close, 1)), %d)+1e-12)" % (d, d)
            for d in windows
        ]  # d期内正价格变化的总强度占比
        names += ["SUMP%d" % d for d in windows]  # 正强度和因子
        fields += [
            "sum(greater(shift(close, 1)-close, 0), %d)/(sum(Abs(close-shift(close, 1)), %d)+1e-12)" % (d, d)
            for d in windows
        ]  # d期内负价格变化的总强度占比
        names += ["SUMN%d" % d for d in windows]  # 负强度和因子
        fields += [
            "(sum(greater(close-shift(close, 1), 0), %d)-sum(greater(shift(close, 1)-close, 0), %d))"
            "/(sum(Abs(close-shift(close, 1)), %d)+1e-12)" % (d, d, d)
            for d in windows
        ]  # d期内净价格变化强度占比
        names += ["SUMD%d" % d for d in windows]  # 净强度因子

        # 11. 成交量技术指标
        fields += ["mean(volume, %d)/(volume+1e-12)" % d for d in windows]  # d期成交量均值与当前成交量的比例
        names += ["VMA%d" % d for d in windows]  # 成交量移动平均因子
        fields += ["std(volume, %d)/(volume+1e-12)" % d for d in windows]  # d期成交量标准差与当前成交量的比例
        names += ["VSTD%d" % d for d in windows]  # 成交量波动率因子
        fields += [
            "std(Abs(close/shift(close, 1)-1)*volume, %d)/(mean(Abs(close/shift(close, 1)-1)*volume, %d)+1e-12)"
            % (d, d)
            for d in windows
        ]  # 收益波动率加权的成交量变异系数
        names += ["WVMA%d" % d for d in windows]  # 加权成交量移动平均变异因子

        # 12. 成交量方向统计因子
        fields += [
            "sum(greater(volume-shift(volume, 1), 0), %d)/(sum(Abs(volume-shift(volume, 1)), %d)+1e-12)"
            % (d, d)
            for d in windows
        ]  # d期内成交量增加的天数强度占比
        names += ["VSUMP%d" % d for d in windows]  # 成交量正强度和因子
        fields += [
            "sum(greater(shift(volume, 1)-volume, 0), %d)/(sum(Abs(volume-shift(volume, 1)), %d)+1e-12)"
            % (d, d)
            for d in windows
        ]  # d期内成交量减少的天数强度占比
        names += ["VSUMN%d" % d for d in windows]  # 成交量负强度和因子
        fields += [
            "(sum(greater(volume-shift(volume, 1), 0), %d)-sum(greater(shift(volume, 1)-volume, 0), %d))"
            "/(sum(Abs(volume-shift(volume, 1)), %d)+1e-12)" % (d, d, d)
            for d in windows
        ]  # d期内成交量净变化强度占比
        names += ["VSUMD%d" % d for d in windows]  # 成交量净强度因子

        return fields, names  # 返回生成的因子表达式列表和名称列表