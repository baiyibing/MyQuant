# MyQuant 研究验收与通用协作流程指针

- 原始研究约定：2026-09-13；2026-11-08 将通用开发流程与脚手架执行核归入 grok-bot-ops。
- 本文保留 MyQuant 的研究验收口径、运行入口和历史硬约束索引。

## 1. 通用流程

任务书、实现、检查、宿主验证、证据判读和回写的通用流程正文位于
[grok-bot-ops：development workflow](https://github.com/baiyibing/grok-bot-ops/blob/master/docs/handoff/development-workflow.md)。
交付清单见 [generic DoD](https://github.com/baiyibing/grok-bot-ops/blob/master/docs/handoff/generic-dod.md)。
Grok Bot 协调场景的角色、模型与合入权限见[本仓 RACI 指针](operations/grok-bot-raci-workflow.md)。

`my_scripts/task_scaffold.py` 只保留本仓研究模板、仓库路径和检查命令，通用执行核读取相邻
`grok-bot-ops/scripts/workflow/task_scaffold.py`。ops checkout 位于其他位置时设置
`MYQUANT_OPS_ROOT`。缺失依赖明确报错，不使用本地实现副本。

## 2. 判读预锁（本仓研究约定）

研究任务书在结果产生之前写明：

1. 采纳条件，例如跨窗同向或独立验证标准。
2. 合法终点，例如负结果、不可比或不改变名单。
3. 禁止说法，例如把信号 IC 直接解释成已实现收益。
4. 预期管理，明确本次实验实际回答的问题。

单窗结果与多次选参的证据边界应在报告中说明。Qlib 的 PortAna、Exchange、成本实验、
收益分析和 replay 都是本仓可用的研究能力，具体采用哪些组件由研究任务决定。
预锁与证据要求保留在研究仓，不进入通用工程脚手架。

## 3. 本仓运行与验证

```text
python my_scripts/task_scaffold.py new <slug> --title <title> --kind plan
python my_scripts/task_scaffold.py check --files my_scripts/<entry>.py
python -m pytest my_tests tests my_scripts/test_zhangting_filter.py -q
```

`new` 会生成研究任务书并执行分支、提交和 push；只有明确要执行这些操作时才运行。
`check` 运行本仓配置的检查；不会调用 `new`。
需要真实数据的实验，记录窗口、模型/参数、数据来源、输出路径和启动时 Git 溯源。
研究结论与已合入状态分别登记到对应计划或报告。

## 4. 共享评审与 PR 发布入口

`my_scripts/ops_workflow.py` 通过独立 Python 进程调用相邻 ops 源码，固定
`--repo-root` 为本入口所在的 MyQuant checkout，传入本仓研究 profile。
它校验 ops 的 `scripts/runtime-api.json` v1；缺失或不兼容时明确失败。
指定其他 ops checkout 可用 `--ops-root <绝对路径>`，优先于 `MYQUANT_OPS_ROOT`。
从别的当前目录启动时，仓库和相对路径仍绑定到本入口所在 checkout。

| 本仓命令 | ops 入口 | 本仓配置 |
|---|---|---|
| `review` | `scripts/run/run_multi_ai_review.py` | [review.json](../configs/ops/review.json)：研究预锁、PIT、跨段标签、数据/指标、Qlib 边界与产物契约 |
| `adversarial` | `scripts/run/run_codex_adversarial_lanes.py` | [adversarial.json](../configs/ops/adversarial.json)：时间/数据、研究/证据、接口/产物三路 |
| `publish` | `scripts/ops/push_github_pr_via_api.py` | 当前功能分支及调用时显式提供的标题/正文等参数 |

先用现有流程文档核对评审接线；以下命令均为 dry-run：

```text
python my_scripts/ops_workflow.py review --plan docs/pipeline-collab-2026-09-13.md --out-dir .test-tmp-ops/review --dry-run
python my_scripts/ops_workflow.py adversarial --plan docs/pipeline-collab-2026-09-13.md --out-dir .test-tmp-ops/lanes --dry-run
python my_scripts/ops_workflow.py publish --title "本次功能分支的 PR 标题" --dry-run
```

子命令后加 `--help` 查看 ops 的完整参数。`--repo-root` 与 `--profile-file` 由本仓固定；
其他仓库或研究 profile 直接调用 ops。其余参数按原样传递，退出码返回调用方。
模型、席位和调度行为由 ops 当前运行时维护，本仓不复制模型目录或 agent 执行实现。

`review --dry-run` 会在输出目录写提示词与版本记录，跳过评审员预检和执行；
`adversarial --dry-run` 不写输出，并保留 ops 的嵌套会话拒绝规则；
`publish --dry-run` 只读本地 Git，不读取认证或访问 API。实际评审或发布应在明确执行该动作时调用。

发布命令在待发布功能分支运行，`master` / `main` 由 ops 拒绝。
该发布器通过 Git Data API 重放提交并创建 PR，同名远端功能分支可能被替换，
重放 SHA 也可能与本机不同；确认需要这种发布方式后再执行实际调用。
CI 检查及合入继续按现有仓库流程处理。
通用运行时合同见 [ops shared runtime](https://github.com/baiyibing/grok-bot-ops/blob/master/docs/multi-ai/shared-runtime-20261109.md)。

## 5. 研究运行约束索引

- 数据产制调用 infra；日线刷新见[操作手册](../my_docs/提示词-qlib-bin刷新.md)，
  分钟见[分钟手册](../my_docs/提示词-qlib-1min-bin刷新.md)。provider、staging 和保护目录显式配置。
- Qlib handler 初始化开销较大，验证按相同数据/配置合批；缓存键与数据身份对应。
- Windows 多进程入口使用 main guard 和适用的 `freeze_support()`。
- 训练进程在启动时记录 Git 溯源；池导出保留 as-of、代码和字节契约。
- 盘后展开已有 recorder 产物用 `analysis_export.py` / `export_positions_trades.py`；
  研究需要重新回测时可显式使用 replay，保留实验参数与结果来源。

原计划和历史实验记录保留在本仓，历史组件“停用”表述以当前 README 的研究定位为准。
