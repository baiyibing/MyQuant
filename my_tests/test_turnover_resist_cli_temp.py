"""TR CLI scratch files must stay outside the input lake and outlive only a call."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys
from threading import Barrier

import pytest

from myquant_factors.bridge import turnover_resist as tr


def _options(lake: Path) -> dict:
    return dict(date="20260825", data_dir=str(lake), window=1000, step=0.01,
                sort_by="circulating", free_float_policy="warn-zero",
                target_date_policy="strict", bb_ddof=1, max_grid_points=250_000)


@pytest.mark.parametrize("mode", ["success", "nonzero", "timeout", "bad_encoding"])
def test_real_cli_child_cleans_scratch_for_every_exit(tmp_path, monkeypatch, mode):
    lake = tmp_path / "行情湖"
    lake.mkdir()
    script = tmp_path / "fake_cli.py"
    script.write_text(
        "import pathlib, sys, time\n"
        "p = pathlib.Path(sys.argv[sys.argv.index('--output')+1])\n"
        "p.write_text('stock_code,stock_name,close\\n000001.SZ,平安,10.5\\n', encoding='utf-8-sig')\n"
        "mode = sys.argv[1]\n"
        "if mode == 'nonzero':\n"
        "    print('合成失败', file=sys.stderr)\n"
        "    raise SystemExit(7)\n"
        "if mode == 'timeout': time.sleep(10)\n"
        "if mode == 'bad_encoding': p.write_bytes(b'\\xff')\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PYTHONIOENCODING", "utf-8")
    monkeypatch.setattr(tr, "_find_exe", lambda: Path(sys.executable))
    run = subprocess.run
    outputs = []

    def child(cmd, **kwargs):
        output = Path(cmd[cmd.index("--output") + 1])
        outputs.append(output)
        assert cmd[cmd.index("--data-dir") + 1] == str(lake)
        assert kwargs["encoding"] == "utf-8" and kwargs["timeout"] == 300
        if mode == "timeout":
            kwargs["timeout"] = 0.1
        return run([sys.executable, str(script), mode, *cmd[1:]], **kwargs)

    monkeypatch.setattr(tr.subprocess, "run", child)
    if mode == "success":
        rows = tr._cli_compute(**_options(lake))
        assert rows == [{"stock_code":"000001.SZ", "stock_name":"平安", "close":10.5}]
    else:
        error = {"nonzero":RuntimeError, "timeout":subprocess.TimeoutExpired,
                 "bad_encoding":UnicodeDecodeError}[mode]
        with pytest.raises(error) as caught:
            tr._cli_compute(**_options(lake))
        if mode == "nonzero":
            assert "exit 7" in str(caught.value) and "合成失败" in str(caught.value)
    assert len(outputs) == 1
    assert not outputs[0].is_relative_to(lake)
    assert not outputs[0].exists()
    assert not outputs[0].parent.exists()
    assert list(lake.iterdir()) == []


def test_same_date_concurrent_calls_have_distinct_output_paths(tmp_path, monkeypatch):
    lake = tmp_path / "lake"
    lake.mkdir()
    barrier = Barrier(2)
    outputs = []
    monkeypatch.setattr(tr, "_find_exe", lambda: Path("synthetic-exe"))

    def child(cmd, **kwargs):
        path = Path(cmd[cmd.index("--output")+1])
        outputs.append(path)
        barrier.wait(timeout=10)
        path.write_text("stock_code,close\n000001.SZ,10.5\n", encoding="utf-8-sig")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(tr.subprocess, "run", child)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: tr._cli_compute(**_options(lake)), range(2)))
    assert all(rows[0]["stock_code"] == "000001.SZ" for rows in results)
    assert len(set(outputs)) == 2
    assert all(not p.exists() and not p.parent.exists() for p in outputs)
    assert list(lake.iterdir()) == []


@pytest.mark.parametrize("source", ["env", "cache"])
def test_temp_root_in_lake_is_rejected_before_any_probe_write(tmp_path, source):
    lake = tmp_path / "lake"
    lake.mkdir()
    # A fresh process matters: gettempdir() normally probes candidates by writing
    # and unlinking a file before it caches the selected directory.
    program = r'''
import os, sys, tempfile
from pathlib import Path
from myquant_factors.bridge import turnover_resist as tr
lake = Path(sys.argv[1]).resolve()
for key in ("TMPDIR", "TEMP", "TMP"):
    os.environ[key] = str(lake)
tempfile.tempdir = str(lake) if sys.argv[2] == "cache" else None
writes = []
def audit(event, args):
    if event == "open":
        path, mode, flags = args
        writing = flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
    elif event == "os.mkdir":
        path, writing = args[0], True
    else:
        return
    if writing and isinstance(path, (str, bytes)) and Path(os.fsdecode(path)).resolve().is_relative_to(lake):
        writes.append((event, str(path)))
sys.addaudithook(audit)
tr._find_exe = lambda: Path(sys.executable)
def forbidden(*args, **kwargs):
    raise AssertionError("CLI must not start")
tr.subprocess.run = forbidden
try:
    tr._cli_compute(date="20260825", data_dir=str(lake))
except ValueError as error:
    assert "outside" in str(error) and "data_dir" in str(error)
else:
    raise AssertionError("unsafe scratch root must be rejected")
assert not writes, writes
'''
    result = subprocess.run([sys.executable, "-c", program, str(lake), source],
                            capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stderr
    assert list(lake.iterdir()) == []
