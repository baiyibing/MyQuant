# C1: qlib day, minute, and ETF production callers

MQ base: `c725808e05acd73702c35f5b44723a2e60019807` (`origin/master`, fetched
before implementation). C1 uses the merged MyQuant-infra `origin/main` commit
**`3c377e9718e811112993579b6d91a603395db699`**, verified against `origin/main`
after infra PR #60 merged. This replaces the initial C1 pin
`4dad4c5d11bad0f001715248ee354f34a547e4f8`. MQ C2 PR #124 has independently
merged; its scanner implementation and tests are unchanged by this fix.

## Installation and boundary

`requirements-infra.txt` is optional and pins `myquant-infra[qlib-data]` by its
full Git commit. Install it in the production-script environment:

```sh
python -m pip install -r requirements-infra.txt
```

The normal `requirements.txt` and public CI dependency installation stay
unchanged. Imports, CLI help, configuration construction, and skipped CSV
preflights require no infra. Production calls load adapters lazily and missing
infra raises an actionable `InstallError` naming `requirements-infra.txt`.
Unrelated missing backend dependencies retain their original errors. Adapter tests
use `pytest.importorskip`; host import/CLI compatibility tests also run with
stdlib-only stubs and test missing-package behavior without site packages.
The CI staging job includes the new host tests without installing infra.

These twelve `qlib_scripts` modules delegate to the same-named module under
`myquant_infra.adapters.qlib_data`:

- Daily: `refresh_mydata`, `merge_archive_and_csv`, `patch_index_data`, `dump_bin`.
- Minute: `refresh_mydata_1min`, `stage_1min_from_lake`, `build_mydata_1min`,
  `qlib_1min_increment_receipt`.
- ETF: `stage_etf_daily_from_lake`, `build_etf_qlib`.
- Checks: `check_dump_bin`, `check_data_health`.

MQ retains only CLI/path compatibility, default configuration, and the
whole-lake/daily-provider boundary bindings. Numeric transforms, staging,
calendar/bin IO, production gates, swap, and receipts execute in infra.
Existing production helper imports forward to the adapters on access; MQ's
stdlib configuration objects retain host defaults. CLI declarations mirror the
pin, with tests checking their options and configuration fields against infra.
Patch adapter functions when spying on their execution.

Feeder, training, handlers, and strategies remain in MQ.
`qlib_scripts/csv_float_scan.py` and its scanner tests are unchanged.
Daily refresh explicitly injects the existing host scanner through infra's
`--csv-validator qlib_scripts.csv_float_scan:scan_csv_dir` interface. This keeps
C1 independent of C2's scanner cutover and avoids another scanner implementation.
The legacy `run_csv_scan_preflight` helper keeps C2's formatted host report and
returns before loading either scanner or production infra when skipped. Explicit
custom validators continue through the adapter's existing validation contract.

## CLI compatibility

Direct `python qlib_scripts/<script>.py ...` invocation still works, including
from another working directory. Help requires neither infra nor configured lake roots.
Underscore dump options and checker invocations such as
`check_data_health.py check_data --csv_path ...` and
`check_dump_bin.py --qlib_dir ... --csv_path ... check` remain accepted.
Checker exit statuses follow the pinned adapters: findings return nonzero.

MQ still resolves `OSKH_SOURCE_PARQUET_ROOT`, the product-specific overrides in
`my_scripts/data_root.py`, and `OSKH_QLIB_CSV_DIR`. It passes resolved paths to
infra; no production lake root is embedded in a caller or test. Existing home
provider/archive and Windows staging defaults remain host policy. Daily staging
and the new provider default to dated siblings of the selected daily provider.
The conventional Windows 7-Zip executable remains a host fallback.

Minute callers supply the daily provider explicitly to infra; `--daily-dir`
can override MQ's home default. ETF supplies both protected providers;
repeatable `--protected-dir` can supply an explicit test or deployment pair.
`build_mydata_1min --skip-stage` continues to need only a prepared staging batch,
without lake environment variables; it calls infra's existing dump helper after
the adapter's path checks. Daily refresh keeps whole-lake path isolation before
delegation and keeps index readback enabled by default. The additive
`--skip-verify-patch` option permits qlib-free offline validation. Normal readback
continues to use the host's separately installed qlib version.

Standalone index patching now defaults its managed scratch root to
`my_data_index_staging` beside the selected provider; `--staging-dir` overrides
it. Infra cleans its temporary child. Child production commands use
`python -m myquant_infra.adapters.qlib_data.<module>` from the selected Python
environment. Daily/ETF full dump workers remain eight; minute workers clamp to
eight. No orchestrator switches to `dump_update`.

The pinned adapter retains its documented publication limits: minute updates
are atomic per field, not across the entire provider; ETF wipe occurs before
staging/gates when explicitly requested. This PR does not change those semantics.

## Offline validation

Tests use temporary input/output trees and copied synthetic fixtures. New
production tests protect source bytes and daily/minute sentinels and exercise
real daily merge/dump/index patch/gates/swap, minute build/append/no-op receipts,
and ETF staging/gates/dump. They require no qlib, lake service, Redis, QMT,
login, orders, secrets, or network. BLAS/Arrow test threads are bounded to one;
the adapter's eight-worker daily/ETF contract is retained.

The shared Python environment initially contained a different infra revision.
Validation used an isolated `git archive` of exactly the pinned commit on
`PYTHONPATH`, without changing that shared installation:

```sh
PYTHONPATH=/tmp/c1-qlib-infra-3c377e9 /workspace/vanna312/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_c1_qlib_infra_switch.py \
  tests/test_build_etf_qlib.py tests/test_etf_daily_qlib_offline_smoke.py \
  tests/test_stage_1min_from_lake.py tests/test_stage_etf_daily_from_lake.py \
  tests/test_train_etf_smoke.py tests/test_ql11_1min_increment_receipt_harness.py \
  my_tests/test_dump_bin_highfreq.py my_tests/test_merge_archive_and_csv.py \
  my_tests/test_parallelism_knobs.py my_tests/test_patch_index_data.py \
  my_tests/test_refresh_mydata.py my_tests/test_refresh_mydata_1min.py \
  my_tests/test_refresh_1min_daily_boundary.py my_tests/test_refresh_mydata_1min_noop.py \
  my_tests/test_refresh_path_isolation.py
```

The original switch validation was **321 passed, 6 skipped**. After the lazy-load
fix, the existing production regression files above (excluding the expanded C1
file) give **276 passed, 6 skipped** (Windows-only path cases) at the new pin.

The C1 branch predates C2, so the C2 regression is run in a temporary integration
tree with the unchanged `origin/master` versions of `csv_float_scan.py` and
`my_tests/test_csv_float_scan_host.py` overlaid. No C2 branch history or files in
this worktree are rewritten. The requested command is:

```sh
PYTHONPATH=/tmp/c1-qlib-infra-3c377e9 /workspace/vanna312/bin/python -m pytest -q -p no:cacheprovider \
  my_tests/test_csv_float_scan_host.py tests/test_c1_qlib_infra_switch.py
```

At the new pin this pair gives **109 passed**. With all `myquant_infra` imports
blocked it gives **79 passed, 30 skipped**, reproducing the public-CI dependency
boundary. Separate `python -S` smoke checks import
`refresh_mydata` and `dump_bin`, exercise both skipped CSV preflight flags, and
assert that no infra import was attempted. No live refresh was invoked.

## Rollback

For a pin-only rollback, restore
`4dad4c5d11bad0f001715248ee354f34a547e4f8` in `requirements-infra.txt`, retain
the lazy-load CI fix, and rerun the offline suites. This changes only the optional
package revision; it does not rewrite any provider or lake data.

For full C1 rollback, revert this PR, then restore the prior optional infra pin or
unpin/uninstall infra in the script environment. This MQ base had no `requirements-infra.txt`,
so the original state is an absent file and no C1 dependency. If another
independent switch has since introduced an infra pin, restore that deployment's
prior pin rather than removing its dependency.

Rollback restores the MQ implementations and prior CLI paths. It does not
rewrite data or undo a separately authorized production refresh; this PR and
its validation perform no live refresh. C2 and other cutovers remain independent.
Open-only draft PR against `master`; hotmail owns merging. Do not merge here.
