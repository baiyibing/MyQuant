# QL11：分钟刷新对日频 provider 的写入隔离

旧入口只拒绝分钟 provider 与日频 provider 完全相同。真实沙盒复现表明：staging 指向日频目录会写入分钟 parquet，日频日历指纹不变；receipt 指向日频 day.txt 时，会在指纹检查通过后覆盖日历并返回成功。baseline.json 保留了两条真实 writer 的返回值和前后文件哈希。

现在启动时检查 minute provider、staging、派生 full_staging 和可选 receipt。展开用户目录、非严格解析路径别名并按平台大小写规则比较组件，拒绝与日频目录等同、包含它或位于其中的目标。receipt 在实际写入前再次检查。普通兄弟目录、首次不存在的输出目录、原有日历检查及回执格式保留。

plan.json 在实现前提交；最终 head 的 Grok CLI 实现复核和规范 CI 见关联 PR。新旧负向矩阵、相关测试和真实成功 append 控制见 acceptance.json。规范 CI 自动收集本文件所在 my_tests。

本片与日频路径修复 PR #117 修改不同文件；在该 PR 合入后已合并最新 master，再验证组合。没有运行实际部署刷新、推广 provider、写行情湖或启动交易。不关闭 QL11 部署验收/P12，也不宣称解决一般多写者或恶意符号链接竞争。
