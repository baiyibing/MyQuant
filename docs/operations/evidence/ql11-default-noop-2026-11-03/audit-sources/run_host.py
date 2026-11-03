"""Default-start/end real-lake noop acceptance; isolated copies only."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from datetime import datetime, timezone

HERE=Path(__file__).resolve().parent
ROOT=HERE/'myquant'
OLD=HERE.parent/'four_repo_batch_next_20261103/myquant'
SEED=HERE.parent/'four_repo_batch_next_20261103/ql11-host-r2/incremental'
EXPECTED='720e42fefaac28d18ea31fecceff35795ebd9c7a'
BASE='bce9613b19ecbd806b96f52e0be5efe09464d11c'
sys.path.insert(0,str(ROOT/'my_scripts'))
from data_root import resolve_stock_1min_none,resolve_index_1min_none


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path,value):
    with Path(path).open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2)
        stream.write('\n')


def snapshot(path):
    return {p.relative_to(path).as_posix():sha(p) for p in path.rglob('*') if p.is_file()}


def pin():
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    dirty=subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip()
    assert head==EXPECTED and not dirty


def anchors():
    base=Path.home()/'.qlib/qlib_data'
    return {str(p):{'exists':p.exists(),'sha256':sha(p) if p.is_file() else None} for p in [
        base/'my_data/calendars/day.txt',base/'my_data_1min/calendars/1min.txt',ROOT/'pred.pkl']}


def main():
    pin()
    for name in ['refresh_mydata_1min.py','stage_1min_from_lake.py']:
        original=subprocess.check_output(['git','show',BASE+':qlib_scripts/'+name],cwd=ROOT)
        assert (OLD/'qlib_scripts'/name).read_bytes().replace(b'\r\n',b'\n')==original
    codes=['SZ000001','SH600000','SZ300750','SH688981','BJ920002','SH000001','SH000300']
    roots=[resolve_stock_1min_none().resolve(strict=True),resolve_index_1min_none().resolve(strict=True)]
    sources={}
    for code in codes:
        found=[]
        for root in roots:
            path=root/('symbol='+code[2:]+'_'+code[:2])/'data.parquet'
            if path.is_file():
                sources[str(path)]=sha(path)
                found.append(path)
        assert found,code
    out=HERE/'host'
    out.mkdir(exist_ok=False)
    seed_before=snapshot(SEED)
    protected=anchors()
    recipe={'registered_utc':datetime.now(timezone.utc).isoformat(),'source_commit':EXPECTED,
        'baseline_source':BASE,'runner_sha256':sha(__file__),'sources':sources,'codes':codes,
        'seed_calendar_last':(SEED/'calendars/1min.txt').read_text().splitlines()[-1],
        'seed_manifest_sha256':hashlib.sha256(json.dumps(seed_before,sort_keys=True).encode()).hexdigest(),
        'protected_anchors_before':protected,'python':sys.version,
        'scope':'Actual CLI no start/end; real lake and isolated provider copies. Not full-market/default-provider deployment.'}
    dump(out/'recipe.json',recipe)
    baseline=out/'baseline-provider'
    fixed=out/'fixed-provider'
    shutil.copytree(SEED,baseline)
    shutil.copytree(SEED,fixed)
    runs=[]
    def run(label,code_root,provider,*,extra=(),selected=None):
        pin()
        stage=out/(label+'-stage')
        stage.mkdir()
        (stage/'previous.parquet').write_bytes(b'prior scratch staging sentinel')
        cmd=[sys.executable,str(code_root/'qlib_scripts/refresh_mydata_1min.py'),
            '--qlib-dir',str(provider),'--staging-dir',str(stage),'--max-workers','2',
            '--receipt',str(out/(label+'-receipt.json')),*extra,'--symbols',*(selected or codes)]
        before=snapshot(provider)
        with (out/(label+'.log')).open('w',encoding='utf-8') as log:
            proc=subprocess.run(cmd,cwd=code_root,stdout=log,stderr=subprocess.STDOUT,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
        assert snapshot(provider)==before,label+' changed provider bytes'
        record={'label':label,'argv':cmd,'exit_code':proc.returncode,
            'provider_files_unchanged':True,'staging_sentinel_preserved':(stage/'previous.parquet').is_file(),
            'receipt_exists':(out/(label+'-receipt.json')).exists()}
        runs.append(record)
        return record
    first=run('baseline',OLD,baseline)
    assert first['exit_code']!=0 and not first['receipt_exists']
    assert 'no 1m parquet staged' in (out/'baseline.log').read_text()
    positive=run('fixed',ROOT,fixed)
    assert positive['exit_code']==0 and positive['receipt_exists']
    receipt=json.loads((out/'fixed-receipt.json').read_text())
    assert receipt['mode']=='noop' and receipt['bars_appended']==receipt['symbols_touched']==0
    proof=receipt['empty_increment_proof']
    assert proof['raw_rows_in_window']==0 and proof['usable_history_rows']>0
    assert proof['provider_close_bins_checked']==len(codes)
    negatives=[('missing-root',fixed,('--lake-root',str(out/'missing-root')),None),
        ('unknown-symbol',fixed,(),codes+['SH999999'])]
    empty=out/'empty-source'
    empty.mkdir()
    negatives.append(('empty-source',fixed,('--lake-root',str(empty),'--skip-index'),None))
    import pandas as pd
    bad=out/'bad-source'
    part=bad/'symbol=000001_SZ'
    part.mkdir(parents=True)
    raw=pd.read_parquet(roots[0]/'symbol=000001_SZ/data.parquet').tail(1).copy()
    raw['close']=float('nan')
    raw.to_parquet(part/'data.parquet',index=False)
    negatives.append(('bad-close',fixed,('--lake-root',str(bad),'--skip-index'),['SZ000001']))
    bad_provider=out/'bad-bin-provider'
    shutil.copytree(SEED,bad_provider)
    (bad_provider/'features/sz000001/close.1min.bin').write_bytes(b'broken')
    negatives.append(('bad-bin',bad_provider,(),None))
    for label,provider,extra,selected in negatives:
        row=run(label,ROOT,provider,extra=extra,selected=selected)
        assert row['exit_code']!=0 and not row['receipt_exists'],label
        if label in ['missing-root','unknown-symbol','empty-source']:
            assert row['staging_sentinel_preserved'],label
    assert snapshot(SEED)==seed_before
    assert anchors()==protected
    assert all(sha(Path(path))==digest for path,digest in sources.items())
    pin()
    dump(out/'acceptance.json',{'status':'PASS_DEFAULT_NOOP_AND_REJECTIONS','package':'P12','audit_id':'QL11',
        'package_closed':False,'source_commit':EXPECTED,'baseline_defect_reproduced':True,
        'default_start_end_omitted':True,'positive_receipt':receipt,'runs':runs,
        'source_files_unchanged':True,'seed_provider_unchanged':True,'protected_anchor_states_unchanged':True,
        'provider_files_verified':len(snapshot(fixed)),
        'limits':['Seven-symbol input request only; no full-market freshness or provider quality signoff.',
            'Default daily/minute calendar and selected pred anchors absent before/after; no default-provider promotion.',
            'Bad-close source and bad-bin provider are clearly labeled private fault copies; no market rewrites.',
            'Source root/list preflight preserves scratch staging; later parse/IO failures do not promise scratch rollback.']})
    print('PASS default noop;',len(negatives),'negative host cases; checked',proof['provider_close_bins_checked'],'provider bins')


if __name__=='__main__':
    main()
