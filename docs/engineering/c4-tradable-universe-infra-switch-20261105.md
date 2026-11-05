# C4: tradable-universe transform host switch

This is an independent draft PR against MyQuant `master`, based on
`b0cdb421f49e109e892c4a192b4791695b383f37` (merged C1 #128). It is not stacked
on C3 #129 and changes none of C3's files. MyQuant-infra `origin/main` was
verified on 2026-11-06 at **`3c377e9718e811112993579b6d91a603395db699`**.
The existing C1-owned `requirements-infra.txt` pin and extras remain unchanged.

## Transform and policy boundary

`my_scripts/build_tradable_universe.py` delegates `read_calendar`,
`drop_excluded`, `shift_start_for_age`, and `build` directly to the existing
`myquant_infra.adapters.qlib_data.universe` APIs at that pin. The host no longer
contains the membership filter, age kernel, or provider IO implementation.
There is no second transform or silent fallback when infra is unavailable.

The generic host API requires every consumer input:

```python
from my_scripts.build_tradable_universe import build, read_calendar

stats = build(
    "/tmp/provider",
    exclusions=set(),  # Explicit, already resolved by the caller; empty is allowed.
    age_days=60,
    calendar=read_calendar("/tmp/provider/calendars/day.txt"),
    asof="2026-01-16",
)
```

Generic wrappers do not import `train_wiring`, `buy_eligibility`, `st_status`,
or Qlib. The CLI calls the separate host `resolve_exclusions` function, which
retains `train_wiring.EXCLUDE_STOCKS_DEFAULT`, supplemental exclusion-file
parsing, and `st_status.load_st_codes_asof` as the host policy authorities.
Only this resolver lazily imports those host policy modules. The resolved
exclusion set, chosen age, explicit calendar, snapshot label, and provider path
are then injected into infra. `buy_eligibility.earliest_buy_date` is no longer
used by this transform; the age calculation runs in infra.

ST selection remains the existing host reader's behavior: select its most recent
available ST set at or before the requested as-of date; use no coverage sidecar
or fallback inputs. `asof` labels the caller's resolved exclusion snapshot;
infra does not select ST data, truncate the calendar, or certify point-in-time
inputs. Static and supplemental exclusions remain unioned with host ST results.
As before, an absent supplemental file adds no codes. Training, strategy,
`train_wiring.py`, `buy_eligibility.py`, and `st_status.py` are untouched.

## Operator and Python API changes

Install the optional private package only in an authorized script environment:

```sh
python -m pip install -r requirements-infra.txt
```

Imports and `--help` work without infra, Qlib, or pandas. Feature use without
infra raises `InstallError` with that install command before input IO or host
policy imports. Other missing backend dependencies retain their original errors.
The CLI's host policy resolver still requires the existing MQ/Qlib dependencies.

Provider home discovery has been removed. `--qlib-dir`, `--calendar`, and
`--asof` must all be explicit. `--st-asof` is retained as an alias for `--asof`;
there is no automatic last-matrix-date default. The host CLI still defaults
`--age-days` to 60 and always supplies the value explicitly to infra.

For a prepared temporary provider, for example:

```sh
python my_scripts/build_tradable_universe.py \
  --qlib-dir /tmp/provider \
  --calendar /tmp/provider/calendars/day.txt \
  --asof 2026-01-16 --age-days 60 \
  --extra-exclude-file /tmp/extra-exclusions.txt \
  --st-daily-file /tmp/st_daily.parquet
```

`read_calendar` now takes the calendar **file**, not a provider directory.
Python `build` takes keyword-only `exclusions`, `age_days`, `calendar`, and
`asof`; its former host-policy arguments belong to `resolve_exclusions`/the
CLI. There are no other repository call sites to migrate. The return stats
retain `total`, `dropped_st`, `kept`, and `path`, with infra's `asof` label added.

The only output is `<provider>/instruments/all_tradable.txt`. Infra retains
`require_explicit_path` and its `require_disjoint` checks against `all.txt`,
`calendars`, and `features`, including resolved symlink overlap. Filtering is
case insensitive and preserves order. Starts before the calendar remain as-is;
exhausted/empty calendars yield `9999-12-31`, minute clock suffixes survive
valid shifts, and inverted ranges are not clipped. No new publication or
atomic-write guarantees are added to the pinned implementation.

## Hermetic validation and public CI

The new suite is in `my_tests/test_c4_tradable_universe_infra_switch.py`, already
collected by public CI's existing `pytest` job. No workflow edits or private
dependency installation were added. Infra-backed cases use fixture-scoped
`pytest.importorskip`; host import, help, missing-package behavior, forwarding,
and policy-resolution cases run without infra. The three existing universe
checks in `my_tests/test_buy_eligibility.py` now also skip without infra; its
other host-policy checks are unchanged.

Tests use only temporary provider trees, explicit calendars, synthetic ST
parquet, and injected exclusions. Network connections and home-provider
discovery are blocked in the new suite. Fresh-process checks forbid imports
of `train_wiring`, `buy_eligibility`, `st_status`, and Qlib through the real
generic infra path. Tests assert unchanged source/calendar/feature bytes,
symlink disjoint guards, rejection without overwriting output, empty exclusion
sets, age overflow, minute timestamps, and host-owned ST selection.

The shared Python installation contains another infra revision. Validation
uses an isolated `git archive` of exactly `3c377e9` at
`/tmp/c4-universe-infra-3c377e9` on `PYTHONPATH`, without changing the shared
installation. To simulate public CI without infra, a process-local import
finder in `/tmp/c4-without-infra/sitecustomize.py` raises `ModuleNotFoundError`
for all `myquant_infra` imports, including subprocesses.

```sh
PYTHONPATH=/tmp/c4-universe-infra-3c377e9 \
  /workspace/vanna312/bin/python -m pytest -q -p no:cacheprovider \
  my_tests/test_c4_tradable_universe_infra_switch.py

PYTHONPATH=/tmp/c4-without-infra \
  /workspace/vanna312/bin/python -m pytest -q -p no:cacheprovider \
  my_tests/test_c4_tradable_universe_infra_switch.py
```

| Scope | With infra at the pin | Without infra |
| --- | --- | --- |
| New C4 suite | 39 passed | 22 passed, 17 skipped |
| C4 + unchanged ST reader + existing C1 caller suite | 138 passed | 91 passed, 47 skipped |

The combined regression command appends `my_tests/test_st_status.py` and
`tests/test_c1_qlib_infra_switch.py` to the commands above. Ruff on the host
script and new C4 suite, and `git diff --check`, also pass.

Local collection of the existing `my_tests/test_buy_eligibility.py` file is
limited by this environment's missing Qlib. An isolated attempt to install
the repository's Qlib source pin `79633dd9` also could not build because the
environment has no C++ compiler; the shared Python environment was not changed.
That file is not included in the passing counts above. Public CI already
installs the Qlib source pin and collects both this file and the new suite;
only its three universe checks require optional infra. The new C4 suite tests
the real pinned transform without Qlib, and separately tests the unchanged host
ST reader with synthetic data. No training was started.

## Rollback and release scope

Rollback is **revert this PR**. No pin, extras, or pin comments were changed,
so retain C1's optional dependency as-is. Rollback is independent of C3 and
restores the previous host implementation and CLI defaults. It performs no
provider/lake rewrite, Redis operation, deployment, scheduler change, training
run, QMT login, or order. Validation performs none of those operations.

This PR is open-only and draft against `master`; hotmail owns merging. Do not
merge it here. No C5/C6/C7, eligibility-policy migration, or production cutover
is included.
