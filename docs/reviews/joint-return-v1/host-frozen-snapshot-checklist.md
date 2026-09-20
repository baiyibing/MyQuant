# Joint return 回测规则 freeze 交接清单

本次在 **Grok Bot 虚拟机**交付和合成验收，不是 4090。原始 10/3 从未实盘、程序未上线，仅有回测，不存在线上原始意图包；**禁止再要求 live `frozen_original_intents`**，也禁止 PortAna 持仓/成交倒推。control recorder READY 不等于本清单全部输入齐备。

研究默认 **50/5**，仓内对此实验积累最多；这是研究默认，**不改线上 10/3 配置**，不表示线上已有程序在运行。20/3、10/3 可显式切换。规则与字段 SSOT 为 [contract](contract.md) §3–6，逐项状态见 [input-register](input-register.md)，测试见 [acceptance](acceptance.md)。当前真实状态 `INPUT_BLOCKED / NOT_RUN`，收益待实测。

## 1. 准备显式输入，不寻找 live 包

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

其余固定项延续合同：MQ/BT 两个实际完整 code_shas 与 implementation_bases 分列；control/candidate IDs、sidecar hash 固定；timezone=Asia/Shanghai，业务时点秒精度 +08:00，price_domain=none；fees 为显式 commission_only/per_order/buy_rate/sell_rate/minimum/source；risk_budget、valuation/benchmark version、order/quantity policy 均须完整。原始 P-REF expected 的规范 hash 为 `d9b503fa40937c6b870fc4b0bf9285e2ca53f0465af223f529f2e854712ae6f8`。

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

## 3. 实际 CLI 顺序

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

## 4. 剩余缺口和回执

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
