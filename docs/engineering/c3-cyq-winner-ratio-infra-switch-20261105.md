# C3: CYQ winner-ratio feeder host switch

`my_scripts/build_winner_ratio.py` now delegates manual builds to the existing
`myquant_infra.derived_data.cyq.cli.main`. Computation and publication have one
implementation in infra; the host retains only dependency-free argument help,
lazy compatibility exports, and an optional-install error. No host kernel or
provider-opening fallback remains.

This is an **independent PR against `master`**, based on
`b0cdb421f49e109e892c4a192b4791695b383f37`. C1 #128 is already merged in that
base; no second C1 implementation or unmerged stack is included. The PR is
open-only and draft; hotmail owns merging.

## Dependency and API boundary

`requirements-infra.txt` is unchanged from C1, including its comments and line:

```text
myquant-infra[qlib-data] @ git+https://github.com/baiyibing/MyQuant-infra.git@3c377e9718e811112993579b6d91a603395db699
```

On 2026-11-06, `git ls-remote` confirmed infra `origin/main` still points to
that SHA and MQ `origin/master` to the base above. Validation uses a separate
`git archive` of the exact infra SHA on `PYTHONPATH`, leaving the shared
installed package unchanged.

The existing `qlib-data` extra supplies NumPy, pandas, and parquet support for
an injected provider. Local qlib reads use MQ's separately source-pinned qlib
installation described in `requirements.txt`; C3 does not replace it with the
infra `qlib` extra's released pyqlib. No extra is required by this switch.
Infra's existing `cyq-jit` extra remains an optional acceleration choice;
without numba, the sole infra kernel supports pure Python.

Only `FeederConfig` is loaded from the CYQ public package. The host loads
`compute_winner_ratio`, `run`, and `NoOutputError` from `.feeder`, the CLI from
`.cli`, and legacy numerical helpers from `._kernel`, on access. These are
existing APIs at the pin. The infra feeder calls
`myquant_infra.adapters.qlib_data.provider.open_local_provider` when a provider
is not injected. No new provider API, `data_root` copy, or local bin reader is
introduced. Unknown module attributes raise `AttributeError` without loading
infra. Compatibility exports refer to infra objects; patch kernel constants
in the infra kernel module, rather than assigning them on the host wrapper.

## Operator compatibility

The old flags `--test`, `--window`, `--step`, `--workers`, `--out`, `--shares`,
and `--codes` remain accepted. Direct-script invocation from another working
directory, module invocation, import, and `--help` remain available. Public
help needs neither private infra nor NumPy, pandas, qlib, home paths, or lake
configuration. Feature use without infra fails with the
`python -m pip install -r requirements-infra.txt` hint; it never computes a
second local implementation.

Two paths are now explicit, matching the pinned infra CLI:

- `--provider-uri` is required. The former `~/.qlib/qlib_data/my_data` default
  is removed. Infra checks the supplied local provider; it does not download it.
- Supply either `--out FILE` or `--output-root CONTAINER`. The host no longer
  discovers an output via `OSKH_SOURCE_PARQUET_ROOT`/`data_root`. Operators may
  resolve a path with the existing host helper and pass it explicitly. Infra's
  existing lake helper owns the canonical output-root filename.

`--kernels` explicitly controls qlib feature workers, default **1**;
`QLIB_KERNELS` is no longer consulted for this feeder. Compute workers remain
**8**, lookback **1000** trading positions, step **0.01**, shares **free**.
`--shares circ` and case-insensitive comma-separated code filtering continue
through infra. Invalid config/dependency/IO errors exit 2; no valid rows exit
3; success exits 0. Progress/error prose follows infra.

Examples below are manual operator commands, not actions run by this PR:

```sh
python my_scripts/build_winner_ratio.py --help
python my_scripts/build_winner_ratio.py \
  --provider-uri /explicit/local/daily-provider \
  --test 2026-01-01:2026-09-14 \
  --out /explicit/derived/cyq_winner_ratio_daily_2026.parquet \
  --workers 8 --kernels 1 --shares free
python -m my_scripts.build_winner_ratio \
  --provider-uri /explicit/local/daily-provider \
  --test 2026-01-01:2026-09-14 --output-root /explicit/parquet-container
```

## Numerical and publication contract

The authoritative frozen contract is the
[pinned infra CYQ README](https://github.com/baiyibing/MyQuant-infra/blob/3c377e9718e811112993579b6d91a603395db699/myquant_infra/derived_data/cyq/README.md).
C3 delegates it without reimplementing the recurrence:

- Prices use the provider's back-adjusted close/high/low. Traded shares are
  `$amount / $adjclose`, never `$volume`. Free capital is `$netcsfree` in
  shares; circ capital is `$basiccurhold * 10000`. Turnover clips to `[0, .999]`.
- The triangular grid caps at 250000 points and widens its step when needed.
  First-day weighting, invalid-day freezing, the minimum ten history rows,
  inward calendar snapping, and the single initial warmup remain in infra.
- Output columns are exactly `stock_code`, `date`, `winner_ratio`, without an
  index. Winner values are float64 and in `[0, 1]`. Provider code spelling and
  naive calendar dates are retained.
- Infra writes `output.with_suffix('.tmp.parquet')`, then `os.replace` for
  whole-table replacement. A smaller capture span replaces the old span.
  Source/output overlap guards apply before publication. Callers must serialize
  builds to the same output; the existing feeder adds no multi-writer lock.
- `--output-root` retains
  `cyq_winner_ratio/cyq_winner_ratio_daily_2026.parquet`, including for other
  capture years; `--out` supplies the full filename. C3 does not rename products.

## Hermetic validation and public CI

The touched/new tests use a twelve-day in-memory qlib-shaped provider, temporary
provider/output trees, and sentinel bytes. Network connection attempts fail.
The integration fixture bypasses optional JIT initialization to avoid cache
writes; real computation and parquet publication still execute in pinned
infra. No real provider or lake is read or written. Public subprocess checks
use `python -S` and an empty `PYTHONPATH`, proving stdlib-only import/help and
an actionable missing-infra failure from an unrelated temporary directory.

The six existing numerical tests now use `pytest.importorskip` for infra and
exercise its actual kernel through the host aliases. The wide-grid test
patches the kernel's constant directly. The qlib-init contract drops the
removed local initialization site; C3 integration checks explicit kernel
forwarding and default 1 at `open_local_provider`, including an ignored
`QLIB_KERNELS=99` environment value. Other qlib-init sites retain their checks.

Run from MQ using `/workspace/vanna312/bin/python`:

```sh
PYTHONPATH=/tmp/c3-cyq-infra-3c377e9 OPENBLAS_NUM_THREADS=1 \
  /workspace/vanna312/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_c3_cyq_infra_switch.py my_tests/test_build_winner_ratio.py \
  my_tests/test_qlib_kernels_contract.py
```

| Suite | With exact pinned infra | Without infra |
| --- | --- | --- |
| Three touched/new test files above | **50 passed** | **24 passed, 21 skipped** |
| Above plus C1 and CSV scanner regressions below | **159 passed** | **103 passed, 51 skipped** |

The regression command adds `tests/test_c1_qlib_infra_switch.py` and
`my_tests/test_csv_float_scan_host.py` to the same invocation. For the
without-infra runs, `PYTHONPATH=/tmp/c3-cyq-noinfra` loads this temporary
`sitecustomize.py` before pytest (other installed dependencies remain usable):

```python
import sys
from importlib.abc import MetaPathFinder

class NoInfra(MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'myquant_infra' or fullname.startswith('myquant_infra.'):
            raise ModuleNotFoundError('private infra blocked for public-CI validation', name=fullname)

sys.meta_path.insert(0, NoInfra())
```

A skipped numerical module counts as one skip, so totals differ between the
two dependency modes. `git diff --check` and Python compilation also pass.
The existing public `data-staging` job now includes the C3 host suite without
installing private infra; backend cases skip through `importorskip`. The
existing `my_tests` CI invocation covers the legacy numerical and qlib kernel
contract files. No private dependency or secret is added to CI. Local tests
use an injected provider; a real pyqlib bin readback was not run.

## Scope evidence and rollback

The only runtime file changed is `my_scripts/build_winner_ratio.py`. Training,
feeder-train, handlers, feature wiring, models, blacklist/age policy, stock
selection, strategy, and orders remain in MQ and are untouched. Calibration
scripts and `diag_cyq_increment.py` are untouched. The host wrapper imports only
stdlib modules; there is no `train_wiring` import. Git's changed-file list is
limited to that wrapper, three tests, this note, and the CI test-list addition.

No Cloud Agents, lake writes, production cutover/deploy, scheduler enablement,
Redis changes, QMT login/orders, secrets output, or training start occurred.
Synthetic parquet replacement was confined to pytest temporary directories.
C3 is independent of disclosure/A14/A15 and starts none of C4-C7, B8, or
A7/A8/A9/A17; vendor QMT winner/chips truth remains separate.

Rollback is **revert this C3 PR**. The optional requirements line/extras/comments
were not changed, so the prior C1-only pin line shown above already remains in
place. If an operator separately changed that line, restore the prior
`myquant-infra[qlib-data]` line at `3c377e9718e811112993579b6d91a603395db699`.
Do not revert or stack another C1 copy. Rollback restores the host feeder and
its old CLI defaults without lake rewrites, Redis changes, or deployment; it
does not undo a separately authorized data build. This PR performs no such build.
