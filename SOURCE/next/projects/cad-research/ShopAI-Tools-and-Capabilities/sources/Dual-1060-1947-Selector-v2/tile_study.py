#!/usr/bin/env python3
"""ShopAI OCR Tile Study v1: two saved Paddle profiles, reusable 4/8/16 tiles.

No network. Keeps PaddleOCR loaded once for all new predictions. SQLite commits
on every completed tile; metadata + gzipped content-addressed predictions;
whole-image predictions come from the independently saved OCR Lab v1 results.
No OCR output is assumed correct just because another tile agrees with it.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
import gzip
import hashlib
import html
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import statistics
import sys
import time
import traceback
import fcntl

import legacy_lab as L

VERSION = 'tile-study-1.0.0'
PROFILES = (1060, 1947)
LEVELS = (4, 8, 16)
# Explicitly include six requested tests and the fully cumulative test.
PLANS = {
    'whole': (),
    'whole+4': (4,),
    'whole+8': (8,),
    'whole+16': (16,),
    'whole+4+16': (4,16),
    'whole+4+8': (4,8),
    'whole+4+8+16': (4,8,16),
}
GRID = {4:(2,2), 8:(4,2), 16:(4,4)}


def sha(obj):
    return hashlib.sha256(L.stable_json(obj).encode('utf-8')).hexdigest()


def read_gzip_json(path):
    with gzip.open(path, 'rt', encoding='utf8') as fp:
        return json.load(fp)


def overlap_tiles(w:int, h:int, n:int, fraction:float=.24):
    """Fixed whole-image pixel-space tiles with 24% intentional overlap."""
    cols, rows = GRID[n]
    out=[]
    tw=min(w, math.ceil(w/(cols-(cols-1)*fraction)))
    th=min(h, math.ceil(h/(rows-(rows-1)*fraction)))
    xs=[int(round(i*(w-tw)/(cols-1))) for i in range(cols)] if cols>1 else [0]
    ys=[int(round(i*(h-th)/(rows-1))) for i in range(rows)] if rows>1 else [0]
    for iy,y in enumerate(ys):
        for ix,x in enumerate(xs):
            out.append({'level':n, 'index':iy*cols+ix, 'col':ix, 'row':iy,
                        'rect':[x,y,min(w,x+tw),min(h,y+th)]})
    return out


def coords_match(a,b):
    """Guard against merging neighboring labels solely because text agrees."""
    ax1,ay1,ax2,ay2=a;bx1,by1,bx2,by2=b
    iw=max(0,min(ax2,bx2)-max(ax1,bx1)); ih=max(0,min(ay2,by2)-max(ay1,by1))
    ia=iw*ih
    aa=max(1,(ax2-ax1)*(ay2-ay1));ba=max(1,(bx2-bx1)*(by2-by1))
    ca=((ax1+ax2)/2,(ay1+ay2)/2);cb=((bx1+bx2)/2,(by1+by2)/2)
    dist=math.hypot(ca[0]-cb[0],ca[1]-cb[1])
    small=min(aa,ba); large=max(aa,ba)
    return (ia/small>.57 and ia/large>.22 and dist<max(20, math.sqrt(large)*.5))


def near_boundary(bbox,rect,margin=5.0):
    x1,y1,x2,y2=bbox; a,b,c,d=rect
    return min(x1-a, y1-b, c-x2, d-y2)<margin


def globalize(detections,tile,profile):
    a,b,c,e=tile['rect']
    result=[]
    for entry in detections:
        d=dict(entry)
        box=d.get('bbox_original_px')
        if box is None: continue
        # The legacy OCR function already unscaled pixel coordinates; add crop origin.
        d['bbox_original_px']=[round(x+a,2) if i%2==0 else round(x+b,2)
                               for i,x in enumerate(box)]
        d['text']=str(d['text']).strip()
        if not d['text']:continue
        d['profile']=profile
        d['tile_level']=tile['level']
        d['tile_index']=tile['index']
        d['near_tile_boundary']=(tile['level']>0 and
            near_boundary(d['bbox_original_px'],tile['rect']))
        # Original crop rectangle is recorded so a crossing token can be re-cropped.
        d['source_rect_original_px']=tile['rect']
        result.append(d)
    return result


def open_original(source:Path,img_hash:str, profiles=PROFILES):
    conn=sqlite3.connect(f'file:{source/"lab.sqlite3"}?mode=ro',uri=True)
    run=conn.execute('SELECT run_id, image_sha256, variant FROM runs ORDER BY created_utc DESC LIMIT 1').fetchone()
    if not run or run[1]!=img_hash:
        raise RuntimeError('Original 2,000-trial database does not match source image SHA256')
    configs={}; full={}; sec={}
    for p in profiles:
        row=conn.execute("SELECT config_json,output_path,inference_seconds,status FROM trials WHERE run_id=? AND trial_index=?",(run[0],p)).fetchone()
        if not row or row[3]!='done': raise RuntimeError(f'Saved trial {p} missing/incomplete')
        data=read_gzip_json(source/row[1]); configs[p]=json.loads(row[0]); full[p]=data['detections'];sec[p]=float(row[2]);
    conn.close()
    return configs,full,sec,run[2]


def init_database(path):
    con=sqlite3.connect(str(path),timeout=60)
    con.execute('PRAGMA journal_mode=WAL'); con.execute('PRAGMA synchronous=FULL')
    con.executescript('''
    CREATE TABLE IF NOT EXISTS tile_predictions (
      key TEXT PRIMARY KEY, profile INTEGER NOT NULL, level INTEGER NOT NULL,
      tile_index INTEGER NOT NULL, crop_json TEXT NOT NULL, config_json TEXT NOT NULL,
      status TEXT NOT NULL, output_path TEXT, input_sha TEXT NOT NULL,
      started_utc TEXT, done_utc TEXT, preprocess_seconds REAL,
      infer_seconds REAL, boxes INTEGER, error_text TEXT);
    CREATE INDEX IF NOT EXISTS tiles_lookup ON tile_predictions(profile,level,tile_index);
    CREATE TABLE IF NOT EXISTS study_metadata(k TEXT PRIMARY KEY,v TEXT NOT NULL);
    ''')
    con.commit()
    return con


def record_job(con,key,profile,tile,cfg,img_hash):
    con.execute('''INSERT INTO tile_predictions(key,profile,level,tile_index,crop_json,config_json,status,input_sha,started_utc)
       VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET
       status='running',started_utc=excluded.started_utc,error_text=NULL''',
       (key,profile,tile['level'],tile['index'],L.stable_json(tile),L.stable_json(cfg),
        'running',img_hash,L.now_utc()))
    con.commit()


def record_done(con,key,rel,pre_s,infer_s,boxes):
    con.execute('''UPDATE tile_predictions SET status='done',output_path=?,preprocess_seconds=?,
      infer_seconds=?,boxes=?,done_utc=?,error_text=NULL WHERE key=?''',
      (str(rel),pre_s,infer_s,boxes,L.now_utc(),key));con.commit()


def record_failure(con,key,exc):
    con.execute("UPDATE tile_predictions SET status='error',error_text=?,done_utc=? WHERE key=?",
                (str(exc)[:5000],L.now_utc(),key));con.commit()


def tiles_for_profile(bgr,pipe,cfg,p,tile,work,con,image_hash,model_hash,force=False):
    import cv2
    key=sha({'version':VERSION,'image_sha256':image_hash,'model_sha256':model_hash,
             'profile':p,'config':cfg,'rect':tile['rect'],'level':tile['level']})
    row=con.execute('SELECT status,output_path FROM tile_predictions WHERE key=?',(key,)).fetchone()
    if row and row[0]=='done' and (work/row[1]).is_file() and not force:
        data=read_gzip_json(work/row[1]);return data['detections'],data['infer_seconds'],True
    record_job(con,key,p,tile,cfg,image_hash)
    try:
        x1,y1,x2,y2=tile['rect']; crop=bgr[y1:y2,x1:x2].copy()
        t=time.perf_counter();pre=L.preprocess(crop,cfg['pre']); pre_s=time.perf_counter()-t
        t=time.perf_counter();predict=pipe.predict(pre,**cfg['paddle'])
        detections,raw=L.collect_predictions(predict,float(cfg['pre']['scale']))
        infer_s=time.perf_counter()-t
        globalized=globalize(detections,tile,p)
        data={'schema':1,'version':VERSION,'image_sha256':image_hash,
              'profile':p,'tile':tile,'config':cfg,
              'preprocess_seconds':pre_s,'infer_seconds':infer_s,
              'detections':globalized,'raw_paddle_results':raw}
        content=L.stable_json(data).encode('utf-8');h=hashlib.sha256(content).hexdigest()
        rel=Path('objects')/h[:2]/f'{h}.json.gz'
        L.atomic_write(work/rel,gzip.compress(content,compresslevel=6,mtime=0))
        record_done(con,key,rel,pre_s,infer_s,len(globalized))
        return globalized,infer_s,False
    except Exception as ex:
        record_failure(con,key,ex);raise


def simple_norm(t):
    t=str(t).strip().upper()
    t=re.sub(r'\s+','',t)
    return t.rstrip(',;')


def fuse_observations(observations):
    """Position-based consolidation, independently from any answer key.

    The whole detection is the anchor; closer tiles add conflicting readings.
    Boundary fragments are marked, not silently invented into words.
    """
    obs=sorted(observations,key=lambda d:(d['tile_level']!=0,d['tile_level'],d['profile'],d['tile_index']))
    groups=[]
    for d in obs:
        box=d['bbox_original_px']
        options=[]
        for i,g in enumerate(groups):
            if coords_match(g['anchor'],box):
                ax,ay,bx,by=g['anchor']; cx,cy,dx,dy=box
                area=max(0,min(bx,dx)-max(ax,cx))*max(0,min(by,dy)-max(ay,cy))
                options.append((area,i))
        if options:
            groups[max(options)[1]]['items'].append(d)
        else:
            groups.append({'anchor':box,'items':[d]})
    # Candidate ranking: multiple distinct views of SAME profile aren't independent
    # OCR engines; collapse within source-level when voting.
    for idx,g in enumerate(groups):
        scores=defaultdict(float); rawby=defaultdict(list)
        sources=defaultdict(dict)
        for d in g['items']:
            norm=simple_norm(d['text'])
            if not norm:continue
            conf=d.get('confidence')
            conf=max(0,min(1,float(conf))) if isinstance(conf,(int,float)) else .5
            w=(.6 + .4*conf)*(0.36 if d.get('near_tile_boundary') else 1)
            if d['tile_level']==0: w*=1.25
            source=(d['profile'],d['tile_level'])
            sources[norm][source]=max(sources[norm].get(source,0),w)
            rawby[norm].append(d)
        for txt,weights in sources.items(): scores[txt]=sum(weights.values())
        if scores:
            top=max(scores,key=lambda t:(scores[t],len(t)))
            alternatives=sorted(({'text':k,'evidence_score':round(v,3),'sources':len(sources[k]),
                     'examples':len(rawby[k])} for k,v in scores.items()),
                   key=lambda x:-x['evidence_score'])
        else:top='';alternatives=[]
        g['id']=idx;g['selected_text']=top;g['alternatives']=alternatives
        g['boundary_fragments']=sum(bool(d.get('near_tile_boundary')) for d in g['items'])
        g['supporting_sources']=len(set((d['profile'],d['tile_level']) for d in g['items']))
    return groups


def eval_regions(groups,refs):
    """Explicitly PROVISIONAL reference comparison; not a tuning oracle."""
    if not refs:return {}
    chosen={};coverage={}
    # exclude two ambiguous annotations established before this experiment
    expected={
        'P000':'LINEAR DIMENSIONS','P001':'RADIUS DIMENSION','P002':'7.0',
        'P003':'0.8R','P004':'0.75 DIA','P005':'2 PLACES',
        'P006':'ALIGNED DIMENSION','P007':'3.6','P008':'1.0R',
        'P009':'2.0R','P011':'1.25R','P012':'2.1','P013':'35°',
        'P014':'1.0R','P016':'ANGULAR DIMENSION','P017':'0.6',
        'P018':'START X5,Y7','P019':'2.0R','P020':'3.0R',
        'P021':'DIAMETER DIMENSION','P022':'4.0','P023':'LEADER',
        'P024':'1.0 DIA','P025':'1.0 R'}
    boxes={r['id']:r['bbox_px'] for r in refs if r['id'] in expected}
    for rid,t in expected.items():
        ref=boxes[rid]; x1,y1,x2,y2=ref; area=max(1,(x2-x1)*(y2-y1))
        candidates=[]
        for g in groups:
            # Match using ANY original detection in the group, not only anchor.
            for d in g['items']:
                a,b,c,e=d['bbox_original_px']
                overlap=max(0,min(c,x2)-max(a,x1))*max(0,min(e,y2)-max(b,y1))/area
                if overlap>=.4:
                    candidates.append((overlap,g))
                    break
        targets={id(g):g for _,g in candidates}
        coverage[rid]=any(simple_norm(d['text'])==simple_norm(t)
                       for g in targets.values() for d in g['items'])
        # A geometry-only match cannot turn a false reading into truth.
        chosen[rid]=any(simple_norm(g['selected_text'])==simple_norm(t)
                          for g in targets.values())
    return {'reference_regions':len(expected),'oracle_candidate_coverage':sum(coverage.values()),
            'automatic_selected_exact':sum(chosen.values()),
            'per_region':{k:{'available':coverage[k],'selected':chosen[k]}
                          for k in expected},
            'warning':'PROVISIONAL reference; oracle coverage assumes a correct choice and is NOT automatic OCR accuracy.'}


def build_summary(work:Path, originals:dict, sec:dict, con, image, refs=None):
    import cv2
    bgr=cv2.imread(str(image)); height,width=bgr.shape[:2]
    profiles={}
    for p in PROFILES:
        # Copy original observations and record provenance. Source geometry is whole image.
        full_tile={'level':0,'index':0,'rect':[0,0,width,height]}
        profiles[p]={0:[globalize(originals[p],full_tile,p)]}
        for level in LEVELS:
            profiles[p][level]=[]
            for tile in overlap_tiles(width,height,level):
                cfg_json=con.execute('''SELECT output_path FROM tile_predictions
                     WHERE profile=? AND level=? AND tile_index=? AND status='done'
                     ORDER BY done_utc DESC LIMIT 1''',(p,level,tile['index'])).fetchone()
                if cfg_json and (work/cfg_json[0]).exists():
                    data=read_gzip_json(work/cfg_json[0]);profiles[p][level].append(data['detections'])
    reports=[]
    for selection in [('1060',(1060,)),('1947',(1947,)),('1060+1947',PROFILES)]:
        for name,levels in PLANS.items():
            detections=[];parts=[]
            for p in selection[1]:
                detections.extend(profiles[p][0][0]);parts.append([p,0,1])
                for level in levels:
                    for tile_obs in profiles[p][level]: detections.extend(tile_obs)
                    parts.append([p,level,len(profiles[p][level])])
            groups=fuse_observations(detections)
            evaluation=eval_regions(groups,refs)
            seconds=sum(sec[p] for p in selection[1])
            for profile in selection[1]:
                for level in levels:
                    tim=con.execute('SELECT SUM(infer_seconds) FROM tile_predictions '
                        "WHERE profile=? AND level=? AND status='done'",(profile,level)).fetchone()[0]
                    seconds+=tim or 0
            reports.append({'profiles':selection[0],'plan':name,
                'unique_view_passes':sum(c for p,l,c in parts),
                'measured_or_partial_inference_seconds':round(seconds,3),
                'raw_detections':len(detections),'distinct_location_groups':len(groups),
                'boundary_fragments':sum(g['boundary_fragments'] for g in groups),
                'provisional_evaluation':evaluation,'groups':groups})
    summary={'version':VERSION,'source_image':image.name,'source_size':[width,height],
        'plans':list(PLANS),'baseline_inference_seconds':{str(k):v for k,v in sec.items()},
        'tiling_overlap_fraction':.24,
        'saved_tile_inferences':con.execute("SELECT COUNT(*) FROM tile_predictions WHERE status='done'").fetchone()[0],
        'rows':reports}
    L.atomic_write(work/'results.json',(json.dumps(summary,indent=2,ensure_ascii=False)+'\n').encode())
    make_html(summary,work/'report.html')
    return summary


def make_html(summary,path):
    esc=html.escape
    css='''body{font:15px system-ui,Arial;max-width:1250px;margin:36px auto;padding:0 22px;color:#202735;background:#fafafa}
    table{width:100%;border-collapse:collapse;background:white}th,td{border:1px solid #d9dce3;padding:8px;text-align:left}
    th{background:#e7eefa;position:sticky;top:0}tr:hover{background:#f4faff}p{line-height:1.55}
    details{background:white;border:1px solid #ddd;padding:10px;margin:12px 0}code{color:#184681}
    .note{border-left:4px solid #e6ad35;padding:8px 14px;background:#fff8e8}
    .hint{color:#555;font-size:13px} input{padding:8px;width:370px}'''
    htmls=['<!doctype html><meta charset="UTF-8"><title>ShopAI OCR tile study</title>',
        f'<style>{css}</style><h1>ShopAI OCR tile study: trials 1060 and 1947</h1>',
        '<p class="note"><b>Unverified OCR hypotheses.</b> Provisional references are not certified. '
        'Oracle candidate coverage is NOT proof that automatic selection can choose correct text. '
        'Only actual saved OCR detections are shown; no source image pixels are invented.</p>',
        f'<p>Image: {esc(summary["source_image"])} {summary["source_size"]} px. '
        'Whole-image baseline is read from the previous immutable 2,000-run database. '
        'Only tile passes incur new inference. Timings in partially completed reports exclude missing tiles. Overlap: 24%.</p>',
        '<input oninput="filterRows(this.value)" placeholder="Filter plan or profile">',
        '<table><thead><tr><th>Profiles</th><th>Views</th><th>Image passes*</th><th>Detections</th>'
        '<th>Spatial groups</th><th>Boundary hits</th><th>Measured inference (s)</th><th>Oracle coverage /24</th><th>Auto-selected /24</th></tr></thead><tbody>']
    for r in summary['rows']:
        e=r['provisional_evaluation'];htmls.append('<tr>'+''.join('<td>'+esc(str(v))+'</td>' for v in
            [r['profiles'],r['plan'],r['unique_view_passes'],r['raw_detections'],r['distinct_location_groups'],r['boundary_fragments'],
             r['measured_or_partial_inference_seconds'],e.get('oracle_candidate_coverage','—'),e.get('automatic_selected_exact','—')])+'</tr>')
    htmls.append('</tbody></table><p class="hint">*Logical input views; cached from prior stages '
                 'when available. The combined rows reuse both individual profile outputs.</p>')
    for r in summary['rows']:
        htmls.append(f'<details><summary>{esc(r["profiles"])} — {esc(r["plan"])}: '
                     f'{len(r["groups"])} spatial groups; click for candidate readings</summary>')
        htmls.append('<table><tr><th>Group</th><th>Location</th><th>Preferred (unverified)</th>'
                     '<th>Alternatives (unverified)</th><th>Boundary cases</th></tr>')
        for g in r['groups']:
            alt='; '.join(f'{x["text"]} ({x["evidence_score"]})' for x in g['alternatives'][:8])
            htmls.append('<tr>'+''.join('<td>'+esc(str(v))+'</td>' for v in
                [g['id'],g['anchor'],g['selected_text'],alt,g['boundary_fragments']])+'</tr>')
        htmls.append('</table></details>')
    htmls.extend(['<script>function filterRows(t){for(const tr of document.querySelectorAll("tbody tr"))'
                  'tr.style.display=tr.textContent.toLowerCase().includes(t.toLowerCase())?"":"none"}</script>',
                  '<p class="hint">Results are also available as structured results.json, per-tile gzipped data and SQLite.</p>'])
    L.atomic_write(path,'\n'.join(htmls).encode('utf-8'))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['run','status','dry-run','report'])
    parser.add_argument('--source-workdir',type=Path,default=Path('/mnt/shopai-data-new/cad-research/benchmarks/ocr-lab-v1/experiments'))
    parser.add_argument('--workdir',type=Path,default=Path('/mnt/shopai-data-new/cad-research/benchmarks/ocr-tile-study-v1/experiments'))
    parser.add_argument('--image',type=Path,default=Path('/mnt/shopai-data-new/cad-research/benchmarks/ocr-tile-study-v1/25-1.jpg'))
    parser.add_argument('--models-root',type=Path,default=Path('/mnt/shopai-data-new/cad-research/ocr-next'))
    parser.add_argument('--max-hours',type=float,default=12)
    parser.add_argument('--max-new-tiles',type=int,default=0,help='0=all; positive number for small smoke test')
    args=parser.parse_args()
    if args.command=='status':
        hb=args.workdir/'heartbeat.json'; print(hb.read_text() if hb.exists() else 'No heartbeat')
        if (args.workdir/'results.json').exists(): print('REPORT='+str(args.workdir/'report.html'))
        return
    import cv2
    image=args.image; bgr=cv2.imread(str(image),cv2.IMREAD_COLOR)
    if bgr is None:raise FileNotFoundError(image)
    h,w=bgr.shape[:2]; img_hash=L.file_sha(image)
    config,full,baseline,variant=open_original(args.source_workdir,img_hash)
    if variant!='server':raise RuntimeError('Original benchmark variant must be server')
    tiles=[t for lvl in LEVELS for t in overlap_tiles(w,h,lvl)]
    if args.command=='dry-run':
        print('SOURCE_IMAGE_SHA256='+img_hash)
        print('SAVED_PROFILES='+str(PROFILES))
        for p in PROFILES:print(f'PROFILE_{p}={L.stable_json(config[p])}')
        for level in LEVELS:print(f'GRID={level} TILES={len([t for t in tiles if t["level"]==level])}')
        print('NEW_TILE_INFERENCE_MAX='+str(len(PROFILES)*len(tiles)))
        print('COMPARE_PLANS='+str(len(PLANS)*3))
        print('NO_MODEL_LOADED;NO_CHANGES')
        return
    work=args.workdir;work.mkdir(parents=True,exist_ok=True)
    con=init_database(work/'tile_lab.sqlite3')
    refs=json.loads((Path(__file__).parent/'provisional_v61_regions.json').read_text())
    if args.command=='report':
        res=build_summary(work,full,baseline,con,image,refs)
        print('REPORT='+str(work/'report.html'));print('SAVED_TILE_INFERENCES='+str(res['saved_tile_inferences']))
        return
    lock=(work/'worker.lock').open('a+')
    try:fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('Another tile-study worker is active')
    det,rec=L.model_pair(args.models_root,'server');model_sig=L.model_fingerprint((det,rec))
    jobs=[]
    total_existing=0
    for p in PROFILES:
        for tile in tiles:
            key=sha({'version':VERSION,'image_sha256':img_hash,'model_sha256':model_sig,
                'profile':p,'config':config[p],'rect':tile['rect'],'level':tile['level']})
            row=con.execute('SELECT status,output_path FROM tile_predictions WHERE key=?',(key,)).fetchone()
            if row and row[0]=='done' and (work/row[1]).exists():
                total_existing+=1
                continue
            jobs.append((p,tile))
    if args.max_new_tiles>0: jobs=jobs[:args.max_new_tiles]
    print(f'WHOLE_SOURCE=existing_ocr_lab_cache profiles={PROFILES}; NEW_TILES={len(jobs)} / {len(tiles)*2}',flush=True)
    status={'done':total_existing,'target':len(tiles)*2,'errors':0,'current':'initializing','state':'running'}
    mon=L.Monitor(work,work/'tile_lab.sqlite3',status)
    mon.start();deadline=time.monotonic()+args.max_hours*3600
    try:
        if jobs:
            pipe,load_s=L.begin_paddle(det,rec)
            print(f'MODEL_LOAD_SECONDS={load_s:.3f}',flush=True)
            # Shared loaded Paddle model for both parameter profiles.
            for p,tile in jobs:
                if time.monotonic()>=deadline:
                    print('MAX_HOURS_REACHED; RESUMABLE',flush=True);break
                available=L.memory_available_gb()
                if available is not None and available < 8:
                    print(f'MEMORY_FLOOR_PAUSE available_GiB={available:.2f} threshold=8',flush=True)
                    break
                mon.update(current=f'{p}/{tile["level"]}/{tile["index"]}')
                try:
                    detections,infer,cached=tiles_for_profile(bgr,pipe,config[p],p,tile,work,con,img_hash,model_sig)
                    status['done']+=1
                    print(f'PROFILE={p} LEVEL={tile["level"]} TILE={tile["index"]} '
                          f'DONE={status["done"]}/{status["target"]} INFER={infer:.3f}s '
                          f'BOXES={len(detections)} CACHED={cached}',flush=True)
                except Exception as e:
                    status['errors']+=1
                    print(f'TILE_ERROR profile={p} level={tile["level"]} tile={tile["index"]}: {e}',flush=True)
                    traceback.print_exc()
                mon.update(**status,last_completed_utc=L.now_utc())
        mon.update(current='summarizing',state='summarizing')
        res=build_summary(work,full,baseline,con,image,refs)
        print('REPORT='+str(work/'report.html'),flush=True)
        print('COMPARISONS='+str(len(res['rows'])),flush=True)
        print('SAVED_TILE_INFERENCES='+str(res['saved_tile_inferences']),flush=True)
        mon.update(current='none',state='complete' if status['done']==status['target'] and status['errors']==0 else 'partial')
    finally:
        mon.close();con.close()

if __name__=='__main__':main()
