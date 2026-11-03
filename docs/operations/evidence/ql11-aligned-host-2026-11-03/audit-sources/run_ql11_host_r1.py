"""Real-lake, isolated-provider QL11 host acceptance. Never promote outputs."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE/'myquant'
EXPECTED='a997760a6baaa893d5f5081a6e08910371754ef9'
sys.path.insert(0,str(ROOT/'my_scripts'))
from data_root import resolve_stock_1min_none, resolve_index_1min_none
import numpy as np
import pandas as pd


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path,value):
    with Path(path).open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2)
        stream.write('\n')


def code_identity():
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    dirty=subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip()
    if head!=EXPECTED or dirty:
        raise RuntimeError('host source must be frozen and clean')


def anchors():
    base=Path.home()/'.qlib/qlib_data'
    return {str(p):{'exists':p.exists(),'sha256':sha(p) if p.is_file() else None} for p in [
        base/'my_data/calendars/day.txt',base/'my_data_1min/calendars/1min.txt',
        ROOT/'pred.pkl']}


def snapshot(provider):
    return {str(p.relative_to(provider)):p.read_bytes() for p in provider.rglob('*') if p.is_file() and p.suffix!='.bak'}


def main():
    code_identity()
    stock,index=resolve_stock_1min_none().resolve(strict=True),resolve_index_1min_none().resolve(strict=True)
    codes=['SZ000001','SH600000','SZ300750','SH688981','BJ920002','SH000001','SH000300']
    paths={}
    for code in codes:
        partition=code[2:]+'_'+code[:2]
        found=[]
        for root in [stock,index]:
            p=root/('symbol='+partition)/'data.parquet'
            if p.is_file():
                paths[str(p)]=sha(p)
                found.append(p)
        if not found:
            raise RuntimeError('required real source missing: '+code)
    # Actual staging uses index tree last if a symbol exists in both trees.
    out=HERE/'ql11-host'
    out.mkdir(exist_ok=False)
    before_anchors=anchors()
    recipe={'registered_utc':datetime.now(timezone.utc).isoformat(),'source_commit':EXPECTED,
        'runner_sha256':sha(__file__),'source_hashes':paths,'stock_root':str(stock),'index_root':str(index),
        'window':['2026-10-23','2026-11-02'],'seed_end':'2026-10-29','codes':codes,
        'protected_anchors_before':before_anchors,'python':sys.version,'executable':sys.executable,
        'scope':'Real lake, seven selected stock/index symbols, fresh isolated providers. No market or default-provider writes/promotion.'}
    write(out/'recipe.json',recipe)
    provider=out/'incremental'
    commands=[]
    def run(label,dest,symbols,end,rebuild=False):
        code_identity()
        cmd=[sys.executable,str(ROOT/'qlib_scripts/refresh_mydata_1min.py'),
            '--qlib-dir',str(dest),'--staging-dir',str(out/('stage-'+label)),
            '--start',recipe['window'][0],'--end',end,'--max-workers','2',
            '--receipt',str(out/(label+'-receipt.json')),'--symbols',*symbols]
        if rebuild:
            cmd.append('--rebuild')
        commands.append(cmd)
        with (out/(label+'.log')).open('w',encoding='utf-8') as log:
            proc=subprocess.run(cmd,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
        if proc.returncode:
            raise RuntimeError(label+' CLI failed, see isolated log')
        code_identity()
    run('seed',provider,codes[:-1],recipe['seed_end'],True)
    old=snapshot(provider)
    run('incremental',provider,codes,recipe['window'][1])
    after=snapshot(provider)
    prefix_files=[n for n in old if n.startswith('features/')]
    assert prefix_files and all(after[n].startswith(old[n]) for n in prefix_files)
    run('rebuild',out/'rebuild',codes,recipe['window'][1],True)
    rebuilt=snapshot(out/'rebuild')
    feature_names={n for n in after if n.startswith('features/')}
    assert feature_names=={n for n in rebuilt if n.startswith('features/')}
    assert all(after[n]==rebuilt[n] for n in feature_names)
    assert after['calendars/1min.txt']==rebuilt['calendars/1min.txt']
    assert sorted(after['instruments/all.txt'].decode().splitlines())==sorted(rebuilt['instruments/all.txt'].decode().splitlines())
    calendar=pd.DatetimeIndex(pd.to_datetime((provider/'calendars/1min.txt').read_text().splitlines()))
    comparisons=[]
    for code in codes:
        partition=code[2:]+'_'+code[:2]
        candidates=[root/('symbol='+partition)/'data.parquet' for root in [stock,index]]
        source=next(p for p in reversed(candidates) if p.is_file())
        raw=pd.read_parquet(source)
        times=pd.to_datetime(raw['time'],unit='ms') if pd.api.types.is_numeric_dtype(raw['time']) else pd.to_datetime(raw['time'])
        raw=raw.assign(date=times).set_index('date')
        raw=raw.loc[(raw.index>=pd.Timestamp(recipe['window'][0]))&(raw.index<pd.Timestamp('2026-11-03'))]
        raw=raw.loc[~raw.index.duplicated(keep='first')].sort_index()
        raw=raw.loc[raw['close'].notna()]
        expected=raw.reindex(calendar[(calendar>=raw.index.min())&(calendar<=raw.index.max())]).copy()
        expected['vwap']=(expected['amount']/(expected['volume']*100)).where(expected['volume']>0)
        for field in ['open','high','low','close','volume','amount','vwap']:
            path=provider/'features'/code.lower()/(field+'.1min.bin')
            binary=np.fromfile(path,dtype='<f4')
            start=int(binary[0])
            assert calendar[start]==expected.index[0]
            np.testing.assert_array_equal(binary[1:],expected[field].to_numpy(dtype='<f4'))
            comparisons.append({'symbol':code,'field':field,'values':len(binary)-1,'bin_sha256':sha(path)})
    pre_noop=snapshot(provider)
    run('noop',provider,codes,recipe['window'][1])
    assert snapshot(provider)==pre_noop
    assert anchors()==before_anchors
    assert all(sha(Path(p))==digest for p,digest in paths.items())
    receipts={name:json.loads((out/(name+'-receipt.json')).read_text()) for name in ['seed','incremental','rebuild','noop']}
    assert [r['mode'] for r in receipts.values()]==['rebuild','incremental','rebuild','noop']
    assert receipts['incremental']['minute_calendar_advanced'] and receipts['incremental']['symbols_touched']==len(codes)
    assert receipts['noop']['bars_appended']==0
    write(out/'acceptance.json',{'audit_id':'QL11','package':'P12','package_closed':False,
        'status':'PASS_LOCAL_ISOLATED_REAL_LAKE','source_commit':EXPECTED,'commands':commands,
        'window':recipe['window'],'codes':codes,'fields_compared':comparisons,
        'seed_calendar_rows':receipts['seed']['minute_calendar_len_after'],
        'final_calendar_rows':len(calendar),'final_calendar_last':str(calendar[-1]),
        'new_calendar_rows':receipts['incremental']['bars_appended'],
        'existing_bin_prefix_files_preserved':len(prefix_files),'increment_rebuild_features_byte_equal':len(feature_names),
        'instruments_equal':True,'noop_provider_bytes_unchanged':True,
        'measured_source_files_unchanged':True,'protected_anchor_states_unchanged':True,
        'protected_anchors_were_absent':all(not s['exists'] for s in before_anchors.values()),
        'limits':['Seven-symbol/window acceptance, not full-market default-provider refresh.',
            'No default provider promotion, daily refresh, model training or trading.',
            'Default-param empty-staging/noop error remains separate; this noop explicitly restages original window.',
            'Per-file writes atomic; interrupted multi-file updates require backup recovery/rebuild.']})
    print('Real-lake QL11 acceptance PASS',len(comparisons),'field comparisons,',len(calendar),'calendar rows')


if __name__=='__main__':
    main()
