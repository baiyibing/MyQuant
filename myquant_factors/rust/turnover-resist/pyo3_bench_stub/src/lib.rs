use pyo3::prelude::*;
use serde::Serialize;

#[pyfunction]
fn nop() -> PyResult<()> {
    Ok(())
}

#[derive(Serialize)]
struct DummyRow {
    stock_code: String,
    stock_name: String,
    date: String,
    close: f64,
    cyqk_t: f64,
    cyqk_t_1: f64,
    profit_chip_diff: f64,
    turnover: f64,
    turnover_resistance: f64,
    turnover_free: f64,
    turnover_resistance_free: f64,
    circulating_capital: f64,
    free_float_capital: f64,
    bb_upper: f64,
    bb_middle: f64,
    bb_lower: f64,
    bb_position: f64,
    bb_width: f64,
}

#[pyfunction]
fn echo_json(n: usize) -> PyResult<String> {
    let rows: Vec<DummyRow> = (0..n)
        .map(|i| DummyRow {
            stock_code: format!("{:06}.SZ", i % 1000000),
            stock_name: format!("Name{}", i),
            date: "20260525".to_string(),
            close: 10.0,
            cyqk_t: 0.5,
            cyqk_t_1: 0.4,
            profit_chip_diff: 0.01,
            turnover: 0.001,
            turnover_resistance: 1.0,
            turnover_free: 0.001,
            turnover_resistance_free: 1.0,
            circulating_capital: 1_000_000_000.0,
            free_float_capital: 500_000_000.0,
            bb_upper: 11.0,
            bb_middle: 10.0,
            bb_lower: 9.0,
            bb_position: 0.5,
            bb_width: 0.2,
        })
        .collect();
    let json = serde_json::to_string(&rows).unwrap();
    Ok(json)
}

#[pymodule]
fn pyo3_bench_stub(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(nop, m)?)?;
    m.add_function(wrap_pyfunction!(echo_json, m)?)?;
    Ok(())
}
