# C2 CSV float validation host switch — 2026-11-05

`qlib_scripts/csv_float_scan.py` now delegates the scanner, report formatters,
and legacy public constants to `myquant_infra.data_validation.csv_float`.
`refresh_mydata.run_csv_scan_preflight` keeps its existing import, warning
report, and `RefreshError` gate for fatal cells. There is no host scanner
fallback: a missing backend prevents validation rather than reporting success.

The host keeps its `--csv-dir` CLI, Chinese help text, report output, and exit
codes: `0` for clean or warning-only CSVs and `2` for fatal cells. Both entry
forms remain supported:

```bash
python qlib_scripts/csv_float_scan.py --csv-dir /path/to/offline/csv
python -m qlib_scripts.csv_float_scan --csv-dir /path/to/offline/csv
```

The host does not expose infra's additional `--fatal-columns` option. Fatal
fields remain `open`, `high`, `low`, `close`, `volume`, `amount`, `factor`, and
`adjclose`; `winratio` and `vwap` remain warnings. Identifier columns remain
excluded. The scanner reads CSVs without changing their contents. One inherited
infra difference is intentional: a missing/non-directory CSV path raises
`NotADirectoryError` instead of producing the old empty, successful report.
The host propagates read/parse errors and dependency errors.

## Optional private installation and pin

Validated MQ base: `8ec68989aefb057a873d8e98ccea9834f734d92a`.
Infra pin: **`7d48c4e310f9636cad9c3e544db1766025db4e3c`**, the `main` tip checked
on 2026-11-05. Infra [PR #59](https://github.com/baiyibing/MyQuant-infra/pull/59)
and [PR #60](https://github.com/baiyibing/MyQuant-infra/pull/60) were both still
open when checked, so no newer merged tip was selected.

MQ has no existing `requirements-infra.txt` convention. Install explicitly in
an authorized host environment with access to the private repository:

```bash
python -m pip install 'myquant-infra[data-validation] @ git+https://github.com/baiyibing/MyQuant-infra.git@7d48c4e310f9636cad9c3e544db1766025db4e3c'
```

Use the host's existing Git authentication; do not embed credentials in the
requirement. `requirements.txt`, `pyproject.toml`, and public CI dependency
installation stay unchanged. Importing the host module or requesting `--help`
does not import the backend. Accessing scanner exports or running validation
requires the optional package and gives an installation-document pointer if
the backend is absent. Unrelated backend dependency failures retain their
original error.

## Hermetic verification

```bash
/workspace/vanna312/bin/python -m pytest -q -p no:cacheprovider \
  my_tests/test_csv_float_scan.py \
  my_tests/test_csv_float_scan_host.py \
  my_tests/test_refresh_mydata.py \
  my_tests/test_refresh_path_isolation.py
```

`test_csv_float_scan.py` uses temporary CSVs (clean, fatal, and warning-only,
including `-1.#J`, `-1.#IND`, `1.#QNAN`, and case-insensitive `1.#inf`), verifies
unchanged input bytes, and runs both CLI entry forms. These real-backend tests
use `pytest.importorskip` when the private package is unavailable. Only the two
real-scanner preflight tests in `test_refresh_mydata.py` similarly skip; other
refresh tests continue to run.

`test_csv_float_scan_host.py` always runs with scoped in-memory backend stubs
or blocked imports. It checks legacy export delegation, CLI status/output,
help and argument errors without infra, actionable missing-package failures,
fatal/warning preflight behavior, and explicit preflight skips. Stubs never
become a runtime fallback. No test fetches packages or uses network services,
configured providers, live lake writes, Redis, QMT, or orders.

Recorded results on 2026-11-05:

| Environment | Result |
| --- | --- |
| Installed scanner verified byte-for-byte against the infra pin | 127 passed, 3 skipped |
| Same targets with all `myquant_infra` imports blocked by a process-local import finder | 109 passed, 6 skipped |

The three baseline skips require Windows case aliases. The no-infra run adds
one skipped real-backend module and the two real-scanner preflight cases;
stubbed host/preflight checks still execute. `git diff --check` also passed.

## Rollback

Revert the C2 commit titled
`feat(validation): thin-wrap csv_float_scan to myquant-infra (C2)` with
`git revert <C2-commit-sha>`. This restores the standalone scanner and original
tests without changing default dependencies. For a targeted emergency restore
in a separate change, recover the scanner from the recorded MQ base:

```bash
git restore --source=8ec68989aefb057a873d8e98ccea9834f734d92a -- qlib_scripts/csv_float_scan.py
```

The optional infra installation can remain for other consumers; the restored
scanner does not use it. Do not bypass validation with `--skip-csv-scan` as a
substitute for rollback. C1 qlib dump, C3–C7, OSkhQuant, and BT are outside
this change. The PR stays open for hotmail to merge.
