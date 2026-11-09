//! 换手阻力核心计算引擎：数据加载 → 并行计算 → 排序。
//!
//! 本模块同时服务于 CLI (`main.rs`) 和 PyO3 绑定 (`lib.rs`)，
//! 避免 binary / library 之间的代码重复。

use std::collections::HashMap;
use std::sync::atomic::{AtomicUsize, Ordering};

use anyhow::Result;
use chrono::NaiveDate;
use rayon::prelude::*;

use crate::algorithm::{
    calc_turnover_rate, compute_curpdfs_once, compute_cyqk_from_curpdfs, ComputeCurpdfError,
};
use crate::bollinger::bollinger_bands;
use crate::cli::{Cli, FreeFloatPolicy, SortBy, TargetDatePolicy};
use crate::data::{
    load_all_stocks_parquet, load_float_shares, load_free_float_shares, stock_code_to_dir,
    ParquetLoadStats,
};
use crate::types::{BarRow, ComputeContext, FloatSharesInfo, FreeFloatSharesInfo, OutputRow};

/// YYYYMMDD 日期 → UTC 午夜的 epoch 毫秒。
pub fn date_to_ms(date: NaiveDate) -> i64 {
    date.and_hms_opt(0, 0, 0)
        .expect("valid date constructor")
        .and_utc()
        .timestamp_millis()
}

#[derive(Debug, Clone, Copy, Eq, PartialEq, Hash)]
pub enum SkipReason {
    MissingFloatShares,
    MissingBars,
    EmptyBars,
    TargetDateMismatch,
    InsufficientBars,
    CurpdfWindowInvalid,
    GridTooLarge,
    MissingFreeFloat,
    InvalidFreeFloatCapital,
}

/// 单只股票的处理管线：读数据 → 切交易日窗口 → 计算 cyqk → 计算阻力 → 布林带 → 输出一行。
pub fn process_one_stock(
    stock_code: &str,
    ctx: &ComputeContext,
    fs_info: &FloatSharesInfo,
    ff_info: Option<&FreeFloatSharesInfo>,
    ff_info_prev: Option<&FreeFloatSharesInfo>,
    free_float_policy: FreeFloatPolicy,
    bars: &[BarRow],
) -> std::result::Result<OutputRow, SkipReason> {
    if bars.is_empty() {
        return Err(SkipReason::EmptyBars);
    }

    let keep_rows = std::cmp::max(ctx.window + 32, ctx.bb_period + 32);
    let bars = if bars.len() > keep_rows {
        &bars[bars.len() - keep_rows..]
    } else {
        bars
    };
    let last_bar = bars.last().ok_or(SkipReason::EmptyBars)?;
    if last_bar.time_ms != ctx.target_date_ms && !ctx.allow_previous_target_date {
        return Err(SkipReason::TargetDateMismatch);
    }

    if bars.len() < 21 {
        return Err(SkipReason::InsufficientBars);
    }
    let t_end = bars.len();
    let t1_end = t_end - 1;
    if t1_end < 20 {
        return Err(SkipReason::InsufficientBars);
    }
    let t_len = std::cmp::min(ctx.window, t_end);
    let t1_len = std::cmp::min(ctx.window, t1_end);
    let aligned_len = std::cmp::min(t_len, t1_len);
    if aligned_len < 20 {
        return Err(SkipReason::InsufficientBars);
    }
    let t_start = t_end - aligned_len;
    let t1_start = t1_end - aligned_len;
    let union_start = std::cmp::min(t_start, t1_start);
    let union_bars: &[BarRow] = &bars[union_start..t_end];

    let t_off = t_start - union_start;
    let t1_off = t1_start - union_start;
    let close_t = last_bar.close;

    let precomputed = match compute_curpdfs_once(
        union_bars,
        t_off,
        t1_off,
        aligned_len,
        ctx.step,
        ctx.max_grid_points,
    ) {
        Ok(v) => v,
        Err(ComputeCurpdfError::GridTooLarge { .. }) => return Err(SkipReason::GridTooLarge),
        Err(_) => return Err(SkipReason::CurpdfWindowInvalid),
    };

    let circ_cap_t = ff_info
        .and_then(|x| (x.circulating_capital > 0.0).then_some(x.circulating_capital))
        .unwrap_or(fs_info.float_shares);
    let circ_cap_t1 = ff_info_prev
        .and_then(|x| (x.circulating_capital > 0.0).then_some(x.circulating_capital))
        .unwrap_or(fs_info.float_shares);
    let (cyqk_circ_t, cyqk_circ_t_1) =
        compute_cyqk_from_curpdfs(&precomputed, circ_cap_t, circ_cap_t1)
            .ok_or(SkipReason::CurpdfWindowInvalid)?;
    let profit_chip_diff_circ = cyqk_circ_t - cyqk_circ_t_1;
    let turnover_circ_t = calc_turnover_rate(last_bar.volume, circ_cap_t);
    let resistance_circ = if turnover_circ_t > 0.0 {
        profit_chip_diff_circ / turnover_circ_t
    } else {
        0.0
    };

    let (turnover_free_t, resistance_free, free_cap, circ_cap_hist) = match ff_info {
        Some(ff) => {
            let fc_t = ff.free_float_capital;
            let cc = ff.circulating_capital;
            if fc_t <= 0.0 {
                return Err(SkipReason::InvalidFreeFloatCapital);
            }
            let fc_t1 = ff_info_prev.map_or(fc_t, |x| {
                if x.free_float_capital > 0.0 {
                    x.free_float_capital
                } else {
                    fc_t
                }
            });
            let (cyqk_free_t, cyqk_free_t_1) = compute_cyqk_from_curpdfs(&precomputed, fc_t, fc_t1)
                .ok_or(SkipReason::CurpdfWindowInvalid)?;
            let profit_free = cyqk_free_t - cyqk_free_t_1;
            let t_free = calc_turnover_rate(last_bar.volume, fc_t);
            let r_free = if t_free > 0.0 {
                profit_free / t_free
            } else {
                0.0
            };
            (t_free, r_free, fc_t, cc)
        }
        None => match free_float_policy {
            // v1.1: use circ_cap_t1 here so the output `circulating_capital`
            // column reflects the T-1 period capital, matching Python behaviour.
            // (The circulating capital cyqk already uses both values correctly
            // at line 114–116; this only affects the output metadata column.)
            FreeFloatPolicy::WarnZero => (0.0, 0.0, 0.0, circ_cap_t1.max(0.0)),
            FreeFloatPolicy::Skip | FreeFloatPolicy::Fail => {
                return Err(SkipReason::MissingFreeFloat)
            }
        },
    };

    let closes: Vec<f64> = bars.iter().map(|b| b.close).collect();
    let bb = bollinger_bands(&closes, ctx.bb_period, ctx.bb_std, ctx.bb_ddof);

    Ok(OutputRow {
        stock_code: stock_code.to_string(),
        stock_name: fs_info.name.clone(),
        date: ctx.date_str.clone(),
        close: (close_t * 100.0).round() / 100.0,
        cyqk_t: (cyqk_circ_t * 10000.0).round() / 10000.0,
        cyqk_t_1: (cyqk_circ_t_1 * 10000.0).round() / 10000.0,
        profit_chip_diff: (profit_chip_diff_circ * 1_000_000.0).round() / 1_000_000.0,
        turnover: (turnover_circ_t * 1_000_000.0).round() / 1_000_000.0,
        turnover_resistance: (resistance_circ * 10000.0).round() / 10000.0,
        turnover_free: (turnover_free_t * 1_000_000.0).round() / 1_000_000.0,
        turnover_resistance_free: (resistance_free * 10000.0).round() / 10000.0,
        circulating_capital: circ_cap_hist,
        free_float_capital: free_cap,
        bb_upper: (bb.upper * 100.0).round() / 100.0,
        bb_middle: (bb.middle * 100.0).round() / 100.0,
        bb_lower: (bb.lower * 100.0).round() / 100.0,
        bb_position: (bb.position * 10000.0).round() / 10000.0,
        bb_width: (bb.width * 10000.0).round() / 10000.0,
    })
}

pub fn skip_reason_label(reason: SkipReason) -> &'static str {
    match reason {
        SkipReason::MissingFloatShares => "missing_float_shares",
        SkipReason::MissingBars => "missing_bars",
        SkipReason::EmptyBars => "empty_bars",
        SkipReason::TargetDateMismatch => "target_date_mismatch",
        SkipReason::InsufficientBars => "insufficient_bars",
        SkipReason::CurpdfWindowInvalid => "curpdf_window_invalid",
        SkipReason::GridTooLarge => "grid_too_large",
        SkipReason::MissingFreeFloat => "missing_free_float",
        SkipReason::InvalidFreeFloatCapital => "invalid_free_float_capital",
    }
}

pub fn print_skip_summary(skip_counts: &HashMap<SkipReason, usize>) {
    let mut items: Vec<(SkipReason, usize)> = skip_counts.iter().map(|(k, v)| (*k, *v)).collect();
    items.sort_by_key(|(_, count)| std::cmp::Reverse(*count));
    eprintln!("  skip breakdown:");
    for (reason, count) in items {
        eprintln!("    - {:>28}: {}", skip_reason_label(reason), count);
    }
}

pub fn print_parquet_load_stats(stats: &ParquetLoadStats) {
    eprintln!(
        "  parquet stats: requested={} loaded={} missing_path={} non_utf8_path={} scan_failed={} empty_after_filter={} decode_failed={}",
        stats.requested,
        stats.loaded,
        stats.missing_path,
        stats.non_utf8_path,
        stats.scan_failed,
        stats.empty_after_filter,
        stats.decode_failed,
    );
}

/// Compute outcome with structured performance profile.
pub struct RunOutcome {
    pub rows: Vec<OutputRow>,
    pub profile: crate::profile::ProfileReport,
    pub skip_counts: HashMap<SkipReason, usize>,
}

/// 核心计算入口：加载数据 → 并行计算 → 排序 → 返回结果。
pub fn run(cli: &Cli) -> Result<Vec<OutputRow>> {
    Ok(run_detailed(cli)?.rows)
}

/// Same as [`run`] but returns phase timings / counts for host profiling.
pub fn run_detailed(cli: &Cli) -> Result<RunOutcome> {
    let mut clock = crate::profile::PhaseClock::new();
    clock.begin("total");

    let target_date_ms = date_to_ms(cli.date);
    let date_str = cli.date.format("%Y%m%d").to_string();
    let data_dir = cli.data_dir.to_str().unwrap_or("stock_data").to_string();

    // ---- 1. 加载流通股本 ----
    let fs_path = std::path::Path::new(&data_dir).join("float_shares.parquet");
    if !fs_path.exists() {
        anyhow::bail!("float_shares.parquet not found at {}", fs_path.display());
    }
    let fs_map = clock.time_result("load_float", || load_float_shares(&fs_path))?;
    let codes: Vec<String> = fs_map.keys().cloned().collect();
    clock.set_count("universe_codes", codes.len() as u64);

    // ---- 2. 加载自由流通股本历史 ----
    let ff_path = std::path::Path::new(&data_dir).join("free_float_shares.parquet");
    let ff_map: Option<HashMap<String, FreeFloatSharesInfo>> =
        clock.time("load_free_float", || {
            if ff_path.exists() {
                match load_free_float_shares(&ff_path, target_date_ms) {
                    Ok(m) if !m.is_empty() => Some(m),
                    Ok(_) | Err(_) => {
                        if cli.free_float_policy == FreeFloatPolicy::Fail {
                            None
                        } else {
                            eprintln!(
                                "  [WARN] free_float_shares.parquet load failed/empty, free-float columns fallback by policy={:?}",
                                cli.free_float_policy
                            );
                            None
                        }
                    }
                }
            } else {
                if cli.free_float_policy != FreeFloatPolicy::Fail {
                    eprintln!(
                        "  [WARN] free_float_shares.parquet not found, fallback by policy={:?}",
                        cli.free_float_policy
                    );
                }
                None
            }
        });
    if cli.free_float_policy == FreeFloatPolicy::Fail {
        if !ff_path.exists() {
            anyhow::bail!("free_float_shares.parquet not found under policy=fail");
        }
        if ff_map.is_none() {
            anyhow::bail!("free_float_shares.parquet exists but no valid rows under policy=fail");
        }
        let available = ff_map.as_ref().map_or(0, HashMap::len);
        anyhow::ensure!(
            available >= codes.len(),
            "free_float_shares coverage mismatch under policy=fail: map={} codes={}",
            available,
            codes.len()
        );
    }
    clock.set_count(
        "free_float_codes",
        ff_map.as_ref().map_or(0, |m| m.len() as u64),
    );

    // ---- 3. 加载 T-1 日自由流通股本 ----
    let target_prev_ms = target_date_ms - 86_400_000;
    let ff_map_prev: Option<HashMap<String, FreeFloatSharesInfo>> =
        clock.time("load_free_float_prev", || {
            if ff_path.exists() {
                load_free_float_shares(&ff_path, target_prev_ms).ok()
            } else {
                None
            }
        });

    eprintln!(
        "date={} window={} step={} max_grid_points={} stocks={} sort_by={:?} free_float_policy={:?} target_date_policy={:?} bb_ddof={}",
        date_str,
        cli.window,
        cli.step,
        cli.max_grid_points,
        codes.len(),
        cli.sort_by,
        cli.free_float_policy,
        cli.target_date_policy,
        cli.bb_ddof
    );

    // ---- 4. 构建共享上下文 ----
    let ctx = ComputeContext {
        target_date_ms,
        window: cli.window,
        step: cli.step,
        bb_period: 20,
        bb_std: 2.0,
        bb_ddof: cli.bb_ddof,
        data_dir: data_dir.clone(),
        date_str: date_str.clone(),
        allow_previous_target_date: cli.target_date_policy == TargetDatePolicy::AllowPrevious,
        max_grid_points: cli.max_grid_points,
    };

    // ---- 5. 批量加载日线数据 ----
    let start_ms = date_to_ms(cli.date - chrono::Duration::days(3000));
    let code_dirs: Vec<String> = codes
        .iter()
        .map(|c| format!("symbol={}", stock_code_to_dir(c)))
        .collect();
    let parquet_result = clock.time_result("load_bars", || {
        load_all_stocks_parquet(&ctx.data_dir, &code_dirs, start_ms, ctx.target_date_ms)
    })?;
    let bars_map = parquet_result.bars_by_code;
    let stats = &parquet_result.stats;
    clock.set_count("parquet_requested", stats.requested as u64);
    clock.set_count("parquet_loaded", stats.loaded as u64);
    clock.set_count("parquet_missing_path", stats.missing_path as u64);
    clock.set_count("parquet_scan_failed", stats.scan_failed as u64);
    clock.set_count(
        "parquet_empty_after_filter",
        stats.empty_after_filter as u64,
    );
    clock.set_count("parquet_decode_failed", stats.decode_failed as u64);
    eprintln!(
        "  [Timing] batch loaded {} stocks (see profile load_bars)",
        bars_map.len(),
    );
    print_parquet_load_stats(stats);

    // ---- 6. 并行计算（rayon） ----
    clock.time("rayon_init", || {
        let stack_size = std::env::var("RUST_MIN_STACK")
            .ok()
            .and_then(|v| v.parse::<usize>().ok())
            .filter(|&v| v > 0)
            .unwrap_or(8 * 1024 * 1024);
        if let Err(err) = rayon::ThreadPoolBuilder::new()
            .stack_size(stack_size)
            .build_global()
        {
            eprintln!("  [WARN] rayon global thread pool init skipped: {}", err);
        }
    });

    let processed = AtomicUsize::new(0);
    let total = codes.len();
    let outcomes: Vec<std::result::Result<OutputRow, SkipReason>> = clock.time("compute", || {
        codes
            .par_iter()
            .map(|code| {
                let n = processed.fetch_add(1, Ordering::Relaxed) + 1;
                if n.is_multiple_of(500) {
                    eprintln!("  {}/{} processed", n, total);
                }
                let info = match fs_map.get(code) {
                    Some(v) => v,
                    None => return Err(SkipReason::MissingFloatShares),
                };
                let ff_info = ff_map.as_ref().and_then(|m| m.get(code));
                let ff_info_prev = ff_map_prev.as_ref().and_then(|m| m.get(code));
                let bars = match bars_map.get(code) {
                    Some(v) => v,
                    None => return Err(SkipReason::MissingBars),
                };
                process_one_stock(
                    code,
                    &ctx,
                    info,
                    ff_info,
                    ff_info_prev,
                    cli.free_float_policy,
                    bars,
                )
            })
            .collect()
    });

    let (mut results, skip_counts) = clock.time("collect", || {
        let mut results: Vec<OutputRow> = Vec::with_capacity(outcomes.len());
        let mut skip_counts: HashMap<SkipReason, usize> = HashMap::new();
        for outcome in outcomes {
            match outcome {
                Ok(row) => results.push(row),
                Err(reason) => {
                    *skip_counts.entry(reason).or_insert(0) += 1;
                }
            }
        }
        (results, skip_counts)
    });
    let skipped = total.saturating_sub(results.len());
    clock.set_count("rows_valid", results.len() as u64);
    clock.set_count("rows_skipped", skipped as u64);
    for (reason, count) in &skip_counts {
        clock.set_count(
            &format!("skip_{}", skip_reason_label(*reason)),
            *count as u64,
        );
    }

    eprintln!("\nTotal: valid={}, skipped={}", results.len(), skipped);
    if skipped > 0 {
        print_skip_summary(&skip_counts);
    }

    if results.is_empty() {
        anyhow::bail!("No valid results");
    }

    // ---- 7. 排序 ----
    clock.time("sort", || match cli.sort_by {
        SortBy::Circulating => results.sort_by(|a, b| {
            b.turnover_resistance
                .abs()
                .partial_cmp(&a.turnover_resistance.abs())
                .unwrap_or(std::cmp::Ordering::Equal)
        }),
        SortBy::Free => results.sort_by(|a, b| {
            b.turnover_resistance_free
                .abs()
                .partial_cmp(&a.turnover_resistance_free.abs())
                .unwrap_or(std::cmp::Ordering::Equal)
        }),
    });

    clock.end("total");
    let profile = clock.report(
        "turnover-resist",
        &date_str,
        cli.window,
        None,
        Some(cli.data_dir.as_path()),
    );

    Ok(RunOutcome {
        rows: results,
        profile,
        skip_counts,
    })
}
