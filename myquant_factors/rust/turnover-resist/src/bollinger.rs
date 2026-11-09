//! 布林带（Bollinger Bands）计算。
//!
//! 公式：
//! - middle = MA(close, 20)
//! - upper  = middle + 2 × σ
//! - lower  = middle - 2 × σ
//! - position = (close_last - lower) / (upper - lower)
//! - width    = (upper - lower) / middle
//!
//! 与 Python `backtest/chip_algorithm.py:bb_position` 行为一致。

use crate::types::BollingerResult;

/// 计算布林带指标。
///
/// # 参数
/// - `closes`: 收盘价序列（从最早到最新）
/// - `period`: 均线周期，通常 20
/// - `nbdev`: 标准差倍数，通常 2.0
///
/// # 边界处理
/// - 数据不足 `period` 根：返回 NaN middle/upper/lower，position=0.5，width=0
/// - `upper == lower`（一字板等）：position = 0.5
/// - `middle <= 0`：width = 0
pub fn bollinger_bands(closes: &[f64], period: usize, nbdev: f64, ddof: usize) -> BollingerResult {
    let n = closes.len();
    // 数据不足 → 返回 NaN 占位
    if n < period {
        return BollingerResult {
            upper: f64::NAN,
            middle: f64::NAN,
            lower: f64::NAN,
            position: 0.5,
            width: 0.0,
        };
    }

    // 取最近 `period` 根收盘价
    let window = &closes[n - period..];

    // 均值 μ
    let sum: f64 = window.iter().sum();
    let mean = sum / period as f64;

    let denom = period.saturating_sub(ddof).max(1) as f64;
    // 标准差 σ = sqrt(Σ(x-μ)²/(N-ddof))
    let variance: f64 = window.iter().map(|v| (v - mean) * (v - mean)).sum::<f64>() / denom;
    let std_dev = variance.sqrt();

    let upper = mean + nbdev * std_dev;
    let lower = mean - nbdev * std_dev;
    let last_close = closes[n - 1];

    // 布林带位置：0=下轨，0.5=中轨，1=上轨
    let position = if upper > lower {
        (last_close - lower) / (upper - lower)
    } else {
        0.5 // 一字板/涨跌停导致上下轨重合时，取中轨位置
    };

    // 布林带宽
    let width = if mean > 0.0 {
        (upper - lower) / mean
    } else {
        0.0
    };

    BollingerResult {
        upper,
        middle: mean,
        lower,
        position,
        width,
    }
}
