# Joint return v1 验收账本

本次范围：R0 + MQ R1 data-free；BT R1 下一刀。真实输入 `INPUT_BLOCKED`，真实运行 `NOT_RUN`，收益结论待实测；MQ 合成绿不等于联合 `IMPLEMENTATION_PASS`。

基线与白名单见 [contract](contract.md)，逐项缺口见 [input-register](input-register.md)。本次无生产/特征/pred/线上 10/3 配置改动；程序未上线，仅有回测。研究默认 50/5，20/3、10/3 可切换，不调用旧回测/PortAna/湖，不写 BT，不做 R2+、residual 叠回或 4090 实测。

## 七条主轴映射

| 主轴 | 本刀动作 / 后续切片 | 验收证据与边界 |
|---|---|---|
| 停新特征刀 | R0 冻结 F-R2；R1 只读已有 score/anti | import fence、修订合同白名单；无训练或新 sidecar |
| 信息有、组合没 | R0 分开 P-REF 标签诊断与净收益 | pref_check 写明非 PnL，真实收益待实测 |
| 组合优先 | R1 P-BASE/P-CHASE 独立递推；R2/R3 后续 | 旧仓/拒绝调出/状态 hash/所选 topk 上限/规则冻结数量 pins |
| 成本成交 | R0 固定 M-REF/M-LAG 与生命周期；BT R1 下一刀，R4 后续 | 本刀仅 MQ 参考费用与交接 hash，不宣称实际撮合接线通过 |
| 弱信息只作过滤 | R1 严格低于中位数跳过、按 score 回填/显式放宽 | ties、等号、回填不足、资格不可放宽；不改 score |
| 不扫 seed/窗/方向、不动线上、不用 PortAna 真钱化 | R0 有限参数/原窗/原 recorder；研究 50/5 默认、20/3/10/3 可切换；R1 无回测 import | 固定 bootstrap 与容差、输入漂移拒绝、规则输入缺列阻塞；不索取 live 原包 |
| 冻结一周、关注换手/回撤/净超额 | R0 定义指标；R1 目标换手；R5/R6 后续 | 实际 NAV/回撤/净超额无伪造值，4090 等完整宿主清单 |

## R0 检查

- §3 全部对象的字段、单位、时点、来源、排序、hash、缺失停止与数量转换有定义。
- contract 的两仓完整实施基线、实际 code_shas 字段、有限参数、两仓白名单与当前范围一致。
- P-REF 复核范围、标签/共同宇宙、严格中位数、bootstrap、RankIC/月季度表、容差、历史 OOS 已观察事实明确；外部候选模型结果不重新计算。
- 资格/研究初始状态/价格/时点/分钟/PIT 缺口全部 INPUT_BLOCKED；不存在的原始 10/3 live 包不是 blocker；合成不能填绿。
- 生命周期状态与阻挡原因区分，“门未拦截”不代表成交；BT 需独立证明现金/T+1/费用接线。
- δ1/δ2 不重做，E-R5/NP2 与完整现金分红/PIT 限制仍在。

## MQ R1 data-free pins

初版历史测试目标 `tests/test_joint_return_portfolio.py`，合成 fixture 在进程/pytest 临时目录生成；不读取真实研究快照。

| 门禁 | 验收内容 |
|---|---|
| P-REF 手算 | 五日×十五只合成数据；T0 A…J、T1 C…L，Top10Spread T0=-.025/T1=-.005/Δ=.02，仅标签诊断；CI 恒定例手算 |
| 排序与阈值 | 全 score 并列仍 instrument 升序；中位数等号保留；不足先合格、后按 score 放宽 |
| 组合映射 | 原始 A/B 换入映射 C/D，原获准卖 P/Q，R 未获准留下；其他旧仓延续；不每日换成 T1 |
| 独立递推 | BASE/CHASE 第二日各自 hash 校验；用 BASE 重置 CHASE 必须 PAIR_INVALID |
| 全输入链 | 规则计划缺失、缺臂日、重复键、NaN、缺标签、候选分数、资格/原价/股数漂移、未来 score/anti、时区/生效/失效错误均拒绝 |
| 资金 / 数量 | 新买整手，卖出不超参考 lot；显式转换审计；目标换手含现金；含费现金不足拒绝；一次 per_order 参考费，不代表 BT fill 费接线 |
| 单位 / 公司行动 | 未证明 share 单位与公司行动非空均阻塞，不能靠默认缩放标绿 |
| 导出 | 四个固定文件、固定列、JSON 标量 CSV 无损往返、全表/分臂/原字节/content hash、不可覆盖 run_id、合成与 NOT_RUN 状态 |
| 隔离 | 新模块无 qlib/host_env/backtrader/mlflow/data_root/analysis_export import；真实快照缺失 CLI 退出 2、INPUT_BLOCKED，不写成功包 |

受控解释器 `/workspace/vanna312/bin/python`（Python 3.12.13）；默认 shell 没有 `python`，通过临时 PATH 选择该已存在环境，不修改环境/依赖。执行命令：

```bash
PATH=/workspace/vanna312/bin:$PATH python -m pytest tests/test_joint_return_portfolio.py -q
```

2026-09-19 实际结果：`52 passed in 0.75s`，exit code 0，无 skip。命令只收集此 data-free 文件，未跑全仓需要数据的测试。`python -m my_scripts.joint_return_portfolio --help` 已核对，UTF-8 / 无 BOM / NUL=0 六文件及相对链接检查通过；新模块 import fence 通过。合成产物全部在 pytest 临时目录，无真实输入或收益产物。

## BT / 联合 / 真实验收仍待交付

| 范围 | 状态 / 必需验收 |
|---|---|
| BT R1 消费 | NOT_RUN：相同 contract/intent hash，CSV 标量解码，目标数量不重算，状态及原始计划可追溯 |
| 时钟 / session | NOT_RUN：available_at 后首个合法 open、同根 close 不倒填 open、午休/收盘/开盘端点、缺分钟顺延 |
| 实际资金与持仓 | NOT_RUN：买入日禁卖、涨跌停/停牌/无 bar、实际现金不足/超卖、部分成交/剩余量、费用只扣一次 |
| 期末 / 公司行动 | NOT_RUN：mark 非 SELL、陈旧估值、整手/零股、未完成订单单位转换、PIT/价域不明则阻塞 |
| 端到端 summary | NOT_RUN：fills→现金/持仓→NAV→换手/回撤/净超额可手算，完整日历/全意图分母 |
| 原始数据与 P-REF | INPUT_BLOCKED：原源文件/hash/可用时点、原窗复核与统计生成/缺失口径核对；无 PortAna 倒推 |
| 4090 / R5 / R6 | NOT_RUN：本刀不派跑数；须补 BT、最小报告门禁与宿主有限清单，未齐不能宣称收益支持 |

## 发布审计

本次提交前检查工作区起点→HEAD、暂存、未暂存、未跟踪范围及 UTF-8/BOM/NUL/whitespace；只提交修订合同白名单。按本次用户令本地 commit，禁止 push、PR、评论，不继承旧任务的发布动作。无真实数值产物入库。

2026-09-20 后续 MQ 拼装器的双文件 data-free 验收命令、输入锁与仍阻塞项见 [回测规则 freeze 交接清单](host-frozen-snapshot-checklist.md)。该刀按用户令仅本地提交，不 push、不开 PR、不评论，不继承上一刀发布动作。

## 2026-09-20 回测规则适配验收

用户三则澄清均落地：原始 10/3 从未实盘、程序未上线，仅回测，禁止再要求 live frozen_original intents；topk/n_drop 可配置；研究默认 50/5，另覆盖 20/3、10/3，不改线上 10/3 配置。

新增 `joint_return_rule_intents.py` 和 `joint_return_merge_scores.py`，freeze/portfolio/contract 全链接收 backtest_rule_intents，持仓和调出上限取 metadata 参数。P-REF 仍为原 Top10 诊断与原 expected hash/窗口/数值门，不能因参数改为 50/5 而放宽。

| 新增验收 | 证据 |
|---|---|
| 50/5、20/3、10/3 | 三组五日×80只合成向量；初次建仓数量/现金手算，满仓调出 n_drop、空槽补仓、无差股票则不强换仓，独立两臂状态；默认 CLI 不传参数确为 50/5；非空但未满仓可补超过 n_drop 个空槽。 |
| 原研究规则 | top/bottom 合并排名、稳定 ties、n_drop=0、显式 hold_thresh；资格拒绝留仓、禁止借被拒卖出槽位；参考数量按卖后现金分配并整手化，含费现金不足停止。 |
| scores 合并 | 四表来源/sidecar 声明/双 hash；缺列、缺共同键、重复键、候选分、非法值阻塞；额外键留账，整日 null 保留、部分标签缺失阻塞。 |
| 时点/数量/身份 | 未来 score/anti/资格、缺价/旧仓分数/持有年龄、证券映射漂移、公司行动缺证据拒绝；零整手/无槽位显式审计，无零量订单。 |
| 完整链 | merge→rules→freeze→portfolio 三组 CLI 接线；frozen 合成 expected 必须在 P-REF hash 门失败；显式 synthetic 手算验证通过；freeze/portfolio 策略 hash 漂移拒绝，已存在输出不覆盖，输出回读失败回滚。 |
| 隔离 | 新入口无 qlib/backtrader/mlflow/host_env/analysis_export/numpy/pandas 导入；实际 --help 和缺文件 CLI 已验证。 |

本次在 Grok Bot 受控 Python 3.12.13 执行：

```bash
/workspace/vanna312/bin/python -m pytest tests/test_joint_return_rule_intents.py tests/test_joint_return_freeze_snapshot.py tests/test_joint_return_portfolio.py -q
```

实际结果：`174 passed in 5.76s`，exit code 0，无 skip。旧 52/111/169 数字是历史/中间记录，不是本次总数。真实输入仍 INPUT_BLOCKED；真实 P-REF/BT/分钟成交/NAV 为 NOT_RUN，收益待实测。未运行训练、湖、PortAna 或 4090 任务；未 push、PR、评论。
