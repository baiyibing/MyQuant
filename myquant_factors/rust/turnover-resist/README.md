# Turnover-resist 源码与构建

源码属于 MyQuant 的 `myquant_factors/rust/turnover-resist`。BT 通过公共因子包调用，
不保留或构建第二份 crate。数据读取/Store 接线仍遵循 infra 与消费者各自的合同。

## 构建

使用选定的 Rust 工具链和研究环境，在本 crate 目录中执行：

```text
cd myquant_factors/rust/turnover-resist
cargo build --locked --release --bin turnover-resist
```

`.cargo/config.toml` 沿用可选的 sccache 配置。没有 sccache 时，在当前 shell 中
将 `RUSTC_WRAPPER` 设为空再构建；CI 已显式这样配置，不要求安装全局 wrapper。

## 产物定位

| 配置 | 行为 |
| --- | --- |
| `TURNOVER_RESIST_EXE` | 显式指定可执行文件；文件不存在或指向目录时立即报错，不改用其他二进制 |
| `CARGO_TARGET_DIR` | 未指定 EXE 时，在此显式构建根的 `release`、`release-fast` 查找 |
| 未配置上述变量 | 使用本 crate 的 `target/release` 或 `target/release-fast` |

同时支持 `turnover-resist.exe` 和 `turnover-resist`。目标目录由当前构建配置决定，
没有固定盘符，也不探测机器上的旧缓存目录。设置 `CARGO_TARGET_DIR` 后，Cargo
会把产物写到该目录，而不是 crate 的默认 `target`。

研究运行须显式传 `--data-dir <configured-parquet-root>` 和 `--output <research-output>`；
通过 Python 桥调用时，由配置的共享路径 API 解析数据根。编译、查找产物或查看帮助
不代表获准运行真实行情计算、写入生产数据或注册任务。

## 验证与溯源

接收侧 CI 保留 `cargo fmt --check`、全 targets/features 的 Clippy（拒绝警告）、
Rust 单测和独立 `cargo check --locked --all-targets`。消费者可记录构建源码提交、
实际可执行文件路径和哈希；包版本不能单独证明一个外部二进制由哪份源码构建。
本轮没有替换用户已部署的二进制或启用真实数据任务。
