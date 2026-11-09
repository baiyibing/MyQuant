"""MyQuant entry for the shared ops review and PR publication CLIs."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
ENTRIES = {
    "review": ("scripts/run/run_multi_ai_review.py", "configs/ops/review.json"),
    "adversarial": ("scripts/run/run_codex_adversarial_lanes.py", "configs/ops/adversarial.json"),
    "publish": ("scripts/ops/push_github_pr_via_api.py", None),
}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(
        add_help=False, allow_abbrev=False,
        description="MyQuant 调用 ops 共享运行时；子命令后 --help 查看 ops 参数。",
    )
    parser.add_argument("command", choices=ENTRIES, help="review / adversarial / publish")
    parser.add_argument("--ops-root", help="ops 源码绝对路径；缺省使用环境变量或同级 grok-bot-ops")
    if argv in ([], ["--help"], ["-h"]):
        parser.print_help()
        return 0 if argv else 2
    args, remaining = parser.parse_known_args(argv)
    if any(arg.split("=", 1)[0] in {"--repo-root", "--profile-file"} for arg in remaining):
        parser.error("MyQuant 固定仓库和研究 profile；其他仓库或 profile 请直接调用 ops")

    configured = args.ops_root or os.environ.get("MYQUANT_OPS_ROOT")
    ops_root = Path(configured).expanduser() if configured else REPO_ROOT.parent / "grok-bot-ops"
    if not ops_root.is_absolute():
        parser.error("--ops-root / MYQUANT_OPS_ROOT 必须是绝对路径")
    ops_root = ops_root.resolve()
    entry, profile_name = ENTRIES[args.command]
    try:
        api = json.loads((ops_root / "scripts/runtime-api.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        parser.error(f"缺少 ops runtime API v1：{ops_root}；请更新相邻源码或设置 MYQUANT_OPS_ROOT ({exc})")
    source = ops_root / entry
    if (not isinstance(api, dict) or type(api.get("schema_version")) is not int
            or api["schema_version"] != 1 or not isinstance(api.get("entries"), list)
            or entry not in api["entries"] or not source.is_file()
            or not source.resolve().is_relative_to(ops_root)):
        parser.error(f"ops runtime API v1 不兼容或缺少入口：{entry}")

    command = [sys.executable, str(source), "--repo-root", str(REPO_ROOT)]
    if profile_name is not None:
        profile = REPO_ROOT / profile_name
        if not profile.is_file():
            parser.error(f"缺少本仓研究 profile：{profile}")
        command.extend(("--profile-file", str(profile)))
    try:
        return subprocess.run(
            command + remaining, cwd=REPO_ROOT,
            env={**os.environ, "PYTHONUTF8": "1"}, check=False,
        ).returncode
    except OSError as exc:
        parser.error(f"无法启动 ops 入口：{exc}")


if __name__ == "__main__":
    raise SystemExit(main())
