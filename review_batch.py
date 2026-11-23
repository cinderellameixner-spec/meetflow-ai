"""Blind two-person review of a completed Chinese benchmark run."""
import argparse
import csv
import json
from pathlib import Path
from random import SystemRandom

from evaluate import WEIGHTS, score


def write_csv(path, rows, fields):
    with path.open('x',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields)
        w.writeheader();w.writerows(rows)


def export(run):
    records=[json.loads(line) for path in sorted(run.glob('v*.jsonl'))
             for line in path.read_text('utf-8').splitlines() if line.strip()]
    if not records or any('gold_tasks' not in r for r in records):
        return
    SystemRandom().shuffle(records)
    template=[];mapping=[]
    for idx,row in enumerate(records,1):
        token=f'R{idx:03}'
        mapping.append({'blind_id':token,'id':row['id'],'version':row['version']})
        if row['result'] is None:
            continue
        template.append({'blind_id':token,'source_text':row['text'],
                         'gold_tasks':json.dumps(row['gold_tasks'],ensure_ascii=False),
                         'summary_reference':row['gold_summary'],
                         'predicted_tasks':json.dumps(row['result']['tasks'],ensure_ascii=False),
                         'predicted_summary':json.dumps(row['result']['summary'],ensure_ascii=False),
                         'matches':'',**dict.fromkeys(WEIGHTS,''),'notes':''})
    if not template:
        return
    write_csv(run/'映射_评后打开.csv',mapping,list(mapping[0]))
    for name in ['评审A','评审B']:
        write_csv(run/(name+'.csv'),template,list(template[0]))


def collect_scores(run):
    def read(name):
        with (run/name).open(encoding='utf-8-sig',newline='') as f:
            rows=list(csv.DictReader(f))
        by_id={r['blind_id']:r for r in rows}
        if len(rows)!=len(by_id):
            raise ValueError('存在重复的盲评编号。')
        return by_id
    lookup=read('映射_评后打开.csv')
    reviews=[read(name+'.csv') for name in ('评审A','评审B')]
    resolved=read('仲裁.csv') if (run/'仲裁.csv').exists() else {}
    records={(r['id'],r['version']):r for p in run.glob('v*.jsonl')
             for r in map(json.loads,p.read_text('utf-8').splitlines())}
    expected={bid for bid,m in lookup.items() if records[m['id'],m['version']]['result'] is not None}
    if any(set(review)!=expected for review in reviews):
        raise ValueError('两份评审须覆盖全部成功结果。')
    def rating(row):
        return sorted(json.loads(row['matches'])),{k:float(row[k]) for k in WEIGHTS}
    disagreements=[]
    for bid in sorted(expected):
        m=lookup[bid]; row=records[m['id'],m['version']]
        first,second=[rating(r[bid]) for r in reviews]
        for matches,ratings in (first,second):
            score([{**row,'matches':matches,'ratings':ratings}])
        final=first
        if first!=second:
            if bid not in resolved or not resolved[bid]['matches']:
                disagreements.append(dict(blind_id=bid,review_a=str(first),review_b=str(second),
                                          matches='',**dict.fromkeys(WEIGHTS,'')))
                continue
            final=rating(resolved[bid])
        row['matches'],row['ratings']=final
    if disagreements:
        if not (run/'仲裁.csv').exists():
            write_csv(run/'仲裁.csv',disagreements,list(disagreements[0]))
        raise ValueError(f'有 {len(disagreements)} 条评审分歧，请填写仲裁.csv。')
    return {v:score([r for r in records.values() if r['version']==v])
            for v in sorted({r['version'] for r in records.values()})}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('run_directory',type=Path)
    run=parser.parse_args().run_directory
    try:
        result=collect_scores(run)
    except (KeyError,ValueError,FileNotFoundError,TypeError) as e:
        parser.exit(1,'请检查评审表：'+str(e)+'\n')
    data=json.dumps(result,ensure_ascii=False,indent=2)
    (run/'quality.json').write_text(data,'utf-8');print(data)

