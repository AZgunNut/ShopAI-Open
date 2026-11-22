#!/usr/bin/env python3
"""ShopAI Engineering Selector v2.0: offline, standards-aware OCR hypothesis ranking.

No model inference, no internet, no dependency beyond Python 3.10 stdlib.
Supports the 21 saved ShopAI OCR tile-study comparisons. Input references are
never read during candidate ranking. The output is hypotheses, NOT validated CAD.
"""
from __future__ import annotations
import argparse
from collections import defaultdict, Counter
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import html
import json
import math
from pathlib import Path
import re
from typing import Any

VERSION='2.0.0'
# A loose vocabulary of shop notes; this is not a copy of any proprietary standard.
NOTE_TOKENS={
 'LINEAR DIMENSIONS','RADIUS DIMENSION','ALIGNED DIMENSION','ANGULAR DIMENSION',
 'DIAMETER DIMENSION','LEADER','SECTION','DETAIL','VIEW','TYP','TYPICAL',
 'THRU','THROUGH','REF','REFERENCE','MAX','MIN','NTS','SCALE','BOTH SIDES',
 'EQUALLY SPACED','EQ SP','CHAMFER','CBORE','CSK','COUNTERSINK','COUNTERBORE',
 'SPOTFACE','RADIUS','DIAMETER','DEPTH','MATERIAL','BREAK ALL SHARP EDGES',
 'REMOVE BURRS','DEBURR','UNLESS OTHERWISE SPECIFIED', 'PLACES'
}
PAT_NUM=r'(?:\d+(?:[.,]\d+)?|[.,]\d+|\d+\s+\d+/\d+|\d+/\d+)'
NUM=re.compile(r'^\s*[+\-]?'+PAT_NUM+r'\s*$',re.I)
# ASME and ISO generally present R / diameter indicators as prefixes; real legacy
# shop drawings (including this reference) sometimes use suffixes. Both accepted.
RADIUS_PRE=re.compile(r'^\s*(SR|CR|R)\s*'+PAT_NUM+r'\s*$',re.I)
RADIUS_POST=re.compile(r'^\s*'+PAT_NUM+r'\s*(SR|CR|R)\s*$',re.I)
DIAM_PRE=re.compile(r'^\s*(?:[⌀ØΦ]|DIA\.?|DIAM\.?|S⌀)\s*'+PAT_NUM+r'\s*$',re.I)
DIAM_POST=re.compile(r'^\s*'+PAT_NUM+r'\s*(?:[⌀ØΦ]|DIA\.?|DIAM\.?)\s*$',re.I)
ANGLE=re.compile(r'^\s*[+\-]?'+PAT_NUM+r'\s*(?:°|DEG\.?|DEGREES?)\s*$',re.I)
TOLERANCE=re.compile(r'^\s*[+\-]?'+PAT_NUM+r'\s*(?:±|\+/-|\+-)\s*'+PAT_NUM+r'\s*$',re.I)
PLUSMINUS=re.compile(r'^\s*[+\-]?'+PAT_NUM+r'\s*\+\s*'+PAT_NUM+r'\s*[-−]\s*'+PAT_NUM+r'\s*$',re.I)
MULTI=re.compile(r'^\s*\d+\s*(?:X|×|PLCS?\.?|PLACES?)\s*(?:'+PAT_NUM+r'|[⌀ØΦ]|R)',re.I)
PLACES=re.compile(r'^\s*\d+\s*(?:PLACES?|PLCS?\.?)\s*$',re.I)
COORD=re.compile(r'^\s*(?:START\s*)?X\s*[+\-]?'+PAT_NUM+r'\s*[,; ]\s*Y\s*[+\-]?'+PAT_NUM+r'\s*$',re.I)
COORD_DOT=re.compile(r'^\s*(?:START\s*)?X\s*[+\-]?'+PAT_NUM+r'\.Y\s*[+\-]?'+PAT_NUM+r'\s*$',re.I)
THREAD=re.compile(r'^\s*(?:M\s*\d+(?:[.,]\d+)?\s*[x×]\s*\d+(?:[.,]\d+)?|\d+\s*/\s*\d+\s*[-–]\s*\d+\s*(?:UNC|UNF|UNEF|UN)?|\d+(?:[.,]\d+)?\s*[-–]\s*\d+\s*(?:UNC|UNF|UNEF))\b',re.I)
SURFACE=re.compile(r'^\s*(?:RA|RZ)\s*'+PAT_NUM+r'\s*(?:µm|um|uin|μm)?\s*$',re.I)
DATUM=re.compile(r'^\s*(?:DATUM\s+)?[A-Z]\s*$',re.I)
# Typical shop callouts: holes, depth, machining operations, allowances, fits.
# These recognize notation classes only; they DO NOT validate machining meaning.
HOLE_CALLOUT=re.compile(
    r'^\s*(?:\d+\s*[x×]\s*)?(?:[⌀ØΦ]|DIA\.?|DIAM\.?)\s*'
    +PAT_NUM+r'\s*(?:(?:THRU|THROUGH|BLIND|DEPTH|\u21a7|\u2304|H\d+|[x×]\s*\d+))*\s*$',re.I)
COUNTERBORE=re.compile(r'^\s*[⌴]\s*(?:[⌀ØΦ]|DIA\.?)*\s*'+PAT_NUM+
                         r'(?:\s*[↧]\s*'+PAT_NUM+r')?\s*$',re.I)
COUNTERSINK=re.compile(r'^\s*[⌵]\s*(?:[⌀ØΦ]|DIA\.?)*\s*'+PAT_NUM+
                         r'(?:\s*[x×]\s*'+PAT_NUM+r'\s*(?:°|DEG\.?))?\s*$',re.I)
DEPTH=re.compile(r'^\s*(?:↧|DEPTH\s*)\s*'+PAT_NUM+r'\s*$',re.I)
THICKNESS=re.compile(r'^\s*'+PAT_NUM+r'\s*(?:THK|THICK|THICKNESS)\s*$',re.I)
CHAMFER=re.compile(r'^\s*'+PAT_NUM+r'\s*[x×]\s*'+PAT_NUM+r'\s*(?:°|DEG\.?)?\s*(?:CHAMFER|C\s*/?\s*F)?\s*$',re.I)

GDNT_CHARS=set('⌖⏥⏤○⌭⌯∠∥⟂⌒↗◎ⓂⓁⓈ')


def compact(text:str)->str:
    return re.sub(r'\s+','',str(text).upper().strip())


def identity_key(text:str)->str:
    """Only collapse trivial whitespace, case, and trailing decorative comma/semicolon.
    Do not equate `0` with `O`, comma with dot, or delete internal hyphens.
    """
    return compact(text).rstrip(',;')


def classify(text:str)->dict:
    t=str(text).strip(); k=compact(t)
    if not t: return dict(kind='empty',quality=-3,style=None,flags=['EMPTY'])
    lead=bool(re.match(r'^[—–:_;*•#]+',t))
    tail=bool(re.search(r'[-—–.:;+*#]$',t))
    weird=bool(re.search(r'[□中＊★…#]',t))
    flags=[]
    if lead:flags.append('LEADING_STRAY_MARK')
    if tail:flags.append('TRAILING_STRAY_MARK')
    if weird:flags.append('UNCERTAIN_OCR_SYMBOL')
    style=None
    if COUNTERBORE.fullmatch(t):kind,quality='counterbore',2.0
    elif COUNTERSINK.fullmatch(t):kind,quality='countersink',2.0
    elif HOLE_CALLOUT.fullmatch(t) and ('THRU' in k or 'THROUGH' in k or 'BLIND' in k):kind,quality='hole_callout',2.05
    elif DEPTH.fullmatch(t):kind,quality='depth',2.0
    elif THICKNESS.fullmatch(t):kind,quality='thickness',1.9
    elif THREAD.fullmatch(t):kind,quality='thread_callout',2.0
    elif COORD.fullmatch(t):kind,quality='coordinate',2.0;style=('coordinate_delimiter','comma_or_space')
    elif COORD_DOT.fullmatch(t):kind,quality='coordinate',0.35;flags.append('SUSPICIOUS_COORDINATE_SEPARATOR')
    elif (m:=RADIUS_PRE.fullmatch(t)):kind,quality='radius',2.2;style=('radius_order','prefix')
    elif (m:=RADIUS_POST.fullmatch(t)):kind,quality='radius',2.2;style=('radius_order','suffix')
    elif (m:=DIAM_PRE.fullmatch(t)):kind,quality='diameter',2.2;style=('diameter_order','prefix')
    elif (m:=DIAM_POST.fullmatch(t)):kind,quality='diameter',2.2;style=('diameter_order','suffix')
    elif ANGLE.fullmatch(t):kind,quality='angle',2.1;style=('angle_notation','degree_symbol' if '°' in t else 'word')
    elif TOLERANCE.fullmatch(t) or PLUSMINUS.fullmatch(t):kind,quality='tolerance',2.1
    elif PLACES.fullmatch(t):kind,quality='quantity_note',1.9
    elif MULTI.match(t):kind,quality='quantity_dimension',1.7
    elif SURFACE.fullmatch(t):kind,quality='surface_finish',1.7
    elif NUM.fullmatch(t):kind,quality='linear_or_value',1.8
    elif k.replace(' ','') in {compact(v) for v in NOTE_TOKENS}:kind,quality='shop_note',1.7
    elif re.fullmatch(r'[A-Z][A-Z\s]{2,}',t.upper()) and len(t)>4:
        kind,quality='text_note',.8
    elif re.fullmatch(r'\(?[+\-]?\d+(?:[.,]\d+)?\)?',t):kind,quality='reference_or_linear',1.5
    elif len(k)==1 and k in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ':kind,quality='datum_or_letter',.5
    elif any(c in GDNT_CHARS for c in t) or ('|' in t and any(c.isdigit() for c in t)):
        kind,quality='gdt_or_fcf_candidate',.2;flags.append('REQUIRES_STRUCTURAL_GDT_PARSER')
    else:
        kind,quality='unclassified',-0.25
        if re.search(r'\d[.,][A-Z]',k) and re.search(r'R$',k):
            quality-=.8;flags.append('LETTER_IN_NUMERIC_FIELD')
        if 'DIA' in k or 'R' in k or '°' in k:flags.append('PARTIAL_DIMENSION_TOKEN')
    # OCR often sees a leader as a tiny terminal dash. Penalize, never silently remove.
    if tail:quality-=1.4
    if lead:quality-=.9
    if weird:quality-=1.1
    # Unusually garbled short engineering notations are weak even with OCR confidence.
    if re.search(r'\d[.,][A-Z]',k) and re.search(r'(R|DIA)$',k):
        quality-=.65
    if re.search(r'\d[.,]\d',k): style_num='decimal_comma' if re.search(r'\d,\d',k) else 'decimal_dot'
    else: style_num=None
    return dict(kind=kind,quality=round(quality,4),style=style,
                decimal_style=style_num, flags=flags)


def robust_conf(d:dict)->float:
    c=d.get('confidence')
    try: return max(0,min(1,float(c))) if c is not None else .5
    except (TypeError,ValueError):return .5


def infer_style(groups:list[dict])->dict:
    """Only high-confidence whole-image, unambiguous printed tokens vote for style.
    No reference answers, no benchmark labels, and no vote from later crops.
    """
    bins=defaultdict(lambda:defaultdict(dict))
    seen_loc=set()
    for g in groups:
        byprof=defaultdict(list)
        for d in g.get('items',[]):
            if int(d.get('tile_level',0))!=0:continue
            byprof[str(d.get('profile','unknown'))].append(d)
        if not byprof:continue
        for p,ds in byprof.items():
            for d in ds:
                txt=str(d.get('text',''));pr=classify(txt)
                if robust_conf(d)<.83 or pr['quality']<1.5:continue
                for item in (pr['style'],('decimal_separator',pr['decimal_style']) if pr['decimal_style'] else None):
                    if not item:continue
                    family,value=item
                    # one vote per original spatial location, across all profiles
                    key=(g.get('id',id(g)),family)
                    weight=min(1,robust_conf(d))
                    bins[family][value][key]=max(bins[family][value].get(key,0),weight)
    styles={}
    for family,choices in bins.items():
        sums={key:sum(loc.values()) for key,loc in choices.items()}
        ranks=sorted(sums.items(),key=lambda a:(-a[1],a[0]))
        best=ranks[0] if ranks else None
        support=len(choices[best[0]]) if best else 0
        share=best[1]/max(.001,sum(sums.values())) if best else 0
        styles[family]={'preferred':best[0] if best and support>=2 and share>=.62 else None,
                        'supporting_locations':support,'share':round(share,3),
                        'alternatives':{k:round(v,2) for k,v in sums.items()},
                        'strength':round(min(.35, .35*share*min(1,support/4)),3) if best and support>=2 else 0}
    return styles


def style_bonus(parsed:dict,styles:dict)->float:
    # A learned preference is SOFT. Close cousins are still valid.
    bonus=0.0
    for item in (parsed.get('style'),
                 ('decimal_separator',parsed.get('decimal_style')) if parsed.get('decimal_style') else None):
        if item is None:continue
        family,value=item
        st=styles.get(family)
        if st and st['preferred']:
            bonus+=st['strength'] if st['preferred']==value else -.35*st['strength']
    return bonus


def rank_group(group:dict,styles:dict)->dict:
    """Rank distinct actual observed candidate strings. Never synthesize a character.

    A profile's whole reading counts at most once, as does its BEST tile reading.
    A pile of overlapping tiles cannot outvote whole-image information.
    """
    bins=defaultdict(list)
    for d in group.get('items',[]):
        text=str(d.get('text','')).strip()
        if text: bins[identity_key(text)].append(d)
    choices=[]
    for key,obs in bins.items():
        pr=max((classify(o['text']) for o in obs),key=lambda p:p['quality'])
        conf=max(robust_conf(d) for d in obs)
        whole_prof={str(d.get('profile','unknown')) for d in obs if int(d.get('tile_level',0))==0}
        profiles={str(d.get('profile','unknown')) for d in obs}
        whole=[robust_conf(d) for d in obs if int(d.get('tile_level',0))==0]
        tiles=[robust_conf(d)*(0.45 if d.get('near_tile_boundary') else 1.0)
               for d in obs if int(d.get('tile_level',0))>0]
        base=max([.55+.45*c for c in whole],default=0.0)*1.05
        near=max([.55+.45*c for c in tiles],default=0.0)*.43
        independent=.18*max(0,len(whole_prof)-1)
        score=base+near+independent+pr['quality']+style_bonus(pr,styles)
        # Text only present in clipped tiles is more suspect.
        if not whole and tiles and all(d.get('near_tile_boundary') for d in obs):score-=.65
        representative=max(obs,key=lambda d:(int(d.get('tile_level',0))==0,
                                               classify(d['text'])['quality'],robust_conf(d)))
        choices.append({'text':representative['text'],'key':key,'score':round(score,5),
                        'kind':pr['kind'],'parse_quality':pr['quality'],
                        'flags':sorted(set(pr['flags'])), 'confidence_peak':round(conf,3),
                        'whole_profiles':sorted(whole_prof),'profiles':sorted(profiles),
                        'tile_samples':sum(int(d.get('tile_level',0))>0 for d in obs),
                        'support_examples':len(obs), 'style_bonus':round(style_bonus(pr,styles),3)})
    choices.sort(key=lambda c:(-c['score'],-len(c['whole_profiles']),-c['parse_quality'],c['key']))
    if not choices:
        return {'id':group.get('id'), 'anchor':group.get('anchor'),
                'selected_text':None,'state':'NO_DETECTION','alternatives':[]}
    first=choices[0];margin=(first['score']-choices[1]['score']) if len(choices)>1 else 0
    state='CANDIDATE_ONLY'
    if first['parse_quality']<0 or first['flags']:state='REVIEW_UNCERTAIN_TOKEN'
    elif len(choices)>1 and margin<.45:state='REVIEW_CONFLICT'
    elif not first['whole_profiles']:state='REVIEW_TILE_ONLY'
    elif first['kind'] in ('gdt_or_fcf_candidate','unclassified'):state='REVIEW_COMPLEX_NOTATION'
    else:state='PLAUSIBLE_UNVERIFIED'
    return {'id':group.get('id'), 'anchor':group.get('anchor'),
            'selected_text':first['text'],'normalized_text':first['key'],
            'kind':first['kind'],'state':state,'margin':round(margin,4),
            'alternatives':choices,'boundary_fragments':group.get('boundary_fragments',0)}


def evaluate_heldout(rows: list, refs:dict)->dict:
    """Offline evaluation ONLY after selection; never used in parsing or ranking."""
    # Legacy provisional 24 annotation labels, same normalized convention as v1.
    boxes={r['id']:r['bbox_px'] for r in refs['regions'] if r['id'] in refs['expected']}
    expected=refs['expected']
    per={}
    for rid,truth in expected.items():
        x1,y1,x2,y2=boxes[rid];area=max(1,(x2-x1)*(y2-y1))
        contenders=[]
        for grp in rows:
            for d in grp.get('source_items',[]):
                a,b,c,e=d['bbox_original_px']
                overlap=max(0,min(c,x2)-max(a,x1))*max(0,min(e,y2)-max(b,y1))/area
                if overlap>=.4:
                    contenders.append(grp)
                    break
        def norm(x):return compact(x).rstrip(',;')
        per[rid]={'expected':truth,'available':any(norm(c['text'])==norm(truth)
                     for grp in contenders for c in grp.get('alternatives',[])),
                  'selected':any(norm(grp.get('selected_text',''))==norm(truth)
                     for grp in contenders)}
    return {'reference_count':len(per),'candidate_available':sum(v['available'] for v in per.values()),
            'auto_selected':sum(v['selected'] for v in per.values()),
            'per_region':per,'warning':'Provisional evaluation only. No reference labels used during inference.'}


def analyze(payload:dict,provisional_refs:dict|None=None)->dict:
    comparison=[]
    for row in payload.get('rows',[]):
        styles=infer_style(row['groups'])
        out=[]
        for g in row['groups']:
            r=rank_group(g,styles)
            r['source_items']=g.get('items',[])
            out.append(r)
        baseline=row.get('provisional_evaluation',{})
        summary={'profiles':row['profiles'],'plan':row['plan'],
                 'passes':row.get('unique_view_passes'),
                 'seconds':row.get('measured_or_partial_inference_seconds'),
                 'style':styles,
                 'baseline_v1_selected':baseline.get('automatic_selected_exact'),
                 'results':out,
                 'review_count':sum(x['state'].startswith('REVIEW') for x in out)}
        if provisional_refs:
            summary['provisional_test']=evaluate_heldout(out,provisional_refs)
        comparison.append(summary)
    return {'selector_version':VERSION,'generated_utc':datetime.now(timezone.utc).isoformat(),
            'source':payload.get('source_image'),'input_study_version':payload.get('version'),
            'rows':comparison, 'reference_isolation':'reference used only after scoring; no tuning during processing'}


def create_report(out:dict)->str:
    e=html.escape
    lines=['<!DOCTYPE html><html><head><meta charset="utf-8"><title>ShopAI Selector v2</title>',
           '<style>body{font:15px system-ui,Arial;max-width:1250px;margin:34px auto;padding:0 20px;color:#1d2939}table{border-collapse:collapse;width:100%}td,th{border:1px solid #dae1eb;padding:7px;text-align:left;vertical-align:top}th{background:#dbeafe}tr:nth-child(even){background:#f8fafc} .note{background:#fff5d6;padding:14px;border-left:4px solid #d69e11}details{margin:20px 0}code{color:#135e76}</style></head><body>',
           '<h1>ShopAI — Engineering OCR Selector v2</h1>',
           '<p class="note"><b>Candidate interpretations only, not certified engineering dimensions.</b> No ground truth is used to choose OCR readings. Automated correctness comparisons use one provisional reference drawing and are not independent validation. CAD geometry and GD&T semantics are not verified.</p>',
           '<h2>All 21 original test plans</h2><table><thead><tr><th>Profiles</th><th>Views</th><th>Inference</th><th>v1 selected /24</th><th>v2 selected /24</th><th>Review flags</th></tr></thead><tbody>']
    for row in out['rows']:
        score=row.get('provisional_test',{}).get('auto_selected','—')
        lines.append('<tr>'+''.join('<td>'+e(str(v))+'</td>' for v in
            (row['profiles'],row['plan'],f"{row['seconds']}s",row['baseline_v1_selected'],score,row['review_count']))+'</tr>')
    lines.append('</tbody></table>')
    for row in out['rows']:
        lines.append(f'<details><summary><b>{e(row["profiles"])} {e(row["plan"])}</b> — expand styles, selections and competing candidates</summary>')
        lines.append('<p>Inferred drawing style: <code>'+e(json.dumps(row['style'],sort_keys=True))+'</code></p>')
        lines.append('<table><tr><th>Location</th><th>Selected</th><th>Classification</th><th>State</th><th>Alternatives</th></tr>')
        for g in row['results']:
            alternatives=' / '.join(f"{c['text']} [{c['score']:.2f}]" for c in g['alternatives'][:6])
            lines.append('<tr>'+''.join('<td>'+e(str(v))+'</td>' for v in (g['anchor'],g['selected_text'],g.get('kind'),g['state'],alternatives))+'</tr>')
        lines.append('</table></details>')
    lines.append('<p>Full alternatives, flags, OCR provenance and provisional per-region comparisons are in <code>selector_v2_results.json</code>. Experimental inputs are unchanged.</p></body></html>')
    return '\n'.join(lines)


def write_csv(out:dict,path:Path):
    import csv
    with path.open('w',newline='',encoding='utf-8') as fp:
        writer=csv.writer(fp)
        writer.writerow(['profiles','plan','group_id','bbox','selected_text','kind','state','margin','alternatives'])
        for r in out['rows']:
            for g in r['results']:
                writer.writerow([r['profiles'],r['plan'],g['id'],json.dumps(g['anchor']),
                                 g['selected_text'],g.get('kind'),g['state'],g.get('margin'),
                                 json.dumps(g['alternatives'],ensure_ascii=False)])


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input',type=Path,required=True,help='Saved tile study results.json')
    ap.add_argument('--output',type=Path,required=True,help='Write only inside new v2 directory')
    ap.add_argument('--reference',type=Path,help='OPTIONAL provisional reference for post-hoc audit only')
    args=ap.parse_args()
    if args.input.resolve()==args.output.resolve(): ap.error('input and output cannot match')
    payload=json.loads(args.input.read_text(encoding='utf-8'))
    refs=None
    if args.reference:
        src=json.loads(args.reference.read_text(encoding='utf-8'))
        refs={'regions':src['regions'],'expected':src['expected']}
    result=analyze(payload,refs)
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/'selector_v2_results.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    (args.output/'report.html').write_text(create_report(result),encoding='utf-8')
    write_csv(result,args.output/'selector_v2_candidates.csv')
    for r in result['rows']:
        extra=r.get('provisional_test',{})
        print(f"PROFILE={r['profiles']} PLAN={r['plan']} "
              f"V1={r['baseline_v1_selected']} V2={extra.get('auto_selected','unscored')} "
              f"REVIEW={r['review_count']}")
    print('REPORT='+str(args.output/'report.html'))
    print('NO_OCR_RERUN_NO_INPUT_CHANGES')

if __name__=='__main__':main()
