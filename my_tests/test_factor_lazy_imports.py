"""A consumer of one small capability need not import the research stack."""
import importlib
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("statement", [
    "import myquant_factors; import myquant_factors._runtime",
    "from myquant_factors.chip.bands import compute_tr_bb_columns; assert callable(compute_tr_bb_columns)",
    "from myquant_factors import compute_tr_bb_columns; assert callable(compute_tr_bb_columns)",
    "from myquant_factors.bridge.turnover_resist import bridge_mode; assert callable(bridge_mode)",
])
def test_light_capabilities_do_not_import_training_numba_or_plotting(statement, tmp_path):
    code = '''
import importlib.abc, sys
blocked = {'qlib', 'numba', 'matplotlib', 'seaborn', 'torch', 'my_scripts',
           'backtest', 'common', 'oskh_data', 'oskh_factors'}
class BlockHeavy(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split('.')[0] in blocked:
            raise AssertionError('unrequested capability loaded: ' + name)
sys.meta_path.insert(0, BlockHeavy())
''' + statement + "\nassert not (blocked & set(sys.modules))\n"
    env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    result = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env,
                            capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("name,module", [
    ("ChipFactor", "cyq"), ("calc_curpdf", "cyq"), ("calc_cumpdf", "cyq"),
    ("calc_dist_chips", "cyq"), ("calc_adj_turnover", "distribution_of_chips"),
    ("calc_triang_pdf", "distribution_of_chips"), ("calc_uniform_pdf", "distribution_of_chips"),
    ("calc_distribution_of_chips", "turnover_coefficient_ops"),
    ("calc_rc", "turnover_coefficient_ops"), ("calc_roll_cyq", "turnover_coefficient_ops"),
    ("rolling_frame", "utils"), ("rolling_windows", "utils"),
    ("classify_tr_bb_signal", "chip.bands"), ("compute_tr_bb_columns", "chip.bands"),
    ("adapt_columns", "chip.core"), ("compute_crossday_turnover_resistance", "chip.core"),
    ("bb_position", "price_bb"), ("DivergenceSignal", "weekly_macd_divergence"),
    ("detect_weekly_macd_divergence", "weekly_macd_divergence"),
])
def test_existing_public_objects_keep_identity_and_are_discoverable(name, module):
    import myquant_factors
    expected = getattr(importlib.import_module("myquant_factors." + module), name)
    assert getattr(myquant_factors, name) is expected
    assert getattr(myquant_factors, name) is expected
    assert name in dir(myquant_factors) and name in myquant_factors.__all__


def test_unknown_capability_raises_attribute_error():
    import myquant_factors
    with pytest.raises(AttributeError, match="no attribute"):
        getattr(myquant_factors, "missing_factor_capability")


@pytest.mark.parametrize("name", [
    "cyq", "distribution_of_chips", "turnover_coefficient_ops", "utils",
    "chip", "price_bb", "weekly_macd_divergence",
])
def test_existing_module_exports_keep_identity(name):
    import myquant_factors
    assert getattr(myquant_factors, name) is importlib.import_module("myquant_factors." + name)


def test_star_import_keeps_the_existing_public_surface():
    namespace = {}
    exec("from myquant_factors import *", namespace)
    assert len([name for name in namespace if not name.startswith("_")]) == 26
    assert callable(namespace["compute_tr_bb_columns"])
    assert namespace["cyq"].ChipFactor is namespace["ChipFactor"]
