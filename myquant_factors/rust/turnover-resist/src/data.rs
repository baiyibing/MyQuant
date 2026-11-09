//! 数据 I/O 层：parquet 文件读取 + 流通股本加载 + 股票代码格式转换。
//!
//! 使用 polars lazy API 读取 parquet，列式批量读取后在 Rust 侧逐行转换为 `BarRow`。
//! 日线数据路径遵循 Hive 分区规范：`{data_dir}/stock/period=1d/dividend_type=front/symbol={CODE}/data.parquet`
//! （hive-split 前旧布局 `{data_dir}/period=1d/...` 仅在 stock 子树不存在时短暂回落，见 `stock_period_1d_root`）

use anyhow::{Context, Result};
use polars::datatypes::DataType;
use polars::prelude::*;
use std::collections::HashMap;
use std::path::Path;
use thiserror::Error;

use crate::types::{BarRow, FloatSharesInfo, FreeFloatSharesInfo};

#[derive(Debug, Error)]
pub enum DataLoadError {
    #[error("parquet path contains invalid UTF-8: {0}")]
    NonUtf8Path(String),
    #[error("polars failure: {0}")]
    Polars(#[from] PolarsError),
}

#[derive(Debug, Clone, Default)]
pub struct ParquetLoadStats {
    pub requested: usize,
    pub loaded: usize,
    pub missing_path: usize,
    pub non_utf8_path: usize,
    pub scan_failed: usize,
    pub empty_after_filter: usize,
    pub decode_failed: usize,
}

#[derive(Debug)]
pub struct ParquetLoadResult {
    pub bars_by_code: HashMap<String, Vec<BarRow>>,
    pub stats: ParquetLoadStats,
}

fn path_to_utf8(path: &Path) -> std::result::Result<&str, DataLoadError> {
    path.to_str()
        .ok_or_else(|| DataLoadError::NonUtf8Path(path.display().to_string()))
}

/// 目录名 → 股票代码：`000001_SZ` → `000001.SZ`
///
/// 日线 parquet 目录使用下划线分隔（`symbol=000001_SZ`），
/// 但其他数据源（float_shares、输出 CSV）使用点分隔的标准格式（`000001.SZ`）。
pub fn dir_to_stock_code(dir_name: &str) -> String {
    dir_name.replace('_', ".")
}

/// 股票代码 → 目录名：`000001.SZ` → `000001_SZ`
///
/// 反向转换，用于从标准代码构造 parquet 文件路径。
pub fn stock_code_to_dir(code: &str) -> String {
    code.replace('.', "_")
}

/// 加载 `float_shares.parquet` → `HashMap<stock_code, FloatSharesInfo>`。
///
/// 返回的 HashMap 以标准股票代码（如 "000001.SZ"）为键，
/// 值包含 `float_shares`（FloatVolume，流通股本，股）和 `name`（中文简称）。
/// 该 map 在随后计算中只读共享，所有 rayon 线程通过 `&` 引用访问。
pub fn load_float_shares(path: &Path) -> Result<HashMap<String, FloatSharesInfo>> {
    // polars lazy scan → 只读取需要的三列
    let path_str = path_to_utf8(path)?;
    let df = LazyFrame::scan_parquet(path_str, ScanArgsParquet::default())?.collect()?;

    // 按列提取数据（列式存储，比逐行读取高效）
    let stock_code_col = df.column("stock_code")?.str()?;
    let float_shares_col = df.column("FloatVolume")?.f64()?;
    let name_col = df.column("name")?.str()?;

    let mut map = HashMap::with_capacity(df.height());
    for i in 0..df.height() {
        let code = stock_code_col.get(i).unwrap_or("").to_string();
        if code.is_empty() {
            continue;
        }
        let fs = float_shares_col.get(i).unwrap_or(0.0);
        let name = name_col.get(i).unwrap_or("").to_string();
        map.insert(
            code,
            FloatSharesInfo {
                float_shares: fs,
                name,
            },
        );
    }

    Ok(map)
}

/// 加载 `free_float_shares.parquet` → `HashMap<stock_code, FreeFloatSharesInfo>`。
///
/// 对每只股票取 `m_timetag <= target_date` 的最新一行（merge_asof 语义）。
/// `target_date` 为 epoch 毫秒（UTC 午夜），用于与 parquet 中的 `m_timetag` 比较。
pub fn load_free_float_shares(
    path: &Path,
    target_date_ms: i64,
) -> Result<HashMap<String, FreeFloatSharesInfo>> {
    let path_str = path_to_utf8(path)?;
    let df = LazyFrame::scan_parquet(path_str, ScanArgsParquet::default())?.collect()?;

    let stock_code_col = df.column("stock_code")?.str()?;
    // m_timetag 是 datetime64[ns]，cast 到 Int64 后除以 1e6 得毫秒
    let timetag_raw = df.column("m_timetag")?.cast(&DataType::Int64)?;
    let timetag_col = timetag_raw.i64()?;
    let free_float_col = df.column("freeFloatCapital")?.f64()?;
    let circ_col = df.column("circulating_capital")?.f64()?;

    let mut map: HashMap<String, FreeFloatSharesInfo> = HashMap::with_capacity(df.height());
    for i in 0..df.height() {
        let code = stock_code_col.get(i).unwrap_or("").to_string();
        if code.is_empty() {
            continue;
        }
        // cast 后是纳秒，除以 1_000_000 得毫秒
        let ts_ms = timetag_col.get(i).unwrap_or(0) / 1_000_000;
        // 只取 <= target_date 的行；跳过非法时间戳
        if ts_ms > target_date_ms || ts_ms == 0 {
            continue;
        }
        let ff = free_float_col.get(i).unwrap_or(0.0);
        let cc = circ_col.get(i).unwrap_or(0.0);
        // merge_asof: 保留每个 stock_code 的最新（最大 timetag）值
        match map.get(&code) {
            Some(existing) => {
                if ts_ms > existing.timetag {
                    map.insert(
                        code,
                        FreeFloatSharesInfo {
                            free_float_capital: ff,
                            circulating_capital: cc,
                            timetag: ts_ms,
                        },
                    );
                }
            }
            None => {
                map.insert(
                    code,
                    FreeFloatSharesInfo {
                        free_float_capital: ff,
                        circulating_capital: cc,
                        timetag: ts_ms,
                    },
                );
            }
        }
    }

    Ok(map)
}

/// 从单个 parquet 文件读取全部历史日线 → `Vec<BarRow>`，按时间升序排列。
///
/// 注意：**不过滤 volume=0 行**，与 Python `StockDataReader.read_stock` 行为一致。
/// volume=0 的交易日（停牌等）在 decay 计算中 turnover=0，对 cumpdf 无影响但消耗一个日期槽位。
pub fn read_parquet_to_barrows(path: &Path) -> Result<Vec<BarRow>> {
    let path_str = path_to_utf8(path)?;
    // polars lazy scan：只投影需要的 7 列，跳过 parquet 文件中 pandas 残留的 __index_level_0__
    let df = LazyFrame::scan_parquet(path_str, ScanArgsParquet::default())?
        .select([
            col("time"),
            col("open"),
            col("high"),
            col("low"),
            col("close"),
            col("volume"),
            col("amount"),
        ])
        .collect()?;

    let n = df.height();
    // 按列提取原始数据（列式内存布局，缓存友好）
    let time_col = df.column("time")?.i64()?;
    let open_col = df.column("open")?.f64()?;
    let high_col = df.column("high")?.f64()?;
    let low_col = df.column("low")?.f64()?;
    let close_col = df.column("close")?.f64()?;
    let volume_col = df.column("volume")?.i64()?;
    let amount_col = df.column("amount")?.f64()?;

    // 逐行转换为 Rust 结构体
    let mut rows = Vec::with_capacity(n);
    for i in 0..n {
        let time_ms = time_col.get(i).unwrap_or(0);
        let open = open_col.get(i).unwrap_or(f64::NAN);
        let high = high_col.get(i).unwrap_or(f64::NAN);
        let low = low_col.get(i).unwrap_or(f64::NAN);
        let close = close_col.get(i).unwrap_or(f64::NAN);
        let volume = volume_col.get(i).unwrap_or(0);
        let amount = amount_col.get(i).unwrap_or(f64::NAN);

        rows.push(BarRow {
            time_ms,
            open,
            high,
            low,
            close,
            volume,
            amount,
        });
    }

    // 按 epoch 毫秒升序排列，保证 `partition_point` 二分查找正确
    rows.sort_by_key(|r| r.time_ms);
    Ok(rows)
}

/// 批量加载（DuckDB 集成，需启用 Cargo.toml 中 duckdb 依赖）。
///
/// 连接 stock_data_front.duckdb，一条 SQL 查询全市场日线。
/// 启用步骤：`cargo build --features duckdb`（并在 main.rs 切换到此函数）；需 build.rs 注入 Windows SDK 路径。
#[cfg(feature = "duckdb")]
pub fn load_all_stocks_duckdb(
    data_dir: &str,
    _code_dirs: &[String],
    start_ms: i64,
    end_ms: i64,
) -> Result<HashMap<String, Vec<BarRow>>> {
    use duckdb::Connection;

    let db_path = std::path::Path::new(data_dir).join("stock_data_front.duckdb");
    let config = duckdb::Config::default().access_mode(duckdb::AccessMode::ReadOnly)?;
    let conn = Connection::open_with_flags(db_path, config)?;

    let mut stmt = conn.prepare(
        "SELECT symbol, time, open, high, low, close, volume, amount \
         FROM stock_data WHERE time >= ? AND time <= ? ORDER BY symbol, time",
    )?;
    let rows_iter = stmt.query_map(duckdb::params![start_ms, end_ms], |row| {
        Ok((
            row.get::<_, String>(0)?,
            row.get::<_, i64>(1)?,
            row.get::<_, f64>(2)?,
            row.get::<_, f64>(3)?,
            row.get::<_, f64>(4)?,
            row.get::<_, f64>(5)?,
            row.get::<_, i64>(6)?,
            row.get::<_, f64>(7)?,
        ))
    })?;

    let mut results: HashMap<String, Vec<BarRow>> = HashMap::new();
    for row_result in rows_iter {
        let (sym, t, o, h, l, c, v, a) = row_result?;
        let code = sym.replace('_', ".");
        results.entry(code).or_default().push(BarRow {
            time_ms: t,
            open: o,
            high: h,
            low: l,
            close: c,
            volume: v,
            amount: a,
        });
    }
    Ok(results)
}

/// 批量加载（polars per-file parquet，无 DuckDB 依赖）。
///
/// 每只股票独立打开 parquet 文件，使用 polars lazy scan + 谓词下推 + tail。
/// 串行执行以避免 rayon 栈溢出。
/// hive-split（2026-09-09）后股票日线根优先 `<data_dir>/stock/period=1d`；
/// 仅旧布局存在时短暂回落 `<data_dir>/period=1d`（S2b 过渡，与 Python 侧
/// `resolve_period_root` 同型）。散装 parquet（float_shares 等）仍在容器根。
fn stock_period_1d_root(data_dir: &str) -> std::path::PathBuf {
    let new_root = Path::new(data_dir).join("stock").join("period=1d");
    if new_root.is_dir() || !Path::new(data_dir).join("period=1d").is_dir() {
        new_root
    } else {
        Path::new(data_dir).join("period=1d")
    }
}

pub fn load_all_stocks_parquet(
    data_dir: &str,
    code_dirs: &[String],
    start_ms: i64,
    end_ms: i64,
) -> Result<ParquetLoadResult> {
    let base = stock_period_1d_root(data_dir).join("dividend_type=front");

    let n_stocks = code_dirs.len();
    let mut stats = ParquetLoadStats {
        requested: n_stocks,
        ..ParquetLoadStats::default()
    };
    let mut results = HashMap::with_capacity(n_stocks);

    for (i, code_dir) in code_dirs.iter().enumerate() {
        let path = base.join(code_dir).join("data.parquet");
        if !path.exists() {
            stats.missing_path += 1;
            continue;
        }
        let Some(path_str) = path.to_str() else {
            stats.non_utf8_path += 1;
            continue;
        };
        let df =
            match LazyFrame::scan_parquet(path_str, ScanArgsParquet::default()).and_then(|lf| {
                lf.filter(col("time").gt_eq(lit(start_ms)))
                    .filter(col("time").lt_eq(lit(end_ms)))
                    .select([
                        col("time"),
                        col("open"),
                        col("high"),
                        col("low"),
                        col("close"),
                        col("volume"),
                        col("amount"),
                    ])
                    .collect()
            }) {
                Ok(d) => d,
                Err(_) => {
                    stats.scan_failed += 1;
                    continue;
                }
            };

        let n = df.height();
        if n == 0 {
            stats.empty_after_filter += 1;
            continue;
        }

        let cols = (
            df.column("time").and_then(|s| s.i64()),
            df.column("open").and_then(|s| s.f64()),
            df.column("high").and_then(|s| s.f64()),
            df.column("low").and_then(|s| s.f64()),
            df.column("close").and_then(|s| s.f64()),
            df.column("volume").and_then(|s| s.i64()),
            df.column("amount").and_then(|s| s.f64()),
        );
        let (
            Ok(time_col),
            Ok(open_col),
            Ok(high_col),
            Ok(low_col),
            Ok(close_col),
            Ok(volume_col),
            Ok(amount_col),
        ) = cols
        else {
            stats.decode_failed += 1;
            continue;
        };

        let mut rows = Vec::with_capacity(n);
        for j in 0..n {
            rows.push(BarRow {
                time_ms: time_col.get(j).unwrap_or(0),
                open: open_col.get(j).unwrap_or(f64::NAN),
                high: high_col.get(j).unwrap_or(f64::NAN),
                low: low_col.get(j).unwrap_or(f64::NAN),
                close: close_col.get(j).unwrap_or(f64::NAN),
                volume: volume_col.get(j).unwrap_or(0),
                amount: amount_col.get(j).unwrap_or(f64::NAN),
            });
        }
        rows.sort_by_key(|r| r.time_ms);
        let code = code_dir.strip_prefix("symbol=").unwrap_or(code_dir);
        results.insert(dir_to_stock_code(code), rows);
        stats.loaded += 1;

        if (i + 1) % 500 == 0 {
            eprintln!("  parquet load {}/{} stocks", i + 1, n_stocks);
        }
    }

    Ok(ParquetLoadResult {
        bars_by_code: results,
        stats,
    })
}

/// 加载单只股票的日线数据。
///
/// # 参数
/// - `data_dir`: 数据根目录，如 "stock_data"
/// - `code_dir`: Hive 分区目录名，如 "symbol=000001_SZ"
///
/// # 返回
/// 按时间升序排列的全部历史日线（不做窗口切分，窗口切分在 `algorithm::slice_window` 中完成）
pub fn load_daily_bars(data_dir: &str, code_dir: &str) -> Result<Vec<BarRow>> {
    load_daily_bars_filtered(data_dir, code_dir, i64::MAX, usize::MAX)
}

/// 加载单只股票的日线数据（带 target 过滤 + 尾部裁剪）。
///
/// 该入口用于全市场批处理，可显著减少无效 I/O：
/// - 在 parquet scan 阶段只保留 `time <= target_ms`
/// - 只保留最后 `keep_rows` 行（典型值 `window + 32`）
pub fn load_daily_bars_filtered(
    data_dir: &str,
    code_dir: &str,
    target_ms: i64,
    keep_rows: usize,
) -> Result<Vec<BarRow>> {
    let path = stock_period_1d_root(data_dir)
        .join("dividend_type=front")
        .join(code_dir)
        .join("data.parquet");

    let path_str = path_to_utf8(&path)?;
    let mut lf = LazyFrame::scan_parquet(path_str, ScanArgsParquet::default())?
        .filter(col("time").lt_eq(lit(target_ms)));
    if keep_rows != usize::MAX {
        lf = lf.tail(keep_rows as IdxSize);
    }
    let df = lf
        .select([
            col("time"),
            col("open"),
            col("high"),
            col("low"),
            col("close"),
            col("volume"),
            col("amount"),
        ])
        .collect()
        .with_context(|| format!("failed to read {}", path.display()))?;

    let n = df.height();
    let time_col = df.column("time")?.i64()?;
    let open_col = df.column("open")?.f64()?;
    let high_col = df.column("high")?.f64()?;
    let low_col = df.column("low")?.f64()?;
    let close_col = df.column("close")?.f64()?;
    let volume_col = df.column("volume")?.i64()?;
    let amount_col = df.column("amount")?.f64()?;

    let mut rows = Vec::with_capacity(n);
    for i in 0..n {
        rows.push(BarRow {
            time_ms: time_col.get(i).unwrap_or(0),
            open: open_col.get(i).unwrap_or(f64::NAN),
            high: high_col.get(i).unwrap_or(f64::NAN),
            low: low_col.get(i).unwrap_or(f64::NAN),
            close: close_col.get(i).unwrap_or(f64::NAN),
            volume: volume_col.get(i).unwrap_or(0),
            amount: amount_col.get(i).unwrap_or(f64::NAN),
        });
    }
    rows.sort_by_key(|r| r.time_ms);
    Ok(rows)
}
