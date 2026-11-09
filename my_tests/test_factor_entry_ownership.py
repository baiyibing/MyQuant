"""Relocated research entries must import without BT or market-data access."""
import ast
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def test_all_factor_sources_have_no_reverse_bt_imports():
    forbidden = {"backtest", "common", "oskh_data", "oskh_factors", "oskh_core", "qlib_cost", "scripts"}
    for path in (ROOT / "myquant_factors").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = ([node.module or ""] if isinstance(node, ast.ImportFrom)
                     else [n.name for n in node.names] if isinstance(node, ast.Import) else [])
            assert not any(n.split(".")[0] in forbidden for n in names), (path, node.lineno, names)


def test_all_relocated_entries_import_with_explicit_empty_roots_and_no_reader(tmp_path):
    code = r'''
import importlib, importlib.abc, json, sys
from pathlib import Path
class BlockBT(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split('.')[0] in {'backtest','common','oskh_data','oskh_factors','oskh_core','qlib_cost','scripts'}:
            raise AssertionError('reverse dependency: ' + name)
sys.meta_path.insert(0, BlockBT())
from myquant_factors import _runtime
root = Path(sys.argv[1])
def no_reader(*a, **kw):
    raise AssertionError('reader initialized during import')
_runtime.configure_host(research_root=lambda: root, period_root=lambda p: root / p,
    parquet_root=lambda: root, reader_factory=no_reader)
manifest = json.loads(Path(sys.argv[2]).read_text())
for entry in manifest:
    module = importlib.import_module(entry['myquant_module'])
    assert callable(module.main), entry
'''
    env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    result = subprocess.run([sys.executable, "-c", code, str(tmp_path),
        str(ROOT / "examples/chip_research/entrypoint-migration.json")],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
