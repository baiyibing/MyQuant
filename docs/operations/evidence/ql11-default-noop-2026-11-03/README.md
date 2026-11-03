# QL11 默认空增量 noop 修复及宿主验收

旧代码把自动start设为provider末尾+1秒，已追平湖数据时合法staging为空却报错。
本片冻结实现 `720e42fefaac28d18ea31fecceff35795ebd9c7a`，修复这个已知尾项。

自动增量先核根目录、文件、显式名单，缺源在清理旧scratch前失败。空/重复别名名单明确拒绝。
staging在原有扫描内可选回传少量统计，正常API仍返回路径列表、原始输出帧不变，不重读全湖。
空结果只有来源有可用历史、窗口内原始行确为0、无坏时间且已有close bin结构有效时才noop。
新坏close被过滤、全坏/空源、provider缺证券或bin异常均拒绝；缺口不会被当作追平。

新的默认空结果回执保留全部原必填字段，附加 `empty_increment_proof`；该证明只对应
配置请求，不代表全市场新鲜度、完整provider字段质量或上游供应商完整性。
显式start/rebuild/skip-stage的空结果仍失败；既有“非空staging但无新日历”noop路径未改。
历史坏时间同样会阻止本次自动noop。解析/IO/provider失败不保证scratch回滚，不能据此消费半成品。

## 真实湖与隔离副本

从#115验收provider复制两个新目录，使用7个股票/指数；两个原CLI均不传start/end。
旧生产源码与基线bce9613b的Git blob按LF核对一致，新源码干净冻结。

- 旧代码非零，日志为no 1m parquet staged，无成功回执。
- 新代码返回noop0，provider内53个文件（含备份）的内容hash与运行前一致。
- 实际扫描7分区、921101行可用历史；窗口内原始行0，坏时间0，核对7个close bin。
- 5个宿主拒绝格：缺根、未知证券、空源、坏close源、坏bin；全部非零且无回执，输入provider字节未变。
- 其中缺根/未知名单/空根在清理scratch前拒绝，已有scratch哨兵保留。
- 所读源文件及#115原始provider前后hash一致。坏close/bad-bin是明确标注的私有故障副本，未改行情湖。
- 所列默认日频/分钟日历和工作树pred锚点前后均不存在；未作默认provider提升，不冒称保护了实际线上全树。

[配方](recipe.json) · [验收](acceptance.json) · [实际noop回执](fixed-receipt.json)。
源码/宿主日志/完整provider留本机忽略目录；发布JSON路径已抽象，原始JSON字节hash与发布Git LF hash分开。
`audit-sources/run_host.py`是原审计脚本，依赖$TASK/myquant和上轮审计布局，复现必须选新输出目录，
不是产品CLI。原始坏输入仅在私有副本，不写下载源。

## 验证与复核

初始19项CLI矩阵在基线上7失败/12通过。扩展后相关88测试、Ruff通过，包含20类拒绝，
默认成功/无receipt选项、正常新增和并行audit帧/路径等价。新my_tests由现有主CI自动选择，
staging新增3项由已有data-staging选择；无需扩大CI豁免。

[方案复核](plan-review.json)和[固定实现复核](implementation-review.json)均APPROVE。
CLI实际是Claude Code2.1.317配置GLM-5.3，非Anthropic模型；工具禁用，依据固定bundle，未冒称复核运行了宿主。
复核文字中的范围/计数泛化在operator_clarifications中澄清。首轮方案请求触及输出上限未有结论，原计划重试获批。

P12仍开放：这关闭默认空增量误报片，不代签全市场provider部署、独立日频刷新、真实既有日频全树保护或模型验收。
