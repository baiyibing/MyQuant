"""Full-data A/B content comparison for PR #102 (plan-hash cache default flip).

usage: python docs/performance/ab-2026-09-25/ab_compare.py \
  <slow_rules_dir> <new_rules_dir> <slow_snapshot.json> <new_snapshot.json> <slow_pack_dir> <new_pack_dir>
Exit 0 = PASS (all required-equal items equal, only expected fields differ), 1 = FAIL.
Imports my_scripts from the checkout containing this file (no PYTHONPATH needed).
"""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # repo root
from my_scripts.joint_return_contract import content_hash

STAMP = "research_acceleration"
sr, nr, ss, ns, sp, np_ = map(Path, sys.argv[1:7])
fail = []
def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 24), b""): h.update(b)
    return h.hexdigest()
def load(p): return json.loads(Path(p).read_bytes())
def pop(d, *path):
    for k in path[:-1]: d = d.get(k, {})
    return d.pop(path[-1], None)
def check(name, ok, detail=""):
    print(f"{'OK  ' if ok else 'FAIL'} {name} {detail}")
    if not ok: fail.append(name)

print("== raw SHA256 (slow | new) ==")
pairs = [(sr/"plans.json", nr/"plans.json"), (sr/"metadata.json", nr/"metadata.json"),
         (sr/"rule-manifest.json", nr/"rule-manifest.json"), (ss, ns)] + \
        [(sp/f, np_/f) for f in ("intents.csv", "constraints.csv", "pref_check.json", "manifest.json")]
raw = {}
for a, b in pairs:
    name = "snapshot.json" if a == ss else a.name
    raw[name] = (sha(a), sha(b))
    print(f"  {name:20s} {raw[name][0]} | {raw[name][1]}  {'SAME' if raw[name][0] == raw[name][1] else 'DIFF'}")

print("== required byte-equal ==")
for f in ("plans.json", "intents.csv", "constraints.csv", "pref_check.json"):
    check(f"{f} bytes", raw[f][0] == raw[f][1])
sp_, np2 = load(sr/"plans.json"), load(nr/"plans.json")
check("plans content_hash", content_hash(sp_) == content_hash(np2), content_hash(np2)[:16])
del sp_, np2

print("== normalized JSON (expected-diff fields removed) ==")
def norm_rules_meta(m):
    stamp = pop(m, STAMP); uri = pop(m, "inputs", "plans", "uri"); return stamp, uri
a, b = load(sr/"metadata.json"), load(nr/"metadata.json")
sa, ua = norm_rules_meta(a); sb, ub = norm_rules_meta(b)
print(f"  rules metadata: stamp slow={sa!r} new={sb!r}; plans.uri slow={ua} new={ub}")
check("rules metadata.json normalized", a == b)
check("new rules metadata carries stamp", sb == "TRACK_B_PLAN_HASH_CACHE_PENDING_REVIEW")
a, b = load(sr/"rule-manifest.json"), load(nr/"rule-manifest.json")
pop(a, "plans", "uri"); pop(b, "plans", "uri")
check("rule-manifest.json normalized (incl. reference_states, plans seals)", a == b)
a, b = load(ss), load(ns)
for sec in ("scores", "initial_state", "plans", "pref"):
    if sec in a or sec in b:
        check(f"snapshot section {sec}", content_hash(a.get(sec)) == content_hash(b.get(sec)))
for x in (a, b): pop(x, "metadata", STAMP); pop(x, "metadata", "inputs", "plans", "uri")
check("snapshot normalized", a == b)
del a, b
a, b = load(sp/"manifest.json"), load(np_/"manifest.json")
for k in ("intent_hash", "arm_intent_hashes", "contract_hash", "artifacts", "reference_states", "initial_state"):
    check(f"portfolio manifest {k}", a.get(k) == b.get(k))
print(f"  run_id slow={a.get('run_id')} new={b.get('run_id')}")
print(f"  snapshot seal slow={a.get('snapshot')}\n                new={b.get('snapshot')}")
for x in (a, b):
    pop(x, "run_id"); pop(x, "snapshot"); pop(x, "metadata", STAMP); pop(x, "metadata", "inputs", "plans", "uri")
check("portfolio manifest normalized", a == b)
if a != b:
    print("  differing top-level keys:", sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k)))
print("RESULT:", "PASS" if not fail else f"FAIL {fail}")
sys.exit(1 if fail else 0)
