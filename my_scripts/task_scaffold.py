"""MyQuant research template and checks over the ops source scaffolder.

Place grok-bot-ops beside MyQuant, or set MYQUANT_OPS_ROOT to its checkout.
The common implementation has no local fallback.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
OPS_ROOT = Path(os.environ.get("MYQUANT_OPS_ROOT") or REPO_ROOT.parent / "grok-bot-ops")
_source = OPS_ROOT / "scripts" / "workflow" / "task_scaffold.py"
if not _source.is_file():
    raise ModuleNotFoundError(
        f"ops source scaffolder not found: {_source}; check out grok-bot-ops beside "
        "MyQuant or set MYQUANT_OPS_ROOT"
    )
_spec = importlib.util.spec_from_file_location("grok_bot_ops_task_scaffold", _source)
_scaffold = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_scaffold)
SLUG_RE = _scaffold.SLUG_RE
KIND_BRANCH = _scaffold.KIND_BRANCH

TEMPLATE = """# {title}

- 日期：{today}
- 状态：草案（任务书；切片/验收/预锁齐后开 PR）
- 上游：docs/pipeline-collab-2026-09-13.md（本仓研究验收约定）；硬约束见中期计划 §0 十五条
- 执行：实现者按片 PR；宿主实跑验收；回写路线图 §0 一行

---

## 1. 定位（钉死，防走样）

<!-- 这件事只动什么、绝不动什么；一段话 -->

## 2. 切片

| 片 | 内容 | 验收 |
|---|---|---|
| A | <!-- --> | <!-- 本地全量测试绿 + 具体断言 --> |

## 3. 判读预锁（跑之前写死，跑完不许改）

1. **采纳条件**：<!-- 如：两窗同向才采纳 -->
2. **合法终点**：<!-- 不可比 / 不改变名单 / 负结果——都算交付 -->
3. **禁止说法**：<!-- 如「模型优于手工」「该改 topk」 -->
4. **预期管理**：<!-- 如：先量集中度再谈效果 -->

## 4. 明确不做

- <!-- -->
"""


def main(argv: list[str] | None = None) -> int:
    return _scaffold.main(
        argv, repo_root=REPO_ROOT, template=TEMPLATE,
        check_command=[sys.executable, "-m", "pytest", "my_tests", "tests",
                       "my_scripts/test_zhangting_filter.py", "-q"],
        check_env={"PYTHONUTF8": "1"},
    )


if __name__ == "__main__":
    raise SystemExit(main())
