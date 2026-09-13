# -*- coding: utf-8 -*-
"""任务 1：host_env setdefault 语义（子进程；不覆盖已有值）。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_MY_SCRIPTS = _ROOT / "my_scripts"
_PYTHON = sys.executable


def _run_probe(env: dict[str, str], code: str) -> str:
    full_env = os.environ.copy()
    # Drop keys under test so parent pollution does not leak; then apply overrides.
    full_env.pop("MLFLOW_ALLOW_FILE_STORE", None)
    full_env.pop("MLFLOW_DISABLE_AGENT_HINT", None)
    full_env.update(env)
    full_env["PYTHONPATH"] = str(_MY_SCRIPTS) + os.pathsep + full_env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [_PYTHON, "-c", code],
        env=full_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def test_host_env_setdefault_applies_defaults():
    out = _run_probe(
        {},
        "import host_env; import os; "
        "print(os.environ.get('MLFLOW_ALLOW_FILE_STORE'), "
        "os.environ.get('MLFLOW_DISABLE_AGENT_HINT'))",
    )
    assert out == "true 1"


def test_host_env_setdefault_does_not_override_preset():
    out = _run_probe(
        {
            "MLFLOW_ALLOW_FILE_STORE": "false",
            "MLFLOW_DISABLE_AGENT_HINT": "0",
        },
        "import host_env; import os; "
        "print(os.environ.get('MLFLOW_ALLOW_FILE_STORE'), "
        "os.environ.get('MLFLOW_DISABLE_AGENT_HINT'))",
    )
    assert out == "false 0"
