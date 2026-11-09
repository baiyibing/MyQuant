//! 数据类型定义：日线 K 线、流通股本、输出行、布林带结果、计算上下文。
//!
//! 本模块为整个计算管线提供统一的数据结构，所有模块通过 `crate::types` 引用。

use serde::Serialize;

/// 单根日线 K 线数据，对应 parquet 文件中一行。
///
/// 列名与 `stock_data/stock/period=1d/dividend_type=front/symbol=*/data.parquet` 的 schema 一致。
#[derive(Debug, Clone)]
pub struct BarRow {
    /// epoch 毫秒（UTC 午夜），对应 parquet 的 `time` 列
    pub time_ms: i64,
    /// 开盘价（前复权）
    pub open: f64,
    /// 最高价（前复权）
    pub high: f64,
    /// 最低价（前复权）
    pub low: f64,
    /// 收盘价（前复权）
    pub close: f64,
    /// 成交量（手，1 手 = 100 股）
    pub volume: i64,
    /// 成交额（元）
    pub amount: f64,
}

/// 从 `float_shares.parquet` 加载的流通股本信息。
#[derive(Debug, Clone)]
pub struct FloatSharesInfo {
    /// 流通股本（股，miniQMT FloatVolume）
    pub float_shares: f64,
    /// 中文股票简称，如"平安银行"
    pub name: String,
}

/// 从 `free_float_shares.parquet` 加载的自由流通股本 + 流通股本历史数据。
///
/// 查询时按 `m_timetag <= target_date` 取最新行（merge_asof 语义）。
#[derive(Debug, Clone)]
pub struct FreeFloatSharesInfo {
    /// 自由流通股本（股，freeFloatCapital）
    pub free_float_capital: f64,
    /// 流通股本（股，circulating_capital）
    pub circulating_capital: f64,
    /// m_timetag epoch 毫秒（仅用于 merge_asof 比较，不输出到 CSV）
    pub timetag: i64,
}

/// 输出 CSV 的一行，所有字段均实现 `Serialize` 以便 `csv` crate 自动写入。
///
/// 双口径输出：
///   - turnover / turnover_resistance：流通股本 (circulating_capital) 口径
///   - turnover_free / turnover_resistance_free：自由流通股本 (freeFloatCapital) 口径
///
/// 精度对齐 Python `full_market_canonical_resist.py`：
/// - close / bb_*：2 位小数
/// - cyqk_* / turnover_resistance / bb_position / bb_width：4 位
/// - profit_chip_diff / turnover：6 位
#[derive(Debug, Clone, Serialize)]
pub struct OutputRow {
    /// 股票代码（点分隔），如 "000001.SZ"
    pub stock_code: String,
    /// 中文简称
    pub stock_name: String,
    /// 截面日期，YYYYMMDD 格式
    pub date: String,
    /// 收盘价（T 日）
    pub close: f64,
    /// T 日获利筹码比例（cyqk，流通股本口径），0~1
    #[serde(rename = "cyqk_T")]
    pub cyqk_t: f64,
    /// T-1 日获利筹码比例（cyqk，流通股本口径），0~1
    #[serde(rename = "cyqk_T_1")]
    pub cyqk_t_1: f64,
    /// 获利筹码变化 cyqk_T - cyqk_T_1（流通股本口径）
    pub profit_chip_diff: f64,
    /// T 日换手率（流通股本口径：vol×100 / circulating_capital）
    pub turnover: f64,
    /// 换手阻力（流通股本口径）= profit_chip_diff / turnover
    pub turnover_resistance: f64,
    /// T 日换手率（自由流通股本口径：vol×100 / freeFloatCapital）
    pub turnover_free: f64,
    /// 换手阻力（自由流通股本口径）
    pub turnover_resistance_free: f64,
    /// 流通股本（股，circulating_capital）
    pub circulating_capital: f64,
    /// 自由流通股本（股，freeFloatCapital）
    #[serde(rename = "freeFloatCapital")]
    pub free_float_capital: f64,
    /// 布林上轨（20 日均线 + 2σ）
    pub bb_upper: f64,
    /// 布林中轨（20 日均线）
    pub bb_middle: f64,
    /// 布林下轨（20 日均线 - 2σ）
    pub bb_lower: f64,
    /// 布林位置 = (close - lower) / (upper - lower)，0~1
    pub bb_position: f64,
    /// 布林带宽 = (upper - lower) / middle
    pub bb_width: f64,
}

/// 布林带（Bollinger Bands）计算结果。
///
/// 公式：middle = MA(close, 20)，upper = middle + 2σ，lower = middle - 2σ
#[derive(Debug)]
pub struct BollingerResult {
    pub upper: f64,
    pub middle: f64,
    pub lower: f64,
    /// 收盘价在布林带中的相对位置，0=下轨，0.5=中轨，1=上轨
    pub position: f64,
    /// 带宽 = (upper - lower) / middle
    pub width: f64,
}

/// 贯穿全市场的不可变计算上下文。
///
/// 所有 rayon 线程共享同一个 `&ComputeContext` 引用（只读，线程安全）。
pub struct ComputeContext {
    /// 目标截面日期的 epoch 毫秒（UTC 午夜）
    pub target_date_ms: i64,
    /// 筹码衰减窗口（交易日数）
    pub window: usize,
    /// 价格网格步长（元）
    pub step: f64,
    /// 布林带周期
    pub bb_period: usize,
    /// 布林带倍数
    pub bb_std: f64,
    /// 标准差自由度（0/1）
    pub bb_ddof: usize,
    /// 数据根目录路径（如 "stock_data"）
    pub data_dir: String,
    /// 截面日期字符串（YYYYMMDD）
    pub date_str: String,
    /// 是否允许目标日缺失时回退到前一交易日（true=allow-previous）。
    pub allow_previous_target_date: bool,
    /// 单股票最大价格网格点数保护阈值。
    pub max_grid_points: usize,
}
