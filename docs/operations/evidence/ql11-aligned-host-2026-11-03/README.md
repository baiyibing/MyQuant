# QL11 完整日历对齐与本机真实数据验收

修复分钟provider追加时的实际错位：个股旧尾或新前缺分钟时，直接append会把后来的价格
读成更早分钟。基线反例将09:33的11元写成09:31；见[原始反例](baseline-counterexample.json)。
修复固定源码 `a997760a6baaa893d5f5081a6e08910371754ef9`。

追加现在使用完整provider日历，全轴下标补NaN并保持旧字节前缀。日历、旧bin、
新证券full-stage不合法则失败；新字段也使用完整日历header。增量日历使用和rebuild相同的
有限锚点并集；新证券补全使用已解析湖根，证券元数据使用实际观测终点。
单文件temp+replace，features成功后才写metadata。整个provider不承诺跨文件事务：
IO中断必须按非零失败处理，半成品不得消费，需备份恢复或rebuild。

本机冻结窗口 `2026-10-23..2026-11-02`，旧段到10/29，源行情只读。
7个股票/指数：SZ000001、SH600000、SZ300750、SH688981、BJ920002、SH000001、SH000300；
SH000300在增量时作为新证券加入。真实原编排器CLI执行初建、增量、独立重建、重复窗口noop。

- 日历1205→1687，新增482根，末尾2026-11-02 15:00。
- 42个旧bin字节前缀保持不变；49个字段bin与独立rebuild逐字节相等。
- 7字段逐一对照原始湖的float32值，包括原有volume手数、amount及原有VWAP公式；未改变单位合同。
- instruments边界与rebuild一致；重复窗口返回真实noop回执，包含备份在内的provider文件字节不变。
- 所测源文件hash前后一致；所列默认日频/分钟日历与工作树pred锚点在运行前均不存在，运行后仍不存在。
  这不是现有线上provider的全树保护实证，未作默认provider切换。

[配方](recipe.json)、[结果](acceptance.json)、四份*-receipt.json保留实际测量。
原始路径被替换为$TASK/$REPO/$LAKE/$USER_HOME；原始JSON和Git发布LF字节的hash分别登记。
完整日志、staging与provider留本机忽略目录。audit-sources为执行过的原审计脚本，要求恢复
$TASK/myquant原目录布局及冻结SHA，不是产品CLI，输出必须选新目录。

首轮host审计因Windows路径分隔符使feature选择为空而失败，未执行价格前缀判断；
保留首版脚本及[修订说明](host-followup.json)，修订后原样重跑真实数据，生产代码未因此变化。
基线新增14项回归失败；修复后相关60测试和Ruff通过。新增测试在现有CI的my_tests选择中。
方案已获[CLI复核APPROVE](plan-review.json)；当前Claude CLI实际配置GLM-5.3，非Anthropic模型。

P12仍开放：本片是7证券固定窗隔离验收，不是全市场、日频独立刷新或线上部署。
默认参数的empty-staging/noop报错仍是已知尾项；本片noop显式重放原窗口，不声称该尾项已修。
旧QL11回执的preserved布尔量只按probe长度判断；本片另外提供完整旧bin前缀与全字段重建比较。
