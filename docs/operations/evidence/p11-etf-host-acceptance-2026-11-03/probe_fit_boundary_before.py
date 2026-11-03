from datetime import datetime, timezone
import hashlib
import inspect
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

here = Path(__file__).resolve().parent
sys.path.insert(0, str(here / 'myquant'))
sys.path.insert(0, str(here / 'myquant/my_scripts'))
import train_etf_smoke as smoke
import host_env
import qlib
from qlib.data import D
from qlib.data.dataset import DatasetH

pre = json.loads((here.parent / 'three_repo_batch6_20261102/etf-e3-precheck.json').read_text())
qlib.init(provider_uri=pre['target'], region='cn', kernels=1, expression_cache=None, dataset_cache=None)
calendar = pd.DatetimeIndex(D.calendar(start_time=smoke.WINDOW_START, end_time=smoke.TEST_END))
rows = []
for segment in ('train', 'valid'):
    start, end = smoke.SEGMENTS[segment]
    dates = calendar[(calendar >= start) & (calendar <= end)][-2:]
    frame = D.features(['SH510050', 'SH510300'], [smoke.LABEL_EXPR], start_time=str(dates[0].date()), end_time=str(dates[-1].date()))
    for (code, date), row in frame.iterrows():
        pos = calendar.get_loc(pd.Timestamp(date))
        future = [str(calendar[pos+h].date()) for h in (1, 2)]
        rows.append({'segment': segment, 'instrument': code, 'signal_date': str(pd.Timestamp(date).date()),
            'nominal_end': end, 'label_dates': future, 'label_is_finite': bool(np.isfinite(row.iloc[0])),
            'metric_mask_accepts': bool(smoke.in_segment_label_mask([date], calendar, start, end)[0])})
source = Path(smoke.__file__).read_text(encoding='utf-8')
result = {'recorded_at_utc': datetime.now(timezone.utc).isoformat(), 'source_head': '76a2fd293398697b851520c4817e1688762b83ea',
    'source_sha256': hashlib.sha256(Path(smoke.__file__).read_bytes()).hexdigest(),
    'dataset_uses_unpurged_SEGMENTS': 'segments=SEGMENTS' in source,
    'dataset_prepare_impl': inspect.getsource(DatasetH._prepare_seg), 'counterexample_rows': rows,
    'all_boundary_labels_finite': all(row['label_is_finite'] for row in rows),
    'all_rejected_only_at_metric_stage': all(not row['metric_mask_accepts'] for row in rows),
    'network_called': False, 'trained': False, 'market_write_performed': False}
assert result['dataset_uses_unpurged_SEGMENTS'] and result['all_boundary_labels_finite'] and result['all_rejected_only_at_metric_stage']
(here / 'fit-boundary-before.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'boundary_counterexamples': len(rows), 'labels_finite': result['all_boundary_labels_finite']}))
