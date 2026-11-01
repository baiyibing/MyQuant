# -*- coding: utf-8 -*-
"""M4-B: write_train_manifest 可单测 helper（无 full train / handler_init）。"""

from __future__ import annotations

import os
import sys
import ast
import subprocess
from pathlib import Path
from types import SimpleNamespace

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_MY_SCRIPTS = os.path.join(_ROOT, "my_scripts")
if _MY_SCRIPTS not in sys.path:
    sys.path.insert(0, _MY_SCRIPTS)

from custom_utils import TimerRecorder  # noqa: E402
from run_manifest import load_manifest, write_train_manifest  # noqa: E402


class _FakeTimer:
    def __init__(self):
        self.nodes = [{"name": "handler_init", "seconds": 1.25}, {"name": "model_fit", "seconds": 0.5}]
        self._t0 = 0.0

    # timings_from_recorder uses timeit.default_timer()-_t0; stub _t0 near now via real TimerRecorder instead


def test_write_train_manifest_with_pred_and_timer(tmp_path: Path):
    pred = tmp_path / "预测结果.csv"
    pred.write_text(
        "datetime,instrument,score\n2026-03-02,SH600000,0.1\n2026-03-02,SZ000001,0.2\n",
        encoding="utf-8",
    )
    rec = TimerRecorder()
    with rec.timer("handler_init"):
        pass
    with rec.timer("model_fit"):
        pass

    cfg = {
        "exp_name": "unit",
        "segments": {"train": ("2026-01-01", "2026-01-31"), "valid": ("2026-02-01", "2026-02-28"), "test": ("2026-03-01", "2026-03-23")},
        "topk": 10,
        "n_drop": 3,
    }
    written = write_train_manifest(
        manifests_dir=tmp_path / "manifests",
        config=cfg,
        pred_path=pred,
        timer_recorder=rec,
        data={"calendar_first": "2026-01-01", "calendar_last": "2026-03-23", "calendar_days": 50},
        git_commit_sha="unitsha",
        created_utc="2026-09-13T03:00:00Z",
        pred_rows=2,
        repo_root=_ROOT,
    )
    assert written[0].name.startswith("train_")
    man = load_manifest(written[0])
    assert man["stage"] == "train"
    assert man["config"]["topk"] == 10
    assert man["config"]["n_drop"] == 3
    assert man["config"]["segments"]["train"][0] == "2026-01-01"
    assert man["artifacts"][0]["rows"] == 2
    assert man["artifacts"][0]["md5"]
    names = [n["name"] for n in man["timings"]["nodes"]]
    assert "handler_init" in names and "model_fit" in names
    # sidecar beside pred
    assert any(p.parent == pred.parent for p in written[1:])


def test_write_train_manifest_without_pred(tmp_path: Path):
    written = write_train_manifest(
        manifests_dir=tmp_path / "manifests",
        config={"topk": 5, "n_drop": 1},
        pred_path=tmp_path / "missing.csv",
        timings={"total_seconds": 0.1, "nodes": []},
        git_commit_sha="x",
        created_utc="2026-09-13T03:01:00Z",
    )
    man = load_manifest(written[0])
    assert man["artifacts"] == []
    assert man["config"]["topk"] == 5


def _run_actual_train_manifest_phase(tmp_path: Path) -> None:
    """Execute the actual terminal phase without importing/training Qlib models."""
    source = Path(_MY_SCRIPTS) / "custom_train_backtest.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    phase, = [node for node in ast.walk(tree) if isinstance(node, ast.Try)
              and any(isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call)
                      and isinstance(stmt.value.func, ast.Name) and stmt.value.func.id == "write_train_manifest"
                      for stmt in node.body)]
    owner, = [node for node in ast.walk(tree) if isinstance(getattr(node, "body", None), list) and phase in node.body]
    index = owner.body.index(phase)
    completion = owner.body[index+1:index+3]
    assert len(completion) == 2
    pred = tmp_path / "pred.csv"
    pred.write_text("datetime,instrument,score\n2026-03-02,SZ300190,2\n", encoding="utf-8")
    namespace = dict(
        write_train_manifest=write_train_manifest, _pred_csv=str(pred), pred_df=[0],
        exp_name="unit", task={"dataset": {"kwargs": {"segments": {"test": ["2026-03-02", "2026-03-02"]}}}},
        port_analysis_config={"strategy": {"kwargs": {"topk": 5, "n_drop": 1}}},
        benchmark="SH000300", start_time="2026-03-02", end_time="2026-03-02", data_handler_config={}, rid="unit",
        exclude_filter_on=False, limit_up_filter_on=False, drop_limit_up_learn_on=False,
        limit_threshold_on=False, cli_args=SimpleNamespace(dataset_cache=False, expr_cache=False,
            handler_cache=False, tradable_universe=False, buy_state_filter=False, model="lgb"),
        _kernels=1, _parallelism={"dump_max_workers": 1}, _lgb_threads=1,
        st_filter_on=False, age_filter_on=False, return_threshold_on=False,
        D=SimpleNamespace(calendar=lambda **kw: []), _portana_metrics={},
        base_dir=str(tmp_path), t_rec=None, _git_prov={"git_commit": "unit"}, timer=lambda: 1.0, r_start=0.0,
    )
    imports = [node for node in tree.body if isinstance(node, ast.Import)
               and all(alias.name in {"os", "sys"} for alias in node.names)]
    code = compile(ast.Module(body=[*imports, phase, *completion], type_ignores=[]), str(source), "exec")
    exec(code, namespace)


def test_train_terminal_phase_requires_manifest_before_completion(tmp_path: Path, capsys):
    _run_actual_train_manifest_phase(tmp_path)
    assert "训练与回测完成！" in capsys.readouterr().out
    manifest, = (tmp_path / "manifests").glob("train_*.json")
    assert load_manifest(manifest)["artifacts"][0]["rows"] == 1


def test_train_required_manifest_failure_stops_completion(tmp_path: Path):
    blocked = tmp_path / "manifests"
    blocked.write_bytes(b"existing file must remain intact")
    code = '''
import sys
from pathlib import Path
from types import SimpleNamespace
from qlib.workflow import QlibRecorder
from my_tests.test_train_manifest import _run_actual_train_manifest_phase
root = Path(sys.argv[1])
recorder = SimpleNamespace(start_exp=lambda **kw: None,
    end_exp=lambda status: (root / "recorder-status.txt").write_text(status, encoding="utf-8"))
with QlibRecorder.start(recorder):
    _run_actual_train_manifest_phase(root)
'''
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    result = subprocess.run([sys.executable, "-c", code, str(tmp_path)], cwd=_ROOT,
                            env=env, capture_output=True, text=True, encoding="utf-8", check=False)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "Failed to write train manifest:" in result.stderr
    assert "Required train manifest could not be written" in result.stderr
    assert "训练与回测完成！" not in result.stdout
    assert "策略回测完成！" not in result.stdout
    assert (tmp_path / "recorder-status.txt").read_text(encoding="utf-8") == "FAILED"
    assert blocked.read_bytes() == b"existing file must remain intact"
