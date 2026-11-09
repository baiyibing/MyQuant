//! 换手阻力全市场计算 — CLI 入口（轻量包装，核心逻辑在 `engine` 模块）。

use std::io::Write;
use std::path::PathBuf;
use std::time::Instant;

use anyhow::Result;
use clap::Parser;

use turnover_resist::cli::Cli;
use turnover_resist::profile::{default_profile_path, print_profile, write_profile_json};

fn main() -> Result<()> {
    let host_start = Instant::now();

    // ---- 1. 解析命令行参数 ----
    let cli = Cli::parse();

    anyhow::ensure!(cli.window >= 20, "--window must be >= 20");
    anyhow::ensure!(cli.step > 0.0, "--step must be > 0");

    let date_str = cli.date.format("%Y%m%d").to_string();
    let output_path = cli.output.clone().unwrap_or_else(|| {
        PathBuf::from(format!(
            "backtest_output/canonical_resist_rust_{}.csv",
            date_str
        ))
    });

    // ---- 2. 核心计算（engine 模块） ----
    let mut outcome = turnover_resist::engine::run_detailed(&cli)?;

    // ---- 3. 输出 CSV（UTF-8 BOM） ----
    let t_write = Instant::now();
    if let Some(parent) = output_path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let file = std::fs::File::create(&output_path)?;
    let mut writer = std::io::BufWriter::new(file);
    writer.write_all(&[0xEF, 0xBB, 0xBF])?;
    let mut csv_writer = csv::Writer::from_writer(writer);
    for row in &outcome.rows {
        csv_writer.serialize(row)?;
    }
    csv_writer.flush()?;
    outcome
        .profile
        .insert_phase("write_csv", t_write.elapsed().as_secs_f64());
    outcome
        .profile
        .stamp_output(&output_path, Some(cli.data_dir.as_path()));
    outcome
        .profile
        .set_wall_s(host_start.elapsed().as_secs_f64());

    // ---- 4. 打印结果摘要 + Top 20 ----
    eprintln!(
        "\n[Timing] total={:.1}s  rows={}",
        outcome.profile.wall_s,
        outcome.rows.len()
    );
    let top_key = match cli.sort_by {
        turnover_resist::cli::SortBy::Circulating => "|turnover_resistance|",
        turnover_resist::cli::SortBy::Free => "|turnover_resistance_free|",
    };
    eprintln!("\nTop 20 by {}:", top_key);
    for (i, row) in outcome.rows.iter().take(20).enumerate() {
        eprintln!(
            "  {:2}. {:>9} {:>8} resist={:>10.4} cyqk_T={:>8.4} cyqk_T_1={:>8.4} turnover={:>10.6}",
            i + 1,
            row.stock_code,
            row.stock_name,
            row.turnover_resistance,
            row.cyqk_t,
            row.cyqk_t_1,
            row.turnover,
        );
    }

    if cli.profile_enabled() {
        print_profile(&outcome.profile);
        let profile_path = cli
            .profile_json
            .clone()
            .unwrap_or_else(|| default_profile_path(&output_path));
        let written = write_profile_json(&profile_path, &outcome.profile)?;
        eprintln!(
            "profile_rust: wall={:.1}s rows={} -> {}",
            outcome.profile.wall_s,
            outcome.rows.len(),
            written.display()
        );
    }

    Ok(())
}
