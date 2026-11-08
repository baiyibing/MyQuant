# C7 — ST / industry consume helper switch

> 历史迁移记录：2026-11-08 的 [#136](https://github.com/baiyibing/MyQuant/pull/136) 已改为直接消费 infra 源码。下文的兼容入口、可选安装、旧 pin 与测试命令记录当时状态；当前安装与调用以 [README](../../README.md#环境搭建) 和[数据产制手册](../../my_docs/提示词-qlib-bin刷新.md)为准。

This independent C7 change starts directly from the supplied MyQuant
`origin/master` base `143004340cc30277cb659bd43ced65b770f89894`. It adds no
C3–C6 feature-branch commits and requires no additional C3–C6 changes. Their
implementations and the C1-owned optional dependency line stay unchanged.

Infra pin: **`3c377e9718e811112993579b6d91a603395db699`**, already present in
`requirements-infra.txt`. The ST, industry and `lake.paths` source trees at
this pin match infra tip `ced981b1973dd36e24295e8ee95f19c91f85d5ba` byte for byte
(`git diff` over those paths is empty). No pin bump, default dependency change,
data migration or production cutover is included. This PR is draft/open-only;
hotmail owns any eventual merge.

## Delegation and compatibility shim

`my_scripts/st_status.py` lazily delegates public code conversion and default
ST index/as-of reads to the existing
`myquant_infra.reference_data.st.readers` APIs. Infra receives an explicit
parquet path. The host retains these compatibility rules:

- **`asof=None`:** load the host daily index, choose `sorted(by_date)[-1]`,
  then call infra `load_st_codes_asof(daily_path, chosen)` with that explicit
  date. An empty index returns an empty set without calling infra as-of.
  Infra's own API still rejects `None`; no new infra API is invented.
- **Hit-only observation dates:** inspection of the supplied MQ base revealed
  an additional skew. MQ drops dates whose rows are all False; infra retains
  them with empty sets. The host filters empty entries from the infra index
  and chooses the latest host observation date at or before an explicit
  target before delegating. For example, True on January 6 followed by all-False
  January 7–8 still yields the January 6 set in MQ, including with `asof=None`.
  Calling infra directly for January 8 yields an empty set. This preserves
  existing MQ eligibility/as-of behavior; it does not change infra's rule.
- **Coverage:** `coverage_fallback_qlib` and the entire `use_coverage=True`
  branch stay host-local, including their legacy conversion, JSON loading,
  absent-sidecar behavior, unknown-end/static codes and snapshot fallback.
  They work without infra. Infra `load_st_coverage` is evidence-only and
  cannot replace this promotion policy. Default reads never read coverage
  or promote `fallback_static`; the as-of helper keeps ignoring both legacy
  coverage arguments. `buy_eligibility` continues to request
  `use_coverage=False` through its unchanged call site.

On supported ST matrices the returned host sets and date policy are preserved.
The default reader exposes infra's existing validation errors for malformed
schemas/dates; it adds no data repair or alternate-file fallback. An as-of
lookup with hits reads the parquet twice, once to resolve host dates and once
inside the existing infra API. No caching or mutable-file snapshot guarantee
is added.

`my_scripts/data_root.py` keeps all `OSKH_*` environment reads, precedence,
explicit argument handling and `DataRootError` checks on the host. Only
`resolve_st_daily`, `resolve_sw_l1_root` and `resolve_sw_l1_map` delegate their
matching joins to `myquant_infra.lake.paths` (`st_daily_path`, `sw_l1_root`,
`sw_l1_map_path`). Infra receives resolved `Path` arguments, with
`must_exist=False` for file joins so the host can preserve its own missing-file
exception and message. Missing environment still raises `DataRootError`
before importing infra. The SW map resolver accepts only `sw_l1_map.csv`,
with no alternate drive or `wind_l1_map.csv`/exports fallback.

Public package-qualified and bare-script imports work without infra, pandas
or Qlib. Calling an infra-backed facade with infra missing raises
`ModuleNotFoundError` mentioning the full pin and
`python -m pip install -r requirements-infra.txt`. Unrelated missing backend
dependencies retain their original exception. No host fallback is cached for
these methods. The optional pin already includes the pandas/pyarrow dependencies
needed by the ST reader through its existing `qlib-data` extra.

## Stay-host scope

- Environment resolution, non-ST/industry path helpers, and consume-file
  existence errors remain host responsibilities.
- `ranking_neutralize.load_industry_map` stays host-local. It accepts
  `code_qlib`/`code_gildata`, `sw_l1`/`wind_sw_l1`, and its existing validation
  and code-normalization policy. Infra's map readers have different column
  precedence, canonical-code output and error behavior. Only the honest
  industry path twins are switched; no parser API is fabricated.
- Wind/Gildata/ST writers and merge scripts remain outside this consume-only
  change. Writer ownership stays with OSkhQuant1.3.
- `train_wiring`, strategy, trading gates, orders, 订单 outbox, broker shim and
  QMT sessions are unchanged. No training module is imported into infra.

## Offline validation

The pinned repository was exported with `git archive` into the temporary
directory `/tmp/c7-infra-3c377e9-lb57lrd2` and supplied on `PYTHONPATH`. The
shared Python environment was not modified. The equivalent archive command is:

```sh
git -C /workspace/mqi-coding/infra-base archive \
  3c377e9718e811112993579b6d91a603395db699 |
  tar -x -C /tmp/c7-infra-3c377e9-lb57lrd2
```

Scoped suite, from the C7 worktree (Bash):

```sh
c7_tests=(
  tests/test_c7_st_industry_infra_switch.py
  my_tests/test_st_status.py
  my_tests/test_data_root.py
  my_tests/test_buy_eligibility.py
  my_tests/test_c4_tradable_universe_infra_switch.py
  my_tests/test_ranking_neutralize.py
  my_tests/test_export_topk_buy_state_sidecar.py
  my_tests/test_export_next_day_pool.py
  my_tests/test_export_daily_pool.py
)
OSKH_RUNTIME_SKIP_SECRETS_YAML=1 PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=/tmp/c7-infra-3c377e9-lb57lrd2 \
/workspace/vanna312/bin/python -m pytest -q -p no:cacheprovider "${c7_tests[@]}"
```

With pin: **158 passed, 1 skipped**. The skipped module
`my_tests/test_buy_eligibility.py` requires Qlib, which is absent here. C7 also
tests its existing `BuyEligibilityFilter` file consumer with Qlib/strategy
import stand-ins: only ST lookup/date behavior is exercised, with no strategy
execution or Qlib integration claim.

For the same suite without infra, a temporary
`/tmp/c7-no-infra-xl0bowr9/sitecustomize.py` blocks even the installed package:

```python
import importlib.abc
import sys

class NoInfra(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "myquant_infra" or fullname.startswith("myquant_infra."):
            raise ModuleNotFoundError("C7 public-CI simulation", name=fullname)

sys.meta_path.insert(0, NoInfra())
```

```sh
OSKH_RUNTIME_SKIP_SECRETS_YAML=1 PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=/tmp/c7-no-infra-xl0bowr9 \
/workspace/vanna312/bin/python -m pytest -q -rs -p no:cacheprovider "${c7_tests[@]}"
```

Without infra: **105 passed, 54 skipped**. Skips cover optional C7, C4 and C6
features plus the same absent-Qlib module. Host coverage, unset-env errors,
public import and missing-package hint checks still execute. Existing tests
that require the optional features use fixture-scoped `importorskip`.

The C7 tests refuse network connections, use temporary synthetic files only,
and verify code/as-of parity, explicit last-day forwarding, dense/empty
matrices, coverage isolation, host-only fallback and explicit path behavior.
Separate `python -S` subprocesses test both import spellings and dependency
failures without site packages; they assert that no output files are created.
Nearby tests also read the repository's existing industry CSV fixture.
No lake writes, QMT login/orders, external data calls, secrets, CloudAgent,
deployment or merge occurred.

`/workspace/vanna312/bin/python -m ruff check` passes for both changed host
modules, the new C7 test and modified nearby test files. `git diff --check`
passes. Public CI's existing `data-staging` job includes the C7 test without
installing private infra. Fast Lane/CI success is not claimed while pending.

## Rollback

Revert this PR. Keep the C1-owned `requirements-infra.txt` line at
`3c377e9718e811112993579b6d91a603395db699`; it was not bumped. Rollback is
independent of C3–C6 and requires no data migration or lake changes.
