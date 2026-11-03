"""All minute-refresh write destinations stay outside the daily provider."""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import refresh_mydata_1min as refresh


def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    lake, provider, daily = tmp_path/'lake', tmp_path/'minute', tmp_path/'daily'
    part = lake/'symbol=000001_SZ'
    part.mkdir(parents=True)
    dates = pd.date_range('2026-11-02 09:30', periods=3, freq='min')
    pd.DataFrame({'time': dates.astype('datetime64[ms]').astype('int64'),
                  'open': 10., 'high': 13., 'low': 9., 'close': [10., 11., 12.],
                  'volume': 10., 'amount': 10000.}).to_parquet(part/'data.parquet', index=False)
    (provider/'calendars').mkdir(parents=True)
    (provider/'features/sz000001').mkdir(parents=True)
    (provider/'instruments').mkdir()
    (provider/'calendars/1min.txt').write_text('2026-11-02 09:30:00\n2026-11-02 09:31:00\n', encoding='utf-8')
    (provider/'instruments/all.txt').write_text('SZ000001\t2026-11-02 09:30:00\t2026-11-02 09:31:00\n', encoding='utf-8')
    np.asarray([0, 10, 11], dtype='<f4').tofile(provider/'features/sz000001/close.1min.bin')
    (daily/'calendars').mkdir(parents=True)
    (daily/'calendars/day.txt').write_text('2026-11-02\n', encoding='utf-8')
    monkeypatch.setattr(refresh, 'DAILY_QLIB', daily)
    return lake, provider, daily


def args_for(inputs, tmp_path, *, qlib=None, staging=None, receipt=None):
    lake, provider, _ = inputs
    args = ['--lake-root', str(lake), '--skip-index', '--qlib-dir', str(qlib or provider),
            '--staging-dir', str(staging or tmp_path/'staging'), '--max-workers', '1']
    if receipt is not None:
        args += ['--receipt', str(receipt)]
    return args


@pytest.mark.parametrize('kind', ['staging', 'receipt'])
def test_real_writers_cannot_pollute_daily(inputs, tmp_path, kind):
    _, _, daily = inputs
    options = {'staging': daily} if kind == 'staging' else {'receipt': daily/'calendars/day.txt'}
    before = snapshot(tmp_path)
    with pytest.raises(SystemExit, match='daily'):
        refresh.main(args_for(inputs, tmp_path, **options))
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize('relation', ['same', 'child', 'parent', 'normalized'])
@pytest.mark.parametrize('role', ['qlib', 'staging', 'receipt'])
@pytest.mark.parametrize('flags', [[], ['--skip-stage', '--rebuild']])
def test_every_output_is_rejected_before_any_writer(inputs, tmp_path, monkeypatch, relation, role, flags):
    _, _, daily = inputs
    target = {'same': daily, 'child': daily/'child', 'parent': daily.parent,
              'normalized': daily/'unused/..'}[relation]
    before = snapshot(tmp_path)
    for name in ['stage_stock_and_index', 'append_new_1min_bars', 'dump_all_1min', 'write_receipt']:
        monkeypatch.setattr(refresh, name, lambda *_a, **_k: pytest.fail('writer reached before refusal'))
    with pytest.raises(SystemExit, match='daily'):
        refresh.main(args_for(inputs, tmp_path, **{role: target})+flags)
    assert snapshot(tmp_path) == before


def test_derived_full_staging_is_also_checked(inputs, tmp_path, monkeypatch):
    daily = tmp_path/'daily_full_new'
    (daily/'calendars').mkdir(parents=True)
    (daily/'calendars/day.txt').write_text('2026-11-02\n', encoding='utf-8')
    monkeypatch.setattr(refresh, 'DAILY_QLIB', daily)
    monkeypatch.setattr(refresh, 'stage_stock_and_index', lambda *_a, **_k: pytest.fail('staging reached'))
    before = snapshot(tmp_path)
    with pytest.raises(SystemExit, match='daily'):
        refresh.main(args_for(inputs, tmp_path, staging=tmp_path/'daily'))
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize('role', ['qlib', 'staging', 'receipt'])
@pytest.mark.skipif(os.name != 'nt', reason='Windows case aliases require Windows paths')
def test_windows_case_aliases(inputs, tmp_path, role):
    _, _, daily = inputs
    target = Path(str(daily).swapcase())
    with pytest.raises(SystemExit, match='daily'):
        refresh.main(args_for(inputs, tmp_path, **{role: target}))


@pytest.mark.parametrize('role', ['qlib', 'staging', 'receipt'])
def test_symlink_aliases(inputs, tmp_path, role):
    _, _, daily = inputs
    alias = tmp_path/'alias'
    try:
        alias.symlink_to(daily, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip('directory symlink creation unavailable on this host')
    before = snapshot(tmp_path)
    with pytest.raises(SystemExit, match='daily'):
        refresh.main(args_for(inputs, tmp_path, **{role: alias}))
    assert snapshot(tmp_path) == before


def test_disjoint_real_append_and_receipt_keep_daily_and_lake_bytes(inputs, tmp_path):
    lake, provider, daily = inputs
    before_lake, before_daily = snapshot(lake), snapshot(daily)
    receipt = tmp_path/'receipt.json'
    assert refresh.main(args_for(inputs, tmp_path, receipt=receipt)) == 0
    assert receipt.is_file()
    assert snapshot(lake) == before_lake and snapshot(daily) == before_daily
    assert (provider/'calendars/1min.txt').read_text().splitlines()[-1] == '2026-11-02 09:32:00'
    assert np.fromfile(provider/'features/sz000001/close.1min.bin', dtype='<f4').tolist() == [0., 10., 11., 12.]
