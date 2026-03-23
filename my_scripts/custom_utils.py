from pprint import pprint, pformat, PrettyPrinter
import pandas as pd  # 导入pandas库进行数据处理
# https://blog.csdn.net/weixin_38175458/article/details/126424837

import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import json
import os
from contextlib import contextmanager
from collections import defaultdict
from timeit import default_timer as timer
from typing import Optional, Dict
from qlib.backtest.position import Position


class TimerRecorder:
    """Lightweight timing recorder.

    Designed for end-to-end scripts: record named wall-clock durations and dump to JSON.
    """

    def __init__(self):
        self._t0 = timer()
        self.nodes = []  # List[{"name": str, "seconds": float}]

    @contextmanager
    def timer_context(self, name: str):
        start = timer()
        try:
            yield
        finally:
            elapsed = timer() - start
            self.nodes.append({"name": name, "seconds": elapsed})

    def timer(self, name: str):
        """Alias for backward/plan compatibility."""
        return self.timer_context(name)

    def dump_json(self, path: str, extra: Optional[Dict] = None):
        base_dir = os.path.dirname(path)
        if base_dir:
            os.makedirs(base_dir, exist_ok=True)

        payload = {
            "total_seconds": timer() - self._t0,
            "nodes": self.nodes,
        }
        if extra:
            payload.update(extra)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)


# Global recorder reference for cross-module timing.
# Used by `custom_strategy.py` / `custom_handler.py` to append into the same JSON dump.
_GLOBAL_TIMER_RECORDER: Optional["TimerRecorder"] = None


def set_global_timer_recorder(rec: "TimerRecorder") -> None:
    """Set the global recorder used by other modules (if running in same process)."""
    global _GLOBAL_TIMER_RECORDER
    _GLOBAL_TIMER_RECORDER = rec


def get_global_timer_recorder() -> Optional["TimerRecorder"]:
    """Get the global recorder; returns None if not set."""
    return _GLOBAL_TIMER_RECORDER


def analyze_and_visualize_positions(report: pd.DataFrame, positions: dict, figsize=(14, 10)):
    """
    专为 Qlib 0.9.7 设计的持仓分析函数
    假设 positions[date] 是一个 dict: {instrument: {'amount', 'price', 'value'}}
    """
    # 标准化 report
    report = report.copy()
    if not isinstance(report.index, pd.DatetimeIndex):
        report.index = pd.to_datetime(report.index)
    report = report.sort_index()

    # 获取公共日期
    position_dates = sorted(positions.keys())
    position_dates_dt = pd.to_datetime(position_dates)
    common_dates = report.index.intersection(position_dates_dt)

    if len(common_dates) == 0:
        raise ValueError("report 和 positions 日期无交集")

    daily_records = []
    holding_days = defaultdict(int)
    prev_instruments = set()

    for date in common_dates:
        date_str = date.strftime('%Y-%m-%d')
        pos_dict = positions[date_str]  # ✅ 直接当作 dict 使用！

        # 转为 DataFrame
        if pos_dict:
            pos_df = pd.DataFrame.from_dict(pos_dict, orient='index')
            pos_df.index.name = 'instrument'
            pos_df = pos_df.reset_index()
        else:
            pos_df = pd.DataFrame(columns=['instrument', 'amount', 'price', 'value'])

        # 分离股票和现金
        if not pos_df.empty:
            stock_df = pos_df[pos_df['instrument'] != 'cash'].copy()
            cash_value = pos_df[pos_df['instrument'] == 'cash']['value'].sum()
        else:
            stock_df = pd.DataFrame()
            cash_value = 0.0

        # 股票分析
        if not stock_df.empty:
            if 'value' not in stock_df.columns:
                stock_df['value'] = stock_df['amount'] * stock_df['price']

            num_stocks = len(stock_df)
            stock_value = stock_df['value'].sum()
            stock_df_sorted = stock_df.sort_values('value', ascending=False)

            top5_value = stock_df_sorted['value'].head(5).sum()
            top10_value = stock_df_sorted['value'].head(10).sum()
            top5_ratio = top5_value / stock_value if stock_value > 0 else 0.0
            top10_ratio = top10_value / stock_value if stock_value > 0 else 0.0

            current_instruments = set(stock_df['instrument'].tolist())
            if prev_instruments:
                turnover = len(current_instruments.symmetric_difference(prev_instruments)) / len(
                    prev_instruments | current_instruments)
            else:
                turnover = 0.0
            prev_instruments = current_instruments

            for inst in current_instruments:
                holding_days[inst] += 1
        else:
            num_stocks = 0
            stock_value = 0.0
            top5_ratio = 0.0
            top10_ratio = 0.0
            turnover = 0.0

        # 对账
        account_value = report.loc[date, 'account']
        computed_total = stock_value + cash_value
        reconciliation_diff = computed_total - account_value
        reconciliation_error_pct = abs(reconciliation_diff) / abs(account_value) if account_value != 0 else 0.0

        daily_records.append({
            'date': date,
            'num_stocks': num_stocks,
            'stock_value': stock_value,
            'cash_value': cash_value,
            'computed_total': computed_total,
            'account_value': account_value,
            'reconciliation_diff': reconciliation_diff,
            'reconciliation_error_pct': reconciliation_error_pct,
            'top5_concentration': top5_ratio,
            'top10_concentration': top10_ratio,
            'turnover_rate': turnover
        })

    analysis_df = pd.DataFrame(daily_records)
    analysis_df.set_index('date', inplace=True)

    avg_holding_days = sum(holding_days.values()) / len(holding_days) if holding_days else 0
    total_unique_stocks = len(holding_days)

    # 可视化
    plt.style.use('seaborn-v0_8')
    fig, axes = plt.subplots(3, 2, figsize=figsize)
    fig.suptitle('Qlib 持仓分析 (Qlib 0.9.7 - positions as dict)', fontsize=16)

    analysis_df['num_stocks'].plot(ax=axes[0, 0], title='每日持仓股票数量')
    analysis_df[['top5_concentration', 'top10_concentration']].plot(ax=axes[0, 1], title='持仓集中度')
    analysis_df[['account_value', 'computed_total']].plot(ax=axes[1, 0], title='对账：Report vs 计算总资产')
    analysis_df['reconciliation_error_pct'].plot(ax=axes[1, 1], title='对账误差百分比')
    analysis_df['turnover_rate'].plot(ax=axes[2, 0], title='日换手率')
    (analysis_df['cash_value'] / analysis_df['account_value']).plot(ax=axes[2, 1], title='现金占比')

    for ax in axes.flat:
        ax.grid(True, linestyle='--', alpha=0.6)
    plt.tight_layout(rect=[0, 0, 1, 0.96])
    plt.show()

    # 打印摘要
    print("=== Qlib 0.9.7 持仓分析摘要 ===")
    print(f"回测期间: {analysis_df.index.min().date()} ~ {analysis_df.index.max().date()}")
    print(f"平均持仓股票数: {analysis_df['num_stocks'].mean():.1f}")
    print(f"平均Top5集中度: {analysis_df['top5_concentration'].mean():.2%}")
    print(f"平均换手率: {analysis_df['turnover_rate'].mean():.2%}")
    print(f"平均持有天数: {avg_holding_days:.2f}")
    print(f"唯一股票总数: {total_unique_stocks}")
    print(f"最大对账误差: {analysis_df['reconciliation_error_pct'].max():.4%}")

    return {
        'analysis_df': analysis_df,
        'avg_holding_days': avg_holding_days,
        'total_unique_stocks': total_unique_stocks,
        'figure': fig
    }


def generate_position_report(positions_dict, output_file='position_analysis.txt'):
    """生成完整的持仓分析报告"""

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("QLib持仓分析报告\n")
        f.write("=" * 50 + "\n\n")

        # 总体统计
        f.write("1. 总体统计信息\n")
        f.write(f"回测期间: {len(positions_dict)} 个交易日\n")
        f.write(f"日期范围: {min(positions_dict.keys())} 至 {max(positions_dict.keys())}\n\n")

        # 按日期详细分析
        f.write("2. 各交易日持仓概览\n")
        for date_str in sorted(positions_dict.keys()):
            position_data = positions_dict[date_str]
            f.write(f"\n日期: {date_str}\n")

            if isinstance(position_data, pd.DataFrame):
                f.write(f"  持仓标的数: {len(position_data)}\n")
                if 'market_value' in position_data.columns:
                    total_value = position_data['market_value'].sum()
                    f.write(f"  总市值: {total_value:.2f}\n")
                if 'amount' in position_data.columns:
                    total_amount = position_data['amount'].sum()
                    f.write(f"  总持仓量: {total_amount}\n")
            elif isinstance(position_data, Position):
                accont_value = position_data.calculate_value()  # 在股票市值基础上加入现金余额（包括结算中现金）
                f.write(f"  总市值: {accont_value:.2f}\n")
                cash = position_data.get_cash()
                f.write(f"  现金: {cash:.2f}\n")
                stock_value = position_data.calculate_stock_value() # 遍历所有股票，计算总市值（数量 × 最新价格）。
                f.write(f"  持仓标的总市值: {stock_value:.2f}\n")
                stock_list = position_data.get_stock_list()
                f.write(f"  持仓标的列表: {stock_list}\n")
                # formatted = pformat(position_data, indent=4, width=80)
                # f.write(formatted)
                all_data = []
                for code in stock_list:
                    all_data.append({'标的': code,
                                     '持股数量': position_data.get_stock_amount(code),
                                     '最新价格': position_data.get_stock_price(code),
                                     '市值': position_data.get_stock_amount(code)*position_data.get_stock_price(code),
                                     '权重': position_data.get_stock_weight(code),
                                     '天数': position_data.get_stock_count(code,'day')})
                #         'count': <how many days the security has been hold>,
                #         'amount': <the amount of the security>,
                #         'price': <the close price of security in the last trading day>,
                #         'weight': <the security weight of total position value>,
                stock_df = pd.DataFrame(all_data)
                f.write(stock_df.to_csv(sep='\t', index=False))
            else:
                pass

            f.write("-" * 30 + "\n")

    print(f"分析报告已保存至: {output_file}")

def analyze_position_by_date(positions_dict, target_date=None):
    if target_date is None:
        target_date = list(positions_dict.keys())[0]

    if target_date in positions_dict:
        position_data = positions_dict[target_date]

        print(f"=== {target_date} 持仓分析 ===")

        if isinstance(position_data, pd.DataFrame):
            # 如果是DataFrame，进行详细分析
            print(f"持仓标的数量: {len(position_data)}")
            print(f"总市值: {position_data.get('market_value', pd.Series([0])).sum():.2f}")
            print(f"持仓明细:")
            print(position_data.to_string())
        else:
            # 如果是字典或其他结构
            print("持仓内容:")
            pprint(position_data)

    return positions_dict.get(target_date)

def pprint_position_report(positions_dict):
    if positions_dict:
        # 查看字典基本信息
        print("字典类型:", type(positions_dict))
        print("字典键:", list(positions_dict.keys()))
        print("字典大小:", len(positions_dict))
        # 基本美化输出
        # pprint(positions_dict)

        # 获取第一个日期键和对应的仓位信息
        sample_date = list(positions_dict.keys())[0]
        sample_data = positions_dict[sample_date]

        print(f"样本日期: {sample_date}")
        print(f"该日期仓位数据类型: {type(sample_data)}")

        if isinstance(sample_data, pd.DataFrame):
            print("仓位数据结构: DataFrame")
            print("DataFrame形状:", sample_data.shape)
            print("列名:", sample_data.columns.tolist())
            print("\n前5行数据:")
            print(sample_data.head())
        else:
            print("仓位数据内容:")
            pprint(sample_data)

# 风险绩效分析结果
def pprint_risk_analysis(analysis_result):
    for k, v in analysis_result.items():
        if isinstance(v, float):
            print(f"{k}: {v:.4f}")
        else:
            print(f"{k}: {v}")


# 示例使用
if __name__ == "__main__":
    example_positions = {
        '2020-01-01': {'AAPL': 0.2, 'MSFT': 0.2, 'GOOG': 0.2, 'AMZN': 0.2, 'TSLA': 0.2},
        '2020-01-02': {'AAPL': 0.25, 'MSFT': 0.25, 'GOOG': 0.2, 'AMZN': 0.15, 'TSLA': 0.15},
        '2020-01-03': {'AAPL': 0.3, 'MSFT': 0.2, 'FB': 0.2, 'AMZN': 0.15, 'TSLA': 0.15},
        '2020-01-04': {'AAPL': 0.25, 'MSFT': 0.25, 'GOOG': 0.15, 'AMZN': 0.2, 'TSLA': 0.15},
        '2020-01-05': {'AAPL': 0.2, 'MSFT': 0.2, 'GOOG': 0.2, 'AMZN': 0.2, 'TSLA': 0.2},
    }

"""
    对site-packages\qlib\backtest\position.py的修改
    def update_order(self, order: Order, trade_val: float, cost: float, trade_price: float) -> None:
        # handle order, order is a order class, defined in exchange.py
        formatted = pformat(order, indent=4, width=80)
        if order.direction == Order.BUY:
            # BUY
            logger.info(f"股票交易记录-BUY:{formatted} 实际成交数量{trade_val / trade_price} 实际成交金额{trade_val} 实际成交价格{trade_price} 交易成本{cost}")
            self._buy_stock(order.stock_id, trade_val, cost, trade_price)
        elif order.direction == Order.SELL:
            # SELL
            logger.info(f"股票交易记录-SEL:{formatted} 实际成交数量{trade_val / trade_price} 实际成交金额{trade_val} 实际成交价格{trade_price} 交易成本{cost}")
            self._sell_stock(order.stock_id, trade_val, cost, trade_price)
        else:
            raise NotImplementedError("do not support order direction {}".format(order.direction))
"""