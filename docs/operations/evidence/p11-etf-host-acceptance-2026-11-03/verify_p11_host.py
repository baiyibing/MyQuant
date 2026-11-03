from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

import numpy as np
import pandas as pd

here = Path(__file__).resolve().parent
root = here / 'myquant'
out = here / 'p11-host/e4-lgb-purged'
old = here.parent / 'three_repo_batch6_20261102'
receipt = json.loads((out / 'acceptance.json').read_text(encoding='utf-8'))
pre = json.loads((old / 'etf-e3-precheck.json').read_text(encoding='utf-8'))
provider = Path(pre['target'])
calendar = pd.DatetimeIndex(pd.to_datetime((provider / 'calendars/day.txt').read_text().splitlines()))
implementation = '3e4c992b444480071100fbd1fb9ea3f8717320c9'

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def manual_mask(dates, start, end):
    dates = pd.DatetimeIndex(dates)
    positions = calendar.get_indexer(dates)
    keep = (positions >= 0) & (positions + 2 < len(calendar)) & (dates >= start) & (dates <= end)
    for horizon in (1, 2):
        future = calendar[np.clip(positions + horizon, 0, len(calendar)-1)]
        keep &= (future >= start) & (future <= end)
    return np.asarray(keep, dtype=bool)

assert receipt['status'] == 'PASS' and set(receipt['models']) == {'lgb'}
assert receipt['models']['lgb']['status'] == 'PASS' and receipt['horizons'] == [1, 2]
assert receipt['policy'] == 'purged-fit-h1-h2.v1' and receipt['mask_bounds'] == 'nominal segments'
runtime_source = (root / 'my_scripts/train_etf_smoke.py').read_bytes()
git_source = subprocess.check_output(['git','show',implementation+':my_scripts/train_etf_smoke.py'], cwd=root)
assert receipt['script_sha256'] == hashlib.sha256(runtime_source).hexdigest()
assert runtime_source.replace(b'\r\n', b'\n') == git_source.replace(b'\r\n', b'\n')
nominal = {'train': ['2020-01-02','2024-12-31'], 'valid': ['2025-01-02','2025-12-31'], 'test': ['2026-01-05','2026-10-13']}
assert receipt['nominal_segments'] == nominal
for name in ('train', 'valid'):
    eligible = calendar[manual_mask(calendar, *nominal[name])]
    assert receipt['effective_segments'][name] == [nominal[name][0], str(eligible[-1].date())]
    facts = receipt['fit_samples'][name]
    assert facts['rows'] > 0 and facts['all_label_dates_in_nominal_segment']
    assert pd.Timestamp(facts['last']) <= eligible[-1] and pd.Timestamp(facts['first']) >= pd.Timestamp(nominal[name][0])
assert receipt['effective_segments']['test'] == nominal['test']
processor_fit = [row for row in receipt['processor_fit'] if row['fit_end_time'] != 'None']
assert processor_fit
assert all(pd.Timestamp(row['fit_end_time']) <= pd.Timestamp(nominal['train'][1]) for row in processor_fit)

reports = {}
for name, item in receipt['models']['lgb']['segments'].items():
    path = (out / item['path']).resolve()
    assert path.is_relative_to(out.resolve()) and sha(path) == item['sha256']
    data = pd.read_parquet(path)
    assert data.index.is_unique and data.index.names == ['datetime','instrument']
    dates = pd.DatetimeIndex(data.index.get_level_values('datetime'))
    keep = manual_mask(dates, *nominal[name])
    finite = np.isfinite(data['pred'].to_numpy()) & np.isfinite(data['label'].to_numpy())
    assert np.array_equal(data['in_segment'].to_numpy(), keep)
    assert np.array_equal(data['finite_pair'].to_numpy(), finite)
    assert np.array_equal(data['accepted'].to_numpy(), keep & finite)
    accepted = data.loc[keep & finite]
    n = len(accepted)
    ic = float(accepted['pred'].corr(accepted['label']))
    rank = float(accepted['pred'].rank().corr(accepted['label'].rank()))
    expected = item['report']
    assert n >= 2 and n == expected['n'] and np.isfinite(ic) and np.isfinite(rank)
    assert abs(ic-expected['ic']) <= 1e-12 and abs(rank-expected['rank_ic']) <= 1e-12
    assert expected['rows'] == len(data) and expected['kept'] == int(keep.sum())
    assert item['rows'] == len(data)
    reports[name] = {'rows': len(data), 'accepted': n, 'ic': ic, 'rank_ic': rank,
        'instruments': data.index.get_level_values('instrument').nunique(),
        'first_signal_date': str(dates.min().date()), 'last_signal_date': str(dates.max().date()),
        'file_sha256': item['sha256'], 'independent_mask_and_metrics_match': True}
manifest = json.loads((old / 'etf-provider-files.json').read_text())
with ThreadPoolExecutor(max_workers=8) as pool:
    matches = list(pool.map(lambda row: sha(provider / row['path']) == row['sha256'], manifest))
assert all(matches)
e3 = json.loads((here / 'e3-revalidation.json').read_text(encoding='utf-8'))
for directory, entries in e3['protected_anchors_before'].items():
    for rel, before in entries.items():
        path = Path(directory) / rel
        assert {'exists': path.is_file(), 'sha256': sha(path) if path.is_file() else None} == before
for rel, expected in receipt['provider_anchors_sha256'].items():
    assert sha(provider / rel) == expected
result = {'schema_version': 1, 'recorded_at_utc': datetime.now(timezone.utc).isoformat(),
    'decision': 'PASS_E3_E4_LOCAL_ISOLATED_SMOKE', 'implementation_head': implementation,
    'runtime_script_sha256': receipt['script_sha256'], 'git_blob_sha256': hashlib.sha256(git_source).hexdigest(),
    'source_equal_after_lf_normalization': True,
    'policy': receipt['policy'], 'historical_policy_ic_not_reused': True,
    'nominal_segments': nominal, 'effective_segments': receipt['effective_segments'],
    'fit_samples': receipt['fit_samples'], 'processor_fit': receipt['processor_fit'],
    'segments': reports, 'provider_files_verified_unchanged': len(matches),
    'protected_anchors_unchanged': True, 'acceptance_json_sha256': sha(out/'acceptance.json'),
    'versions': receipt['versions'], 'threads': receipt['threads'],
    'invocation': {'models': ['lgb'], 'num_boost_round': 80, 'exp_name': 'p11_etf_20261103_purged',
        'write_acceptance_artifacts': True, 'fresh_mlflow_worktree': str(root)},
    'limits': ['Fixed historical provider/window, not a newly updated live-lake provider',
        'Front-adjustment basis and etf_full end-date selection retain the documented research biases',
        'IC and RankIC are pooled finite-row smoke metrics, not evidence of strategy profitability or daily IC stability',
        'No default-provider promotion, market writes, QMT login, trading or additional model selection'],
    'e3_accepted': True, 'e4_accepted': True, 'package_closed': True}
(here / 'p11-host-acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'decision':result['decision'],'test':reports['test'],'provider_files':len(matches)}))
