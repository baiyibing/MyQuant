//! CLI 参数定义，使用 clap derive 宏自动生成解析、校验和 `--help` 文档。

use chrono::NaiveDate;
use clap::{Parser, ValueEnum};
use std::path::PathBuf;

/// 命令行参数结构体，clap 从 `#[arg(long)]` 自动推导出 `--date`、`--window` 等选项。
#[derive(Parser, Debug)]
#[command(name = "turnover-resist")]
#[command(
    about = "Canonical turnover resistance calculation (Rust)",
    version = "0.1.0"
)]
pub struct Cli {
    /// 截面日期，YYYYMMDD 格式，必填。如 `--date 20260522`
    #[arg(long, value_parser = parse_date)]
    pub date: NaiveDate,

    /// 目标日期命中策略：strict=要求最后一根 K 线必须命中 --date；allow-previous=允许回退到前一交易日。
    #[arg(long, value_enum, default_value_t = TargetDatePolicy::Strict)]
    pub target_date_policy: TargetDatePolicy,

    /// 筹码衰减窗口（交易日数），默认 1000。不足时自动用全部可用交易日。
    #[arg(long, default_value = "1000")]
    pub window: usize,

    /// 价格网格步长（元），默认 0.01（一分钱）。控制筹码分布的精度。
    #[arg(long, default_value = "0.01")]
    pub step: f64,

    /// 单股票最大价格网格点数保护阈值，超过后跳过并统计（防止极端个股隐式 OOM）。
    #[arg(long, default_value_t = 250_000)]
    pub max_grid_points: usize,

    /// Bollinger 标准差自由度（0=总体标准差, 1=样本标准差）。
    /// 默认 1，对齐 pandas rolling(...).std() 默认行为。
    #[arg(long, default_value_t = 1)]
    pub bb_ddof: usize,

    /// 排序口径：circulating=|turnover_resistance|，free=|turnover_resistance_free|
    #[arg(long, value_enum, default_value_t = SortBy::Free)]
    pub sort_by: SortBy,

    /// free_float_shares 缺失策略：warn-zero=告警后 free 列置零，skip=缺失股票跳过，fail=直接报错退出。
    #[arg(long, value_enum, default_value_t = FreeFloatPolicy::WarnZero)]
    pub free_float_policy: FreeFloatPolicy,

    /// 输出 CSV 路径，默认 `backtest_output/canonical_resist_rust_{date}.csv`（带 _rust_ 后缀，避免与 Python 版冲突）
    #[arg(long)]
    pub output: Option<PathBuf>,

    /// 数据根目录（含 `float_shares.parquet` 与 `stock/period=1d/` 日线树；旧布局 `period=1d/` 自动回落），默认 `stock_data`
    #[arg(long, default_value = "stock_data")]
    pub data_dir: PathBuf,

    /// 写性能埋点 JSON（默认开；`OSKH_PROFILE_SIM=0` 关）。显式 `--profile` / `--no-profile` 覆盖环境变量。
    #[arg(long, action = clap::ArgAction::SetTrue, overrides_with = "no_profile")]
    pub profile: bool,

    /// 关闭性能埋点输出（仍会做轻量计时对象；不写 JSON、少打分相）。
    #[arg(long, action = clap::ArgAction::SetTrue, overrides_with = "profile")]
    pub no_profile: bool,

    /// 性能埋点 JSON 路径；默认写在 CSV 旁 `*.profile.json`。
    #[arg(long)]
    pub profile_json: Option<PathBuf>,
}

impl Cli {
    /// Resolve whether to emit profile JSON / stderr summary.
    pub fn profile_enabled(&self) -> bool {
        if self.no_profile {
            return false;
        }
        if self.profile {
            return true;
        }
        crate::profile::profile_enabled(None)
    }
}

/// 解析 YYYYMMDD → `NaiveDate`，格式不对时给出可读的错误提示。
fn parse_date(s: &str) -> Result<NaiveDate, String> {
    NaiveDate::parse_from_str(s, "%Y%m%d").map_err(|e| format!("invalid date '{}': {}", s, e))
}

#[derive(Copy, Clone, Debug, Eq, PartialEq, ValueEnum)]
pub enum SortBy {
    Circulating,
    Free,
}

#[derive(Copy, Clone, Debug, Eq, PartialEq, ValueEnum)]
pub enum FreeFloatPolicy {
    WarnZero,
    Skip,
    Fail,
}

#[derive(Copy, Clone, Debug, Eq, PartialEq, ValueEnum)]
pub enum TargetDatePolicy {
    Strict,
    AllowPrevious,
}
