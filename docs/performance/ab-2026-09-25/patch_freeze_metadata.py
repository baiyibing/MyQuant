"""usage: python patch_freeze_metadata.py <slow_freeze_metadata.json> <new_plans.json> <out_metadata.json>
Copies the slow-run freeze metadata, re-points inputs.plans.uri at the NEW plans.json, and adds the
research stamp (as rule metadata would carry it). raw/content hashes are NOT touched: freeze then
fails closed with "plans raw_sha256/content_sha256 drift" if the cached plans differ from the slow ones.
"""
import hashlib
import json
import sys
from pathlib import Path

src, plans, out = Path(sys.argv[1]), Path(sys.argv[2]).resolve(), Path(sys.argv[3])
m = json.loads(src.read_bytes())
m["inputs"]["plans"]["uri"] = str(plans)
m["research_acceleration"] = "TRACK_B_PLAN_HASH_CACHE_PENDING_REVIEW"
if out.exists():
    sys.exit(f"refusing to overwrite {out}")
out.write_bytes(json.dumps(m, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n")
print("plans raw_sha256", m["inputs"]["plans"]["raw_sha256"], "actual", hashlib.sha256(plans.read_bytes()).hexdigest())
