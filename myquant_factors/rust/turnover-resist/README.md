# turnover-resist 构建配置指南

> **重要**：本项目的 Rust 构建产物不在 `target/` 目录，而是在 `F:\rust-targets\`。
>
> 2026-10-19 迁盘：`rust-targets` / `rust-sccache-cache` / `rust-ci-target` 三棵树由 E: 整体 `/MOVE` 到 F:，用户级 env 已改 F。旧 E: 路径已作废。

## 环境变量（用户级，对所有 Rust 项目生效）

| 变量 | 值 | 作用 |
|------|-----|------|
| `CARGO_TARGET_DIR` | `F:\rust-targets` | 构建产物输出到 F 盘，避免 C 盘空间不足 |
| `RUSTC_WRAPPER` | `sccache` | 编译缓存，加速增量编译 |
| `SCCACHE_DIR` | `F:\rust-sccache-cache` | sccache 缓存目录，也在 F 盘 |

## 二进制位置

| 二进制 | 正确路径 | ~~错误路径~~ |
|--------|---------|-------------|
| turnover-resist | `F:\rust-targets\release\turnover-resist.exe` | ~~`turnover-resist\target\release\turnover-resist.exe`~~ |
| debug-precision | `F:\rust-targets\release\debug-precision.exe` | ~~`turnover-resist\target\release\debug-precision.exe`~~ |

**`turnover-resist/target/` 目录可能残留旧二进制，不要使用。**

## 常用命令

```bash
# 编译（从 turnover-resist/ 目录）
cargo build --release --bin turnover-resist

# 运行（从仓库根目录）
F:\rust-targets\release\turnover-resist.exe --date 20260525 --output backtest_output/result.csv

# sccache 状态
sccache --show-stats

# 清除 sccache 缓存（不影响构建产物）
sccache --zero-stats

# 全量重编（清除构建产物 + sccache 缓存）
cargo clean
# 注意：cargo clean 清除的是 CARGO_TARGET_DIR 下的产物
```

## .cargo/config.toml 关键配置

```toml
[build]
rustc-wrapper = "sccache"    # 编译缓存（与 RUSTC_WRAPPER 环境变量双重配置）
```

项目级 `.cargo/config.toml` 也配了 `rustc-wrapper = "sccache"`，与环境变量 `RUSTC_WRAPPER=sccache` 是 belt-and-suspenders（双重保障）。

## 常见坑

### 1. 二进制路径搞错

**症状**：`cargo build` 报 "Finished" 但 `turnover-resist/target/release/` 下的二进制时间戳没更新。

**原因**：`CARGO_TARGET_DIR=F:\rust-targets`，二进制实际输出到 `F:\rust-targets\release\`。

**解决**：始终使用 `F:\rust-targets\release\` 下的二进制。

### 2. sccache 报错但编译成功

**症状**：`sccache: error: failed to execute compile` 但 cargo 最终报 "Finished"。

**原因**：sccache 缓存失效或路径问题，但 rustc 直接编译仍然成功。

**解决**：以 cargo 最终输出为准，sccache 报错不影响编译结果。如需禁用 sccache：
```bash
CARGO_BUILD_RUSTC_WRAPPER= cargo build --release
```

### 3. cargo clean 后全量重编很慢

**原因**：`cargo clean` 清除 `F:\rust-targets` 下所有缓存，全量重编 polars 等依赖约需 15-20 分钟。

**加速**：
- 只清除当前项目：`cargo clean`（不影响其他项目）
- 使用 `release-fast` profile（无 LTO，编译快 5x）：`cargo build --profile release-fast`
- 日常开发用 `release-fast`，最终发布用 `release`

### 4. Cargo.toml 中的 profile 说明

| Profile | LTO | 用途 | 编译时间 |
|---------|-----|------|---------|
| `dev` | 无 | 调试/测试 | 快（~30s） |
| `release` | thin | 正式发布 | 慢（~10min） |
| `release-fast` | 无 | 日常开发迭代 | 中（~2min） |
