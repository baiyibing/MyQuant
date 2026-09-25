# 4090 narrow pack 重导：BUG_ALIGNMENT

派工方 qlib；4090bot 仅作为 runner。VM 不持有真实 scores/lake，不运行下述真数流程。
路径依据 `/workspace/handoffs/joint_return_20260922/HANDOFF_TO_BT_MODE_B.md` §3/§5，
2026-09-22 回执仍指向以下族；实际输入文件名须在 4090 用旧 manifest 核验，不猜路径。

- MQ：`D:\PycharmProjects\MyQuant`
- 运行根：`D:\PycharmProjects\MyQuant\runs\joint_return_4090_20260920_pr95`
- 旧交接：`handoff_bt_20260922\narrow_20260922\portfolio_joint-return-control-only-50-5-narrow`
- 收窄证据：`handoff_bt_20260922\NARROW.md`（614 full_window；剔除 9 no_file + 150 over_window）。
- 现有 bars：`D:\exports\joint_return_pbase_narrow_20260922\frozen_explicit_bars.json`
- 湖（仅真实导出需要）：`C:\Users\wangc\.qlib\qlib_data\my_data_1min`

错误：09-07 15:03 available/effective → 同日 16:00 expiry；交易会话已结束，
严格晚于 15:03 的合法 open 数量为零。正确 helper 示例：保留 09-07 15:00 mark / 15:02 decision，
available/effective=显式下一 session 09-08 09:30，expiry=09-08 15:00；首个允许 open=09:31。
所有时间 +08:00，见合同 §5.2.1 的连续 session convention。

## 1. 输入复用与必须重建

拉取本 PR 合并提交后登记实际 MQ SHA。BT 由 bt 核对代码 SHA 和**新合同字节/hash**，
旧锁不能直接通过；此步骤不修改 BT fill kernel。

可复用经核验的 **narrow** scores.json、initial_state.json 及其来源/资格/参考价证据；
宇宙、研究初态、费用和策略保持原窄包声明。已有 sessions 的 market、mark、decision、资格及
公司行动声明可作为输入复用，但必须重建其执行时钟。禁止拿全宇宙 scores 替换 narrow scores。
原 metadata 的策略/来源声明可作模板，但合同 hash、实际 code_shas、execution_calendar、
输入 URI/双 hash 必须重新登记。**sessions、metadata、plans、freeze、portfolio、intents 和所有对应
manifest/hash 必须重新生成**；不可只编辑旧 CSV，旧 frozen packs 不可复用。

从已有显式市场日历提供完整 `execution-calendar.json`（JSON 日期数组，包含全部研究日及最后
信号之后的下一市场 session），保留日历来源回执。不能由周一至周五推算，不能造 bar，不能暗删末日。
如果真实源无法提供末日后 session/覆盖，停止并登记具体缺口，交 qlib/bt 裁定。

现有 narrow bars **在宇宙不变且新执行/估值窗口的日期、session、证券覆盖全部满足时可以复用**。
即使宇宙不变，最后信号移到下一 session 也可能需真实导出尾日；先让 bt 按新包重新核验覆盖。
不足时仅由原真实湖 exporter 导出缺失窗口或重导 narrow bars，绝不补造分钟。
不在本文虚构未核验的宿主湖导出脚本名或更改 lake reader。

## 2. PowerShell：准备新时钟和来源锁

在 4090 的 MQ 根目录运行；`$Py` 用原成功运行的解释器绝对路径。
下列 Read-Host 项须填旧 narrow rule-manifest / frozen metadata.inputs 中核验过的真实文件，
不是请求新数据或未声明默认值。输出 `narrow_clock_20260922` 是本次**新建**目录名，已存在即停止。
先在 MQ 工作副本更新到 qlib 派工指定的本 PR 合并提交（记录 `git rev-parse HEAD`）。

```powershell
Set-Location D:\PycharmProjects\MyQuant
$Py = Read-Host '原成功运行的 Python 绝对路径'
$Scores = Read-Host '旧 narrow scores.json 的真实绝对路径'
$Initial = Read-Host '旧 narrow initial_state.json 的真实绝对路径'
$Sessions = Read-Host '旧 narrow sessions.json 的真实绝对路径'
$Metadata = Read-Host '旧 narrow metadata.json 的真实绝对路径'
$Calendar = Read-Host '已核验含尾部下一 session 的显式 execution-calendar.json 绝对路径'
$BtSha = Read-Host 'bt 已核验的实际完整 BT code SHA（已对齐新合同）'
$Root = 'D:\PycharmProjects\MyQuant\runs\joint_return_4090_20260920_pr95'
$Out = Join-Path $Root 'handoff_bt_20260922\narrow_clock_20260922'
@'
import subprocess, sys
from pathlib import Path
from my_scripts.joint_return_contract import (
    canonical_bytes, contract_hash, load_json_bytes, next_session_clocks, sha,
)
from my_scripts.joint_return_freeze_snapshot import _read_json
scores, initial, sessions, metadata, calendar, bt_sha, output = sys.argv[1:]
out = Path(output)
assert not out.exists(), 'new output directory required'
m, _ = _read_json(Path(metadata).resolve())
rows, _ = _read_json(Path(sessions).resolve())
assert m['scores_mode'] == 'control_only'
m['execution_calendar'] = load_json_bytes(Path(calendar).read_bytes())
m['contract_hash'] = contract_hash()
m['code_shas'] = {'MQ': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                  'BT': bt_sha}
for value in m['code_shas'].values():
    sha(value, 40)
for row in rows:
    row.update(next_session_clocks(decision_at=row['decision_at'], mark_at=row['mark_at'], metadata=m))
for name, supplied in [('scores', scores), ('initial_state', initial)]:
    _, source = _read_json(Path(supplied).resolve())
    m['inputs'][name].update(source)  # preserve verified version/coverage/provenance
out.mkdir(parents=True)
(out / 'sessions.json').write_bytes(canonical_bytes(rows) + b'\n')
(out / 'metadata.json').write_bytes(canonical_bytes(m) + b'\n')
print('MQ', m['code_shas']['MQ'], 'contract_hash', m['contract_hash'])
'@ | & $Py - $Scores $Initial $Sessions $Metadata $Calendar $BtSha $Out
if ($LASTEXITCODE -ne 0) { throw 'clock preparation failed' }
```

显式 helper 是唯一改写动作；rule/freeze/portfolio 接口只验证。核对生成 sessions：日期集合不变、
每个最后信号都有下一 session、没有 15:03→当日 16:00 窗口。将日历路径/双 hash、来源、
convention 与 BT session 核对结果写入新目录的宿主回执。

## 3. PowerShell：重建规则 → freeze → portfolio

继续同一会话；不传 pref，不重算 score，不运行训练。

2026-09-25 起，rule/portfolio 默认启用 plan-hash cache（产品相同，metadata/manifest 带 `research_acceleration: TRACK_B_PLAN_HASH_CACHE_PENDING_REVIEW` 研究标记）；两端加 `--no-cache-plan-hash` 可复现慢速参考路径。

```powershell
& $Py -m my_scripts.joint_return_rule_intents --scores $Scores --initial-state $Initial --sessions "$Out\sessions.json" --metadata "$Out\metadata.json" --arms P-BASE --topk 50 --n-drop 5 --output-dir "$Out\rules"
if ($LASTEXITCODE -ne 0) { throw 'rule generation failed' }
& $Py -m my_scripts.joint_return_freeze_snapshot --scores $Scores --initial-state $Initial --plans "$Out\rules\plans.json" --metadata "$Out\rules\metadata.json" --output "$Out\snapshot.json"
if ($LASTEXITCODE -ne 0) { throw 'freeze failed' }
& $Py -m my_scripts.joint_return_portfolio --snapshot "$Out\snapshot.json" --run-id joint-return-control-only-50-5-narrow-clock --output-root "$Out\portfolio"
if ($LASTEXITCODE -ne 0) { throw 'portfolio failed' }
```

新交接目录：`$Out\portfolio\joint-return-control-only-50-5-narrow-clock`。
保留完整 `intents.csv,manifest.json,constraints.csv,pref_check.json` 相邻文件及上游 rules/snapshot；
不要复用旧 intent_hash/contract_hash。回执登记新数量、available/effective/expiry 分布、
PORTFOLIO_CONSTRAINTS_PASS、测试/运行退出码和实际 MQ/BT SHA。无成交结论仍 NOT_RUN。

交给 bt：新 pack 路径、新合同字节/hash、NARROW.md、显式 bars 路径与新窗口覆盖核验。
bt 再派 4090 重跑 P-BASE / M-LAG，核验机会数/fills/expiry 原因及真实收益指标；
先收口 P-BASE，再决定 Mode B，不在 MQ 代跑 BT 或修改撮合核。
