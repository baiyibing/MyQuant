# ETF daily qlib local offline smoke

2026-11-03: separate [P11 isolated host E3/E4 acceptance](operations/evidence/p11-etf-host-acceptance-2026-11-03/README.md) is now available. This page continues to describe only the historical offline-fixture slice and its limits.

PATH: `myquant-etf-daily-qlib-smoke-harden`.

This slice hardens Linux pytest and the local offline fixture smoke for the ETF
daily qlib dump path. It exercises real staging, calendar subset and VWAP basis
gates, protected-provider refusal (including a POSIX symlink or Windows
junction), and `dump_all` arguments with eight workers. Wipe and dump are spies;
the dry-run CLI only prints the plan. Test outputs stay under pytest's temporary
directory, and network/subprocess calls are blocked in the offline smoke tests.

The [infra fixture](https://github.com/baiyibing/MyQuant-infra/blob/main/tests/adapters/qlib_data/conftest.py)
now generates the synthetic lake in a temporary directory for each test.
MyQuant removes the unused duplicate generator and committed parquet files.
The fixture has matching front/none trees, four symbols, and a sparse 31-weekday
calendar spanning 2020-01-02 through 2026-10-13, with no Wind samples. It is
intentionally too small for `etf_full`; the #107 `ETF_FULL_*` and training split
constants remain unchanged.

With sibling source checkouts, pytest, pandas, numpy, and pyarrow available,
run the producer tests in infra and the training acceptance tests in MyQuant:

```bash
cd ../MyQuant-infra
python -m pytest -q \
  tests/adapters/qlib_data/test_stage_etf_daily_from_lake.py \
  tests/adapters/qlib_data/test_build_etf_qlib.py \
  tests/adapters/qlib_data/test_etf_daily_qlib_offline_smoke.py \
  --tb=short
cd ../MyQuant
python -m pytest -q tests/test_train_etf_smoke.py --tb=short
```

On another Linux or M5 environment, replace the interpreter path with its local
Python. No qlib binary dump, network access, or LightGBM training is required.

Passing this smoke does **not** claim host E3 real-lake dump/readback acceptance
or E4 Alpha158 IC on a production provider. Those remain separate host work.

**Hard NO:** no Wind lake writes; no mutation of `E:\stock_data`, `F:\`, or
production `OSKH_SOURCE_PARQUET_ROOT` contents; no writes or wipes of stock
`~/.qlib/qlib_data/my_data` or `my_data_1min`. Do not call `refresh_mydata.py`,
`patch_index_data.py`, or `dump_update`. No Cloud Agents, push, PR, or merge is
part of this slice.
