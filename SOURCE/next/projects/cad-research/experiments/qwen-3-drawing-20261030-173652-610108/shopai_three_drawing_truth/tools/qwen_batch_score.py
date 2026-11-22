#!/usr/bin/env python3
"""Score already-SAVED raw-image predictions independently, then reveal truth.
Does not execute candidate code, touch originals, or promote any candidate.
Missing predictions are NOT scored and their truth is NOT disclosed.
"""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import sys
import uuid

TOOLS=Path(__file__).resolve().parent
ROOT=TOOLS.parent
sys.path.insert(0,str(TOOLS))
from score import evaluate
import qwen_batch_lab as lab


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--attempts',nargs='*',type=int,help='Optional attempt IDs; defaults to every numbered attempt')
    args=p.parse_args()
    cfg=lab.control()
    active=cfg['active_drawings']
    if not (1<=len(active)<=3) or any(d not in {'D1','D2','D3'} for d in active):
        raise SystemExit('STOP: invalid active drawing stage')
    existing=sorted((ROOT/'attempts').glob('[0-9][0-9][0-9][0-9]*'))
    selected=[x for x in existing if x.is_dir() and x.name.isdigit()
             and (args.attempts is None or int(x.name) in args.attempts)]
    scored=[]
    any_predicted=set()
    for attempt in selected:
        per=[]
        for name in active:
            predicted=attempt/'predictions'/f'{name}.json'
            if not predicted.is_file():
                per.append({'drawing_id':name,'status':'UNTESTED: no saved raw-image prediction'})
                continue
            # Truth is read ONLY after prediction already exists on disk.
            reference=ROOT/'truth'/f'{name}.truth.json'
            if not reference.is_file():
                raise SystemExit('Missing truth: '+str(reference))
            try:
                result=evaluate(json.loads(reference.read_text()),json.loads(predicted.read_text()))
            except (KeyError,ValueError,TypeError,json.JSONDecodeError) as exc:
                result={'drawing_id':name,'passed':False,'score_pct':0,'error':'invalid prediction: '+str(exc)}
            result['prediction_sha256']=digest(predicted)
            result['truth_sha256']=digest(reference)
            report=attempt/'evaluation'/f'{name}.report.json'
            if report.exists():
                prior=json.loads(report.read_text())
                if prior!=result:
                    raise SystemExit('STOP: prediction or truth changed after scoring; refusing overwrite: '+str(report))
            else:
                lab.json_write_new(report,result)
            per.append(result)
            any_predicted.add(name)
        completed=all('score_pct' in r for r in per)
        passed=completed and all(x.get('passed') is True for x in per)
        scored.append({'attempt':int(attempt.name),'complete':completed,'passed':passed,
                       'score_min_pct':min((x['score_pct'] for x in per if 'score_pct' in x),default=None),
                       'score_total_checks':sum(x.get('checks_total',0) for x in per),
                       'score_passed_checks':sum(x.get('checks_passed',0) for x in per),
                       'results':per})
    tested=[x for x in scored if x['complete']]
    tested.sort(key=lambda x:(x['passed'],x['score_min_pct'],x['score_passed_checks']),reverse=True)
    report={'created_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
            'active_drawings':active,'attempts_found':len(scored),
            'fully_tested':len(tested),'not_yet_tested':len(scored)-len(tested),
            'fully_passing':sum(x['passed'] for x in tested),
            'top_five_qualified_candidates':[{'attempt':x['attempt'],
                 'passed':x['passed'],'score_min_pct':x['score_min_pct'],
                 'score_passed_checks':x['score_passed_checks'],
                 'score_total_checks':x['score_total_checks']} for x in tested[:5]],
            'attempts':scored}
    out=ROOT/'batch_lab'/'score_reports'/('score-'+dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%f')+'-'+uuid.uuid4().hex[:6]+'.json')
    lab.json_write_new(out,report)
    print('SCORE REPORT:',out)
    print('TOTAL attempts:',len(scored),'FULLY TESTED:',len(tested),'100% all active:',report['fully_passing'])
    for row in tested[:10]:
        print(f"  {row['attempt']:04d}: {row['score_passed_checks']}/{row['score_total_checks']} checks; worst={row['score_min_pct']}%; PASS={row['passed']}")
    if any_predicted:
        # Completed-test truth is allowed as corrective feedback to Qwen but
        # MUST NEVER be passed to the image predictor or copied into source/.
        feedback={'source':'post-test scoring only',
                  'active_drawings':active,
                  'already_tested_truth':{d:json.loads((ROOT/'truth'/f'{d}.truth.json').read_text()) for d in sorted(any_predicted)},
                  'recent_tested_candidates':[{'attempt':x['attempt'],
                     'results':x['results']} for x in tested[:5]],
                  'warning':'This truth is for debugging Python algorithms AFTER predictions were saved. Never hardcode drawing-specific answers.'}
        lab.json_atomic(ROOT/'batch_lab'/'feedback_for_qwen.json',feedback)
        print('POST-TEST TRUTH FEEDBACK SAVED:',ROOT/'batch_lab'/'feedback_for_qwen.json')
    else:
        print('NO IMAGE PREDICTIONS FOUND: no truth revealed to Qwen.')
    if not tested:
        print('No scored candidate. DO NOT claim pipeline accuracy; first integrate verified predictor.')

if __name__=='__main__':main()
