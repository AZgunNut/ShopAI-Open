#!/usr/bin/env python3
"""Blind, on-device ShopAI engineering OCR generalization test.

No target labels; reads original OCR Lab database in SQLite mode=ro.
PaddleOCR Server loaded once per execution. Inputs and output objects saved by hash.
Output is hypotheses, not verified engineering constraints.
"""
from __future__ import annotations
import argparse, fcntl, gzip, hashlib, html, json, os, sqlite3, statistics, time
from pathlib import Path
from datetime import datetime, timezone
import legacy_lab as L
import tile_study as T
import selector_v2 as S

PROFILES=(1060,1947)
LEVELS=(4,8,16)
PLANS={'whole':(), 'whole+4':(4,), 'whole+8':(8,), 'whole+16':(16,),
       'whole+4+16':(4,16),'whole+4+8':(4,8), 'whole+4+8+16':(4,8,16)}

def profile_configs(source):
    db=source/'lab.sqlite3'
    if not db.is_file(): raise FileNotFoundError('Original OCR Lab database not found: '+str(db))
    c=sqlite3.connect('file:'+str(db.resolve())+'?mode=ro',uri=True)
    try:
        rows=c.execute('SELECT trial_index,config_json FROM trials WHERE status=? AND trial_index IN (1060,1947)',('done',)).fetchall()
        result={int(i):json.loads(cfg) for i,cfg in rows}
        if set(result)!=set(PROFILES): raise RuntimeError('Missing trials 1060/1947 in original database')
        return result
    finally:c.close()

def database(dbfile):
    c=sqlite3.connect(dbfile)
    c.execute('PRAGMA journal_mode=WAL');c.execute('PRAGMA synchronous=FULL')
    c.execute("""CREATE TABLE IF NOT EXISTS inference (
      key TEXT PRIMARY KEY, profile INTEGER NOT NULL, level INTEGER NOT NULL,
      tile_index INTEGER NOT NULL, status TEXT NOT NULL,
      image_sha TEXT NOT NULL, config_json TEXT NOT NULL, rect_json TEXT NOT NULL,
      result_path TEXT, pre_seconds REAL, infer_seconds REAL, boxes INTEGER,
      finished_utc TEXT, error TEXT)""")
    c.commit(); return c

def prediction_key(img_hash,model_sig,p,cfg,tile):
    return L.sha_bytes(L.stable_json({'img':img_hash,'model':model_sig,'profile':p,
              'config':cfg,'tile':tile['rect'],'level':tile['level'],'index':tile['index'],
              'algorithm':'blind-v1'}).encode())

def save_prediction(c,work,bgr,pipe,img_hash,model_sig,p,cfg,tile):
    key=prediction_key(img_hash,model_sig,p,cfg,tile)
    row=c.execute('SELECT status,result_path,infer_seconds,boxes FROM inference WHERE key=?',(key,)).fetchone()
    if row and row[0]=='done' and row[1] and (work/row[1]).is_file():
        with gzip.open(work/row[1],'rt',encoding='utf-8') as fh: data=json.load(fh)
        print(f'PROFILE={p} LEVEL={tile["level"]} TILE={tile["index"]} '
              f'INFER={row[2]:.3f}s BOXES={row[3]} CACHED=True',flush=True)
        return data
    c.execute('INSERT OR REPLACE INTO inference '
              '(key,profile,level,tile_index,status,image_sha,config_json,rect_json) '
              'VALUES(?,?,?,?,?,?,?,?)',
              (key,p,tile['level'],tile['index'],'running',img_hash,
               L.stable_json(cfg),L.stable_json(tile['rect'])))
    c.commit()
    try:
        x1,y1,x2,y2=tile['rect']
        t=time.perf_counter();inp=L.preprocess(bgr[y1:y2,x1:x2],cfg['pre']);pre=time.perf_counter()-t
        t=time.perf_counter();pred=pipe.predict(inp,**cfg['paddle'])
        boxes,raw=L.collect_predictions(pred,cfg['pre']['scale']);infer=time.perf_counter()-t
        boxes=T.globalize(boxes,tile,p)
        data={'version':'blind-1.0','source_image_sha256':img_hash,'profile':p,
              'tile':tile,'config':cfg,'preprocess_seconds':pre,'infer_seconds':infer,
              'detections':boxes,'raw_paddle_results':raw}
        bits=L.stable_json(data).encode('utf-8');obj=L.sha_bytes(bits)
        path=Path('objects')/obj[:2]/(obj+'.json.gz')
        L.atomic_write(work/path,gzip.compress(bits,compresslevel=6,mtime=0))
        c.execute('UPDATE inference SET status=?,result_path=?,pre_seconds=?,infer_seconds=?,boxes=?,finished_utc=?,error=NULL WHERE key=?',
                  ('done',str(path),pre,infer,len(boxes),L.now_utc(),key));c.commit()
        print(f'PROFILE={p} LEVEL={tile["level"]} TILE={tile["index"]} '
              f'INFER={infer:.3f}s BOXES={len(boxes)} CACHED=False',flush=True)
        return data
    except Exception as e:
        c.execute('UPDATE inference SET status=?,error=?,finished_utc=? WHERE key=?',
                  ('error',str(e)[:1000],L.now_utc(),key));c.commit();raise

def summarize(c,work,image,w,h,levels):
    data_by_profile={}
    times={}
    for p in PROFILES:
        data_by_profile[p]={}
        times[p]={}
        for level in (0,)+tuple(levels):
            expected=[{'level':0,'index':0,'rect':[0,0,w,h]}] if level==0 else T.overlap_tiles(w,h,level)
            records=[];seconds=0.0
            for t in expected:
                row=c.execute('SELECT result_path,infer_seconds FROM inference '
                  'WHERE profile=? AND level=? AND tile_index=? AND image_sha=? AND status=? '
                  'ORDER BY finished_utc DESC LIMIT 1',
                  (p,level,t['index'],L.file_sha(image),'done')).fetchone()
                if row and (work/row[0]).is_file():
                    with gzip.open(work/row[0],'rt',encoding='utf-8') as fp: saved=json.load(fp)
                    if saved['tile']['rect']==t['rect']:
                        records.append(saved['detections']);seconds+=row[1]
            data_by_profile[p][level]=records
            times[p][level]=seconds
    rows=[]
    profile_groups=[('1060',(1060,)),('1947',(1947,)),('1060+1947',PROFILES)]
    for groupname,pr in profile_groups:
        for plan,plan_levels in PLANS.items():
            if not set(plan_levels).issubset(set(levels)):continue
            observations=[];seconds=0.0;passes=0
            for p in pr:
                for lev in (0,)+plan_levels:
                    for ds in data_by_profile[p].get(lev,[]): observations.extend(ds);passes+=1
                    seconds+=times[p].get(lev,0.0)
            if not passes:continue
            spatial=T.fuse_observations(observations)
            rows.append({'profiles':groupname,'plan':plan,'groups':spatial,
                         'unique_view_passes':passes,'raw_detections':len(observations),
                         'distinct_location_groups':len(spatial),
                         'measured_or_partial_inference_seconds':round(seconds,3),
                         'provisional_evaluation':{}})
    payload={'version':'blind-drawing-1.0','source_image':image.name,
             'source_size':[w,h],'rows':rows,'plans':list(PLANS),
             'reference_data':'NONE; held-out image; no answer key'}
    L.atomic_write(work/'results.json',json.dumps(payload,indent=2,ensure_ascii=False).encode())
    result=S.analyze(payload)
    outdir=work/'selector';outdir.mkdir(exist_ok=True)
    L.atomic_write(outdir/'selector_v2_results.json',json.dumps(result,indent=2,ensure_ascii=False).encode())
    S.write_csv(result,outdir/'selector_v2_candidates.csv')
    L.atomic_write(outdir/'report.html',S.create_report(result).encode())
    make_visual_report(work,image,result,w,h)
    for row in result['rows']:
        print('SELECTOR='+row['profiles']+' PLAN='+row['plan']+' GROUPS='+str(len(row['results']))+
            ' REVIEWS='+str(row['review_count'])+' INFER_SECONDS='+str(row['seconds']),flush=True)
    print('BLIND_REPORT='+str(work/'blind_report.html'),flush=True)
    print('SELECTOR_JSON='+str(outdir/'selector_v2_results.json'),flush=True)
    print('NO_REFERENCE_ANSWERS_USED',flush=True)

def make_visual_report(work,image,result,w,h):
    import cv2
    # Draw boxes for merged dual-profile / whole-image only.
    combined=next((x for x in result['rows'] if x['profiles']=='1060+1947' and x['plan']=='whole'),None)
    im=cv2.imread(str(image))
    if combined:
        for idx,d in enumerate(combined['results']):
            a,b,c,e=[round(float(x)) for x in d['anchor']]
            color=(0,120,220) if d['state'].startswith('REVIEW') else (50,150,35)
            cv2.rectangle(im,(max(0,a),max(0,b)),(min(w-1,c),min(h-1,e)),color,1)
            cv2.putText(im,str(idx),(max(0,a),max(7,b-2)),cv2.FONT_HERSHEY_SIMPLEX,.26,color,1,cv2.LINE_AA)
    cv2.imwrite(str(work/'overlay.png'),cv2.resize(im,None,fx=2,fy=2,interpolation=cv2.INTER_NEAREST))
    from base64 import b64encode
    img64=b64encode((work/'overlay.png').read_bytes()).decode()
    original64=b64encode(image.read_bytes()).decode()
    rows=[ '<!doctype html><html><head><meta charset="utf-8"><title>ShopAI blind OCR drawing test</title>',
    '<style>body{font:14px system-ui,Arial;color:#213045;max-width:1200px;margin:24px auto;padding:0 15px}table{border-collapse:collapse;width:100%;font-size:13px}th,td{border:1px solid #ddd;padding:6px;text-align:left}th{background:#dcecff}tr:nth-child(even){background:#f7f7fa}details{padding:10px;border:1px solid #ccc;margin:12px 0}img{max-width:100%;image-rendering:auto} .alert{background:#fff1d6;padding:12px}</style></head><body>',
    '<h1>ShopAI Blind Generalization Test — New Drawing</h1>',
    '<p class="alert"><b>Unverified OCR only.</b> This drawing was not part of the 2,000-trial selection dataset. No human-certified reference text, no accuracy %, and no geometric feature verification. Reading count is not accuracy.</p>',
    '<p>Profiles 1060 and 1947 loaded unchanged from the old read-only experiment database. The overlay numbers identify spatial groups, <b>not dimension numbers</b>.</p>',
    '<div style="display:flex;gap:16px;flex-wrap:wrap"><div><b>Original drawing</b><br><img width="447" src="data:image/jpeg;base64,'+original64+'"></div><div><b>Selected locations / review flags</b><br><img width="650" src="data:image/png;base64,'+img64+'"></div></div>',
    '<h2>Result plans (blind)</h2><table><tr><th>Profiles</th><th>Views</th><th>Seconds</th><th>Distinct locations</th><th>Review flags</th></tr>']
    for r in result['rows']:
        rows.append('<tr>'+''.join('<td>'+html.escape(str(x))+'</td>' for x in [r['profiles'],r['plan'],r['seconds'],len(r['results']),r['review_count']])+'</tr>')
    rows.append('</table>')
    for r in result['rows']:
        rows.append('<details'+(' open' if r['profiles']=='1060+1947' and r['plan']=='whole' else '')+'><summary><b>'+html.escape(r['profiles']+' '+r['plan'])+'</b> — click for decisions and alternatives</summary><table><tr><th>ID</th><th>Original bbox</th><th>Chosen text</th><th>Kind</th><th>State</th><th>Other readings</th></tr>')
        for idx,g in enumerate(r['results']):
            alt=' / '.join(z['text']+' ('+str(z['score'])+')' for z in g['alternatives'][:5])
            rows.append('<tr>'+''.join('<td>'+html.escape(str(s))+'</td>' for s in [idx,g['anchor'],g['selected_text'],g.get('kind'),g['state'],alt])+'</tr>')
        rows.append('</table></details>')
    rows.append('</body></html>')
    L.atomic_write(work/'blind_report.html','\n'.join(rows).encode())

def run(args,engine_factory=L.begin_paddle):
    import cv2
    work=args.workdir.resolve();work.mkdir(parents=True,exist_ok=True)
    lock=(work/'worker.lock').open('a+')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('Another worker is writing this experiment directory')
    image=args.image.resolve()
    bgr=cv2.imread(str(image));
    if bgr is None:raise ValueError('Cannot open drawing: '+str(image))
    h,w=bgr.shape[:2];image_hash=L.file_sha(image)
    cfgs=profile_configs(args.source_workdir)
    c=database(work/'blind.sqlite3')
    det,rec=L.model_pair(args.models_root/'models'/'paddle','server')
    model_sig=L.model_fingerprint((det,rec))
    levels=LEVELS if args.tiles else ()
    tasks=[(p,{'level':0,'index':0,'rect':[0,0,w,h]}) for p in PROFILES]
    if args.tiles:
        tasks.extend((p,t) for p in PROFILES for level in LEVELS for t in T.overlap_tiles(w,h,level))
    cached=0
    for p,t in tasks:
        k=prediction_key(image_hash,model_sig,p,cfgs[p],t)
        row=c.execute('SELECT status,result_path FROM inference WHERE key=?',(k,)).fetchone()
        cached+=bool(row and row[0]=='done' and row[1] and (work/row[1]).is_file())
    print(f'IMAGE={image} SIZE={w}x{h} SHA256={image_hash}',flush=True)
    print(f'CONFIG_SOURCE=existing 2,000-run DB READ-ONLY; profiles={PROFILES}',flush=True)
    print(f'TOTAL_PASSES={len(tasks)} CACHE_HITS={cached} NEW_INFERENCES={len(tasks)-cached}',flush=True)
    try:
        pipe=None
        if cached<len(tasks):
            pipe,loaded=engine_factory(det,rec)
            print('MODEL_LOAD_SECONDS='+format(loaded,'.3f'),flush=True)
        for p,t in tasks:
            save_prediction(c,work,bgr,pipe,image_hash,model_sig,p,cfgs[p],t)
        summarize(c,work,image,w,h,levels)
        L.make_backup(work/'blind.sqlite3',work/'backups')
        c.close()
    finally:lock.close()

def main():
    p=argparse.ArgumentParser()
    here=Path(__file__).resolve().parent
    p.add_argument('--image',type=Path,default=here/'new_drawing.jpeg')
    p.add_argument('--workdir',type=Path,default=here/'experiments')
    p.add_argument('--source-workdir',type=Path,default=Path('/mnt/shopai-data-new/cad-research/benchmarks/ocr-lab-v1/experiments'))
    p.add_argument('--models-root',type=Path,default=Path('/mnt/shopai-data-new/cad-research/ocr-next'))
    p.add_argument('--tiles',action='store_true',help='OPTIONAL: run progressive 4,8,16 tiling in addition to the 2 whole passes')
    args=p.parse_args()
    run(args)
if __name__=='__main__':main()
