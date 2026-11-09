//! 精度排查工具：对指定股票打印每个计算环节的中间值，用于与 Python 端逐步对比。
//!
//! 用法:
//!   cd turnover-resist && cargo build --release
//!   ./target/release/debug-precision --code 002374.SZ --date 20260525

use anyhow::Result;
use chrono::NaiveDate;
use clap::Parser;
use std::path::Path;

use turnover_resist::algorithm::{
    calc_cumpdf_decay, calc_single_day_curpdf_into, calc_turnover_rate,
};
use turnover_resist::data::{
    load_all_stocks_parquet, load_float_shares, load_free_float_shares, stock_code_to_dir,
};
use turnover_resist::types::BarRow;

#[derive(Parser)]
#[command(
    name = "debug-precision",
    about = "Precision debug tool for turnover-resist"
)]
struct Cli {
    #[arg(long, default_value = "002374.SZ")]
    code: String,

    #[arg(long, value_parser = parse_date)]
    date: NaiveDate,

    #[arg(long, default_value_t = 1000)]
    window: usize,

    #[arg(long, default_value_t = 0.01)]
    step: f64,

    #[arg(long, default_value = "stock_data")]
    data_dir: String,
}

fn parse_date(s: &str) -> Result<NaiveDate, String> {
    NaiveDate::parse_from_str(s, "%Y%m%d").map_err(|e| format!("invalid date: {}", e))
}

fn date_to_ms(date: NaiveDate) -> i64 {
    date.and_hms_opt(0, 0, 0)
        .expect("valid date")
        .and_utc()
        .timestamp_millis()
}

fn print_vec_f64(label: &str, v: &[f64], head: usize, tail: usize) {
    let n = v.len();
    if n <= head + tail {
        println!("{} (len={}): {:?}", label, n, v);
    } else {
        print!("{} (len={}): [", label, n);
        for (i, value) in v.iter().take(head).enumerate() {
            if i > 0 {
                print!(", ");
            }
            print!("{:.15e}", value);
        }
        print!(" ... ");
        for (idx, value) in v.iter().skip(n - tail).enumerate() {
            print!("{:.15e}", value);
            if idx + 1 < tail {
                print!(", ");
            }
        }
        println!("]");
    }
}

fn print_nonzero_bins(label: &str, xs: &[f64], pdf: &[f64], head: usize, tail: usize) {
    let nonzero: Vec<(usize, f64, f64)> = xs
        .iter()
        .zip(pdf.iter())
        .enumerate()
        .filter(|(_, (_, v))| **v != 0.0)
        .map(|(i, (x, v))| (i, *x, *v))
        .collect();
    let n = nonzero.len();
    println!("{} (nonzero_bins={}/{}):", label, n, xs.len());
    if n <= head + tail {
        for (i, x, v) in &nonzero {
            println!("  bin[{}] x={:.6} v={:.15e}", i, x, v);
        }
    } else {
        for (i, x, v) in nonzero.iter().take(head) {
            println!("  bin[{}] x={:.6} v={:.15e}", i, x, v);
        }
        println!("  ... ({} more) ...", n - head - tail);
        for (i, x, v) in nonzero.iter().skip(n - tail) {
            println!("  bin[{}] x={:.6} v={:.15e}", i, x, v);
        }
    }
}

fn main() -> Result<()> {
    let cli = Cli::parse();
    let target_date_ms = date_to_ms(cli.date);
    let date_str = cli.date.format("%Y%m%d").to_string();

    eprintln!("=== Rust precision debug ===");
    eprintln!(
        "stock={} date={} window={} step={}",
        cli.code, date_str, cli.window, cli.step
    );

    // Load data
    let fs_path = Path::new(&cli.data_dir).join("float_shares.parquet");
    let fs_map = load_float_shares(&fs_path)?;
    let ff_path = Path::new(&cli.data_dir).join("free_float_shares.parquet");
    let ff_map = load_free_float_shares(&ff_path, target_date_ms)?;

    let fs_info = fs_map
        .get(&cli.code)
        .ok_or_else(|| anyhow::anyhow!("{} not in float_shares", cli.code))?;
    let ff_info = ff_map
        .get(&cli.code)
        .ok_or_else(|| anyhow::anyhow!("{} not in free_float_shares", cli.code))?;

    let code_dir = format!("symbol={}", stock_code_to_dir(&cli.code));
    let start_ms = date_to_ms(cli.date - chrono::Duration::days(3000));
    let bars_result =
        load_all_stocks_parquet(&cli.data_dir, &[code_dir], start_ms, target_date_ms)?;
    let bars = bars_result
        .bars_by_code
        .get(&cli.code)
        .ok_or_else(|| anyhow::anyhow!("{} no bars loaded", cli.code))?;

    eprintln!("Loaded {} bars for {}", bars.len(), cli.code);

    // Tail trim
    let keep_rows = std::cmp::max(cli.window + 32, 20 + 32);
    let bars: &[BarRow] = if bars.len() > keep_rows {
        &bars[bars.len() - keep_rows..]
    } else {
        bars
    };
    eprintln!("After keep_rows trim: {} bars", bars.len());

    // Window slicing (same as main.rs)
    let t_end = bars.len();
    let t1_end = t_end - 1;
    let t_len = std::cmp::min(cli.window, t_end);
    let t1_len = std::cmp::min(cli.window, t1_end);
    let aligned_len = std::cmp::min(t_len, t1_len);
    let t_start = t_end - aligned_len;
    let t1_start = t1_end - aligned_len;
    let union_start = std::cmp::min(t_start, t1_start);
    let union_bars = &bars[union_start..t_end];
    let t_off = t_start - union_start;
    let t1_off = t1_start - union_start;

    println!("\n=== WINDOW ALIGNMENT ===");
    println!(
        "bars_total={} keep_rows={} aligned_len={}",
        bars.len(),
        keep_rows,
        aligned_len
    );
    println!(
        "t_start={} t_end={} t1_start={} t1_end={}",
        t_start, t_end, t1_start, t1_end
    );
    println!(
        "union_start={} union_len={} t_off={} t1_off={}",
        union_start,
        union_bars.len(),
        t_off,
        t1_off
    );
    println!(
        "T  window: first_date={} last_date={}",
        ms_to_date(union_bars[t_off].time_ms),
        ms_to_date(union_bars[t_off + aligned_len - 1].time_ms)
    );
    println!(
        "T-1 window: first_date={} last_date={}",
        ms_to_date(union_bars[t1_off].time_ms),
        ms_to_date(union_bars[t1_off + aligned_len - 1].time_ms)
    );
    println!("T  window bars count: {}", aligned_len);
    println!("T-1 window bars count: {}", aligned_len);

    // Capital values
    let circ_cap = if ff_info.circulating_capital > 0.0 {
        ff_info.circulating_capital
    } else {
        fs_info.float_shares
    };
    let free_cap = ff_info.free_float_capital;
    println!("\ncirculating_capital={:.6}", circ_cap);
    println!("freeFloatCapital={:.6}", free_cap);
    println!("NOTE: Rust uses SAME circ_cap for both T and T-1 windows");

    // Price grid (from union_bars)
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
    let n_prices = ((max_p - min_p) / cli.step).ceil() as usize + 1;
    let xs: Vec<f64> = (0..n_prices).map(|i| min_p + i as f64 * cli.step).collect();

    println!("\n=== PRICE GRID ===");
    println!(
        "min_p={:.15e} max_p={:.15e} step={} n_prices={}",
        min_p, max_p, cli.step, n_prices
    );
    println!("xs[0]={:.15e} xs[-1]={:.15e}", xs[0], xs[n_prices - 1]);

    // Compute curpdfs for all union_bars
    println!("\n=== CURPDF (all union_bars) ===");
    let mut all_curpdfs: Vec<f64> = Vec::with_capacity(union_bars.len() * n_prices);
    let mut all_turnovers_base: Vec<f64> = Vec::with_capacity(union_bars.len());
    let mut day_buf = vec![0.0f64; n_prices];

    for (di, bar) in union_bars.iter().enumerate() {
        let turnover_base = calc_turnover_rate(bar.volume, 1.0);
        all_turnovers_base.push(turnover_base);

        calc_single_day_curpdf_into(
            bar.close,
            bar.high,
            bar.low,
            bar.volume as f64,
            &xs,
            cli.step,
            &mut day_buf,
        );
        all_curpdfs.extend_from_slice(&day_buf);

        // Print first, middle, and last day curpdf details
        if di == 0 || di == union_bars.len() / 2 || di == union_bars.len() - 1 {
            println!(
                "\n--- Day {} date={} close={:.6} high={:.6} low={:.6} vol={} ---",
                di,
                ms_to_date(bar.time_ms),
                bar.close,
                bar.high,
                bar.low,
                bar.volume
            );
            let hl_diff = (bar.high - bar.low).abs();
            println!(
                "  high-low={:.15e} limit_up_down={}",
                hl_diff,
                hl_diff < 1e-12
            );
            let c_param = if hl_diff > 0.0 {
                (bar.close - bar.low) / (bar.high - bar.low)
            } else {
                0.0
            };
            println!("  c_param={:.15e}", c_param);

            let offset = di * n_prices;
            let curpdf = &all_curpdfs[offset..offset + n_prices];
            let sum: f64 = curpdf.iter().sum();
            println!("  curpdf_sum={:.15e} (should be ~{})", sum, bar.volume);
            print_nonzero_bins(&format!("  curpdf_day{}", di), &xs, curpdf, 10, 10);
        }
    }

    // Scale turnovers for circ_cap
    let scale_circ = 1.0 / circ_cap;
    let all_turnovers_circ: Vec<f64> = all_turnovers_base.iter().map(|t| t * scale_circ).collect();

    // Extract T window
    let t_turnovers: Vec<f64> = all_turnovers_circ[t_off..t_off + aligned_len].to_vec();
    let mut t_curpdfs: Vec<f64> = Vec::with_capacity(aligned_len * n_prices);
    for i in t_off..t_off + aligned_len {
        let off = i * n_prices;
        t_curpdfs.extend_from_slice(&all_curpdfs[off..off + n_prices]);
    }

    // Extract T-1 window
    let t1_turnovers: Vec<f64> = all_turnovers_circ[t1_off..t1_off + aligned_len].to_vec();
    let mut t1_curpdfs: Vec<f64> = Vec::with_capacity(aligned_len * n_prices);
    for i in t1_off..t1_off + aligned_len {
        let off = i * n_prices;
        t1_curpdfs.extend_from_slice(&all_curpdfs[off..off + n_prices]);
    }

    println!("\n=== TURNOVER RATES (circ_cap={:.6}) ===", circ_cap);
    println!(
        "T  turnover[0]={:.15e} turnover[-1]={:.15e}",
        t_turnovers[0],
        t_turnovers[aligned_len - 1]
    );
    println!(
        "T-1 turnover[0]={:.15e} turnover[-1]={:.15e}",
        t1_turnovers[0],
        t1_turnovers[aligned_len - 1]
    );
    // Print turnovers around the boundary (last day of T-1 = first day excluded from T)
    let boundary = 5;
    println!("T  turnover around boundary:");
    for (i, value) in t_turnovers
        .iter()
        .take(boundary.min(aligned_len))
        .enumerate()
    {
        println!("  T[{}]={:.15e}", i, value);
    }
    println!("T-1 turnover around boundary:");
    for (i, value) in t1_turnovers
        .iter()
        .enumerate()
        .skip(aligned_len - boundary)
        .take(boundary)
    {
        println!("  T-1[{}]={:.15e}", i, value);
    }

    // cumpdf for T window
    println!("\n=== CUMPDF (T window, circ) ===");
    let cumpdf_t = calc_cumpdf_decay(&t_curpdfs, &t_turnovers, aligned_len, n_prices);
    let total_t: f64 = cumpdf_t.iter().sum();
    println!("cumpdf_T sum={:.15e}", total_t);
    print_vec_f64(
        "cumpdf_T first 10 bins",
        &cumpdf_t[..10.min(n_prices)],
        10,
        0,
    );
    // Print last 10 nonzero
    print_nonzero_bins("cumpdf_T", &xs, &cumpdf_t, 10, 10);

    // cumpdf for T-1 window
    println!("\n=== CUMPDF (T-1 window, circ) ===");
    let cumpdf_t1 = calc_cumpdf_decay(&t1_curpdfs, &t1_turnovers, aligned_len, n_prices);
    let total_t1: f64 = cumpdf_t1.iter().sum();
    println!("cumpdf_T1 sum={:.15e}", total_t1);
    print_vec_f64(
        "cumpdf_T1 first 10 bins",
        &cumpdf_t1[..10.min(n_prices)],
        10,
        0,
    );
    print_nonzero_bins("cumpdf_T1", &xs, &cumpdf_t1, 10, 10);

    // Per-day cumpdf evolution (print every 100 days to track divergence accumulation)
    println!("\n=== CUMPDF EVOLUTION (T window, every 100 days) ===");
    {
        let mut cumpdf_evol = vec![0.0f64; n_prices];
        let t0 = t_turnovers[0];
        for j in 0..n_prices {
            cumpdf_evol[j] = t_curpdfs[j] * t0;
        }
        println!("day=0: sum={:.15e}", cumpdf_evol.iter().sum::<f64>());

        for (i, &t) in t_turnovers.iter().enumerate().skip(1).take(aligned_len - 1) {
            let diff = 1.0 - t;
            let offset = i * n_prices;
            for j in 0..n_prices {
                cumpdf_evol[j] = cumpdf_evol[j] * diff + t_curpdfs[offset + j] * t;
            }
            if i % 100 == 0 || i == aligned_len - 1 {
                let sum: f64 = cumpdf_evol.iter().sum();
                println!(
                    "day={}: sum={:.15e} first_bin={:.15e}",
                    i, sum, cumpdf_evol[0]
                );
            }
        }
        // Verify matches
        let max_diff = cumpdf_evol
            .iter()
            .zip(cumpdf_t.iter())
            .map(|(a, b)| (a - b).abs())
            .fold(0.0f64, f64::max);
        println!("evolution vs calc_cumpdf_decay max_diff={:.15e}", max_diff);
    }

    // cyqk
    let close_t = union_bars[t_off + aligned_len - 1].close;
    let close_t1 = union_bars[t1_off + aligned_len - 1].close;

    println!("\n=== CYQK ===");
    println!("close_T={:.15e} close_T1={:.15e}", close_t, close_t1);

    // T window cyqk
    let total_t: f64 = cumpdf_t.iter().sum();
    let mut winner_t = 0.0f64;
    let mut winner_bins_t = 0usize;
    for (j, &price) in xs.iter().enumerate() {
        if price <= close_t {
            winner_t += cumpdf_t[j];
            winner_bins_t += 1;
        }
    }
    let cyqk_t = if total_t > 0.0 {
        winner_t / total_t
    } else {
        f64::NAN
    };
    println!(
        "T:  winner={:.15e} total={:.15e} cyqk={:.15e} winner_bins={}/{}",
        winner_t, total_t, cyqk_t, winner_bins_t, n_prices
    );

    // T-1 window cyqk
    let total_t1: f64 = cumpdf_t1.iter().sum();
    let mut winner_t1 = 0.0f64;
    let mut winner_bins_t1 = 0usize;
    for (j, &price) in xs.iter().enumerate() {
        if price <= close_t1 {
            winner_t1 += cumpdf_t1[j];
            winner_bins_t1 += 1;
        }
    }
    let cyqk_t1 = if total_t1 > 0.0 {
        winner_t1 / total_t1
    } else {
        f64::NAN
    };
    println!(
        "T-1: winner={:.15e} total={:.15e} cyqk={:.15e} winner_bins={}/{}",
        winner_t1, total_t1, cyqk_t1, winner_bins_t1, n_prices
    );

    let profit_chip_diff = cyqk_t - cyqk_t1;
    let turnover_circ_t = calc_turnover_rate(bars[t_end - 1].volume, circ_cap);
    let resistance = if turnover_circ_t > 0.0 {
        profit_chip_diff / turnover_circ_t
    } else {
        0.0
    };

    println!("\n=== FINAL RESULTS (circ) ===");
    println!("cyqk_T={:.15e}", cyqk_t);
    println!("cyqk_T_1={:.15e}", cyqk_t1);
    println!("profit_chip_diff={:.15e}", profit_chip_diff);
    println!("turnover_T={:.15e}", turnover_circ_t);
    println!("turnover_resistance={:.15e}", resistance);

    // Also compute with alternative winner method (normalize first, like Python)
    println!("\n=== CYQK ALTERNATIVE (normalize first, like Python) ===");
    let acc_cum_t: f64 = cumpdf_t.iter().map(|v| v / total_t).sum::<f64>();
    let winner_alt_t: f64 = xs
        .iter()
        .zip(cumpdf_t.iter())
        .filter(|(x, _)| **x <= close_t)
        .map(|(_, v)| v / total_t)
        .sum();
    println!(
        "T  alt: sum(acc_cum)={:.15e} winner_alt={:.15e} diff_vs_above={:.15e}",
        acc_cum_t,
        winner_alt_t,
        (winner_alt_t - cyqk_t).abs()
    );

    Ok(())
}

fn ms_to_date(ms: i64) -> String {
    let secs = ms / 1000;
    let dt = chrono::DateTime::from_timestamp(secs, 0)
        .map(|d| d.format("%Y-%m-%d").to_string())
        .unwrap_or_else(|| format!("ms={}", ms));
    dt
}
