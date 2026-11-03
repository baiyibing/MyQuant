from pathlib import Path
import json
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE/'myquant/qlib_scripts'))
import numpy as np
import pandas as pd
from refresh_mydata_1min import append_new_1min_bars

out = HERE/'alignment-before'
out.mkdir(exist_ok=False)
provider=out/'provider'
(provider/'calendars').mkdir(parents=True)
(provider/'instruments').mkdir()
calendar=pd.date_range('2026-10-30 09:30',periods=4,freq='min').tolist()
(provider/'calendars/1min.txt').write_text('\n'.join(map(str,calendar[:2]))+'\n',encoding='utf-8')
(provider/'instruments/all.txt').write_text('SZ000001\t2026-10-30 09:30:00\t2026-10-30 09:30:00\n',encoding='utf-8')
feature=provider/'features/sz000001/close.1min.bin'
feature.parent.mkdir(parents=True)
np.array([0,10],dtype='<f4').tofile(feature)
inc=out/'inc'
full=out/'full'
inc.mkdir()
full.mkdir()
pd.DataFrame({'date':[calendar[3]],'symbol':['SZ000001'],'close':[11.0]}).to_parquet(inc/'sz000001.parquet',index=False)
append_new_1min_bars(inc,full,provider,calendar[2:],calendar)
values=np.fromfile(feature,dtype='<f4')
actual=[{'time':str(calendar[int(values[0])+i]),'close':float(v)} for i,v in enumerate(values[1:])]
result={'baseline_source':'8f65e08685d47f3ed736409336726654a21723ae','expected':[
    {'time':str(calendar[0]),'close':10.0}, {'time':str(calendar[1]),'close':None},
    {'time':str(calendar[2]),'close':None}, {'time':str(calendar[3]),'close':11.0}],
    'actual':actual,'defect_reproduced':actual[-1]['time']!=str(calendar[3]),
    'scope':'Synthetic counterexample only, no lake/default-provider writes'}
(HERE/'alignment-before.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8',newline='\n')
assert result['defect_reproduced']
print(json.dumps(result,indent=2))
