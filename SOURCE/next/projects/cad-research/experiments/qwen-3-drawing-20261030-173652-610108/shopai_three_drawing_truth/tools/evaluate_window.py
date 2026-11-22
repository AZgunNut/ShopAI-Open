#!/usr/bin/env python3
"""Evaluate 1–3 active drawings from one immutable attempt. No services changed."""
import argparse,json,sys
from pathlib import Path
from score import evaluate

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--attempt',type=Path,required=True)
    p.add_argument('--truth-dir',type=Path,required=True)
    p.add_argument('--drawings',nargs='+',choices=('D1','D2','D3'),required=True)
    a=p.parse_args()
    if len(set(a.drawings))!=len(a.drawings) or len(a.drawings)>3:
        raise SystemExit('Exactly 1–3 distinct active drawings required')
    attempt=a.attempt.expanduser().resolve(strict=True)
    out=attempt/'evaluation';out.mkdir(exist_ok=True)
    results=[]
    for d in a.drawings:
        truth=a.truth_dir/f'{d}.truth.json'
        prediction=attempt/'predictions'/f'{d}.json'
        if not prediction.is_file():
            result={'drawing_id':d,'passed':False,'error':'Missing actual prediction','score_pct':0,'checks_passed':0,'checks_total':0}
        else:
            result=evaluate(json.loads(truth.read_text()),json.loads(prediction.read_text()))
        target=out/f'{d}.report.json'
        if target.exists():
            previous=json.loads(target.read_text())
            if previous!=result:
                raise SystemExit(f'Conflicting saved report; refusing to overwrite {target}. Create a new attempt.')
        else:
            target.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
        results.append(result)
        print(f"{d}: {result['checks_passed']}/{result['checks_total']} = {result['score_pct']}%; PASS={result['passed']}")
    all_passed=all(r['passed'] for r in results)
    summary={'active_drawings':a.drawings,'all_passed':all_passed,'results':[
             {'drawing_id':r['drawing_id'],'passed':r['passed'],'score_pct':r['score_pct']} for r in results],
             'note':'Automated pass still requires visual verification and later blind tests.'}
    target=out/'stage_summary.json'
    if target.exists():raise SystemExit(f'Refusing to overwrite {target}; new attempt required')
    target.write_text(json.dumps(summary,indent=2)+'\n')
    print('WINDOW PASS' if all_passed else 'WINDOW FAIL — Qwen must revise copied source and rerun all active drawings')
    return 0 if all_passed else 1
if __name__=='__main__':sys.exit(main())
