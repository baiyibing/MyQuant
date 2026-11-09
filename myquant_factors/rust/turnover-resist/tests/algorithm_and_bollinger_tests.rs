use std::time::Instant;
use turnover_resist::algorithm::{
    calc_cumpdf_decay, calc_cyqk, calc_single_day_curpdf, calc_turnover_rate,
    compute_cyqk_for_adjacent_windows, compute_cyqk_for_window, compute_cyqk_ohlcv_window,
    compute_cyqk_series,
};
use turnover_resist::bollinger::bollinger_bands;
use turnover_resist::types::BarRow;

fn bar(time_ms: i64, close: f64, high: f64, low: f64, volume: i64) -> BarRow {
    BarRow {
        time_ms,
        open: close,
        high,
        low,
        close,
        volume,
        amount: close * volume as f64 * 100.0,
    }
}

#[test]
fn turnover_rate_uses_hands_to_shares_conversion() {
    let t = calc_turnover_rate(1_000, 10_000_000.0);
    assert!((t - 0.01).abs() < 1e-12);
}

#[test]
fn single_day_pdf_conserves_volume() {
    let xs: Vec<f64> = (0..101).map(|i| 10.0 + i as f64 * 0.01).collect();
    let pdf = calc_single_day_curpdf(10.5, 11.0, 10.0, 12_345.0, &xs, 0.01);
    let s: f64 = pdf.iter().sum();
    assert!((s - 12_345.0).abs() < 1e-6);
}

#[test]
fn decay_and_cyqk_are_well_formed() {
    let n_days = 2usize;
    let n_prices = 3usize;
    let curpdfs = vec![
        1.0, 2.0, 3.0, // day0
        2.0, 2.0, 2.0, // day1
    ];
    let turnover = vec![0.5, 0.4];
    let cumpdf = calc_cumpdf_decay(&curpdfs, &turnover, n_days, n_prices);
    assert_eq!(cumpdf.len(), 3);
    let xs = vec![1.0, 2.0, 3.0];
    let cyqk = calc_cyqk(&cumpdf, &xs, 2.0);
    assert!(cyqk.is_finite());
    assert!((0.0..=1.0).contains(&cyqk));
}

#[test]
fn decay_matches_golden_vector() {
    // day0: [1, 2], turnover=0.5 => [0.5, 1.0]
    // day1: [3, 4], turnover=0.2 => [0.5*0.8+3*0.2, 1.0*0.8+4*0.2] = [1.0, 1.6]
    // day2: [5, 6], turnover=0.1 => [1.0*0.9+5*0.1, 1.6*0.9+6*0.1] = [1.4, 2.04]
    let curpdfs = vec![
        1.0, 2.0, // day0
        3.0, 4.0, // day1
        5.0, 6.0, // day2
    ];
    let turnover = vec![0.5, 0.2, 0.1];
    let out = calc_cumpdf_decay(&curpdfs, &turnover, 3, 2);
    assert!((out[0] - 1.4).abs() < 1e-12);
    assert!((out[1] - 2.04).abs() < 1e-12);
}

#[test]
fn adjacent_window_matches_baseline_window_compute() {
    let mut bars = Vec::new();
    for i in 0..45 {
        let c = 10.0 + i as f64 * 0.05;
        bars.push(bar(i as i64, c, c + 0.2, c - 0.2, 50_000 + i as i64 * 100));
    }
    let float_shares = 1_000_000_000.0;
    let step = 0.01;
    let w = 20usize;
    let t_end = bars.len();
    let t1_end = t_end - 1;
    let t_start = t_end - w;
    let t1_start = t1_end - w;
    let union = &bars[t1_start..t_end];
    let (cyqk_t, cyqk_t1) =
        compute_cyqk_for_adjacent_windows(union, 1, 0, w, float_shares, step).unwrap();
    let base_t = compute_cyqk_for_window(&bars[t_start..t_end], float_shares, step).unwrap();
    let base_t1 = compute_cyqk_for_window(&bars[t1_start..t1_end], float_shares, step).unwrap();
    // 邻接窗口共享网格（union low/high）与单窗口独立网格存在系统偏差；
    // 在真实数据分布下差异通常很小，这里保留宽松阈值用于防回归。
    assert!((cyqk_t - base_t).abs() < 5e-2);
    assert!((cyqk_t1 - base_t1).abs() < 5e-2);
}

fn bars_to_ohlcv(bars: &[BarRow]) -> (Vec<f64>, Vec<f64>, Vec<f64>, Vec<f64>) {
    (
        bars.iter().map(|b| b.close).collect(),
        bars.iter().map(|b| b.high).collect(),
        bars.iter().map(|b| b.low).collect(),
        bars.iter().map(|b| b.volume as f64).collect(),
    )
}

#[test]
fn daily_share_window_matches_single_share_when_constant() {
    let mut bars = Vec::new();
    for i in 0..25 {
        let c = 10.0 + i as f64 * 0.05;
        bars.push(bar(i as i64, c, c + 0.2, c - 0.2, 50_000 + i as i64 * 100));
    }
    let float_shares = 1_000_000_000.0;
    let step = 0.01;
    let expected = compute_cyqk_for_window(&bars, float_shares, step).unwrap();
    let (close, high, low, volume) = bars_to_ohlcv(&bars);
    let shares = vec![float_shares; bars.len()];
    let got = compute_cyqk_ohlcv_window(&close, &high, &low, &volume, &shares, step).unwrap();
    assert!((got - expected).abs() < 1e-12);
}

#[test]
fn daily_share_window_changes_when_shares_change() {
    let mut bars = Vec::new();
    for i in 0..25 {
        let c = 10.0 + i as f64 * 0.05;
        bars.push(bar(i as i64, c, c + 0.2, c - 0.2, 50_000 + i as i64 * 100));
    }
    let step = 0.01;
    let (close, high, low, volume) = bars_to_ohlcv(&bars);
    let constant = vec![1_000_000_000.0; bars.len()];
    let mut varied = constant.clone();
    for s in varied.iter_mut().skip(12) {
        *s = 2_000_000_000.0;
    }
    let a = compute_cyqk_ohlcv_window(&close, &high, &low, &volume, &constant, step).unwrap();
    let b = compute_cyqk_ohlcv_window(&close, &high, &low, &volume, &varied, step).unwrap();
    assert!((a - b).abs() > 1e-8);
}

#[test]
fn daily_share_window_nan_share_is_none() {
    let close = vec![10.0; 20];
    let high = vec![10.2; 20];
    let low = vec![9.8; 20];
    let volume = vec![50_000.0; 20];
    let mut shares = vec![1_000_000_000.0; 20];
    shares[7] = f64::NAN;
    assert!(compute_cyqk_ohlcv_window(&close, &high, &low, &volume, &shares, 0.01).is_none());
}

#[test]
fn cyqk_series_nan_prefix_and_recovers_after_poisoned_day() {
    let n = 30usize;
    let window = 20usize;
    let mut close = Vec::with_capacity(n);
    let mut high = Vec::with_capacity(n);
    let mut low = Vec::with_capacity(n);
    let mut volume = Vec::with_capacity(n);
    for i in 0..n {
        let c = 10.0 + i as f64 * 0.04;
        close.push(c);
        high.push(c + 0.15);
        low.push(c - 0.15);
        volume.push(40_000.0);
    }
    let mut shares = vec![1_000_000_000.0; n];
    shares[0] = f64::NAN;
    let out = compute_cyqk_series(&close, &high, &low, &volume, &shares, window, 0, 0.01);
    assert_eq!(out.len(), n);
    assert!(out[..window - 1].iter().all(|v| v.is_nan()));
    assert!(out[window - 1].is_nan());
    assert!(out[window].is_finite());
}

#[test]
fn bollinger_ddof_changes_band_width() {
    let closes: Vec<f64> = (1..=40).map(|i| i as f64).collect();
    let bb0 = bollinger_bands(&closes, 20, 2.0, 0);
    let bb1 = bollinger_bands(&closes, 20, 2.0, 1);
    assert!(bb1.upper > bb0.upper);
    assert!(bb1.lower < bb0.lower);
}

#[test]
#[ignore = "micro benchmark for local profiling"]
fn bench_like_curpdf_runtime() {
    let xs: Vec<f64> = (0..4000).map(|i| 8.0 + i as f64 * 0.01).collect();
    let begin = Instant::now();
    for _ in 0..300 {
        let pdf = calc_single_day_curpdf(19.73, 20.30, 18.92, 1_250_000.0, &xs, 0.01);
        std::hint::black_box(pdf);
    }
    eprintln!(
        "[bench_like] curpdf elapsed_ms={}",
        begin.elapsed().as_millis()
    );
}

#[test]
#[ignore = "micro benchmark for local profiling"]
fn bench_like_decay_runtime() {
    let n_days = 1000usize;
    let n_prices = 1800usize;
    let mut curpdfs = vec![0.0f64; n_days * n_prices];
    for i in 0..n_days {
        for j in 0..n_prices {
            let idx = i * n_prices + j;
            curpdfs[idx] = ((i + j) % 17) as f64 + 1.0;
        }
    }
    let turnover_rates: Vec<f64> = (0..n_days)
        .map(|i| 0.002 + (i % 7) as f64 * 0.0003)
        .collect();
    let begin = Instant::now();
    for _ in 0..80 {
        let out = calc_cumpdf_decay(&curpdfs, &turnover_rates, n_days, n_prices);
        std::hint::black_box(out);
    }
    eprintln!(
        "[bench_like] decay elapsed_ms={}",
        begin.elapsed().as_millis()
    );
}
