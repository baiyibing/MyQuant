//! 核心算法模块：三角分布 PDF、换手率衰减累积、CYQK 获利占比。
//!
//! 本节一字不差地复刻 Python `qlib_cost/cyq.py` + `distribution_of_chips.py` 的 numba jit 实现，
//! 所有公式语义与 Python 端一致，差异仅在于 f64 浮点累积精度。

use crate::types::BarRow;
use rayon::prelude::*;
use thiserror::Error;

/// 三角分布 PDF 单点求值，等价于 numba jit `triang_pdf`（`distribution_of_chips.py:52-105`）。
///
/// 三角分布形状：
/// ```
///         ▲
///        /|\       峰值在 close（= loc + scale × c）
///       / | \
///      /  |  \     上坡段：线性从 low → close
///     /   |   \    下坡段：线性从 close → high
///    /    |    \   界外：0
///   low  close  high
/// ```
///
/// # 参数
/// - `x`: 待求值的价格点
/// - `c`: 众数位置，(close-low)/(high-low)，∈[0,1]
/// - `loc`: 区间下界 = low
/// - `scale`: 区间长度 = high - low
/// - `upper`: 区间上界 = low + scale = high（预先计算以减少重复运算）
/// - `square_scale`: scale²（预先计算以减少重复运算）
///
/// # 退化情形
/// - `c == 0`（close == low）：右三角，密度从 high 向 low 线性递减
/// - `c == 1`（close == high）：左三角，密度从 low 向 high 线性递增
#[inline(always)]
fn triang_pdf_single(x: f64, c: f64, loc: f64, scale: f64, upper: f64, square_scale: f64) -> f64 {
    let peak = loc + scale * c; // 三角分布的峰值位置 = close
    if x < loc || x > upper {
        return 0.0; // 价格在 [low, high] 之外 → 概率为 0
    }
    if x <= peak {
        // 上坡段：x 在 [low, close] 之间
        if c == 0.0 {
            // 众数在左边界：从 peak(=low) 到 upper 线性下降
            2.0 * (upper - x) / square_scale
        } else if (c - 1.0).abs() < 1e-14 {
            // 众数在右边界：从 loc 到 peak(=high) 线性上升
            2.0 * (x - loc) / square_scale
        } else {
            // 一般情况：上坡段公式
            2.0 * (x - loc) / (c * square_scale)
        }
    } else {
        // 下坡段：x 在 (close, high] 之间
        let denom = square_scale * (1.0 - c);
        if denom.abs() < 1e-15 {
            0.0 // 防止 c≈1 时除零
        } else {
            2.0 * (upper - x) / denom
        }
    }
}

/// 单日筹码分布：将当天的成交量按三角分布展开到价格网格上。
///
/// # 参数
/// - `close, high, low, vol`: 当日 OHLC + 成交量（手）
/// - `xs`: 全局价格网格（整个窗口共享同一个网格）
/// - `step`: 网格步长（用于涨跌停时定位 close 所在 bin）
///
/// # 返回
/// `Vec<f64>`，长度 = xs.len()，元素之和 ≈ vol。
///
/// # 涨跌停处理
/// 当 `high == low` 时（一字涨跌停），当日全部成交量集中到 close 对应的一个价格 bin 上，
/// 不做三角分布展开。与 Python `calc_triang_pdf` 行为一致。
pub fn calc_single_day_curpdf(
    close: f64,
    high: f64,
    low: f64,
    vol: f64,
    xs: &[f64],
    step: f64,
) -> Vec<f64> {
    let n = xs.len();
    let mut pdf = vec![0.0f64; n];

    // 涨跌停 / 一字板：所有成交量集中到 close 所在 bin
    if (high - low).abs() < 1e-12 {
        let idx = ((close - xs[0]) / step).round() as isize;
        if idx >= 0 && (idx as usize) < n {
            pdf[idx as usize] = 1.0;
        }
        for v in pdf.iter_mut() {
            *v *= vol;
        }
        return pdf;
    }

    // 计算三角分布参数
    let c = (close - low) / (high - low); // 众数位置 ∈ [0, 1]
    let loc = low;
    let scale = high - low;

    // 非法参数（数据异常）→ 返回 NaN 向量，下游会跳过
    if !(0.0..=1.0).contains(&c) || scale < 0.0 {
        pdf.fill(f64::NAN);
        return pdf;
    }

    let upper = loc + scale; // = high
    let square_scale = scale * scale; // = (high - low)²

    // 逐格计算三角分布概率密度
    for (i, &x) in xs.iter().enumerate() {
        pdf[i] = triang_pdf_single(x, c, loc, scale, upper, square_scale);
    }

    // 归一化：pdf / Σpdf × vol，使输出之和 = vol
    // 这保证每天的总筹码量等于当天成交量（物理含义：当天换手的筹码按价格分布）
    let sum: f64 = pdf.iter().sum();
    if sum.abs() > 1e-15 {
        for v in pdf.iter_mut() {
            *v = *v / sum * vol;
        }
    }
    pdf
}

/// 复用输出缓冲区版本，减少热点循环中的 `Vec` 分配。
pub fn calc_single_day_curpdf_into(
    close: f64,
    high: f64,
    low: f64,
    vol: f64,
    xs: &[f64],
    step: f64,
    out: &mut [f64],
) {
    out.fill(0.0);
    let n = xs.len();

    if (high - low).abs() < 1e-12 {
        let idx = ((close - xs[0]) / step).round() as isize;
        if idx >= 0 && (idx as usize) < n {
            out[idx as usize] = vol;
        }
        return;
    }

    let c = (close - low) / (high - low);
    let loc = low;
    let scale = high - low;
    if !(0.0..=1.0).contains(&c) || scale < 0.0 {
        out.fill(f64::NAN);
        return;
    }
    let upper = loc + scale;
    let square_scale = scale * scale;
    for (i, &x) in xs.iter().enumerate() {
        out[i] = triang_pdf_single(x, c, loc, scale, upper, square_scale);
    }
    let sum: f64 = out.iter().sum();
    if sum.abs() > 1e-15 {
        for v in out.iter_mut() {
            *v = *v / sum * vol;
        }
    }
}

/// 换手率衰减累积（canonical 模型，A=1.0）。
///
/// 等价于 Python `cyq.py:calc_cumpdf`（numba jit）。
///
/// # 递推公式
/// ```text
/// cumpdf₀[j] = curpdf₀[j] × turnover₀                              (i=0)
/// cumpdfᵢ[j] = cumpdfᵢ₋₁[j] × (1 - turnoverᵢ) + curpdfᵢ[j] × turnoverᵢ   (i≥1)
/// ```
///
/// # 经济学解释
/// - `cumpdfᵢ₋₁ × (1 - turnoverᵢ)`：旧筹码中未被换手的部分，继续留存
/// - `curpdfᵢ × turnoverᵢ`：当日新换手的筹码，按当日价格分布加入
/// - 换手率越高 → 历史筹码被"洗掉"越快 → 近期价格分布权重越大
///
/// # 参数
/// - `curpdfs`: 扁平数组，长度 = n_days × n_prices，行主序存储
/// - `turnover_rates`: 逐日换手率，长度 = n_days
///
/// # 返回
/// 最终累积筹码分布向量，长度 = n_prices
pub fn calc_cumpdf_decay(
    curpdfs: &[f64],
    turnover_rates: &[f64],
    n_days: usize,
    n_prices: usize,
) -> Vec<f64> {
    // 调试断言：确保维度一致
    debug_assert_eq!(curpdfs.len(), n_days * n_prices);
    debug_assert_eq!(turnover_rates.len(), n_days);

    if n_days == 0 {
        return vec![0.0; n_prices];
    }

    let mut cumpdf = vec![0.0f64; n_prices];

    // 第 0 天（最早）：cumpdf₀ = curpdf₀ × turnover₀
    let t0 = turnover_rates[0];
    let day0_offset = 0;
    for j in 0..n_prices {
        cumpdf[j] = curpdfs[day0_offset + j] * t0;
    }

    // 第 1..n_days-1 天：递推累积
    // 编译器会对内层循环自动向量化（AVX2：4 个 f64 同时计算）
    for (i, &t) in turnover_rates.iter().enumerate().take(n_days).skip(1) {
        let diff = 1.0 - t; // 留存比例
        let offset = i * n_prices; // 当日 curpdf 在扁平数组中的起始偏移
        for j in 0..n_prices {
            cumpdf[j] = cumpdf[j] * diff + curpdfs[offset + j] * t;
        }
    }

    cumpdf
}

/// 计算 CYQK（获利筹码占比）：在收盘价以下买入的筹码占总筹码的比例。
///
/// 等价于 Python `ChipFactor.get_cyqk_c()` → `get_winner(close)`。
///
/// # 公式
/// ```text
/// total  = Σ cumpdf[j]                    （总筹码量）
/// winner = Σ{cumpdf[j] | price[j] ≤ close}（收盘价以下的筹码量）
/// cyqk   = winner / total                 （获利占比）
/// ```
///
/// # 边界
/// - `total <= 0`：分布为空或损坏 → 返回 `NaN`（与 Python P0-17 fix 一致，禁止静默返回 0）
pub fn calc_cyqk(cumpdf: &[f64], xs: &[f64], close_last: f64) -> f64 {
    let total: f64 = cumpdf.iter().sum();
    if total <= 0.0 {
        return f64::NAN;
    }

    // 累加价格 ≤ close 的筹码量
    let mut winner = 0.0f64;
    for (j, &price) in xs.iter().enumerate() {
        if price <= close_last {
            winner += cumpdf[j];
        }
    }

    winner / total
}

/// 计算换手率 = (volume × 100) / float_shares。
///
/// - `volume`: 成交量（手，1 手 = 100 股）
/// - `float_shares`: 流通股本（股）
///
/// 与 Python `_estimate_turnover` 公式完全一致。
pub fn calc_turnover_rate(volume: i64, float_shares: f64) -> f64 {
    if float_shares <= 0.0 {
        return 0.0;
    }
    (volume as f64 * 100.0) / float_shares
}

/// 对单个窗口计算 CYQK：构造价格网格 → 逐日计算三角分布 → 衰减累积 → 获利占比。
///
/// 这是 `process_one_stock` 调用的核心入口，一只股票的 T 窗口和 T-1 窗口各调用一次。
///
/// # 返回
/// `Some(cyqk)` 成功，`None` 表示数据不足（< 20 天）/ 价格范围为空 / cyqk 为 NaN。
pub fn compute_cyqk_for_window(bars: &[BarRow], float_shares: f64, step: f64) -> Option<f64> {
    let n_days = bars.len();
    // 少于 20 个交易日 → cyqk 不稳定，跳过
    if n_days < 20 {
        return None;
    }

    // ---- 1. 构建全局价格网格 ----
    // 网格范围：窗口内所有 K 线的 [min(low), max(high)]，跳过 NaN
    let mut min_p = f64::INFINITY;
    let mut max_p = f64::NEG_INFINITY;
    for bar in bars {
        if !bar.low.is_nan() && bar.low < min_p {
            min_p = bar.low;
        }
        if !bar.high.is_nan() && bar.high > max_p {
            max_p = bar.high;
        }
    }

    if min_p.is_nan() || max_p.is_nan() || max_p <= min_p {
        return None; // 价格范围无效（全 NaN 或全部同价）
    }

    // 网格点数：价格跨度 / step，不做截断（跟随 Python 行为）
    let n_prices_raw = ((max_p - min_p) / step).ceil() as usize + 1;
    let n_prices = n_prices_raw; // 不截断，接受极端高价股的大网格

    // xs = [min_p, min_p+step, min_p+2*step, ..., max_p]
    let xs: Vec<f64> = (0..n_prices).map(|i| min_p + i as f64 * step).collect();

    // ---- 2. 逐日计算 curpdf + 换手率 ----
    // 使用扁平 Vec<f64> 存储（行主序），比 `Vec<Vec<f64>>` 缓存更友好
    let mut turnovers = Vec::with_capacity(n_days);
    let mut curpdfs: Vec<f64> = Vec::with_capacity(n_days * n_prices);

    let mut day_buf = vec![0.0f64; n_prices];
    for bar in bars {
        let turnover = calc_turnover_rate(bar.volume, float_shares);
        turnovers.push(turnover);

        // 当日三角分布 → 扩展到价格网格
        calc_single_day_curpdf_into(
            bar.close,
            bar.high,
            bar.low,
            bar.volume as f64,
            &xs,
            step,
            &mut day_buf,
        );
        curpdfs.extend_from_slice(&day_buf);
    }

    // ---- 3. 换手率衰减累积 ----
    let cumpdf = calc_cumpdf_decay(&curpdfs, &turnovers, n_days, n_prices);

    // ---- 4. 获利占比 ----
    let close_last = bars.last().unwrap().close;
    let cyqk = calc_cyqk(&cumpdf, &xs, close_last);

    if cyqk.is_nan() {
        None
    } else {
        Some(cyqk)
    }
}

/// 单窗口 CYQK：窗内每一日用该日流通股本算换手（`vol × 100 / shares[i]`）。
///
/// 价格网格按**本窗口** `min(low)` / `max(high)` 重建，与 Python `calc_dist_chips` 一致。
/// 不要复用 `compute_cyqk_for_window`（整窗单一股本）。
///
/// 窗内任一日股本非有限或 ≤0、OHLCV 非有限、价格范围无效 → `None`。
/// 不设「至少 20 根」门槛：窗口长度由调用方决定（策略锁 200）。
pub fn compute_cyqk_ohlcv_window(
    close: &[f64],
    high: &[f64],
    low: &[f64],
    volume: &[f64],
    shares: &[f64],
    step: f64,
) -> Option<f64> {
    let n_days = close.len();
    if n_days == 0
        || high.len() != n_days
        || low.len() != n_days
        || volume.len() != n_days
        || shares.len() != n_days
        || !step.is_finite()
        || step <= 0.0
    {
        return None;
    }

    let mut min_p = f64::INFINITY;
    let mut max_p = f64::NEG_INFINITY;
    let mut turnovers = Vec::with_capacity(n_days);
    for i in 0..n_days {
        let c = close[i];
        let h = high[i];
        let l = low[i];
        let vol = volume[i];
        let sh = shares[i];
        if !c.is_finite()
            || !h.is_finite()
            || !l.is_finite()
            || !vol.is_finite()
            || vol < 0.0
            || !sh.is_finite()
            || sh <= 0.0
        {
            return None;
        }
        if l < min_p {
            min_p = l;
        }
        if h > max_p {
            max_p = h;
        }
        turnovers.push((vol * 100.0) / sh);
    }

    if !min_p.is_finite() || !max_p.is_finite() || max_p <= min_p {
        return None;
    }

    let n_prices = ((max_p - min_p) / step).ceil() as usize + 1;
    let xs: Vec<f64> = (0..n_prices).map(|i| min_p + i as f64 * step).collect();
    let mut curpdfs: Vec<f64> = Vec::with_capacity(n_days * n_prices);
    let mut day_buf = vec![0.0f64; n_prices];
    for i in 0..n_days {
        calc_single_day_curpdf_into(
            close[i],
            high[i],
            low[i],
            volume[i],
            &xs,
            step,
            &mut day_buf,
        );
        if day_buf.iter().any(|v| !v.is_finite()) {
            return None;
        }
        curpdfs.extend_from_slice(&day_buf);
    }

    let cumpdf = calc_cumpdf_decay(&curpdfs, &turnovers, n_days, n_prices);
    let cyqk = calc_cyqk(&cumpdf, &xs, close[n_days - 1]);
    if cyqk.is_nan() {
        None
    } else {
        Some(cyqk)
    }
}

/// 滚动窗口 CYQK 序列。`out[i]` = 窗口 `[i-window+1, i]`（含 i）。
///
/// `i < max(window-1, start_i)` 或窗口无效 → `NaN`。按日并行（rayon）。
#[allow(clippy::too_many_arguments)] // 数值序列入参天然多参；与 pyo3 绑定签名一一对应
pub fn compute_cyqk_series(
    close: &[f64],
    high: &[f64],
    low: &[f64],
    volume: &[f64],
    shares: &[f64],
    window: usize,
    start_i: usize,
    step: f64,
) -> Vec<f64> {
    let n = close.len();
    let mut out = vec![f64::NAN; n];
    if window == 0
        || n < window
        || high.len() != n
        || low.len() != n
        || volume.len() != n
        || shares.len() != n
    {
        return out;
    }
    let first = start_i.max(window - 1);
    if first >= n {
        return out;
    }

    let computed: Vec<(usize, f64)> = (first..n)
        .into_par_iter()
        .map(|i| {
            let lo = i + 1 - window;
            let v = compute_cyqk_ohlcv_window(
                &close[lo..=i],
                &high[lo..=i],
                &low[lo..=i],
                &volume[lo..=i],
                &shares[lo..=i],
                step,
            )
            .unwrap_or(f64::NAN);
            (i, v)
        })
        .collect();
    for (i, v) in computed {
        out[i] = v;
    }
    out
}

/// 计算相邻两个窗口（T 与 T-1）的 CYQK，避免重复构建价格网格。
///
/// `union_bars` 至少包含 T 窗口和 T-1 窗口的并集，通常长度为 `window+1`。
/// 阶段 1 优化：一次性计算所有 bar 的 curpdf（三角分布），返回扁平化数组。
/// curpdf 只依赖价格/成交量，与股本无关。circ 和 free 可复用同一份 curpdf。
///
/// 返回 `(all_curpdfs_flat, all_turnovers, n_prices, xs, t_start, t1_start, window_len)`
#[derive(Debug)]
pub struct PrecomputedCurpdf {
    pub all_curpdfs: Vec<f64>,
    pub all_turnovers_base: Vec<f64>,
    pub n_prices: usize,
    pub xs: Vec<f64>,
    pub t_start: usize,
    pub t1_start: usize,
    pub window_len: usize,
    pub close_t: f64,
    pub close_t1: f64,
}

#[derive(Debug, Error)]
pub enum ComputeCurpdfError {
    #[error("window length {window_len} is too short")]
    WindowTooShort { window_len: usize },
    #[error("window range out of bounds: union_len={union_len} t_start={t_start} t1_start={t1_start} window_len={window_len}")]
    WindowOutOfBounds {
        union_len: usize,
        t_start: usize,
        t1_start: usize,
        window_len: usize,
    },
    #[error("invalid price range for grid construction")]
    InvalidPriceRange,
    #[error("grid points {n_prices} exceed max {max_grid_points}")]
    GridTooLarge {
        n_prices: usize,
        max_grid_points: usize,
    },
}

pub fn compute_curpdfs_once(
    union_bars: &[BarRow],
    t_start: usize,
    t1_start: usize,
    window_len: usize,
    step: f64,
    max_grid_points: usize,
) -> Result<PrecomputedCurpdf, ComputeCurpdfError> {
    if window_len < 20 {
        return Err(ComputeCurpdfError::WindowTooShort { window_len });
    }
    let union_len = union_bars.len();
    if t_start + window_len > union_len || t1_start + window_len > union_len {
        return Err(ComputeCurpdfError::WindowOutOfBounds {
            union_len,
            t_start,
            t1_start,
            window_len,
        });
    }

    let mut min_p = f64::INFINITY;
    let mut max_p = f64::NEG_INFINITY;
    for bar in union_bars {
        if !bar.low.is_nan() && bar.low < min_p {
            min_p = bar.low;
        }
        if !bar.high.is_nan() && bar.high > max_p {
            max_p = bar.high;
        }
    }
    if min_p.is_nan() || max_p.is_nan() || max_p <= min_p {
        return Err(ComputeCurpdfError::InvalidPriceRange);
    }

    let n_prices = ((max_p - min_p) / step).ceil() as usize + 1;
    if n_prices > max_grid_points {
        return Err(ComputeCurpdfError::GridTooLarge {
            n_prices,
            max_grid_points,
        });
    }
    let xs: Vec<f64> = (0..n_prices).map(|i| min_p + i as f64 * step).collect();

    let mut all_turnovers = Vec::with_capacity(union_len);
    let mut all_curpdfs = Vec::with_capacity(union_len * n_prices);
    let mut day_buf = vec![0.0f64; n_prices];
    for bar in union_bars {
        all_turnovers.push(calc_turnover_rate(bar.volume, 1.0)); // placeholder, scaled later
        calc_single_day_curpdf_into(
            bar.close,
            bar.high,
            bar.low,
            bar.volume as f64,
            &xs,
            step,
            &mut day_buf,
        );
        all_curpdfs.extend_from_slice(&day_buf);
    }
    let close_t = union_bars[t_start + window_len - 1].close;
    let close_t1 = union_bars[t1_start + window_len - 1].close;
    Ok(PrecomputedCurpdf {
        all_curpdfs,
        all_turnovers_base: all_turnovers,
        n_prices,
        xs,
        t_start,
        t1_start,
        window_len,
        close_t,
        close_t1,
    })
}

/// 从预计算的 curpdf（volume-scaled）计算 cyqk，只需提供对应股本下的 turnover。
/// turnover_rate = vol * 100 / float_shares，curpdf 已含 volume，这里做归一化缩放。
///
/// `float_shares_t` 用于 T 窗口，`float_shares_t1` 用于 T-1 窗口，
/// 与 Python 端 `circ_cap_t` / `circ_cap_prev` 分别加载的行为对齐。
pub fn compute_cyqk_from_curpdfs(
    precomputed: &PrecomputedCurpdf,
    float_shares_t: f64,
    float_shares_t1: f64,
) -> Option<(f64, f64)> {
    let PrecomputedCurpdf {
        all_curpdfs,
        all_turnovers_base,
        n_prices,
        xs,
        t_start,
        t1_start,
        window_len,
        close_t,
        close_t1,
    } = precomputed;
    // calc_turnover_rate(vol, 1.0) = vol * 100 / 1.0 = vol * 100
    // We need vol * 100 / real_float_shares, so scale = 1.0 / real_float_shares
    let scale_t = 1.0 / float_shares_t;
    let scale_t1 = 1.0 / float_shares_t1;
    if *window_len == 0 || *n_prices == 0 || !scale_t.is_finite() || !scale_t1.is_finite() {
        return None;
    }
    let mut cumpdf_buf = vec![0.0f64; *n_prices];

    calc_cumpdf_decay_window_scaled(
        all_curpdfs,
        all_turnovers_base,
        scale_t,
        *t_start,
        *window_len,
        *n_prices,
        &mut cumpdf_buf,
    );
    let cyqk_t = calc_cyqk(&cumpdf_buf, xs, *close_t);

    calc_cumpdf_decay_window_scaled(
        all_curpdfs,
        all_turnovers_base,
        scale_t1,
        *t1_start,
        *window_len,
        *n_prices,
        &mut cumpdf_buf,
    );
    let cyqk_t1 = calc_cyqk(&cumpdf_buf, xs, *close_t1);

    if cyqk_t.is_nan() || cyqk_t1.is_nan() {
        None
    } else {
        Some((cyqk_t, cyqk_t1))
    }
}

fn calc_cumpdf_decay_window_scaled(
    all_curpdfs: &[f64],
    all_turnovers_base: &[f64],
    scale: f64,
    start: usize,
    window_len: usize,
    n_prices: usize,
    out: &mut [f64],
) {
    debug_assert!(window_len > 0);
    debug_assert_eq!(out.len(), n_prices);
    let first_day_off = start * n_prices;
    let t0 = all_turnovers_base[start] * scale;
    for (j, out_j) in out.iter_mut().enumerate().take(n_prices) {
        *out_j = all_curpdfs[first_day_off + j] * t0;
    }
    for i in 1..window_len {
        let global_day = start + i;
        let t = all_turnovers_base[global_day] * scale;
        let diff = 1.0 - t;
        let off = global_day * n_prices;
        for j in 0..n_prices {
            out[j] = out[j] * diff + all_curpdfs[off + j] * t;
        }
    }
}

/// - `t_start` / `t1_start` 是在 `union_bars` 上的起点偏移
/// - `window_len` 是两个窗口相同的长度
pub fn compute_cyqk_for_adjacent_windows(
    union_bars: &[BarRow],
    t_start: usize,
    t1_start: usize,
    window_len: usize,
    float_shares: f64,
    step: f64,
) -> Option<(f64, f64)> {
    let precomputed =
        compute_curpdfs_once(union_bars, t_start, t1_start, window_len, step, usize::MAX).ok()?;
    compute_cyqk_from_curpdfs(&precomputed, float_shares, float_shares)
}

/// 从已按时间排序的 bars 中切出最后 `window` 根满足 `time_ms <= target_ms` 的 K 线。
///
/// 使用 `partition_point` 二分查找（O(log n)），假设 bars 已按 `time_ms` 升序排列。
///
/// # 边界
/// - `end < window`：有多少用多少（与 Python `unique_dates[-window:]` 行为一致）
/// - `end == 0`：无数据满足条件 → 返回空切片
pub fn slice_window(bars: &[BarRow], target_ms: i64, window: usize) -> &[BarRow] {
    // 二分查找第一个 time_ms > target_ms 的位置 = 满足 <= target 的元素个数
    let end = bars.partition_point(|b| b.time_ms <= target_ms);
    let start = end.saturating_sub(window);
    &bars[start..end]
}
