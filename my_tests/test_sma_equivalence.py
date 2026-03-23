import os
import sys
import unittest

import numpy as np
import pandas as pd


_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_MY_SCRIPTS = os.path.join(_ROOT, "my_scripts")
sys.path.insert(0, _MY_SCRIPTS)

try:
    # Best-effort import. Some environments may not have qlib fully installed
    # (e.g., missing `setuptools_scm`), so we fall back to a pure-kernel test.
    from custom_ops import SMA  # type: ignore  # noqa: E402
except Exception:  # pragma: no cover
    SMA = None


def sma_reference(values: np.ndarray, N: int, M: int) -> np.ndarray:
    """Reference implementation that matches the original Python loop semantics."""
    values = np.asarray(values, dtype=np.float64)
    n = len(values)
    sma = np.full(n, np.nan, dtype=np.float64)

    alpha = M / N
    beta = 1.0 - alpha

    first_valid = None
    for i in range(n):
        if not np.isnan(values[i]):
            sma[i] = values[i]
            first_valid = i
            break

    if first_valid is None:
        return sma

    for i in range(first_valid + 1, n):
        if np.isnan(values[i]):
            sma[i] = np.nan
        else:
            sma[i] = alpha * values[i] + beta * sma[i - 1]

    return sma


def sma_vectorized_kernel(values: np.ndarray, N: int, M: int) -> np.ndarray:
    """Vectorized implementation that matches the updated production SMA semantics."""
    values = np.asarray(values, dtype=np.float64)
    n = len(values)
    sma = np.full(n, np.nan, dtype=np.float64)

    valid_mask = ~np.isnan(values)
    if not valid_mask.any():
        return sma

    first_valid = int(valid_mask.argmax())
    if first_valid + 1 < n:
        tail_invalid_mask = ~valid_mask[first_valid + 1 :]
        if tail_invalid_mask.any():
            first_nan_rel = int(tail_invalid_mask.argmax())
            end = first_valid + 1 + first_nan_rel  # exclusive
        else:
            end = n
    else:
        end = first_valid + 1

    v = values[first_valid:end]  # no NaNs
    m = len(v)

    alpha = M / N
    beta = 1.0 - alpha

    if m == 1:
        sma[first_valid] = v[0]
    elif beta == 0.0:
        sma[first_valid:end] = v
    else:
        pow_b = beta ** np.arange(m, dtype=np.float64)
        w = np.zeros(m, dtype=np.float64)
        w[1:] = alpha * v[1:]

        inv_pow_b = beta ** (-np.arange(m, dtype=np.float64))
        s = np.cumsum(w * inv_pow_b)
        sma[first_valid:end] = pow_b * (v[0] + s)

    return sma


class TestSMAEquivalence(unittest.TestCase):
    def test_sma_nan_semantics(self):
        # Edge cases + typical cases
        cases = [
            ("all_nan", [np.nan, np.nan, np.nan, np.nan]),
            ("leading_nan", [np.nan, np.nan, 1.0, 2.0, 3.0]),
            ("no_nan", [1.0, 2.0, 3.0, 4.0]),
            ("nan_after_first_valid", [np.nan, 2.0, np.nan, 3.0, 4.0]),
            ("nan_middle", [1.0, 2.0, np.nan, 4.0]),
            ("first_valid_not_at_zero", [np.nan, 5.0, 6.0, np.nan, 7.0]),
        ]

        # Include both beta==0 (M==N) and typical beta!=0
        params = [
            (3, 1),  # used in COST-KDJ (SMA(x,3,1))
            (5, 5),  # alpha=1, beta=0
            (10, 3),
        ]

        for case_name, arr in cases:
            values = np.asarray(arr, dtype=np.float64)

            for N, M in params:
                with self.subTest(case=case_name, N=N, M=M):
                    out = sma_vectorized_kernel(values, N, M)
                    ref = sma_reference(values, N, M)

                    ref_nan = np.isnan(ref)
                    out_nan = np.isnan(out)
                    self.assertTrue(np.array_equal(ref_nan, out_nan))

                    valid_mask = ~ref_nan
                    if valid_mask.any():
                        np.testing.assert_allclose(out[valid_mask], ref[valid_mask], rtol=1e-12, atol=1e-12)

        # If qlib is importable, additionally validate the production SMA op directly on one case.
        if SMA is not None:  # pragma: no cover
            values = np.asarray([np.nan, 5.0, 6.0, np.nan, 7.0], dtype=np.float64)
            series = pd.Series(values, index=pd.RangeIndex(len(values)))

            class _DummyFeature:
                def __init__(self, s: pd.Series):
                    self._s = s

                def load(self, instrument, start_index, end_index, *args):
                    return self._s

            sma_op = SMA(_DummyFeature(series), 3, 1)
            out = sma_op._load_internal("DUMMY", 0, len(values) - 1).to_numpy(dtype=np.float64)
            ref = sma_reference(values, 3, 1)
            self.assertTrue(np.array_equal(np.isnan(out), np.isnan(ref)))
            np.testing.assert_allclose(out[~np.isnan(ref)], ref[~np.isnan(ref)], rtol=1e-12, atol=1e-12)


if __name__ == "__main__":
    unittest.main()

