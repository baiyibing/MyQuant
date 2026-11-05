# C6: signal-bundle and run-manifest infra callers

This is an independent PR against MQ `master`, based directly on
`b0cdb421f49e109e892c4a192b4791695b383f37` (merged C1 #128). It contains no
C3 #129, C4 #130, or C5 #131 history and does not require those PRs. Open as a
draft only; hotmail owns merging.

MyQuant-infra `main` was checked with `git ls-remote` on 2026-11-06 (Asia/Shanghai)
and remains **`3c377e9718e811112993579b6d91a603395db699`**. The existing C1-owned
line in `requirements-infra.txt` already pins that commit and is unchanged.

## Call-site boundary and installation

`myquant_contract.signal_bundle` delegates its three existing operations to
`myquant_infra.contracts.signal_bundle`: `build_signal_bundle`,
`canonical_json_bytes`, and `validate_signal_bundle`. The host `SCHEMA` identity
and packaged `schema/signal-bundle-1.schema.json` remain unchanged. A parity
test checks the schema asset byte-for-byte against the pin. CSV verification
remains the consumer's responsibility; the facade preserves its original
validator signature.

`my_scripts/run_manifest.py` delegates canonical JSON, config hashes, MD5,
artifact fingerprints, manifest build/validation/serialization/IO, git capture,
and unknown timings to `myquant_infra.artifacts.provenance`. Existing public
function names and signatures remain available, including bare `run_manifest`
imports from script entry points. The host `ManifestError` remains importable
without infra; shared `ManifestError` exceptions are translated to that class
with their message and cause retained.

MQ retains recorder snapshots and the existing train/export/sweep metadata
assembly helpers. These only describe caller-supplied artifacts, metadata and
timings. Training, strategy and signal selection remain in MQ. Neither facade
imports `train_wiring`; provenance does not start training, select signals,
calculate fees, execute orders, or discover market inputs. No BT/C7/B8 switch
is included.

Infra requires an explicit git `repo_root`. The host passes the caller's
supplied root or, when omitted, the MQ checkout containing `run_manifest.py`
(`Path(__file__).resolve().parents[1]`). Changing the process working directory
cannot change that default source repository. Infra retains its own explicit-root
requirement, five-second git timeout and lock-free status invocation. Startup
git capture still survives a later HEAD/branch change when passed to the
manifest helper. The shared pin's existing path/basename and nonnegative artifact
row guards apply; these do not change canonical bytes or hashes of valid v1 data.

Both infra modules are stdlib-only. Install the campaign's optional dependency
in the feature environment using the existing pin:

```sh
python -m pip install -r requirements-infra.txt
```

Public imports and access to existing public names require no infra. Imports
do not even attempt to load it. Feature use loads it lazily and an absent
package raises `ModuleNotFoundError` naming the install command above. Unrelated
backend import failures keep their original error. There is no host fallback
canonicalization, hashing or contract validation implementation.

## v1 preservation evidence

The identities remain `myquant.signal-bundle/1` and `myquant.run-manifest/1`.
Signal canonical JSON still uses sorted keys, compact separators, literal UTF-8,
no BOM, no non-finite numbers and exactly one trailing LF, including hash inputs.
Row order is preserved; `calendar_id` hashes sorted unique target sessions.
`bundle_sha256` excludes only the outer `bundle_sha256` field.

Run config canonical JSON retains its separate v1 behavior: sorted keys, compact
separators, literal UTF-8, **no trailing LF**, and the original JSON numeric
behavior. `config_hash` excludes only the top-level `config_hash`, keeping any
nested field of that name. Written MQ manifests retain their pretty JSON bytes
and final LF. No hash normalization has been added.

[`tests/fixtures/c6/v1-golden.json`](../../tests/fixtures/c6/v1-golden.json)
freezes original MQ outputs from the base commit: four bundles, four configs,
all four manifest stages and three metadata-helper manifests. The fixture
README describes capture provenance. Tests compare both host and infra against
fixed bytes and digests, validate persisted fixture bundles without mutation,
and compare manifest write/load/sidecar results. Representative fixed hashes:

| Case | SHA-256 |
| --- | --- |
| Empty bundle | `9f21203c5e6163e4dc8d0d2463fe7b3ec854ecb1b0c7791dbb172811be625abc` |
| Prediction, unproven | `8c26c35aab1dd4c1c11968ef97e0f6761b5b9aa5ef6821b13ae0563dbc72f58e` |
| Declared availability, unsorted rows | `ba5d739213b51ade97c61d6f077aa74f77d565f115a6947ddc5ae8bd2f86fe78` |
| Identity policy | `e5e4400c91dde1d64d4c96570edaddd2638387744786b3d4962622507d2a7c10` |
| Empty config | `44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a` |
| Config with segments | `b655607f771afd4a5b0abf779a31f7de4c3de9a3778dec339f4b192006db37a8` |
| Unicode/numeric config | `9912d1f202269d29a5e3cfc1ebf8aa3dfbb73c13b5a584538e0fe4d90e2bc453` |

No API gap or v1 hash mismatch was found at the pin.

## Hermetic validation and public CI

The exact pinned source was exported from the clean local infra checkout with
`git archive` into `/tmp/c6-infra-3c377e9` and supplied on `PYTHONPATH`, without
changing the shared Python environment. The installed signal core and provenance
source bytes also match the pin; the existing file-path CLI test deliberately
clears `PYTHONPATH` and uses that installed copy.

Run the scoped suite from the MQ checkout:

```sh
PYTHONPATH=/tmp/c6-infra-3c377e9 /workspace/vanna312/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_c6_signal_bundle_infra_switch.py \
  my_tests/test_signal_bundle_contract.py my_tests/test_signal_bundle_validate_negative.py \
  my_tests/test_run_manifest.py my_tests/test_export_signal_bundle_flag.py \
  my_tests/test_git_provenance_startup.py my_tests/test_train_manifest.py \
  my_tests/test_export_manifest.py my_tests/test_summarize_model_runs.py \
  my_tests/test_predict_extended.py my_tests/test_handler_frame_cache.py \
  my_tests/test_sweep_ranking.py my_tests/test_sweep_live_adapter.py \
  my_tests/test_export_daily_pool.py
```

Result: **240 passed, 2 skipped**. The two skips require Qlib handler-reload and
Qlib recorder-failure integration; Qlib is absent from this environment. The
metadata and terminal-phase tests execute without training. Manifest tests use
recorder-shaped test objects rather than importing plotting/training packages.

For the same suite without private infra, place this `sitecustomize.py` in a
temporary directory and use that directory alone on `PYTHONPATH` in place of
the infra archive:

```python
import importlib.abc
import sys

class NoInfra(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "myquant_infra" or fullname.startswith("myquant_infra."):
            raise ModuleNotFoundError("C6 public-CI simulation", name=fullname)

sys.meta_path.insert(0, NoInfra())
```

Result: **72 passed, 170 skipped**. Infra-backed tests use fixture-scoped
`pytest.importorskip`; import/help compatibility, parser, selection and missing
dependency tests remain runnable. Separate `python -S` subprocess tests exclude
site packages entirely, assert no infra import attempt on public imports, check
actionable feature errors and verify that no output is written. New C6 tests
refuse network connections and all artifact IO uses temporary synthetic files.
No lake writes, production Redis, QMT login/orders, deployment or training runs
occurred. No secrets were printed and no Cloud Agents were used.

`ruff check myquant_contract my_scripts/run_manifest.py
tests/test_c6_signal_bundle_infra_switch.py` and `git diff --check` pass.
Public CI installs no private infra: the existing `data-staging` job now includes
the new C6 host-boundary tests; the main job already runs the adjusted `my_tests`.
The optional pin is not added to public `requirements.txt` or CI installs.

## Rollback

Revert this PR. Keep the existing C1 `requirements-infra.txt` pin at
`3c377e9718e811112993579b6d91a603395db699`. Reverting restores the host
implementations and tests; no data migration or provider rewrite is needed.
Rollback is independent of C3–C5. This PR performs no production cutover and
must not be merged by the implementation agent.
