//! Wall-clock phase timings for the Rust turnover-resist host path.
//!
//! Mirrors the Python `csv_sim_profile.SimPhaseClock` shape enough that hosts can
//! compare `profile_rust.json` with `profile_export.json` / `profile_sim.json`.
//! Instrumentation must not change numeric outputs.

use std::collections::BTreeMap;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::time::Instant;

use chrono::{DateTime, Local};
use serde::Serialize;

/// Parent timers that wrap children; excluded from phase_share.
const WRAPPER_PHASES: &[&str] = &["total"];

#[derive(Debug, Clone, Serialize)]
pub struct ProfileReport {
    pub started_at: String,
    pub finished_at: String,
    pub wall_s: f64,
    pub phases_s: BTreeMap<String, f64>,
    pub phase_share: BTreeMap<String, f64>,
    pub counts: BTreeMap<String, u64>,
    pub job: String,
    pub date: String,
    pub window: usize,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub output: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub data_dir: Option<String>,
}

#[derive(Debug)]
pub struct PhaseClock {
    started_at: DateTime<Local>,
    started: Instant,
    seconds: BTreeMap<String, f64>,
    counts: BTreeMap<String, u64>,
    open: BTreeMap<String, Instant>,
}

impl PhaseClock {
    pub fn new() -> Self {
        Self {
            started_at: Local::now(),
            started: Instant::now(),
            seconds: BTreeMap::new(),
            counts: BTreeMap::new(),
            open: BTreeMap::new(),
        }
    }

    pub fn begin(&mut self, name: &str) {
        self.open.insert(name.to_string(), Instant::now());
    }

    pub fn end(&mut self, name: &str) {
        if let Some(started) = self.open.remove(name) {
            let add = started.elapsed().as_secs_f64();
            *self.seconds.entry(name.to_string()).or_insert(0.0) += add;
        }
    }

    pub fn count(&mut self, name: &str, n: u64) {
        *self.counts.entry(name.to_string()).or_insert(0) += n;
    }

    pub fn set_count(&mut self, name: &str, n: u64) {
        self.counts.insert(name.to_string(), n);
    }

    /// Run `f` under a named phase.
    pub fn time<T>(&mut self, name: &str, f: impl FnOnce() -> T) -> T {
        self.begin(name);
        let out = f();
        self.end(name);
        out
    }

    /// Fallible variant.
    pub fn time_result<T, E>(
        &mut self,
        name: &str,
        f: impl FnOnce() -> Result<T, E>,
    ) -> Result<T, E> {
        self.begin(name);
        let out = f();
        self.end(name);
        out
    }

    pub fn report(
        &self,
        job: &str,
        date: &str,
        window: usize,
        output: Option<&Path>,
        data_dir: Option<&Path>,
    ) -> ProfileReport {
        let finished = Local::now();
        let wall_s = self.started.elapsed().as_secs_f64();
        let phases_s: BTreeMap<String, f64> = self
            .seconds
            .iter()
            .map(|(k, v)| (k.clone(), round6(*v)))
            .collect();
        let leaf_total: f64 = phases_s
            .iter()
            .filter(|(k, _)| !WRAPPER_PHASES.contains(&k.as_str()))
            .map(|(_, v)| *v)
            .sum();
        let phase_share = phases_s
            .iter()
            .filter(|(k, _)| !WRAPPER_PHASES.contains(&k.as_str()))
            .map(|(k, v)| {
                let share = if leaf_total > 0.0 {
                    round4(*v / leaf_total)
                } else {
                    0.0
                };
                (k.clone(), share)
            })
            .collect();
        ProfileReport {
            started_at: self
                .started_at
                .to_rfc3339_opts(chrono::SecondsFormat::Secs, true),
            finished_at: finished.to_rfc3339_opts(chrono::SecondsFormat::Secs, true),
            wall_s: round3(wall_s),
            phases_s,
            phase_share,
            counts: self.counts.clone(),
            job: job.to_string(),
            date: date.to_string(),
            window,
            output: output.map(|p| p.display().to_string()),
            data_dir: data_dir.map(|p| p.display().to_string()),
        }
    }
}

impl Default for PhaseClock {
    fn default() -> Self {
        Self::new()
    }
}

fn round3(v: f64) -> f64 {
    (v * 1000.0).round() / 1000.0
}

fn round4(v: f64) -> f64 {
    (v * 10000.0).round() / 10000.0
}

fn round6(v: f64) -> f64 {
    (v * 1_000_000.0).round() / 1_000_000.0
}

/// Host default is on. `OSKH_PROFILE_SIM=0/false/off` disables. Explicit CLI wins.
pub fn profile_enabled(explicit: Option<bool>) -> bool {
    if let Some(v) = explicit {
        return v;
    }
    match std::env::var("OSKH_PROFILE_SIM") {
        Ok(raw) => {
            let s = raw.trim().to_ascii_lowercase();
            !matches!(s.as_str(), "0" | "false" | "no" | "off")
        }
        Err(_) => true,
    }
}

pub fn phase_label(key: &str) -> &str {
    match key {
        "load_float" => "流通股本",
        "load_free_float" => "自由流通",
        "load_free_float_prev" => "自由流通T-1",
        "load_bars" => "批量日线",
        "rayon_init" => "线程池",
        "compute" => "并行计算",
        "collect" => "汇总跳过",
        "sort" => "排序",
        "write_csv" => "写CSV",
        "serialize_json" => "序列化JSON",
        "total" => "合计",
        other => other,
    }
}

pub fn format_profile_lines(report: &ProfileReport) -> Vec<String> {
    let mut lines = vec![
        format!("  开始: {}", report.started_at),
        format!("  结束: {}", report.finished_at),
        format!("  墙钟: {:.1}s", report.wall_s),
    ];
    if !report.phases_s.is_empty() {
        let mut bits = Vec::new();
        for (key, val) in &report.phases_s {
            let label = phase_label(key);
            if WRAPPER_PHASES.contains(&key.as_str()) {
                bits.push(format!("{label} {val:.1}s"));
                continue;
            }
            let pct = report.phase_share.get(key).copied().unwrap_or(0.0) * 100.0;
            bits.push(format!("{label} {val:.1}s ({pct:.0}%)"));
        }
        lines.push(format!("  分相: {}", bits.join(" | ")));
    }
    if !report.counts.is_empty() {
        let bits: Vec<String> = report
            .counts
            .iter()
            .map(|(k, v)| format!("{k}={v}"))
            .collect();
        lines.push(format!("  埋点计数: {}", bits.join(" | ")));
    }
    lines
}

pub fn print_profile(report: &ProfileReport) {
    eprintln!("[profile_rust]");
    for line in format_profile_lines(report) {
        eprintln!("{line}");
    }
}

impl ProfileReport {
    pub fn insert_phase(&mut self, name: &str, secs: f64) {
        self.phases_s.insert(name.to_string(), round6(secs));
        self.recompute_phase_share();
    }

    pub fn recompute_phase_share(&mut self) {
        let leaf_total: f64 = self
            .phases_s
            .iter()
            .filter(|(k, _)| !WRAPPER_PHASES.contains(&k.as_str()))
            .map(|(_, v)| *v)
            .sum();
        self.phase_share = self
            .phases_s
            .iter()
            .filter(|(k, _)| !WRAPPER_PHASES.contains(&k.as_str()))
            .map(|(k, v)| {
                let share = if leaf_total > 0.0 {
                    round4(*v / leaf_total)
                } else {
                    0.0
                };
                (k.clone(), share)
            })
            .collect();
    }

    pub fn stamp_output(&mut self, output: &Path, data_dir: Option<&Path>) {
        self.output = Some(output.display().to_string());
        if let Some(d) = data_dir {
            self.data_dir = Some(d.display().to_string());
        }
    }

    pub fn set_wall_s(&mut self, wall_s: f64) {
        self.wall_s = round3(wall_s);
        self.finished_at = Local::now().to_rfc3339_opts(chrono::SecondsFormat::Secs, true);
    }
}

pub fn write_profile_json(path: &Path, report: &ProfileReport) -> std::io::Result<PathBuf> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    let text = serde_json::to_string_pretty(report).map_err(std::io::Error::other)?;
    let mut file = fs::File::create(path)?;
    file.write_all(text.as_bytes())?;
    file.write_all(b"\n")?;
    Ok(path.to_path_buf())
}

/// Default profile path beside the CSV: `canonical_resist_rust_YYYYMMDD.profile.json`.
pub fn default_profile_path(csv_output: &Path) -> PathBuf {
    let stem = csv_output
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("turnover_resist");
    let parent = csv_output.parent().unwrap_or_else(|| Path::new("."));
    parent.join(format!("{stem}.profile.json"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::thread;
    use std::time::Duration;

    #[test]
    fn phase_clock_accumulates_and_shares() {
        let mut clock = PhaseClock::new();
        clock.time("load_bars", || thread::sleep(Duration::from_millis(5)));
        clock.time("compute", || thread::sleep(Duration::from_millis(10)));
        clock.count("rows", 3);
        let report = clock.report("turnover-resist", "20260603", 1000, None, None);
        assert!(report.phases_s.contains_key("load_bars"));
        assert!(report.phases_s.contains_key("compute"));
        assert_eq!(report.counts.get("rows"), Some(&3));
        let share_sum: f64 = report.phase_share.values().sum();
        assert!((share_sum - 1.0).abs() < 0.02, "share_sum={share_sum}");
        let text = serde_json::to_string(&report).unwrap();
        assert!(text.contains("load_bars"));
        assert!(!text.contains('\0'));
    }

    #[test]
    fn profile_enabled_env() {
        assert!(profile_enabled(Some(true)));
        assert!(!profile_enabled(Some(false)));
    }
}
