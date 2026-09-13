# -*- coding: utf-8 -*-
"""协作流水线脚手架：任务书生成 + 分支/提交/推送 + 本地门禁。

用法::

    python my_scripts/task_scaffold.py new <slug> --title "标题" [--kind plan|feat|fix]
        # 生成 docs/plan-<slug>-<今天>.md（含预锁四件套模板）→ 切分支 → 提交 → push
        # 打印开 PR 的 compare 链接（本机网络到不了 api.github.com，PR 在网页/MCP 侧开）

    python my_scripts/task_scaffold.py check [--files a.py b.py]
        # py_compile 指定文件（如有）→ 全量 pytest（流水线第③步前的本地门禁）

模板里的「判读预锁」四件套（采纳条件/合法终点/禁止说法/预期管理）必填——
这是 docs/pipeline-collab-2026-09-13.md §2 的要求，删掉即违反流水线。
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
KIND_BRANCH = {"plan": "docs/", "feat": "feat/", "fix": "fix/"}

TEMPLATE = """# {title}

- 日期：{today}
- 状态：草案（任务书；切片/验收/预锁齐后开 PR）
- 上游：docs/pipeline-collab-2026-09-13.md（流水线 SSOT）；硬约束见中期计划 §0 十五条
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


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", **kw)


def cmd_new(args: argparse.Namespace) -> int:
    slug = args.slug
    if not SLUG_RE.match(slug):
        print(f"slug 非法（小写字母/数字/连字符）: {slug!r}")
        return 2
    branch = KIND_BRANCH[args.kind] + slug
    status = run(["git", "status", "--porcelain"], cwd=REPO_ROOT)
    tracked_dirty = [l for l in status.stdout.splitlines() if l.strip() and not l.startswith("??")]
    if tracked_dirty:
        print("工作树有已跟踪文件的未提交改动，先处理再脚手架：")
        print("\n".join(tracked_dirty[:5]))
        return 2
    today = date.today().isoformat()
    doc = REPO_ROOT / "docs" / f"plan-{slug}-{today}.md"
    if doc.exists():
        print(f"已存在: {doc}")
        return 2
    doc.write_text(TEMPLATE.format(title=args.title or slug, today=today), encoding="utf-8", newline="\n")
    steps = [
        ["git", "checkout", "-b", branch],
        ["git", "add", str(doc.relative_to(REPO_ROOT))],
        ["git", "commit", "-m", f"docs: 任务书 {slug}（流水线脚手架生成）"],
        ["git", "push", "-u", "origin", branch],
    ]
    for s in steps:
        r = run(s, cwd=REPO_ROOT)
        if r.returncode != 0:
            print("步骤失败:", " ".join(s), "\n", r.stderr[-500:])
            return 1
    remote = run(["git", "remote", "get-url", "origin"], cwd=REPO_ROOT).stdout.strip()
    print(f"任务书: {doc}")
    print(f"分支: {branch} 已推送")
    print(f"开 PR: 将 {branch} 与默认分支比较（remote={remote}），或交给有 GitHub API 权限的一方")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    for f in args.files:
        r = run([sys.executable, "-m", "py_compile", f], cwd=REPO_ROOT)
        if r.returncode != 0:
            print("py_compile 失败:", f, r.stderr[-300:])
            return 1
    r = subprocess.run([sys.executable, "-m", "pytest", "my_tests", "my_scripts/test_zhangting_filter.py", "-q"],
                       cwd=REPO_ROOT)
    return r.returncode


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="协作流水线脚手架")
    sub = p.add_subparsers(dest="cmd", required=True)
    pn = sub.add_parser("new", help="生成任务书 + 分支 + 提交 + push")
    pn.add_argument("slug")
    pn.add_argument("--title", default=None)
    pn.add_argument("--kind", choices=sorted(KIND_BRANCH), default="plan")
    pn.set_defaults(fn=cmd_new)
    pc = sub.add_parser("check", help="本地门禁：py_compile + 全量 pytest")
    pc.add_argument("--files", nargs="*", default=[])
    pc.set_defaults(fn=cmd_check)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
