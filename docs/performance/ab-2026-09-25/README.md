# Full-data A/B kit: plan-hash cache default flip (PR #102)

Gate for merging PR #102 ([report](../2026-09-25-joint-return-plan-hash-cache.md#full-data-ab-gate)).
On the 4090: rerun C1 rules and C3 portfolio from the PR branch **with the new default (cache on)**, using
the same inputs as the existing slow run, into a NEW directory. Then compare against the slow products
(plans.json content `e56994d8...`, snapshot `8a2854d8...`, portfolio pack).

| File | Purpose |
|---|---|
| `patch_freeze_metadata.py` | Copies the slow run's freeze metadata. Changes only `inputs.plans.uri` to point at the new plans.json and adds the research stamp. Plans raw/content hashes are left as-is, so freeze fails closed if the cached plans differ. |
| `ab_compare.py` | Prints raw SHA256 slow vs new, then does the normalized content comparison. Exit 0 = PASS. Imports `my_scripts` from its own checkout, so no PYTHONPATH is needed. |
| `../../../tests/test_joint_return_ab_kit.py` | CI self-test. A synthetic slow vs default chain must PASS, and a tampered `intents.csv` must FAIL. |

Outputs go to `$New\ab\`. Nothing under `$Out` (the slow run) is written.

```powershell
$Py='<vanna312 python.exe>'; $MQ='<MyQuant checkout>'; $MQWt="$MQ-wt-plancache"
$Scores='<same as slow>'; $Initial='<same as slow>'
$Out='<slow run dir: sessions.json, metadata.json, rules\, snapshot.json, portfolio\>'
$SlowFreezeMetadata='<metadata given to freeze in the slow run ($FreezeMetadata or "$Out\rules\metadata.json")>'
$SlowRunId='<slow portfolio run id>'; $New="$Out-ab-cache-$(Get-Date -Format yyyyMMdd-HHmm)"
$Kit="$MQWt\docs\performance\ab-2026-09-25"
git -C $MQ fetch origin perf/plan-hash-cache-default-2026-09-25
git -C $MQ worktree add $MQWt origin/perf/plan-hash-cache-default-2026-09-25
git -C $MQWt log -1 --format=%H
Set-Location $MQWt; New-Item -ItemType Directory $New,"$New\ab" | Out-Null
Measure-Command { & $Py -m my_scripts.joint_return_rule_intents --scores $Scores --initial-state $Initial --sessions "$Out\sessions.json" --metadata "$Out\metadata.json" --arms P-BASE --topk 50 --n-drop 5 --output-dir "$New\rules" | Out-Host } | Tee-Object "$New\ab\time-rules.txt"
if ($LASTEXITCODE -ne 0) { throw 'rule failed' }
& $Py "$Kit\patch_freeze_metadata.py" $SlowFreezeMetadata "$New\rules\plans.json" "$New\ab\freeze-metadata.json"
if ($LASTEXITCODE -ne 0) { throw 'patch failed' }
& $Py -m my_scripts.joint_return_freeze_snapshot --scores $Scores --initial-state $Initial --plans "$New\rules\plans.json" --metadata "$New\ab\freeze-metadata.json" --output "$New\snapshot.json"
if ($LASTEXITCODE -ne 0) { throw 'freeze failed (plans drift => A/B FAIL)' }
Measure-Command { & $Py -m my_scripts.joint_return_portfolio --snapshot "$New\snapshot.json" --run-id $SlowRunId --output-root "$New\portfolio" | Out-Host } | Tee-Object "$New\ab\time-portfolio.txt"
if ($LASTEXITCODE -ne 0) { throw 'portfolio failed' }
& $Py "$Kit\ab_compare.py" "$Out\rules" "$New\rules" "$Out\snapshot.json" "$New\snapshot.json" "$Out\portfolio\$SlowRunId" "$New\portfolio\$SlowRunId" | Tee-Object "$New\ab\ab-compare.txt"
if ($LASTEXITCODE -ne 0) { throw 'A/B FAIL' } else { 'A/B PASS' }
```

`ab_compare.py` output starts with a raw SHA256 table (slow | new | SAME/DIFF) covering plans.json, rules
metadata.json, rule-manifest.json, snapshot.json, intents.csv, constraints.csv, pref_check.json and
manifest.json. For an independent cross-check, run `Get-FileHash -Algorithm SHA256` on the same files.

**Must be equal:**
- plans.json, intents.csv, constraints.csv and pref_check.json bytes, plus the plans content hash.
- The declared plans raw/content seals.
- Snapshot sections (scores, initial_state, plans).
- `reference_states` in rule-manifest and the portfolio manifest.
- Portfolio manifest `intent_hash`, `arm_intent_hashes`, `artifacts`, `contract_hash` and `initial_state`.

**Expected to differ.** These fields are removed before the normalized comparison:
- The `research_acceleration` stamp.
- `inputs.plans.uri`, which follows the new output directory.
- The portfolio manifest's `snapshot` source seal.
- As a result, the raw hashes of rules metadata.json, rule-manifest.json, snapshot.json and manifest.json
  differ, and `8a2854d8...` is not reproduced byte-for-byte.

No timestamps are written into these files. Reusing `$SlowRunId` under a new output root removes the run_id
difference. If `contract_hash` differs, check the line endings of `docs/reviews/joint-return-v1/contract.md`
in the new worktree (CRLF vs LF), since that hash is taken over the raw file bytes. `ab_compare.py` loads whole
JSON files, so the large snapshot needs a lot of RAM.

Report `ab-compare.txt`, the time files, `git -C $MQWt log -1` and the exit codes on PR #102 before merge.
