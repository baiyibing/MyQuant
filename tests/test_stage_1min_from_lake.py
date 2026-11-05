# -*- coding: utf-8 -*-
import pytest

pytest.importorskip("myquant_infra.adapters.qlib_data", reason="optional C1 infra pin")

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qlib_scripts.stage_1min_from_lake import (  # noqa: E402
    lake_partition_to_qlib_code,
    qlib_code_to_partition,
    stage_stock_and_index,
    stage_symbol,
    stage_lake,
)


def test_symbol_roundtrip():
    assert lake_partition_to_qlib_code("symbol=000001_SZ") == "SZ000001"
    assert lake_partition_to_qlib_code("600000_SH") == "SH600000"
    assert qlib_code_to_partition("SZ000001") == "000001_SZ"
    assert qlib_code_to_partition("000001.SZ") == "000001_SZ"


def _audit_source(root, name='000001_SZ', *, bad_tail=False):
    part=root/('symbol='+name)
    part.mkdir(parents=True)
    pd.DataFrame({'time':[int(pd.Timestamp('2026-11-02 09:30').value//1_000_000),
        int(pd.Timestamp('2026-11-02 09:31').value//1_000_000)],
        'close':[10.,float('nan') if bad_tail else 11.], 'volume':[10.,10.],
        'amount':[10000.,11000.]}).to_parquet(part/'data.parquet',index=False)


def test_audited_empty_stage_preserves_source_evidence(tmp_path):
    root=tmp_path/'lake'
    _audit_source(root)
    audit=[]
    assert stage_lake(root,tmp_path/'out',start='2026-11-02 09:32',audit=audit)==[]
    assert len(audit)==1
    assert audit[0]['source_rows']==audit[0]['usable_source_rows']==2
    assert audit[0]['requested_rows']==audit[0]['staged_rows']==0
    assert audit[0]['source_max']=='2026-11-02 09:31:00'


def test_audit_exposes_new_raw_rows_discarded_for_bad_close(tmp_path):
    root=tmp_path/'lake'
    _audit_source(root,bad_tail=True)
    audit=[]
    assert stage_lake(root,tmp_path/'out',start='2026-11-02 09:31',audit=audit)==[]
    assert audit[0]['usable_source_rows']==1
    assert audit[0]['requested_rows']==1 and audit[0]['staged_rows']==0


def test_parallel_audit_keeps_public_paths_and_frames_identical(tmp_path):
    root=tmp_path/'lake'
    _audit_source(root)
    _audit_source(root,'600000_SH')
    plain=stage_lake(root,tmp_path/'plain',max_workers=2)
    audit=[]
    measured=stage_lake(root,tmp_path/'measured',max_workers=2,audit=audit)
    assert {p.name for p in plain}=={p.name for p in measured}
    assert {row['code'] for row in audit}=={'SZ000001','SH600000'}
    for path in measured:
        pd.testing.assert_frame_equal(pd.read_parquet(path),pd.read_parquet(tmp_path/'plain'/path.name))


def test_stage_writes_dump_columns(tmp_path: Path):
    part = tmp_path / "symbol=600000_SH"
    part.mkdir()
    idx = pd.date_range("2026-08-03 09:30:00", periods=3, freq="min")
    raw = pd.DataFrame(
        {
            "time": (idx.view("int64") // 1_000_000).astype("int64"),
            "open": [10.0, 10.1, 10.2],
            "high": [10.2, 10.2, 10.3],
            "low": [9.9, 10.0, 10.1],
            "close": [10.1, 10.15, 10.25],
            "volume": [100, 80, 90],
            "amount": [101000.0, 81200.0, 92250.0],
        },
        index=idx,
    )
    raw.to_parquet(part / "data.parquet")
    dest = stage_symbol(part, tmp_path / "staging", "2026-08-03", "2026-08-03")
    assert dest is not None
    staged = pd.read_parquet(dest)
    assert list(staged.columns)[:2] == ["date", "symbol"]
    assert staged["symbol"].iloc[0] == "SH600000"
    assert "vwap" in staged.columns
    assert len(staged) == 3


def test_stage_stock_and_index(tmp_path: Path):
    stock = tmp_path / "stock" / "symbol=000001_SZ"
    index = tmp_path / "index" / "symbol=000300_SH"
    stock.mkdir(parents=True)
    index.mkdir(parents=True)
    idx = pd.date_range("2026-09-18 09:30:00", periods=2, freq="min")
    for part, close in ((stock, 10.0), (index, 4000.0)):
        pd.DataFrame(
            {
                "time": (idx.view("int64") // 1_000_000).astype("int64"),
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": 10,
                "amount": 100.0,
            },
            index=idx,
        ).to_parquet(part / "data.parquet")
    written = stage_stock_and_index(stock.parent, index.parent, tmp_path / "staging", max_workers=1)
    names = sorted(p.name for p in written)
    assert names == ["sh000300.parquet", "sz000001.parquet"]
