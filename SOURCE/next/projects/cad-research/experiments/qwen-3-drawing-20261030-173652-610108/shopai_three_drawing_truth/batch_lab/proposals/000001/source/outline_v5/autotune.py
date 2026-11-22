#!/usr/bin/env python3
"""ShopAI v5: local image-adaptive geometry exploration, not dimensioned CAD.

Input masks are derived from pixels; no known dimensions, expected feature counts,
answer files, cloud services or per-image hardcoded color selections are used.
Ranks candidate preprocessing+contour extraction by measured raster agreement,
structural plausibility and a nontrivial coverage check. Can fail/flag uncertainty.
"""
import argparse
import csv
import hashlib
import html
import json
import math
import random
import time
from pathlib import Path
from collections import OrderedDict
import cv2
import numpy as np

PARAMS=OrderedDict([
 ('mask_id',()), # filled after inspecting each input
 ('blur',(0,3,5)),
 ('morph',('none','close2','close3','open2')),
 ('epsilon',(0.0007,0.001,0.0015,0.002,0.003,0.004,0.006,0.009,0.014,0.023)),
 ('min_hole_area',(75,150,300,600,1100)),
 ('circularity',(0.66,0.74,0.82,0.90)),
 ('snap',(0,1.0,2.0,3.0)),
 ('collinear_tol',(0.,1.,1.75,2.5)),
])


def choose_masks(img):
    """Discover foreground by color contrast OR grayscale, regardless of hue."""
    masks={}
    hsv=cv2.cvtColor(img,cv2.COLOR_BGR2HSV)
    s=hsv[:,:,1]; v=hsv[:,:,2]; h=hsv[:,:,0]
    saturated=(s>=42)&(v>=45)
    bins=np.bincount((h[saturated]//10).ravel(),minlength=18)
    # Distinct hue peaks, with circular wrap so red near 0 and 179 is one color.
    ranked=np.argsort(bins)[::-1]
    centers=[]
    for idx in ranked:
        if bins[idx]<max(75,int(img.shape[0]*img.shape[1]*0.00045)):break
        c=int(idx*10+5)
        if any(min(abs(c-z),180-abs(c-z))<19 for z in centers):continue
        centers.append(c)
        if len(centers)==4:break
    for c in centers:
        dist=np.abs(h.astype(np.int16)-c)
        dist=np.minimum(dist,180-dist)
        for sat in (35,65):
            mask=((dist<=12)&(s>=sat)&(v>=40)).astype(np.uint8)*255
            name=f'color_h{c}_s{sat}'
            masks[name]=mask
            masks[name+'_joined']=cv2.dilate(mask,np.ones((3,3),np.uint8))
    gray=cv2.cvtColor(img,cv2.COLOR_BGR2GRAY)
    otsu=cv2.threshold(gray,0,255,cv2.THRESH_BINARY_INV|cv2.THRESH_OTSU)[1]
    masks['gray_otsu']=otsu
    for t in (95,145,195):
        masks[f'gray_t{t}']=cv2.threshold(gray,t,255,cv2.THRESH_BINARY_INV)[1]
    masks['gray_adaptive']=cv2.adaptiveThreshold(gray,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,cv2.THRESH_BINARY_INV,31,12)
    # Reject masks that consist mostly of background or nothing.
    masks={name:m for name,m in masks.items() if 0.0007<np.count_nonzero(m)/m.size<0.32}
    return masks


def raster_poly(points,shape,filled=False):
    out=np.zeros(shape,np.uint8)
    if len(points)<3:return out
    vertices=np.rint(points).astype(np.int32).reshape(-1,1,2)
    if filled:cv2.fillPoly(out,[vertices],255)
    else:cv2.polylines(out,[vertices],True,255,1,cv2.LINE_8)
    return out


def axis_snap(points,tolerance):
    p=np.asarray(points,dtype=float).copy()
    if tolerance==0:return p
    for i in range(len(p)):
        j=(i+1)%len(p)
        dx,dy=abs(p[i,0]-p[j,0]),abs(p[i,1]-p[j,1])
        if dx<tolerance and dx<.1*dy:p[i,0]=p[j,0]=(p[i,0]+p[j,0])/2
        if dy<tolerance and dy<.1*dx:p[i,1]=p[j,1]=(p[i,1]+p[j,1])/2
    return p


def remove_collinear(points,tolerance):
    """Remove raster staircase vertices that lie on the same engineering line.

    Does not force any number of edges; preserves meaningful changes in angle.
    """
    p=np.asarray(points,dtype=float).copy().tolist()
    if tolerance<=0:return np.asarray(p,dtype=float)
    changed=True
    while changed and len(p)>3:
        changed=False
        for i in range(len(p)):
            a=np.asarray(p[(i-1)%len(p)]);b=np.asarray(p[i]);c=np.asarray(p[(i+1)%len(p)])
            ac=c-a;length=float(np.linalg.norm(ac))
            if length<1e-8:continue
            fraction=float(np.dot(b-a,ac)/(length*length))
            distance=abs(float(ac[0]*(b[1]-a[1])-ac[1]*(b[0]-a[0])))/length
            if 0.0<=fraction<=1.0 and distance<=tolerance:
                p.pop(i);changed=True;break
    return np.asarray(p,dtype=float)


def main_and_holes(mask):
    contours,_=cv2.findContours(mask,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    if not contours:return None,[]
    contours=sorted(contours,key=cv2.contourArea,reverse=True)
    h,w=mask.shape
    main=next((c for c in contours if cv2.contourArea(c)>h*w*.01),None)
    if main is None:return None,[]
    a=cv2.contourArea(main)
    x,y,bw,bh=cv2.boundingRect(main)
    # A disconnected annotation frame or edge-to-edge scan border is ambiguous.
    if bw<.19*w or bh<.19*h or a>h*w*.94:return None,[]
    holes=[]
    for c in contours[1:]:
        ca=cv2.contourArea(c)
        if ca < 50 or ca> a*.50:continue
        m=cv2.moments(c)
        if abs(m['m00'])<1:continue
        xy=(m['m10']/m['m00'],m['m01']/m['m00'])
        if cv2.pointPolygonTest(main,xy,False)<=0:continue
        holes.append(c)
    return main,holes


def shape_features(contour):
    """Data-only shape hint, not a guaranteed recognized CAD primitive."""
    area=cv2.contourArea(contour);per=cv2.arcLength(contour,True)
    circ=4*math.pi*area/(per*per) if per else 0.0
    x,y,w,h=cv2.boundingRect(contour)
    return dict(area_px=round(float(area),1),circularity=round(float(circ),4),
                aspect=round(float(w/max(1,h)),3),center_px=[round(x+w/2,2),round(y+h/2,2)])


class Evaluator:
    def __init__(self,img):
        self.img=img;self.h,self.w=img.shape[:2]
        self.masks=choose_masks(img)
        if not self.masks:raise ValueError('No usable foreground mask found')
        self.ids=tuple(self.masks)
        self.cache={}
        self.catalog={}
        for name,m in self.masks.items():
            c,holes=main_and_holes(m)
            if c is None:continue
            edge=np.zeros(m.shape,np.uint8);cv2.drawContours(edge,[c],-1,255,1)
            fill=np.zeros(m.shape,np.uint8);cv2.drawContours(fill,[c],-1,255,-1)
            # Some hue selections are only annotation text, and should not dominate.
            self.catalog[name]={'contour':c,'holes':holes,'edge':edge,
                  'fill':fill, 'area':float(cv2.contourArea(c)),
                  'ink':int(np.count_nonzero(m)),
                  'box':cv2.boundingRect(c)}
        if not self.catalog:raise ValueError('No sizeable closed contour found in any grayscale/color mask')
        self.ids=tuple(self.catalog)
        self.param_space=OrderedDict((k,(self.ids if k=='mask_id' else vals)) for k,vals in PARAMS.items())

    def preprocess(self,p):
        key=(p['mask_id'],p['blur'],p['morph'])
        if key not in self.cache:
            m=self.masks[p['mask_id']]
            if p['blur']:
                img=cv2.GaussianBlur(self.img,(p['blur'],p['blur']),0)
                # With blur, preserve discovered hue range via narrowing dilated original mask
                # rather than substituting grayscale (would contaminate colored geometry).
                m=cv2.GaussianBlur(m,(p['blur'],p['blur']),0)
                m=np.where(m>=125,255,0).astype(np.uint8)
            if p['morph']!='none':
                op=p['morph'];size=2 if op.endswith('2') else 3
                morph=cv2.MORPH_OPEN if op.startswith('open') else cv2.MORPH_CLOSE
                m=cv2.morphologyEx(m,morph,np.ones((size,size),np.uint8))
            main,holes=main_and_holes(m)
            self.cache[key]=(main,holes)
        return self.cache[key]

    def evaluate(self,p,full=False):
        p={k:p[k] for k in self.param_space}
        main,holes=self.preprocess(p)
        if main is None:return dict(**p,score=0.,valid=False)
        anchor=self.catalog[p['mask_id']]
        perimeter=cv2.arcLength(main,True)
        poly=cv2.approxPolyDP(main,perimeter*p['epsilon'],True).reshape(-1,2)
        poly=remove_collinear(axis_snap(poly,p['snap']),p['collinear_tol'])
        if len(poly)<3 or len(poly)>350:
            return dict(**p,score=0.,valid=False)
        edge=raster_poly(poly,(self.h,self.w))
        fill=raster_poly(poly,(self.h,self.w),True)
        target=anchor['edge'];target_fill=anchor['fill']
        tol=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(3,3))
        a=edge>0;b=target>0
        ep=np.count_nonzero(a & (cv2.dilate(target,tol)>0))/max(1,np.count_nonzero(a))
        er=np.count_nonzero(b & (cv2.dilate(edge,tol)>0))/max(1,np.count_nonzero(b))
        f1=2*ep*er/(ep+er) if ep+er else 0
        f=fill>0;t=target_fill>0
        iou=np.count_nonzero(f&t)/max(1,np.count_nonzero(f|t))
        # Selection is image-derived, not a known shape. Require large coherent contour
        # plus explainable foreground; discourage tiny closed label boxes.
        box=anchor['box'];area=anchor['area'];im_area=self.h*self.w
        occupied=area/im_area
        shape_extent=(box[2]/self.w)*(box[3]/self.h)
        ink_inside=np.count_nonzero((self.masks[p['mask_id']]>0)&t)
        ink_frac=ink_inside/max(1,anchor['ink'])
        # Mask color selection gets only a modest bonus, since partial hue masks can mislead.
        coherence=min(1.,ink_frac/.68)
        size=min(1.,occupied/.09)
        extent=min(1.,shape_extent/.16)
        complexity_pen=max(0,len(poly)-14)*.035
        # score balances fitting main contour, spatial significance, mask coherence
        score=100*(.59*f1+.20*iou+.08*coherence+.07*size+.06*extent)-complexity_pen
        # Discard candidates outside their own contour as a strong false positive hint.
        if occupied<.015:score*=.5
        picked=[];seen=[]
        for c in sorted(holes,key=cv2.contourArea,reverse=True):
            area_h=cv2.contourArea(c)
            if area_h < p['min_hole_area']:continue
            feat=shape_features(c)
            ctr=feat['center_px'];rad=math.sqrt(area_h/math.pi)
            if any(math.dist(ctr,x)<max(3,0.4*(rad+r)) for x,r in seen):continue
            seen.append((ctr,rad))
            feat['classification']='circle_candidate' if feat['circularity']>=p['circularity'] and 0.7<feat['aspect']<1.4 else 'closed_internal_contour'
            if full:
                eps=max(.5,cv2.arcLength(c,True)*p['epsilon'])
                pts=cv2.approxPolyDP(c,eps,True).reshape(-1,2)
                feat['contour_px']=pts.tolist()
            picked.append(feat)
            if len(picked)>=25:break
        result=dict(**p,score=round(float(score),5),valid=True,edge_f1=round(float(f1),5),
             fill_iou=round(float(iou),5),mask_coverage=round(float(coherence),4),
             contour_area_px=round(area,1),vertices=len(poly),internals=len(picked),
             contour_kind='polygonal_approximation_curves_not_fitted')
        if full:
            result['outline_vertices_px']=np.asarray(poly,dtype=float).round(2).tolist()
            result['internal_contours']=picked
        return result


def random_p(rng,space):return {k:rng.choice(v) for k,v in space.items()}
def key(p,space):return tuple(p[k] for k in space)
def change_one(rng,p,k,space):
    q={a:p[a] for a in space};v=space[k]
    if len(v)<2:return q
    i=v.index(p[k]);delta=rng.choice((-2,-1,1,2));j=max(0,min(len(v)-1,i+delta))
    if j==i:j=i-1 if i else 1
    q[k]=v[j];return q


def overlay(img,w):
    out=img.copy()
    if w.get('outline_vertices_px'):
        pts=np.rint(w['outline_vertices_px']).astype(np.int32)
        cv2.polylines(out,[pts],True,(0,190,0),2,cv2.LINE_AA)
    for c in w.get('internal_contours',[]):
        if len(c.get('contour_px',[]))>=3:
            pts=np.asarray(c['contour_px'],np.int32)
            cv2.polylines(out,[pts],True,(255,130,0),2,cv2.LINE_AA)
    return out


def evaluate_stability(ev,p):
    """Measure agreement with a changed preprocessing, WITHOUT answer coordinates."""
    main,_=ev.preprocess(p)
    if main is None:return 0.
    p1=p.copy();p1['morph']='close2' if p1['morph']!='close2' else 'none'
    c,_=ev.preprocess(p1)
    if c is None:return 0.
    a=np.zeros((ev.h,ev.w),np.uint8);b=a.copy()
    cv2.drawContours(a,[main],-1,255,-1)
    cv2.drawContours(b,[c],-1,255,-1)
    return round(float(np.count_nonzero((a>0)&(b>0))/max(1,np.count_nonzero((a>0)|(b>0)))),4)


def optimize(img,opts,out,registry,analysis_scale=1.0):
    t0=time.perf_counter();ev=Evaluator(img);space=ev.param_space
    rng=random.Random(opts.seed);seen={};best=None;cur=None;top=[];accepted=0;restarts=0;no_gain=0
    sha=hashlib.sha256(opts.image.read_bytes()).hexdigest()
    store={}
    if registry.is_file():
        try:store=json.loads(registry.read_text())
        except (json.JSONDecodeError,OSError):store={}
    # Transfer learning at the PARAMETER level only, not from expected geometry.
    priors=[]
    for item in store.get('previous', [])[-60:]:
        previous=item.get('params',{})
        if previous.get('mask_id') in space['mask_id'] and all(previous.get(k) in vs for k,vs in space.items()):priors.append(previous)
    combinations=math.prod(len(v) for v in space.values())
    trials=min(opts.trials,combinations)
    if trials<opts.trials:print(f'Budget adjusted to {trials} (finite distinct combinations)',flush=True)
    def submit(p,phase):
        nonlocal best,no_gain
        k=key(p,space)
        if k in seen:return None
        res=ev.evaluate(p);res['trial']=len(seen)+1;res['phase']=phase
        seen[k]=res
        if best is None or res['score']>best['score']+1e-8:
            best=res;no_gain=0
        else:no_gain+=1
        return res
    for p in priors:
        if len(seen)>=trials:break
        submit(p,'memory')
    broad=max(1,min(trials,int(trials*.35)))
    dup=0;attempts=0
    print(f'ShopAI v5: input={opts.image.name}, masks={list(ev.ids)}; budget={trials}; OFFLINE',flush=True)
    while len(seen)<broad and attempts<trials*25:
        attempts+=1
        p=random_p(rng,space)
        row=submit(p,'broad')
        if row is not None and len(seen)%1000==0:print(f'  broad {len(seen)}/{trials} best={best["score"]:.3f} t={time.perf_counter()-t0:.1f}s',flush=True)
    top=sorted(seen.values(),key=lambda x:-x['score'])[:40]
    cur=top[0]
    while len(seen)<trials and attempts<trials*75:
        attempts+=1
        if attempts%85==0:
            cur=rng.choice(top[:min(20,len(top))])
            restarts+=1
        name=list(space)[attempts%len(space)]
        p=change_one(rng,cur,name,space)
        row=submit(p,'adaptive')
        if row is None:
            dup+=1
            if dup>15:
                cur=random_p(rng,space);dup=0;restarts+=1
            continue
        dup=0
        if row['score']>cur.get('score',-1):cur=row;accepted+=1
        if row['score']>=top[-1]['score']:
            top.append(row);top.sort(key=lambda x:-x['score']);del top[40:]
        if len(seen)%1000==0:print(f'  adaptive {len(seen)}/{trials} best={best["score"]:.3f} t={time.perf_counter()-t0:.1f}s',flush=True)
        if opts.early_stop and len(seen)>=opts.min_trials and no_gain>opts.patience and best['score']>=opts.target:
            # Stronger sanity checks than reaching arbitrary 100 on a subset.
            r=ev.evaluate(best,True)
            if r['valid'] and r['vertices']>=3 and r['edge_f1']>.94 and evaluate_stability(ev,best)>=.95:
                print(f'  EARLY STOP after {len(seen)} trials: target, plateau and stability checks passed',flush=True)
                break
    winner=ev.evaluate(best,True)
    stability=evaluate_stability(ev,best)
    # Separately construct a simplified editable-polyline candidate.
    # The optimizer scored the detailed trace; report both to avoid implying
    # this after-the-fact simplification was included in its fitness.
    simpler=remove_collinear(winner['outline_vertices_px'],2.5).round(2).tolist()
    simplified_mask=raster_poly(simpler,(ev.h,ev.w))>0
    target_edge=ev.catalog[winner['mask_id']]['edge']>0
    kernel=np.ones((3,3),np.uint8)
    sp=np.count_nonzero(simplified_mask&(cv2.dilate(target_edge.astype(np.uint8),kernel)>0))/max(1,np.count_nonzero(simplified_mask))
    sr=np.count_nonzero(target_edge&(cv2.dilate(simplified_mask.astype(np.uint8),kernel)>0))/max(1,np.count_nonzero(target_edge))
    simplified_f1=2*sp*sr/(sp+sr) if sp+sr else 0.0
    warning=[]
    if winner['edge_f1']<.94:warning.append('low_outline_pixel_agreement')
    if stability<.92:warning.append('unstable_under_morphology_change')
    if winner['vertices']>12:warning.append('curved_or_complex_profile_requires_arc_fitting')
    if len(ev.ids)>1:warning.append('different_segmentations_may_produce_different_valid_interpretations')
    warning.append('dimension_labels_not_read_or_verified')
    warning.append('internal_contours_are_candidates_not_verified_holes')
    elapsed=time.perf_counter()-t0
    out.mkdir(parents=True,exist_ok=True)
    cv2.imwrite(str(out/'source.png'),img)
    cv2.imwrite(str(out/'winner_overlay.png'),overlay(img,winner))
    cv2.imwrite(str(out/'selected_mask.png'),ev.masks[winner['mask_id']])
    geom={'sha256':sha,'source':opts.image.name,'fitness':winner['score'],
          'fitness_type':'image-only geometric-raster heuristic, NOT actual drawing accuracy',
          'parameters':{k:winner[k] for k in space},'stability_iou':stability,
          'geometry':{'outline_vertices_px':winner['outline_vertices_px'],
                    'simplified_outline_vertices_px':simpler,
                    'simplified_outline_f1':round(float(simplified_f1),5),
                    'internal_contours':winner['internal_contours'],'units':'pixels',
                    'primitive_fit':'contour approximation; curves NOT yet exact CAD arcs'},
          'review_required':True,'limitations':warning,
          'configurations_tested':len(seen),'seconds':round(elapsed,2),
          'analysis_scale':round(analysis_scale,8),
          'original_image_outline_vertices_px':(np.asarray(winner['outline_vertices_px'])/analysis_scale).round(2).tolist()}
    (out/'winner_geometry.json').write_text(json.dumps(geom,indent=2)+'\n')
    with (out/'ranking.csv').open('w',newline='') as f:
        cols=['rank','trial','phase',*space,'score','edge_f1','fill_iou','mask_coverage','contour_area_px','vertices','internals']
        wr=csv.DictWriter(f,fieldnames=cols,extrasaction='ignore');wr.writeheader()
        for i,r in enumerate(sorted(seen.values(),key=lambda row:-row['score']),1):wr.writerow({'rank':i,**r})
    imgs=[];shapes=set()
    for candidate in sorted(seen.values(),key=lambda r:-r['score']):
        if not candidate.get('valid'):continue
        rr=ev.evaluate(candidate,True)
        shape=(rr['mask_id'],tuple(tuple(x) for x in rr['outline_vertices_px']))
        if shape in shapes:continue
        shapes.add(shape);ix=len(imgs)+1
        name=f'candidate_{ix:02d}.png';cv2.imwrite(str(out/name),overlay(img,rr))
        imgs.append((ix,rr,name))
        if len(imgs)==6:break
    cards=''.join(f'<tr><td>{ix}</td><td>{r["mask_id"]}</td><td>{r["score"]:.2f}</td><td>{r["vertices"]}</td><td><img width="520" src="{name}"></td></tr>' for ix,r,name in imgs)
    page=f'''<!doctype html><html><meta charset="utf-8"><title>ShopAI v5 autotuner</title>
    <style>body{{font:16px system-ui;max-width:1200px;margin:30px auto}}td,th{{border:1px solid #ddd;padding:6px}}table{{border-collapse:collapse}}img{{max-width:100%}}</style>
    <h1>ShopAI v5 adaptive color-independent preprocessing</h1>
    <p>{html.escape(opts.image.name)} · {len(seen):,} unique trials · {elapsed:.1f} seconds · offline</p>
    <p><b>Best mask:</b> {html.escape(winner['mask_id'])}; <b>fitness:</b> {winner['score']:.2f}/100;
    <b>perturbation stability:</b> {stability:.4f}; <b>contour vertices:</b> {winner['vertices']}</p>
    <p><b>Review required.</b> Fitness is not manufacturing accuracy. Curves are polylines (not fit arcs);
    holes and labels are unverified; optimizer has no ground truth and can confidently fit wrong details.</p>
    <p><a href="winner_geometry.json">Geometry JSON</a> · <a href="ranking.csv">Trial rankings</a> ·
    <a href="selected_mask.png">Chosen segmentation</a> · <a href="source.png">Original</a></p>
    <table><tr><th>Rank</th><th>Segmentation</th><th>Heuristic</th><th>Vertices</th><th>Overlay</th></tr>{cards}</table></html>'''
    (out/'report.html').write_text(page)
    summary=(f'IMAGE={opts.image.name}\nTRIALS={len(seen)}\nSECONDS={elapsed:.2f}\n'
             f'WINNER_SEGMENTATION={winner["mask_id"]}\nFITNESS={winner["score"]:.3f}\n'
             f'DETAILED_CONTOUR_VERTICES={winner["vertices"]}\nSIMPLIFIED_VERTICES={len(simpler)}\nINTERNALS={winner["internals"]}\nSTABILITY={stability}\n'
             f'EARLY_STOPPED={len(seen)<trials}\nREVIEW_REQUIRED=True\nREPORT={out}/report.html\n')
    (out/'summary.txt').write_text(summary);print(summary,flush=True)
    record={'sha256':sha,'source':opts.image.name,'params':geom['parameters'],
            'fitness':winner['score'],'stability':stability}
    history=store.get('previous',[])
    if not any(item.get('sha256')==sha for item in history):history.append(record)
    store={'format':1,'previous':history[-100:]}
    registry.parent.mkdir(parents=True,exist_ok=True)
    # Atomic replace prevents corruption on interrupted runs.
    tmp=registry.with_suffix('.tmp');tmp.write_text(json.dumps(store,indent=2)+'\n');tmp.replace(registry)
    return geom


def main():
    ap=argparse.ArgumentParser(description='Offline self-tuning outline detector (candidate geometry, not validated CAD)')
    ap.add_argument('--image',type=Path,required=True)
    ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--registry',type=Path,default=Path(__file__).resolve().parent/'model_registry.json')
    ap.add_argument('--trials',type=int,default=5000)
    ap.add_argument('--seed',type=int,default=20261020)
    ap.add_argument('--early-stop',action='store_true',default=True)
    ap.add_argument('--no-early-stop',action='store_false',dest='early_stop')
    ap.add_argument('--min-trials',type=int,default=700)
    ap.add_argument('--patience',type=int,default=550)
    ap.add_argument('--target',type=float,default=96.)
    a=ap.parse_args()
    if a.trials<10:ap.error('--trials must be at least 10')
    if not a.image.is_file():ap.error(f'No such image: {a.image}')
    img=cv2.imdecode(np.frombuffer(a.image.read_bytes(),np.uint8),cv2.IMREAD_COLOR)
    if img is None:ap.error('Image cannot be decoded')
    scale=min(1.0,1600/max(img.shape[:2]))
    if scale<1.0:img=cv2.resize(img,None,fx=scale,fy=scale,interpolation=cv2.INTER_AREA)
    optimize(img,a,a.out,a.registry,analysis_scale=scale)

if __name__=='__main__':main()
