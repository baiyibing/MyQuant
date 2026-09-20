# 4090 显式 frozen snapshot 宿主清单

本刀在 Grok Bot 仅交付 MQ 拼装器和 data-free 验收。宿主回执已登记 control recorder `8a061ea4` READY；这不补齐原始 10/3 意图。真实状态仍为 `INPUT_BLOCKED / NOT_RUN`。本清单承接 [contract](contract.md)、[input-register](input-register.md) 和 [acceptance](acceptance.md)，不改合同字节、BT 或既有 portfolio 门禁。

## 1. 4090 必须显式提供的五个本地 JSON 文件

CLI 只读取以下五个指定文件，以及代码固定的 `contract.md`；不搜索 recorder、湖、缓存或最近版本，不执行预测、PortAna 导出或原意图重建。四个 section 文件的 JSON 顶层就是对应段，不能再包一层同名 key。保留原始值和数组次序；UTF-8、无 BOM/NUL、无重复 key、无 NaN/Infinity。

| 文件 / 参数 | 内容与必需来源 |
|---|---|
| `scores.json` / `--scores` | 行数组；`date,instrument,score,score_available_at,source_version,anti_rank,anti_available_at,candidate_present,label`。score 只能来自完整 control recorder；candidate 只用于共同宇宙，`candidate_present=true`，禁止 `candidate_score`。保留原 score/anti/label 和可得时点，不重新预测或制作 sidecar。 |
| `initial_state.json` / `--initial-state` | 两臂共同起点：显式 `cash,positions,quantity_unit="share",native_stop="N/A"`；每个持仓有 `quantity,lot_id,instance_id`。现金、数量、none 价域和时点必须有真实来源。 |
| `plans.json` / `--plans` | 原始计划数组。portfolio calendar 每日分别有 P-BASE/P-CHASE，无交易也提交空列表计划。必需字段见下段。缺少原包即阻塞，不能从 PortAna 已成交持仓倒推失败订单，不能编造 10/3 或复制 BASE 的后续状态给 CHASE。 |
| `pref.json` / `--pref` | `calendar,windows,expected,label,bootstrap`。完整共同宇宙日历；expected 是完整原 MQ-PJSON 对象，不只是 windows 子段。原窗为 `2025_valid:2025-01-03…2025-12-31`、`2026_oos:2026-01-01…2026-09-14`。label 固定 `Ref($close,-2)/Ref($close,-1)-1`，bootstrap 固定 block=5/reps=10000/seed=20260919。 |
| `metadata.json` / `--metadata` | 合同 §3 的完整 metadata 对象，字段见下一节；包括预先登记的四个文件 URI、双 hash、coverage、version。不给真实费用、风险预算、资格等填默认值。 |

每条 plan 必须有 `date,arm_id,source,pre_state_hash,decision_at,available_at,effective_at,expires_at,marks,mark_at,sells,buys,buy_candidates,corporate_actions`。`source="frozen_original_intents"`；`corporate_actions=[]`，真实有事件则不能删掉来过门。`sells` 包含批准和拒绝的原卖出数量记录及 `approved,approval_reason`；`buys` 为获准原买入 instrument 有序列表；`buy_candidates` 包含冻结资格/回填数量及 `eligible,eligibility_reason`。

所有数量记录均有 `instrument,execution_symbol,instance_id,lot_id,target_weight,original_target_quantity,reference_price,reference_price_at,quantity_unit,quantity_conversion`。数量是原始买卖量；`quantity_conversion="SNAPSHOT_FIXED"`。参考价、转换预算和各臂 `pre_state_hash` 必须来自原包，拼装器不生成这些值。若原始意图确实不存在，退回另刀冻结规则适配，不能靠此 CLI 解除缺口。

## 2. metadata 与源文件锁

| 字段 | 必填值 / 宿主登记要求 |
|---|---|
| `code_shas` | MQ、BT 实际运行提交的完整 40 位 SHA；与 implementation bases 分开，不能拿测试基线冒充实际提交。 |
| `implementation_bases` | MQ=`4e4368b274ada2e27da5902f7420aa5a8ae5950c`；BT=`1049b904bdd818dbb79f51f1830a008c8f83b141`。 |
| `contract_hash` | 本次使用的 `docs/reviews/joint-return-v1/contract.md` 原字节 SHA-256，MQ/BT 固定同一文档字节。 |
| `pred_recorder_id` | `8a061ea428e04bb3a199a485ade49d0e`，禁止短 ID 和 candidate recorder。 |
| `candidate_recorder_id` | `d03e8ffcb6d14668b4d6fc2b192bc8c7`，只登记共同宇宙。 |
| `sidecar_sha256` | `27320f8b7f6de3854802f97325f682039732470ce387f21bc9cd6c3083b7b348`。 |
| `generated_at,window,calendar,timezone` | 显式生成时间、portfolio 起止日期和排序无重复交易日；业务时点为秒精度 `+08:00`，timezone=`Asia/Shanghai`。portfolio calendar 可小于 P-REF 全日历，但必须有各臂完整计划，不能自动截窗。 |
| `price_domain,valuation_version,benchmark_version` | `none`，显式估值版本、同 fill P-BASE 基准版本。 |
| `strategy` | `topk=10,n_drop=3,source="frozen_original_intents",native_stop="N/A"`，以及有来源的 `eligibility_version`、完整非空 `eligibility_rules`。不推断 ST/年龄/涨幅资格。 |
| `fees` | `model="commission_only",granularity="per_order"`；显式 `buy_rate,sell_rate,minimum,source`。不能继承合成零费。 |
| `risk_budget` | 有来源的 [0,1] 目标股票权重上限，不能把测试值当真实政策。 |
| `order_policy` | `retry_policy="NEXT_LEGAL_BAR_LIMIT_DOWN_NEXT_SESSION"`、`conflict_policy="CANCEL_OLDER_REMAINDER_SELL_FIRST"`、`expiry_policy="CANCEL_REMAINDER_EXPIRY_EXIT_DEFER_NO_BAR"`。 |
| `quantity_policy` | `unit="share",buy_lot=100,sell="FULL_LOT_EXIT",corporate_actions="EXPLICIT_ONLY"`。 |
| `inputs` | 恰好 `scores,initial_state,plans,pref` 四项，每项 `uri,raw_sha256,content_sha256,coverage,version`。URI 为对应 CLI 文件的解析后绝对路径；coverage 登记日期、证券、行数及缺失原因；version 登记可核验来源。若 scores 声明额外 `recorder_id`，也必须等于 control recorder。 |

双 hash 是宿主对已核验文件的事先登记，CLI 会重新读取并比对，漂移即停止，不回填或覆盖声明。raw hash 覆盖实际文件字节；content hash 使用合同规范 JSON，无尾 LF。URI 只与 CLI 路径比对，绝不解引用成另一个输入。登记时可对**明确给出的文件**打印 hash，填入 metadata 后冻结：

```bash
# 在 MQ 仓库根目录；替换为 4090 的实际解释器与五个已备齐文件的位置。
MQ_PYTHON=/absolute/path/to/python
FREEZE_INPUT_DIR=/absolute/path/to/verified-inputs
"$MQ_PYTHON" - "$FREEZE_INPUT_DIR/scores.json" \
  "$FREEZE_INPUT_DIR/initial_state.json" "$FREEZE_INPUT_DIR/plans.json" \
  "$FREEZE_INPUT_DIR/pref.json" <<'PY'
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

还需宿主独立核验上游 control pred、共同宇宙对齐、原 sidecar、原意图及发布时间/PIT/覆盖证据，并记录原 URI、hash、版本、核验人和时点。拼装器核验的是四个 JSON 文件，不会自动证明它们来自所声明 recorder 或核验 sidecar 文件。原 MQ-PJSON 文件 raw hash 为 `22d86384e7d4fcf82586e51fce4a212309baeab584e5cbb64054788460035e82`，`pref.expected` 的规范 hash 必须为 `d9b503fa40937c6b870fc4b0bf9285e2ca53f0465af223f529f2e854712ae6f8`；portfolio 将检查后者及原窗/完整数值，禁止反写 expected 或调容差凑绿。

## 3. 拼装与 portfolio 调用

在 MQ 仓库根目录执行，所有输入必须先齐备；以下路径均须替换成 4090 实际路径。使用新的输出目录与 run ID，真实产物保存在宿主，不入 Git。

```bash
set -e
MQ_PYTHON=/absolute/path/to/python
FREEZE_INPUT_DIR=/absolute/path/to/verified-inputs
FREEZE_OUT_DIR=/absolute/path/to/new-freeze-output
mkdir -p "$FREEZE_OUT_DIR"
"$MQ_PYTHON" -m my_scripts.joint_return_freeze_snapshot \
  --scores "$FREEZE_INPUT_DIR/scores.json" \
  --initial-state "$FREEZE_INPUT_DIR/initial_state.json" \
  --plans "$FREEZE_INPUT_DIR/plans.json" \
  --pref "$FREEZE_INPUT_DIR/pref.json" \
  --metadata "$FREEZE_INPUT_DIR/metadata.json" \
  --output "$FREEZE_OUT_DIR/snapshot.json" \
  > "$FREEZE_OUT_DIR/freeze-manifest.json"

"$MQ_PYTHON" -m my_scripts.joint_return_portfolio \
  --snapshot "$FREEZE_OUT_DIR/snapshot.json" \
  --run-id joint-return-host-frozen-v1 \
  --output-root "$FREEZE_OUT_DIR/portfolio"
```

缺文件、缺声明、hash/固定 metadata 漂移、PortAna source 或候选分输入时，freeze 退出 2，stdout 为 `INPUT_BLOCKED` 或契约等价状态及原因，不产生新 snapshot。已有输出不覆盖；写入/回读失败会移除本次新文件。重定向文件可能包含失败状态，必须同时检查退出码和 JSON，不能仅以文件存在判断成功。

成功退出 0 时 snapshot 固定 `kind="frozen"`，已通过 `validate_snapshot` 和写后 `load_snapshot`；stdout manifest 为 `FROZEN_SNAPSHOT_ASSEMBLED`，含 snapshot、metadata 输入、四段文件的 URI/raw/content hashes。`input_raw_hashes_verified=true` **仅指这四个显式 JSON 文件**；`input_status=INPUT_BLOCKED`、`execution_status=portfolio_status=NOT_RUN`。

拼装不执行 P-REF 数值复核、原 expected hash/窗口门禁或两臂参考状态递推；这些由随后 portfolio 按 `kind=frozen` 验证。纯合成文件可以验证拼装工程，但无法通过真实 P-REF hash 门禁。现有 portfolio manifest 的 `input_raw_hashes_verified=false` 与真实 `INPUT_BLOCKED` 状态保持原样：它只读内嵌 snapshot，不消费 freeze 回执来自动解除宿主门禁。归档两份 manifest，分别核对，不将其改成 READY 或联合通过。

## 4. 仍阻塞的项与宿主回执

| 项 | 状态 / 责任 |
|---|---|
| 原始 10/3 意图、各臂参考数量和状态、资格/费用来源 | 未提供即 `INPUT_BLOCKED`；MQ/宿主提供可追溯原包，不用 PortAna 倒推。recorder READY 不解除此项。 |
| 原 score/anti 发布时点、共同宇宙、P-REF 原统计生成口径 | `INPUT_BLOCKED`，直至宿主逐源核验及 portfolio 数值门通过；不自动声称真实收益支持。 |
| 中性臂 PIT 行业/size 及换手臂预登记 ε/τ | `INPUT_BLOCKED`；需明确字段定义、可用/生效时点、覆盖与 hash，并在看新增收益前登记 ε/τ。此刀只登记缺口，不设默认阈值、不新增臂。 |
| Mode B 真湖、分钟/session、公司行动与数量映射 | 归 BT；本刀不改 BT、不读湖、不扩 Mode B。MQ 遇显式公司行动仍 `SEMANTICS_BLOCKED`，不能删除事件当作无事件。 |
| 成交/NAV/换手/回撤/净超额 | `NOT_RUN / 待实测`，后续 BT 与宿主验收，不能用拼装或 MQ 测试绿代替。 |

4090 回执登记：实际 MQ/BT code SHA、合同 hash、五个输入的 URI/hash/覆盖/来源、freeze 命令/退出码/manifest、snapshot URI/双 hash、portfolio 命令/退出码及四个输出路径、逐项未解 blocker。缺任何真实输入就保留原因和 `INPUT_BLOCKED / NOT_RUN`，不补造产物。

Grok Bot data-free 验收命令（只读合成临时文件）：

```bash
/workspace/vanna312/bin/python -m pytest tests/test_joint_return_freeze_snapshot.py tests/test_joint_return_portfolio.py -q
```
