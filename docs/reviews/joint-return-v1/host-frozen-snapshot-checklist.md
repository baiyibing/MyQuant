# Joint return 回测规则 freeze 交接清单

本次在 **Grok Bot 虚拟机**交付和合成验收，不是 4090。原始 10/3 从未实盘、程序未上线，仅有回测，不存在线上原始意图包；**禁止再要求 live `frozen_original_intents`**，也禁止 PortAna 持仓/成交倒推。control recorder READY 不等于本清单全部输入齐备。

研究默认 **50/5**，仓内对此实验积累最多；这是研究默认，**不改线上 10/3 配置**，不表示线上已有程序在运行。20/3、10/3 可显式切换。规则与字段 SSOT 为 [contract](contract.md) §3–6，逐项状态见 [input-register](input-register.md)，测试见 [acceptance](acceptance.md)。2026-09-20 用户裁定已开放下列瘦入口，缺 anti/universe/labels 不再阻塞 P-BASE 组合约束。真实收益与 BT 仍 `NOT_RUN`。

## 0. 只有 control 时走瘦合同

以下是宿主只读研究准备流程；原全量流程保留在 §1–4。不要复制 full 的 candidate/sidecar/pref 依赖到瘦包，也不要把它们补成假值。

| 最小输入 | 显式研究合同 |
|---|---|
| control | 固定 `8a061ea428e04bb3a199a485ade49d0e` 的原 date/instrument/score，全部键保留。已有 score_available_at/source_version/recorder_id 时直接 merge；否则另给下述来源声明。 |
| control-metadata（仅三列原料需要） | 恰含 recorder_id、source_version、score_available_at_by_date（日期→秒精度 +08:00）；每个 control 日期都有经核验的可得时点，不能由日期猜收盘时间。 |
| initial_state | 可显式选定研究起始现金并空仓：`{"cash":<研究者选定的CNY数值>,"positions":{},"quantity_unit":"share","native_stop":"N/A"}`。不是线上账户余额；inputs 的 version/coverage 登记研究假设和起点。不需要旧仓、holding_days 或历史成交。缺此文件不自动初始化。 |
| sessions（生成 plans 时） | 仍用 §1 / contract §5.2 的研究 session，日期集合恰等于 metadata.calendar；每个 control 证券有显式参考价、execution_symbol、买卖资格/原因/可得时点。只需这些显式 JSON，不需要连接湖或分钟引擎。不可全设 eligible=true、price=1 来过门；无来源即局部 INPUT_BLOCKED。 |
| plans（已有时） | 可以直接冻结符合合同的 P-BASE backtest_rule_intents；freeze/portfolio 无需另给 sessions 文件。必须保留来源证据、参考价、资格、冻结数量和状态链，不接受 PortAna 倒推。 |
| pref / universe / anti / labels | 瘦路径不需要。pref 必须从 snapshot、metadata.inputs 与 freeze CLI 省略；candidate_recorder_id/sidecar_sha256 省略或 null。后置不等于通过。 |

来源补充文件结构（尖括号必须由宿主真实证据替换，不是默认值）：

```text
{
  "recorder_id": "8a061ea428e04bb3a199a485ade49d0e",
  "source_version": "<control导出版本及来源>",
  "score_available_at_by_date": {
    "<实际交易日期>": "<该日分数实际可得的YYYY-MM-DDTHH:MM:SS+08:00>"
  }
}
```

瘦 metadata 增加 `"scores_mode":"control_only","arms":["P-BASE"]`；其余策略/费用/研究预算/时钟/单位字段延续 §2，只有 topk/n_drop 有默认。inputs 在规则生成前登记 scores/initial_state 的 URI/双 hash/coverage/version，生成器补入 plans 后恰为三段。来源补充文件由 merge manifest 锁定，宿主须保存该回执；sessions/原 metadata 的双 hash 在生成 plans 的 rule_inputs 中保留。不能以 hash 字串代替上游验证。

```bash
set -e
MQ_PYTHON=/absolute/path/to/python
FREEZE_INPUT_DIR=/absolute/path/to/verified-research-inputs
FREEZE_OUT_DIR=/absolute/path/to/new-slim-output
"$MQ_PYTHON" -m my_scripts.joint_return_merge_scores \
  --mode control_only \
  --control "$FREEZE_INPUT_DIR/control.json" \
  --control-metadata "$FREEZE_INPUT_DIR/control-metadata.json" \
  --output-dir "$FREEZE_OUT_DIR/merged"
```

若 control 已含完整来源字段，省略 `--control-metadata`。然后按 §2 的双 hash 命令，仅登记 merged/scores.json 和 initial_state.json（**不传 pref**），写好上述瘦 metadata，再运行：

```bash
"$MQ_PYTHON" -m my_scripts.joint_return_rule_intents \
  --scores "$FREEZE_OUT_DIR/merged/scores.json" \
  --initial-state "$FREEZE_INPUT_DIR/initial_state.json" \
  --sessions "$FREEZE_INPUT_DIR/sessions.json" \
  --metadata "$FREEZE_INPUT_DIR/metadata.json" \
  --arms P-BASE --topk 50 --n-drop 5 \
  --output-dir "$FREEZE_OUT_DIR/rules"

"$MQ_PYTHON" -m my_scripts.joint_return_freeze_snapshot \
  --scores "$FREEZE_OUT_DIR/merged/scores.json" \
  --initial-state "$FREEZE_INPUT_DIR/initial_state.json" \
  --plans "$FREEZE_OUT_DIR/rules/plans.json" \
  --metadata "$FREEZE_OUT_DIR/rules/metadata.json" \
  --output "$FREEZE_OUT_DIR/snapshot.json"

"$MQ_PYTHON" -m my_scripts.joint_return_portfolio \
  --snapshot "$FREEZE_OUT_DIR/snapshot.json" \
  --run-id joint-return-control-only-50-5 \
  --output-root "$FREEZE_OUT_DIR/portfolio"
```

已有经研究规则生成的 plans 时可跳过生成器，在三段 metadata 中明确登记该 plans，再直接 freeze。切换 20/3、10/3 仍需显式参数与 metadata 相符。所有输出必须为新目录/新文件；CLI 失败退出 2，成功退出 0 只说明相应本地阶段完成。

验收回执检查 `portfolio_status=PORTFOLIO_CONSTRAINTS_PASS`、P-BASE 状态链/数量/费用/目标换手，`pairing.arms` 和 `arm_intent_hashes` 仅有 P-BASE；constraints 的 anti_rank/t0_median 为 null。`pref_check=NOT_RUN`，scope_status 分列 P-CHASE INPUT_BLOCKED、P-REF-anti NOT_RUN、WEAK_SIGNAL INPUT_BLOCKED、Mode B INPUT_BLOCKED/NOT_RUN。frozen 顶层 INPUT_BLOCKED 仍指上游来源待核验；不能再次拿后置 anti/universe/labels 当 P-BASE blocker。

仅三列分数不能产生可信价格和资格。本最小链允许研究者显式给空仓初态、研究 sessions 或已冻结的规则 plans；缺真实价格/资格/可得时点仍停止并指出该项，不静默读湖或造字段。回撤、实际换手、净超额需要后续同窗/同成本/同资金的执行与估值台账；本刀输出仅供组合约束研究入口，不产生真实收益结论、不启动 Mode B。

## 1. full 模式准备显式输入，不寻找 live 包

所有输入都是 UTF-8 JSON，无 BOM/NUL/重复 key/NaN/Infinity。工具只读 CLI 显式路径和固定合同；不搜索 recorder/湖/缓存，不重新预测、不调用 Exchange/PortAna。文件中 source URI 只是声明，不自动解引用。

| 输入 | 内容与停止条件 |
|---|---|
| control.json | 行数组，date/instrument/score/score_available_at/source_version/完整 control recorder_id；仅已有 control score。 |
| universe.json | 已核验共同宇宙行数组，date/instrument/candidate_present=true/完整 candidate recorder_id；只含成员，不能含 score。 |
| anti.json | 原 sidecar 的显式导出：date/instrument/anti_rank/anti_available_at/source_version/source_sha256；原 hash 固定合同值。导出 raw hash 另算，不能将二者混用。 |
| labels.json | date/instrument/label/source_version；整日缺值用 null 保留键，部分缺值阻塞。 |
| initial_state.json | 显式研究 cash/positions/quantity_unit=share/native_stop=N/A；可现金空仓，不要求线上账户。非空仓逐只 quantity/lot_id/instance_id/holding_days，最多所选 topk。 |
| sessions.json | 每个 portfolio calendar 日期一个 session；clock、none 价格域、source_version、eligibility_version、market、corporate_actions；market 每只价格/映射/买卖资格布尔/原因/可得时点。完整列见合同 §5.2。缺列或缺市场行 INPUT_BLOCKED。 |
| pref.json | calendar/windows/expected/label/bootstrap；保留原 P-REF 全日历/两窗/完整 MQ-PJSON expected，不生成新 expected 来凑绿。 |
| metadata.json | 完整合同 metadata；生成器之前可省 strategy 的 topk/n_drop/source/rule_version，由 CLI 明确填入；其余规则、资格、现金/费用/预算/时点无隐含默认。inputs 至少含 scores/initial_state/pref 的 URI/双 hash/coverage/version；plans 由生成器输出新声明。 |

scores 合并以显式共同宇宙为分母；control/anti/label 任一共同键缺失都 INPUT_BLOCKED，不靠 inner join 消除困难样本。其他表额外键完整记录在 merge manifest。必须由宿主证明 universe 本身是完整共同宇宙，不能用人为删减名单冒充。

## 2. 规则 metadata 和输入锁

`strategy` 示例结构（尖括号项必须用有来源的真实研究值替换；示例不是可运行数据）：

```text
{
  "topk": 50,
  "n_drop": 5,
  "source": "backtest_rule_intents",
  "rule_version": "topk-dropout-reference-v1",
  "rule_parameters": {
    "method_buy": "top",
    "method_sell": "bottom",
    "only_tradable": false,
    "hold_thresh": <显式非负整数>,
    "risk_degree": <显式0到1>
  },
  "eligibility_version": "<逐日资格来源版本>",
  "eligibility_rules": {"<规则名>": "<完整定义/参数/证据>"},
  "native_stop": "N/A"
}
```

仅研究 `--topk 50 --n-drop 5` 有默认。metadata 中已登记参数必须和 CLI 相同；切换 20/3 或 10/3 时显式改两个开关及相应研究登记，不能只改开关覆盖旧锁。

其余固定项延续合同：MQ/BT 两个实际完整 code_shas 与 implementation_bases 分列；control ID 始终固定，full 才需 candidate ID、sidecar hash，瘦模式按 §0 省略/null；timezone=Asia/Shanghai，业务时点秒精度 +08:00，price_domain=none；fees 为显式 commission_only/per_order/buy_rate/sell_rate/minimum/source；risk_budget、valuation/benchmark version、order/quantity policy 均须完整。full 原始 P-REF expected 的规范 hash 为 `d9b503fa40937c6b870fc4b0bf9285e2ca53f0465af223f529f2e854712ae6f8`。

原 contract_hash 因本次合同修订失效；用当前文件原字节 SHA-256。后续 BT 必须核对相同合同字节并重新验收，不能复用旧已通过标记。本次不改 BT，也不代替 BT 兼容性验收。

对明确文件登记双 hash：

```bash
MQ_PYTHON=/absolute/path/to/python
"$MQ_PYTHON" - /absolute/path/to/scores.json /absolute/path/to/initial_state.json /absolute/path/to/pref.json <<'PY'
import sys
from pathlib import Path
from my_scripts.joint_return_contract import content_hash, load_json_bytes, raw_hash
for supplied in sys.argv[1:]:
    path = Path(supplied).resolve()
    raw = path.read_bytes()
    print(path, "raw_sha256=" + raw_hash(raw),
          "content_sha256=" + content_hash(load_json_bytes(raw)))
PY
sha256sum docs/reviews/joint-return-v1/contract.md
```

URI 必须是对应 CLI 输入的解析后绝对路径。记录日期/证券/行数/缺失原因、版本、时区/单位/价域和核验人/核验时点。规则生成器预先核验 scores/initial_state 锁，冻结观察到的 sessions/metadata 双 hash；freeze 再核验四段文件全部锁。上游数据来源/PIT 不会因写了一个 hash 字串自动得到证明。

## 3. full 模式实际 CLI 顺序

以下命令已由本次 data-free tests 接线验证，路径必须替换为宿主明确准备好的研究输入和**新目录**。它们不是授权 4090 开跑分钟回测的命令。

先合并 scores：

```bash
set -e
MQ_PYTHON=/absolute/path/to/python
FREEZE_INPUT_DIR=/absolute/path/to/verified-inputs
FREEZE_OUT_DIR=/absolute/path/to/new-freeze-output
"$MQ_PYTHON" -m my_scripts.joint_return_merge_scores \
  --control "$FREEZE_INPUT_DIR/control.json" \
  --universe "$FREEZE_INPUT_DIR/universe.json" \
  --anti "$FREEZE_INPUT_DIR/anti.json" \
  --labels "$FREEZE_INPUT_DIR/labels.json" \
  --output-dir "$FREEZE_OUT_DIR/merged"
```

将上步 `merged/scores.json` 的 URI/双 hash/覆盖登记到输入 metadata；initial_state/pref 同样登记。再生成规则计划（省略两个参数也是 50/5）：

```bash
"$MQ_PYTHON" -m my_scripts.joint_return_rule_intents \
  --scores "$FREEZE_OUT_DIR/merged/scores.json" \
  --initial-state "$FREEZE_INPUT_DIR/initial_state.json" \
  --sessions "$FREEZE_INPUT_DIR/sessions.json" \
  --metadata "$FREEZE_INPUT_DIR/metadata.json" \
  --topk 50 --n-drop 5 \
  --output-dir "$FREEZE_OUT_DIR/rules"
```

生成器按每臂独立理想参考路径输出 plans 和新 metadata。规则核心为 TopkDropout top/bottom；持有门槛、资格和参考数量均显式。拒绝卖出的槽位不可买入，缺旧仓 score 阻塞、ties 按 instrument；这些合同约束与原 Qlib 撮合路径的差异已在 contract §5.1 登记。它不复原历史 PortAna 成交，也不产生真实收益。

最后拼装并运行原 portfolio 门禁：

```bash
"$MQ_PYTHON" -m my_scripts.joint_return_freeze_snapshot \
  --scores "$FREEZE_OUT_DIR/merged/scores.json" \
  --initial-state "$FREEZE_INPUT_DIR/initial_state.json" \
  --plans "$FREEZE_OUT_DIR/rules/plans.json" \
  --pref "$FREEZE_INPUT_DIR/pref.json" \
  --metadata "$FREEZE_OUT_DIR/rules/metadata.json" \
  --output "$FREEZE_OUT_DIR/snapshot.json"

"$MQ_PYTHON" -m my_scripts.joint_return_portfolio \
  --snapshot "$FREEZE_OUT_DIR/snapshot.json" \
  --run-id joint-return-backtest-rule-50-5 \
  --output-root "$FREEZE_OUT_DIR/portfolio"
```

合并器输出 scores.json/merge-manifest.json；生成器输出 plans.json/metadata.json/rule-manifest.json；freeze stdout 输出拼装回执。失败退出 2 并写明 INPUT_BLOCKED/PAIR_INVALID/SEMANTICS_BLOCKED/OUTPUT_BLOCKED，不把残留文件存在当成功。新目录/快照不可覆盖，写失败回滚本次新文件。

freeze 成功退出 0 的 `FROZEN_SNAPSHOT_ASSEMBLED` 只证明显式四段拼装；`kind=frozen`、input_status=INPUT_BLOCKED、execution_status=portfolio_status=NOT_RUN。portfolio 仍验证原 P-REF expected hash/两窗/数值及状态/数量/现金递推。合成 expected 不可借拼装通过真实门；P-REF 仍是 Top10，不随持仓 topk 扩大。

## 4. full 模式剩余缺口和回执（瘦模式按 §0 分列）

| 项 | 状态 |
|---|---|
| 不存在的原始 10/3 live 意图包 | 已撤销该要求；不是 blocker，不再索取。 |
| control/common-universe/anti/label 实际文件与时点/覆盖 | INPUT_BLOCKED，真实导出及上游来源须逐项核验。 |
| 研究初态、hold_thresh/risk_degree、逐日资格、none marks/映射、费用和风险预算 | 规则接口及生成器已交付；真实输入缺任一必需列即 INPUT_BLOCKED。 |
| 原 P-REF expected/完整日历/统计生成口径 | INPUT_BLOCKED / NOT_RUN，需真实复核，不改原 Top10 标签口径。 |
| PIT 行业/size 与 ε/τ | 后续臂局部 INPUT_BLOCKED；本次不新增这些臂。 |
| BT、分钟/session、公司行动/单位映射 | NOT_RUN / 待核验；合同 hash 变更后 BT 须重新对齐；本次不改 BT、不读湖、不扩 Mode B。 |
| 成交/NAV/回撤/实际换手/净超额 | NOT_RUN / 待实测；MQ 合成绿不是联合通过或收益支持。 |

后续执行回执应记录：机器、解释器、实际两仓 code SHA/合同 hash、研究参数、每个源的 URI/双 hash/覆盖/版本/可得时点、merge/rules/freeze/portfolio 命令和退出码、所有 manifest 和 intent hash、尚未解除的 blocker。真实数值留宿主，不入 Git；不能用不存在 live 包这一理由再次阻塞研究规则路径。

Grok Bot 本次验收命令：

```bash
/workspace/vanna312/bin/python -m pytest tests/test_joint_return_rule_intents.py tests/test_joint_return_freeze_snapshot.py tests/test_joint_return_portfolio.py -q
```
