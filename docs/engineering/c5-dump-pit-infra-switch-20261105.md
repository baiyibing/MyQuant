# C5: financial PIT dump host caller

MQ base: `b0cdb421f49e109e892c4a192b4791695b383f37` (`origin/master`, C1 #128
already merged). This is an independent PR against `master`; it does not stack
on C3 #129 or C4 #130. Open as a draft only; hotmail owns merging.

The merged MyQuant-infra `origin/main` tip was confirmed with `git ls-remote`
as **`3c377e9718e811112993579b6d91a603395db699`** on 2026-11-06. Its existing
`myquant_infra.adapters.qlib_data.pit` exports `DumpPitData` and `main`, and its
CLI exposes `dump-pit`. The optional C1 pin in `requirements-infra.txt` remains
unchanged, as do normal public-CI dependencies.

## Host boundary and CLI

`qlib_scripts/dump_pit.py` now follows `dump_bin.py`: it parses with the host
`cli.pit_parser`, serializes through `_infra_qlib.arguments`, and delegates to
`_infra_qlib.adapter("pit").main`. `_qlib_cli.py` mirrors the pinned PIT parser
so help and usage errors need only the standard library. Tests compare the
declarations, including aliases, required paths, types, and defaults, to infra.

`DumpPitData` remains available through a lazy attribute export of the actual
infra class. The old host implementation is removed; there is no second dumper
or fallback. Importing the host entry does not load infra, Qlib, pandas, Fire,
or training code. Using the feature without infra raises the existing helper's
`InstallError`, with this installation hint:

```sh
python -m pip install -r requirements-infra.txt
```

Both `csv_path` and `qlib_dir` remain explicit, required caller inputs. There
are no lake or provider defaults to resolve. Example with caller-prepared CSVs
and a separate scratch provider:

```sh
python qlib_scripts/dump_pit.py \
  --csv-path /tmp/c5-input/SH600000.csv --qlib-dir /tmp/c5-provider \
  --interval quarterly --max-workers 1 --date-column-name available_date

python -m myquant_infra.adapters.qlib_data dump-pit \
  --csv-path /tmp/c5-input/SH600000.csv --qlib-dir /tmp/c5-provider \
  --interval quarterly --max-workers 1 --date-column-name available_date
```

The CLI uses the pinned argparse interface, including `--interval quarterly`
or `annual`, `--overwrite`, and underscore aliases such as `--csv_path`.
It no longer uses Fire's method dispatch. Python callers retain the infra
constructor's `freq` and `dump(interval=..., overwrite=...)` interface.
Help also works through `python -m qlib_scripts.dump_pit --help`.

Infra's default Qlib `I/I/d/I` record and uint32 NA pointer are used without
importing or initializing `qlib.config.C`. Callers needing existing custom
`record_type` or `na_index` can pass those through the exported infra class;
the host introduces no record formats. Training, strategies, and train wiring
remain in MQ; this caller does not import `train_wiring`.

## Semantic lock: report end is not availability

**`date` is the caller-supplied data-available date, NEVER the report end.**
The CSV must explicitly supply it in `date`, or in the column selected by
`--date-column-name` / `date_column_name`. The host forwards the selected
column unchanged to infra. Neither layer shifts a calendar or infers an
availability date from a reporting period, report end, or another CSV column.
The caller is responsible for supplying the correct available date.

`period` is `YYYYQQ` for quarterly reports (quarters `01` through `04`), or
`YYYY` for annual reports. For example:

```csv
date,period,value,field,report_end
2024-05-17,202401,1.25,roe,2024-03-31
```

The written record contains availability **20240517** and period **202401**.
It is unavailable as of 2024-03-31 and 2024-05-16. The same applies to an annual
2023 report ending 2023-12-31 and becoming available on 2024-05-17. An extra
`report_end` column is never substituted for missing availability. Missing or
empty availability raises before provider output is created.

Tests cover both intervals, the default and a configured date column, dashed
and compact dates, host CLI delegation, the exported Python class, and infra's
`dump-pit` dispatcher. Exact data/index bytes and independent as-of reads pin
the availability date, unchanged reporting period, and revision chain. An
out-of-order second publication remains dated 2024-06-03. Source CSV bytes
remain unchanged. Infra's existing update, overwrite, and allocated-year
limits are unchanged by this caller switch.

## Offline validation and public CI

Validation used `/workspace/vanna312/bin/python` and an isolated `git archive`
of the exact pin on `PYTHONPATH`; the shared environment's installed infra
revision differs, and was not changed. All inputs and providers are temporary.
Network connections are refused in the tests; stdlib-only subprocess probes
use `-S`, run outside the checkout, and write nothing.

```sh
PYTHONPATH=/tmp/c5-infra-3c377e9-kb3w69eu \
  /workspace/vanna312/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_c5_dump_pit_infra_switch.py tests/test_c1_qlib_infra_switch.py

PYTHONPATH=/tmp/c5-no-infra-54ugh0e3 \
  /workspace/vanna312/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_c5_dump_pit_infra_switch.py tests/test_c1_qlib_infra_switch.py
```

| Suite | With exact infra pin | Without infra |
| --- | --- | --- |
| C5 and existing C1 regression | **126 passed** | **79 passed, 47 skipped** |

For reproducibility, create the first temporary tree with `git archive` of
the pin from an infra checkout. The second temporary tree contains only this
`sitecustomize.py`, which blocks infra before pytest starts without modifying
the shared installation:

```python
import importlib.abc
import sys

class NoInfra(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "myquant_infra" or fullname.startswith("myquant_infra."):
            raise ModuleNotFoundError("optional infra blocked", name=fullname)

sys.meta_path.insert(0, NoInfra())
```

The public `data-staging` CI job now includes the C5 test file and still does
not install private infra. Infra-backed tests use `pytest.importorskip`;
host import/help, option forwarding, and actionable missing-dependency checks
continue to run. Ruff checks for the touched Python files and `git diff --check`
also pass. Hosted CI status belongs to the draft PR and is separate from these
local counts.

## Rollback and scope

Rollback is **revert this PR**, restoring the previous host PIT implementation
and removing the C5 parser/tests/CI addition. **Keep the C1 optional pin** in
`requirements-infra.txt`; C5 does not alter it. C3/C4 remain independent.

This is a library move and call-site switch only. Validation performs no real
lake writes, production provider rewrite, cutover/deploy, Redis access, QMT
login/orders, training start, or secret output. No merge is performed here.
