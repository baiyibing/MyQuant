from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

here = Path(__file__).resolve().parent
old = here.parent / 'three_repo_batch6_20261102'
root = here / 'myquant'
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / 'my_scripts'))
from qlib_scripts import build_etf_qlib as build
import host_env

receipt = json.loads((old / 'etf-e3-acceptance.json').read_text(encoding='utf-8'))
precheck = json.loads((old / 'etf-e3-precheck.json').read_text(encoding='utf-8'))
provider = Path(precheck['target'])
stage = provider.parent / 'staging'
manifest = json.loads((old / 'etf-provider-files.json').read_text(encoding='utf-8'))

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def check(row):
    path = provider / row['path']
    return {**row, 'current_sha256': sha(path), 'current_bytes': path.stat().st_size}

with ThreadPoolExecutor(max_workers=8) as pool:
    checked = list(pool.map(check, manifest))
bad = [row['path'] for row in checked if row['bytes'] != row['current_bytes'] or row['sha256'] != row['current_sha256']]
expected_names = {row['path'] for row in manifest}
extra = [str(p.relative_to(provider)).replace('\\', '/') for p in provider.rglob('*') if p.is_file() and str(p.relative_to(provider)).replace('\\', '/') not in expected_names]
assert not bad and not extra, (bad[:5], extra[:5])
calendar = pd.DatetimeIndex(pd.to_datetime((provider / 'calendars/day.txt').read_text().splitlines()))
assert calendar.is_unique and calendar.is_monotonic_increasing and len(calendar) == 1640
assert calendar[0] == pd.Timestamp(build.WINDOW_START) and calendar[-1] == pd.Timestamp(build.WINDOW_END)
assert not (calendar.weekday >= 5).any()

def anchors():
    return {directory: {rel: {'exists': (Path(directory) / rel).is_file(),
        'sha256': sha(Path(directory) / rel) if (Path(directory) / rel).is_file() else None}
        for rel in values} for directory, values in precheck['protected_before'].items()}

protected_before = anchors()
import qlib
from qlib.constant import REG_CN
from qlib.data import D
qlib.init(provider_uri=str(provider), region=REG_CN, kernels=1, expression_cache=None, dataset_cache=None)
readback = []
fields = ['open', 'high', 'low', 'close', 'volume', 'amount', 'vwap']
for code in build.READBACK_CODES:
    frozen = pd.read_parquet(stage / (code.lower() + '.parquet')).set_index('date')
    frozen.index = pd.DatetimeIndex(frozen.index)
    observed = D.features([code], ['$' + name for name in fields], start_time=build.WINDOW_START, end_time=build.WINDOW_END)
    if isinstance(observed.index, pd.MultiIndex):
        observed = observed.xs(code, level='instrument')
    observed.index = pd.DatetimeIndex(observed.index).normalize()
    aligned = observed.reindex(frozen.index)
    rows = {'code': code, 'rows': len(frozen), 'fields': {}}
    for name in fields:
        actual = aligned['$' + name].to_numpy(dtype=float)
        expected = frozen[name].to_numpy(dtype=float)
        assert np.isfinite(actual).all() and np.isfinite(expected).all()
        assert np.allclose(actual, expected, rtol=2e-6, atol=1e-4), (code, name)
        rows['fields'][name] = {'max_absolute_error': float(np.abs(actual-expected).max()),
            'max_relative_error': float((np.abs(actual-expected) / np.maximum(np.abs(expected), 1e-12)).max())}
    readback.append(rows)
protected_after = anchors()
assert protected_before == protected_after
assert all(sha(provider / row['path']) == row['sha256'] for row in manifest)
source_drift = []
for name, recorded in precheck['source_files_before'].items():
    path = Path(name)
    source_drift.append({'path': name, 'historical_sha256': recorded['sha256'],
        'current_sha256': sha(path), 'changed_since_build': sha(path) != recorded['sha256']})
result = {'schema_version': 1, 'recorded_at_utc': datetime.now(timezone.utc).isoformat(),
    'decision': 'PASS_FROZEN_PROVIDER_READBACK', 'window': [build.WINDOW_START, build.WINDOW_END],
    'provider': str(provider), 'provider_files_verified': len(manifest), 'provider_changed_files': bad,
    'provider_extra_files': extra, 'calendar_days': len(calendar), 'all_count': receipt['all_count'],
    'etf_full_count': receipt['etf_full_count'], 'four_full_window_seven_field_readbacks': readback,
    'protected_anchors_before': protected_before, 'protected_anchors_after': protected_after,
    'live_source_drift': source_drift, 'market_writes': False, 'provider_writes': False,
    'scope': 'Existing frozen staging/provider snapshot. Current live-lake advancement is reported separately; no current-lake snapshot or production-provider promotion claim.'}
(here / 'e3-revalidation.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'decision': result['decision'], 'provider_files': len(manifest), 'readback_codes': len(readback), 'source_drift_files': sum(x['changed_since_build'] for x in source_drift)}))
