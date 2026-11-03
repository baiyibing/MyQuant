from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / 'qlib_scripts'
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
import refresh_mydata_1min as refresh  # noqa: E402


def source(root, *, dates=None, close=None, name='000001_SZ'):
    part = root / ('symbol='+name)
    part.mkdir(parents=True, exist_ok=True)
    times = pd.DatetimeIndex(dates if dates is not None else ['2026-11-02 09:30','2026-11-02 09:31'])
    pd.DataFrame({'time': times.astype('datetime64[ms]').astype('int64'),
        'open':10.,'high':11.,'low':9.,'close':close if close is not None else [10.,11.],
        'volume':10.,'amount':10000.}).to_parquet(part/'data.parquet',index=False)


def setup(tmp_path, monkeypatch):
    root, provider = tmp_path/'lake', tmp_path/'provider'
    source(root)
    (provider/'calendars').mkdir(parents=True)
    (provider/'features/sz000001').mkdir(parents=True)
    (provider/'instruments').mkdir()
    (provider/'calendars/1min.txt').write_text('2026-11-02 09:30:00\n2026-11-02 09:31:00\n',encoding='utf-8')
    (provider/'instruments/all.txt').write_text('SZ000001\t2026-11-02 09:30:00\t2026-11-02 09:31:00\n',encoding='utf-8')
    np.asarray([0,10,11],dtype='<f4').tofile(provider/'features/sz000001/close.1min.bin')
    daily = tmp_path/'daily'
    (daily/'calendars').mkdir(parents=True)
    (daily/'calendars/day.txt').write_text('2026-11-02\n',encoding='utf-8')
    monkeypatch.setattr(refresh,'DAILY_QLIB',daily)
    args=['--lake-root',str(root),'--skip-index','--qlib-dir',str(provider),
          '--staging-dir',str(tmp_path/'staging'),'--max-workers','1',
          '--receipt',str(tmp_path/'receipt.json')]
    return root, provider, daily, args


def snapshot(root):
    return {p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file()}


@pytest.mark.parametrize('symbols',[[],['--symbols','SZ000001'],['--symbols','000001.SZ']])
def test_default_empty_increment_is_measured_noop(tmp_path, monkeypatch, symbols):
    _, provider, daily, args = setup(tmp_path,monkeypatch)
    before, old_daily = snapshot(provider), snapshot(daily)
    assert refresh.main(args+symbols)==0
    import json
    receipt = json.loads((tmp_path/'receipt.json').read_text())
    assert receipt['mode']=='noop' and receipt['bars_appended']==receipt['symbols_touched']==0
    assert receipt['daily_day_txt_sha256_before']==receipt['daily_day_txt_sha256_after']
    assert receipt['empty_increment_proof']['raw_rows_in_window']==0
    assert receipt['empty_increment_proof']['usable_history_rows']==2
    assert receipt['empty_increment_proof']['provider_close_bins_checked']==1
    assert snapshot(provider)==before and snapshot(daily)==old_daily


@pytest.mark.parametrize('kind',[
    'missing_root','empty_root','unknown_symbol','missing_file','all_bad_close','new_bad_close',
    'empty_symbols','duplicate_aliases','bad_parquet','empty_parquet',
    'bad_time','missing_provider_symbol','empty_bin','bad_header','future_bin','bad_calendar','mixed_bad_source',
    'explicit_empty_window','rebuild_empty_window','skip_stage_empty',
])
def test_empty_increment_cannot_hide_bad_input(tmp_path,monkeypatch,kind):
    root, provider, daily, args = setup(tmp_path,monkeypatch)
    feature=provider/'features/sz000001/close.1min.bin'
    if kind=='missing_root':
        args[1]=str(tmp_path/'missing')
    elif kind=='empty_root':
        (root/'symbol=000001_SZ/data.parquet').unlink()
    elif kind=='unknown_symbol':
        args+=['--symbols','SZ000001','SH999999']
    elif kind=='empty_symbols':
        args+=['--symbols']
    elif kind=='duplicate_aliases':
        args+=['--symbols','SZ000001','000001.SZ']
    elif kind=='bad_parquet':
        (root/'symbol=000001_SZ/data.parquet').write_bytes(b'not parquet')
    elif kind=='empty_parquet':
        source(root,dates=[],close=[])
    elif kind=='missing_file':
        (root/'symbol=000001_SZ/data.parquet').unlink()
        args+=['--symbols','SZ000001']
    elif kind=='all_bad_close':
        source(root,close=[np.nan,np.nan])
    elif kind=='new_bad_close':
        source(root,dates=['2026-11-02 09:30','2026-11-02 09:32'],close=[10,np.nan])
    elif kind=='bad_time':
        source(root,dates=['2026-11-02 09:30',pd.NaT])
    elif kind=='mixed_bad_source':
        source(root,name='600000_SH',close=[np.nan,np.nan])
    elif kind=='missing_provider_symbol':
        source(root,name='600000_SH')
        args+=['--symbols','SZ000001','SH600000']
    elif kind=='empty_bin':
        feature.write_bytes(b'')
    elif kind=='bad_header':
        np.asarray([np.nan,10,11],dtype='<f4').tofile(feature)
    elif kind=='future_bin':
        np.asarray([0,10,11,12],dtype='<f4').tofile(feature)
    elif kind=='bad_calendar':
        (provider/'calendars/1min.txt').write_text('2026-11-02 09:31:00\n2026-11-02 09:30:00\n',encoding='utf-8')
    elif kind=='explicit_empty_window':
        args+=['--start','2026-11-03']
    elif kind=='rebuild_empty_window':
        args+=['--rebuild','--start','2026-11-03']
    elif kind=='skip_stage_empty':
        args+=['--skip-stage']
    (tmp_path/'staging').mkdir(exist_ok=True)
    sentinel=tmp_path/'staging/previous.parquet'
    sentinel.write_bytes(b'previous staging')
    # skip-stage must really consume an empty staging directory.
    if kind=='skip_stage_empty':
        sentinel.unlink()
    before, old_daily=snapshot(provider),snapshot(daily)
    with pytest.raises((SystemExit,ValueError,FileNotFoundError)):
        refresh.main(args)
    assert not (tmp_path/'receipt.json').exists()
    assert snapshot(provider)==before and snapshot(daily)==old_daily
    if kind in ['missing_root','empty_root','unknown_symbol','missing_file']:
        assert sentinel.read_bytes()==b'previous staging'


def test_default_nonempty_increment_still_advances(tmp_path,monkeypatch):
    root,provider,_,args=setup(tmp_path,monkeypatch)
    source(root,dates=['2026-11-02 09:30','2026-11-02 09:31','2026-11-02 09:32'],close=[10,11,12])
    assert refresh.main(args)==0
    np.testing.assert_array_equal(np.fromfile(provider/'features/sz000001/close.1min.bin',dtype='<f4'),[0,10,11,12])


def test_default_noop_without_receipt_flag(tmp_path,monkeypatch):
    _,provider,_,args=setup(tmp_path,monkeypatch)
    before=snapshot(provider)
    assert refresh.main(args[:-2])==0
    assert snapshot(provider)==before
    assert not (tmp_path/'receipt.json').exists()
