#!/usr/bin/env python3
"""Compare saved raw-image prediction to human truth AFTER prediction generation.
No model calls, no image-specific predictor code; Python standard library only.
The scorer matches by text, classification, numeric value and association;
source truth IDs are used ONLY to name check results, not required in predictions.
Do not use truth/ to construct predictions.
"""
import argparse, json, math, re, sys
from pathlib import Path

def norm(s):
    return re.sub(r'\s+','',str(s)).casefold().replace('º','°').replace('Ø','ø')

def numeric_equal(a,b,tol=1e-6):
    if isinstance(a,bool) or isinstance(b,bool):return a is b
    if isinstance(a,(int,float)) and isinstance(b,(int,float)):
        return math.isfinite(a) and math.isfinite(b) and abs(float(a)-float(b))<=tol
    return a==b

def compare_nested(actual,expected,tol):
    if isinstance(expected,list):
        if not isinstance(actual,list) or len(actual)!=len(expected):return False
        return all(compare_nested(x,y,tol) for x,y in zip(actual,expected))
    if isinstance(expected,dict):
        if not isinstance(actual,dict):return False
        return all(k in actual and compare_nested(actual[k],v,tol) for k,v in expected.items())
    return numeric_equal(actual,expected,tol)

def cyclic_equal_profile(actual,expected,tol):
    if not isinstance(actual,list) or len(actual)!=len(expected):return False
    n=len(expected)
    for sequence in (actual,list(reversed(actual))):
        for shift in range(n):
            if compare_nested(sequence[shift:]+sequence[:shift],expected,tol):return True
    return False

def read_path(obj,path):
    for part in path.split('.'):
        if not isinstance(obj,dict) or part not in obj:return False,None
        obj=obj[part]
    return True,obj

def evaluate(truth,pred):
    reports=[]
    if pred.get('drawing_id')!=truth['drawing_id']:
        return {'drawing_id':truth['drawing_id'],'checks_total':0,'checks_passed':0,
                'score_pct':0,'passed':False,'error':'drawing_id mismatch','checks':[]}
    readings=pred.get('readings',[])
    if not isinstance(readings,list):readings=[]
    # Match by observed content, not by reference IDs. A real extractor cannot
    # know an unseen drawing's truth IDs. Multiple identical labels are
    # distinguished by their target associations and consumed only once.
    used=set()
    for expected in truth['visible_readings']:
        found=None
        for i,actual in enumerate(readings):
            if i in used or not isinstance(actual,dict):continue
            ok=(norm(actual.get('text',''))==norm(expected['text']) and
                actual.get('kind')==expected['kind'] and
                actual.get('target')==expected['target'])
            if 'value' in expected:
                ok=ok and compare_nested(actual.get('value'),expected['value'],1e-5)
            if ok:
                found=i;break
        if found is not None:
            used.add(found)
            actual=readings[found]
            reports.append({'id':expected['id'],'category':'visible_reading','pass':True,
                            'expected':expected,'actual':actual,'problem':''})
        else:
            near=[r for i,r in enumerate(readings) if i not in used
                  and isinstance(r,dict) and norm(r.get('text',''))==norm(expected['text'])]
            reports.append({'id':expected['id'],'category':'visible_reading','pass':False,
                            'expected':expected,'actual':near[:5],
                            'problem':'Missing exact observation, classification, value or association'})
    for item in truth['geometry_checks']:
        found,act=read_path(pred,item['path'])
        tolerance=item.get('tolerance',1e-6)
        expected=item['expected']
        if found and item['path']=='geometry.outer_profile_vertices':
            ok=cyclic_equal_profile(act,expected,tolerance)
        else:ok=found and compare_nested(act,expected,tolerance)
        reports.append({'id':item['id'],'category':'geometry','pass':ok,'expected':expected,
                        'actual':act if found else None,'problem':'' if ok else 'Missing or unequal geometric assertion'})
    n=len(reports); passed=sum(x['pass'] for x in reports)
    # Unmatched extra observations need review: could be hallucinations or
    # legitimate additional content missed by this human-curated ground truth.
    extras=[r for i,r in enumerate(readings) if i not in used]
    warnings=[]
    if extras:warnings.append(f'{len(extras)} unmatched/extra predictions need human verification')
    return {'drawing_id':truth['drawing_id'],'checks_total':n,'checks_passed':passed,
            'score_pct':round(100*passed/n,2) if n else 0,
            'passed':bool(n and passed==n and not extras),
            'human_image_review_required':True,'warnings':warnings,'checks':reports}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--truth',type=Path,required=True)
    ap.add_argument('--prediction',type=Path,required=True)
    ap.add_argument('--report',type=Path,required=True)
    args=ap.parse_args()
    t=json.loads(args.truth.read_text());p=json.loads(args.prediction.read_text())
    rep=evaluate(t,p)
    args.report.parent.mkdir(parents=True,exist_ok=True)
    if args.report.exists():raise SystemExit('Refusing to overwrite existing report; use a NEW attempt folder')
    args.report.write_text(json.dumps(rep,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(f"{rep['drawing_id']}: {rep['checks_passed']}/{rep['checks_total']} = {rep['score_pct']:.2f}% | PASS={rep['passed']}")
    for it in rep['checks']:
        if not it['pass']:print('  FAIL',it['id'],it['problem'])
    print('Report:',args.report)
    return 0 if rep['passed'] else 1
if __name__=='__main__':sys.exit(main())
