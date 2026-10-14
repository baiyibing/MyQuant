# -*- coding: utf-8 -*-
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "my_scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "my_scripts"))

from qlib_scripts.build_etf_qlib import BuildEtfError  # noqa: E402
from train_etf_smoke import (  # noqa: E402
    acceptance_ic,
    assert_etf_provider,
    finite_corr,
    in_segment_label_mask,
)


def test_cross_boundary_label_is_excluded():
    calendar = pd.bdate_range("2024-01-01", periods=6)
    # 段只到第 3 个交易日。T=第 2 天的 +1/+2 会落到段外。
    dates = list(calendar[:4])
    mask = in_segment_label_mask(dates, calendar, str(calendar[0].date()), str(calendar[2].date()))
    assert mask.tolist() == [True, False, False, False]


def test_finite_corr_rejects_empty_and_non_finite():
    assert finite_corr([1.0, np.nan], [1.0, 2.0]) == (None, 1)
    ic, n = finite_corr([1.0, 2.0, 3.0], [1.0, 2.0, 4.0])
    assert n == 3
    assert ic is not None and np.isfinite(ic)


def test_acceptance_ic_drops_cross_boundary_rows():
    calendar = pd.bdate_range("2024-01-01", periods=8)
    pred = np.arange(6, dtype="float64")
    label = pred * 2
    report = acceptance_ic(pred, label, calendar[:6], calendar, str(calendar[0].date()), str(calendar[3].date()))
    assert report["kept"] < report["rows"]
    assert report["n"] == report["kept"]
    assert report["ic"] is not None and np.isfinite(report["ic"])


def test_provider_name_and_alias(tmp_path: Path):
    stock = tmp_path / "my_data"
    etf = tmp_path / "my_data_etf"
    nested = stock / "my_data_etf"
    stock.mkdir()
    etf.mkdir()
    nested.mkdir()
    with pytest.raises(BuildEtfError):
        assert_etf_provider(stock, protected=(stock,))
    with pytest.raises(BuildEtfError):
        assert_etf_provider(nested, protected=(stock,))
    assert assert_etf_provider(etf, protected=(stock,))
