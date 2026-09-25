# Track B: step-local plan hash cache

2026-09-23. Research comparison only; Grok CLI 4.7 review and human/qlib merge remain pending.

`_step` previously called `content_hash(plan)` for every candidate validation,
approved/unapproved sell validation, and selected buy. The completed plan is
read-only within `_step`; the cache path computes the same canonical hash once
per nonempty step and passes it to `_intent`. Empty steps need no plan hash.
The binding expires on return. No object-id/global cache, cross-day parallelism,
canonicalization changes, session hash changes, quantity identity changes, or
BASE_MQ/contract rotation is involved. Every candidate is still validated.

2026-09-25 update: **both** rule-intents and portfolio CLIs now default to the
cache. `--cache-plan-hash` remains accepted as an explicit-on no-op;
`--no-cache-plan-hash` restores the slow reference path, which re-hashes the full
plan per candidate. Freeze is unchanged. See the
[performance study and full-data A/B merge gate](../../../performance/2026-09-25-joint-return-plan-hash-cache.md).
Python API defaults remain `cache_plan_hash=False`; callers can select
`cache_plan_hash=True` on `generate_plans`, `build_portfolio`, or `run_snapshot`.

Both CLI artifact writers stamp metadata with
`research_acceleration: TRACK_B_PLAN_HASH_CACHE_PENDING_REVIEW` when the cache
is enabled, so the stamp now appears by default. `--no-cache-plan-hash` does not
add it; use the opt-out on both CLIs with unstamped inputs to reproduce an
unstamped slow-path chain. Existing upstream stamps are preserved.
Rule metadata carries that stamp through freeze into the portfolio manifest.
Pure generation/build APIs return identical products without adding metadata;
callers packaging those products must preserve the research designation.
The stamp does not assert a successful review or full production regeneration.

## Measurement

Linux Bot VM, Python 3.13.5, existing 80-instrument synthetic test fixture,
50/5, both P-BASE and P-CHASE. No production data, bars, eligibility, or clocks
were created or fetched. Each row is a fresh subprocess, one timed sample;
fixture/import setup is excluded. Wall includes generation, serial `_step`
replay, and canonical product/plans and stable intent CSV serialization; it
excludes full CLI disk I/O, freeze, and P-REF bootstrap. RSS is process peak,
including imports/setup. Small-sample differences include scheduling noise.

| Days | Path | Generation s | Combined wall s | CPU/wall | Peak RSS MiB |
|---|---|---:|---:|---:|---:|
| 1 | Unmodified 1c1fe43 | 0.1064 | 0.2031 | 1.000 | 32.52 |
| 1 | Current slow reference | 0.1188 | 0.2224 | 1.000 | 31.00 |
| 1 | B cache | 0.0228 | 0.0465 | 1.000 | 31.00 |
| 5 | Unmodified 1c1fe43 | 0.1610 | 0.3193 | 1.000 | 34.27 |
| 5 | Current slow reference | 0.1560 | 0.3115 | 1.000 | 32.14 |
| 5 | B cache | 0.0562 | 0.1116 | 1.000 | 32.04 |
| — | A CLOCK_PATCH | Already shipped elsewhere; wall/CPU/RSS unavailable here | — | — | — |

B combined speedup versus original: **4.37x (1 day), 2.86x (5 days)**.
Versus current reference: 4.79x and 2.79x. Raw hashes, candidate counts and
metrics are in `benchmark.jsonl`. The first day has 80 candidates per arm;
later pairs have 0/30. One-day original cProfile: 0.168 s total, `_intent`
0.118 s cumulative (260 calls), `json.dumps` 0.091 s cumulative across all
callers (~54% total). This confirms a useful repeated-serialization hotspot
on fixtures, not the predicted >=90% production share. First-day whole-plan
hashes fall from 260 to 2 per generation/replay pass.

Reproduce with the repo test dependencies installed:

```sh
PYTHONPATH=tests:. python3 tests/benchmark_joint_return_hash_accel.py
python3 -m pytest -q tests/test_joint_return_hash_accel.py tests/test_joint_return_rule_intents.py tests/test_joint_return_freeze_snapshot.py tests/test_joint_return_portfolio.py tests/test_joint_return_intent_clocks.py tests/test_joint_return_control_only.py
```

The benchmark loads the actual portfolio/rule-intents source from `1c1fe43`
using `git show` for its original baseline. It asserts all three paths produce
matching SHA-256s for canonical plans, complete generation products (including
reference histories/final states), and stable CSV intents. Differential pytest
also directly compares bytes for 50/5, 20/3, 10/3 in full/control-only modes.
Tests cover same-object mutation between steps (fresh hash), empty steps,
unselected invalid candidates, freeze/CLI research-stamp propagation, and
portfolio CLI intent bytes. Canonical/session helpers remain untouched.

## Identity and limits

- Plans/intents business fields and identities are byte-identical on these
  fixtures. No tolerated numerical differences or research-stamp changes to
  plans/intents. Reference histories/final states match exactly.
- CLI `metadata.json` and downstream manifest metadata intentionally gain the
  research stamp. Separate output locations/run IDs also change their existing
  provenance paths/IDs; those are not business-field drift. Rule-manifest
  reference-state content matches; full rule-manifest bytes are not asserted
  across different output directories because they embed output paths.
- Production ~5k-candidate counts and >=90% hashing share are not independently
  verified here. Track P must confirm those. If confirmed, the plan-hashing
  component changes from candidates × plan-size to one plan-size per step;
  remaining validation, deep copies, serialization, and disk writes still cost
  time. No full-regen wall-time promise follows from these small fixtures.
- No 20-day fixture run: the existing fixture supplies five sessions. No
  synthetic extension is presented as real sessions. No 4090 regen was run.
- The cache assumes the current read-only use of `plan` within `_step`; future
  in-step mutation would require revisiting it. Grok review and production
  profiling remain merge/rollout evidence, not completed work in this PR.

Validation: 246 targeted tests passed. EXIT:0 for Track B implementation and
fixture acceptance; production performance and review remain pending.
