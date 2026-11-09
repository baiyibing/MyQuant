/// DuckDB bundled 在 Windows 下需要 Rstrtmgr.lib（Windows SDK），
/// 但该库不在 MSVC 默认搜索路径中。通过 build.rs 显式注入链接参数。
fn main() {
    // 仅在启用 duckdb feature 时注入链接参数，避免默认路径硬依赖。
    if std::env::var("CARGO_FEATURE_DUCKDB").is_err() {
        return;
    }
    let sdk_lib = r"C:\Program Files (x86)\Windows Kits\10\Lib\10.0.26100.0\um\x64";
    println!("cargo:rustc-link-search=native={}", sdk_lib);
    println!("cargo:rustc-link-lib=Rstrtmgr");
}
