//! turnover-resist library entry.
pub mod algorithm;
pub mod bollinger;
pub mod cli;
pub mod data;
pub mod engine;
pub mod profile;
pub mod types;

// ---- PyO3 绑定（选型 benchmark 用最小原型） ----
use pyo3::prelude::*;

/// Python 入口：接收标量参数 → 调用 Rust 核心计算 → 返回 JSON 字符串。
///
/// 返回 JSON 数组，每个元素是一个 OutputRow 的对象表示。
/// 字段名与 CSV 输出一致（含 serde(rename) 映射）。
#[allow(clippy::too_many_arguments)] // Python 入参偏多；pyo3 绑定天然多参
#[pyfunction]
#[pyo3(signature = (
    date,
    window,
    step,
    data_dir,
    sort_by,
    free_float_policy,
    target_date_policy,
    bb_ddof,
    max_grid_points,
    include_profile=false,
    profile_json=None,
))]
fn compute_turnover_resist(
    date: &str,
    window: usize,
    step: f64,
    data_dir: &str,
    sort_by: &str,
    free_float_policy: &str,
    target_date_policy: &str,
    bb_ddof: usize,
    max_grid_points: usize,
    include_profile: bool,
    profile_json: Option<&str>,
) -> PyResult<String> {
    let date = chrono::NaiveDate::parse_from_str(date, "%Y%m%d").map_err(|e| {
        pyo3::exceptions::PyValueError::new_err(format!("invalid date '{}': {}", date, e))
    })?;

    let sort_by = match sort_by {
        "circulating" => cli::SortBy::Circulating,
        "free" => cli::SortBy::Free,
        _ => {
            return Err(pyo3::exceptions::PyValueError::new_err(format!(
                "sort_by must be 'circulating' or 'free', got '{}'",
                sort_by
            )))
        }
    };

    let free_float_policy = match free_float_policy {
        "warn-zero" => cli::FreeFloatPolicy::WarnZero,
        "skip" => cli::FreeFloatPolicy::Skip,
        "fail" => cli::FreeFloatPolicy::Fail,
        _ => {
            return Err(pyo3::exceptions::PyValueError::new_err(format!(
                "free_float_policy must be 'warn-zero', 'skip' or 'fail', got '{}'",
                free_float_policy
            )))
        }
    };

    let target_date_policy = match target_date_policy {
        "strict" => cli::TargetDatePolicy::Strict,
        "allow-previous" => cli::TargetDatePolicy::AllowPrevious,
        _ => {
            return Err(pyo3::exceptions::PyValueError::new_err(format!(
                "target_date_policy must be 'strict' or 'allow-previous', got '{}'",
                target_date_policy
            )))
        }
    };

    let cli = cli::Cli {
        date,
        target_date_policy,
        window,
        step,
        max_grid_points,
        bb_ddof,
        sort_by,
        free_float_policy,
        output: None,
        data_dir: std::path::PathBuf::from(data_dir),
        profile: false,
        no_profile: true,
        profile_json: profile_json.map(std::path::PathBuf::from),
    };

    let outcome = engine::run_detailed(&cli)
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("compute failed: {}", e)))?;

    // Side-channel JSON file never changes the historical array return shape.
    if let Some(path) = profile_json {
        let _ = profile::write_profile_json(std::path::Path::new(path), &outcome.profile);
    }

    if include_profile {
        profile::print_profile(&outcome.profile);
        let wrapped = serde_json::json!({
            "rows": outcome.rows,
            "profile": outcome.profile,
        });
        return serde_json::to_string(&wrapped).map_err(|e| {
            pyo3::exceptions::PyRuntimeError::new_err(format!("serialize failed: {}", e))
        });
    }

    let json = serde_json::to_string(&outcome.rows).map_err(|e| {
        pyo3::exceptions::PyRuntimeError::new_err(format!("serialize failed: {}", e))
    })?;

    Ok(json)
}

/// 滚动窗口盈筹率序列：窗内每一日用该日流通股本算换手。
///
/// 数组等长；`out[i]` 对应截至第 i 根（含）的 `window` 日窗口。
/// `start_i` 之前（以及不满一整窗）为 NaN。
#[pyfunction]
#[pyo3(signature = (close, high, low, volume, shares, window, start_i=0, step=0.01))]
#[allow(clippy::too_many_arguments)] // 9 个 Python 入参，pyo3 绑定天然多参；重构 struct 会动 Python 侧签名
fn compute_cyqk_series(
    py: Python<'_>,
    close: Vec<f64>,
    high: Vec<f64>,
    low: Vec<f64>,
    volume: Vec<f64>,
    shares: Vec<f64>,
    window: usize,
    start_i: usize,
    step: f64,
) -> PyResult<Vec<f64>> {
    let n = close.len();
    if high.len() != n || low.len() != n || volume.len() != n || shares.len() != n {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "close/high/low/volume/shares must have the same length",
        ));
    }
    Ok(py.allow_threads(|| {
        algorithm::compute_cyqk_series(&close, &high, &low, &volume, &shares, window, start_i, step)
    }))
}

/// Python 模块名 turnover_resist（与 Cargo [lib] name 一致）。
#[pymodule]
fn turnover_resist(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(compute_turnover_resist, m)?)?;
    m.add_function(wrap_pyfunction!(compute_cyqk_series, m)?)?;
    Ok(())
}
