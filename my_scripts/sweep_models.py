"""Sequential DatasetH model sweep. One process per learner; continue on failure.

Handler cache is shared when windows / universe / gates match. Each model still
fits, predicts, and backtests. Example::

    python sweep_models.py --models ridge,lasso,gru --handler-cache ^
        --train 2020-01-01:2024-12-31 --valid 2025-01-01:2025-12-31 ^
        --test 2026-01-01:2026-09-14 --topk 50 --n-drop 5
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = _SCRIPT_DIR.parent
TRAIN = _SCRIPT_DIR / "custom_train_backtest.py"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Sweep --model names through custom_train_backtest")
    parser.add_argument(
        "--models",
        required=True,
        help="Comma-separated model names (configs/models/<name>.yaml)",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python executable (default: current interpreter)",
    )
    parser.add_argument(
        "--summary",
        default=None,
        help="Append-only text summary (default: manifests/model_sweep_<UTC>.txt)",
    )
    args, passthrough = parser.parse_known_args(argv)
    models = [m.strip() for m in str(args.models).split(",") if m.strip()]
    if not models:
        parser.error("no models")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    summary = Path(args.summary) if args.summary else REPO_ROOT / "manifests" / f"model_sweep_{stamp}.txt"
    summary.parent.mkdir(parents=True, exist_ok=True)
    summary.write_text(f"sweep {stamp} models={','.join(models)}\n", encoding="utf-8")
    rc_all = 0
    for name in models:
        print(f"==== START {name} {datetime.now().isoformat(timespec='seconds')} ====", flush=True)
        cmd = [args.python, "-u", str(TRAIN), "--model", name, *passthrough]
        proc = subprocess.run(cmd, cwd=str(_SCRIPT_DIR))
        line = f"\n==== {name} exit={proc.returncode} ====\n"
        with summary.open("a", encoding="utf-8") as fh:
            fh.write(line)
        print(line, end="", flush=True)
        if proc.returncode != 0:
            rc_all = proc.returncode
    print(f"SWEEP_DONE summary={summary}", flush=True)
    return rc_all


if __name__ == "__main__":
    raise SystemExit(main())
