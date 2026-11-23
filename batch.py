"""Local, one-at-a-time benchmark jobs; credentials never enter result files."""
import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import math
import threading
import time

from meetflow import AnalysisError, MODEL, REVIEW_MODEL, analyze, split_text, test_connection
from review_batch import export as export_review

ROOT=Path(__file__).resolve().parent
CORPUS={
    'en':ROOT/'MeetFlow-Benchmark-20/02_inputs/meetings.jsonl',
    'regression':ROOT/'MeetFlow-Benchmark-20/02_inputs/meetings.jsonl',
    'zh':ROOT/'benchmark/zh_holdout.jsonl'}
OUT=ROOT/'benchmark/runs'
LOCK=threading.Lock()
STATE={'running':False,'done':0,'total':0}


def update(**changes):
    with LOCK:
        STATE.update(changes)


def state():
    with LOCK:
        return dict(STATE)


def timings(records):
    groups={}
    for name,group in [('all',records),('short',[r for r in records if r['chunks']==1]),
                       ('long',[r for r in records if r['chunks']>1])]:
        seconds=sorted(r['elapsed_s'] for r in group if r['result'] is not None)
        first=sorted(r["result"]["first_ready_s"] for r in group if r["result"] and "first_ready_s" in r["result"])
        groups[name]={'submitted':len(group),'success':len(seconds),
                      'first_ready_median_s':statistics.median(first) if first else None,
                      'first_ready_p95_s':first[math.ceil(.95*len(first))-1] if first else None,
                      'median_s':statistics.median(seconds) if seconds else None,
                      'p95_s':seconds[math.ceil(.95*len(seconds))-1] if seconds else None,
                      'max_s':max(seconds,default=None),
                      'under_3s_rate':sum(s<3 for s in seconds)/len(group) if group else None}
    return groups


def start(dataset, key, compare=False, background=True):
    if not isinstance(dataset,str) or dataset not in CORPUS or (compare and dataset!='zh'):
        raise AnalysisError('未知评测集。')
    rows=[json.loads(s) for s in CORPUS[dataset].read_text('utf-8').splitlines() if s.strip()]
    if dataset=='regression':
        rows=[r for r in rows if r["id"] in {"M01","M03","M11","M12"}]
    versions=['v1','v2','v3'] if compare else ['v3']
    total=len(rows)*len(versions)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    dest=OUT/(stamp+'-'+dataset)
    with LOCK:
        if STATE['running']:
            raise AnalysisError('已有评测正在进行。','busy')
        STATE.clear()
        STATE.update(running=True,done=0,success=0,total=total,folder=str(dest),message='正在验证模型连接…')
    def run():
        records=[]
        reason=None
        code=None
        try:
            dest.mkdir(parents=True)
            test_connection(key)
            for version in versions:
                for row in rows:
                    mid=row['id'];update(message=f'{version} · {mid} 正在整理')
                    begin=time.perf_counter()
                    try:
                        result=analyze(row['text'],key,version=version,fixed_chunking=True,crosscheck=not compare)
                        error=None
                    except AnalysisError as exc:
                        result=None;error=str(exc)
                    record=dict(id=mid,version=version,chunks=len(split_text(row['text'].strip())),
                                elapsed_s=round(time.perf_counter()-begin,3),result=result,error=error)
                    if dataset=='zh':
                        record.update(text=row['text'],gold_tasks=row['gold_tasks'],gold_summary=row['gold_summary'],
                                      matches=None,ratings=dict.fromkeys(['coverage','fidelity','conciseness','readability']))
                    with (dest/(version+'.jsonl')).open('a',encoding='utf-8') as f:
                        f.write(json.dumps(record,ensure_ascii=False)+'\n')
                    records.append(record)
                    update(done=len(records),success=sum(r['result'] is not None for r in records))
        except AnalysisError as exc:
            reason,code=str(exc),exc.code
        except (ValueError,OSError,KeyError):
            reason,code='批次文件读写或数据处理失败。','local'
        finally:
            report={'dataset':dataset,'versions':versions,'model':MODEL,'review_model':None if compare else REVIEW_MODEL,'planned':total,
                    'submitted':len(records),'skipped':total-len(records),'error':reason,'code':code,
                    'by_version':{v:timings([r for r in records if r['version']==v]) for v in versions}}
            try:
                (dest/'run.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
                if dataset=='zh':
                    export_review(dest)
                with (dest/'status.csv').open('w',encoding='utf-8-sig',newline='') as f:
                    w=csv.writer(f);w.writerow(['version','id','status','elapsed_s','error','first_ready_s'])
                    found={(r['version'],r['id']):r for r in records}
                    for v in versions:
                        for row in rows:
                            r=found.get((v,row['id']))
                            w.writerow([v,row['id'],'skipped' if r is None else 'ok' if r['result'] else 'failed',
                                        r['elapsed_s'] if r else '',r['error'] if r else reason,
                                        (r['result'] or {}).get('first_ready_s','') if r else ''])
            finally:
                update(running=False,message=reason or '评测结束',code=code)
    if background:
        threading.Thread(target=run,daemon=True).start()
    else:
        run()
    return state()


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('dataset',choices=CORPUS)
    p.add_argument('--compare',action='store_true')
    args=p.parse_args()
    info=start(args.dataset,'',args.compare,False)
    print(json.dumps(info,ensure_ascii=False,indent=2))
    raise SystemExit(0 if info['success']==info['total'] else 1)

