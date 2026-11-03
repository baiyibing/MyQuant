# QL10：日频刷新路径隔离

旧刷新入口允许 `--new-qlib-dir` 与现有 `--qlib-dir` 指向同一目录。再加 `--wipe-new-qlib-dir` 后，清理步骤会先删掉现有 provider；baseline.json 记录的是一次性沙盒复现。

现在 staging/new 输出与 live provider、archive、CSV、指数输入以及显式 SOURCE 容器必须相互隔离。使用非严格解析后的绝对路径及平台大小写规则，按路径组件检查等同和两个方向的包含关系，支持首次不存在的输出目录。`my_data`、`my_data_new_DATE` 等同前缀兄弟目录仍合法。

CLI 在任何子命令之前拒绝重叠；清理 helper 在建议 wipe 之前检查，并在删除前再次检查；直接 swap 在任何 rename 之前检查它接收的两个根。SOURCE 在构造配置时捕获，校验 helper 不读取后来改变的环境。直接构造 RefreshConfig 的调用方可以显式传入 source_parquet_root。

计划及其复核见 plan.json、plan-review.json；最终实现复核和规范 CI 见关联 PR。基线与修后结果见 acceptance.json。新测试在 CI 的既有 my_tests 全量收集范围内。

本片只修路径配置错误的拒绝语义。没有运行实际 provider 刷新、推广、行情下载或湖写入；不关闭 QL10 部署验收或 P12 整包，也不重做已关闭的 QL12/QL13。不处理恶意并发替换符号链接或多写者协调。
