#!/usr/bin/env python3
"""ShopAI incremental evidence-based optimizer, CPU test + local Qwen formula edits.
Never reads ground truth while generating predictions; human-readable independent scorer.
"""
import argparse, ast, collections, csv, datetime, fcntl, hashlib, json, math, os, pathlib, random, re, shutil, signal, sqlite3, subprocess, sys, time, urllib.request
P=pathlib.Path('/mnt/shopai-data-new/cad-research/experiments/qwen-3-drawing-20261030-173652-610108/shopai_three_drawing_truth')
R=P/'batch_lab'/'evolution_mm_v1'; INPUT=P/'images'; TRUTH=P/'truth'; STOP=R/'TERMINATE'
IMAGES={'D1':'drawing_01.png','D2':'drawing_02.jpeg','D3':'drawing_03.jpg'}
EXPR='dist + angle_weight * abs(dy) + area_weight / (1 + area) + confidence_weight * (1 - confidence)'
PARAMS={'angle_weight':0.0,'area_weight':0.0,'confidence_weight':0.0}
NAMES={'dist','dx','dy','area','confidence','angle_weight','area_weight','confidence_weight'}
FUNCS={'abs':abs,'min':min,'max':max,'sqrt':math.sqrt,'log1p':math.log1p}

def now():return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
def jread(p):return json.loads(pathlib.Path(p).read_text())
def atomic(p,obj):
    p=pathlib.Path(p);t=p.with_name(p.name+'.tmp.'+str(os.getpid()))
    t.write_text(json.dumps(obj,indent=2,ensure_ascii=False)+'\n');os.replace(t,p)
def sha(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def log(*a):print(now(),*a,flush=True)
def check_expr(expr):
    tree=ast.parse(expr,mode='eval')
    if len(expr)>280 or len(list(ast.walk(tree)))>90:raise ValueError('Expression too complex')
    for n in ast.walk(tree):
        if isinstance(n,(ast.Expression,ast.BinOp,ast.UnaryOp,ast.Call,ast.Load,ast.Name,ast.Constant)):pass
        elif isinstance(n,(ast.Add,ast.Sub,ast.Mult,ast.Div,ast.Mod,ast.USub,ast.UAdd)):pass
        else:raise ValueError('Unsupported syntax '+type(n).__name__)
        if isinstance(n,ast.Name) and n.id not in NAMES|set(FUNCS):raise ValueError('Unapproved name '+n.id)
        if isinstance(n,ast.Call) and (not isinstance(n.func,ast.Name) or n.func.id not in FUNCS or n.keywords):raise ValueError('Unapproved function')
        if isinstance(n,ast.Constant) and (not isinstance(n.value,(int,float)) or abs(n.value)>1e6):raise ValueError('Unapproved literal')
    return compile(tree,'<verified-association-formula>','eval')

def center(bb):
    if isinstance(bb,dict):
        x=bb.get('x',bb.get('left'));y=bb.get('y',bb.get('top'))
        if x is not None and y is not None:return float(x),float(y)
    if isinstance(bb,(list,tuple)):
        if len(bb)>=4 and all(isinstance(v,(int,float)) for v in bb[:4]):
            x0,y0,x1,y1=bb[:4];return (x0+x1)/2,(y0+y1)/2
        if len(bb)==2 and all(isinstance(v,(int,float)) for v in bb):return tuple(map(float,bb))
    return None

def unit_check(t,d):
    for k in ('units','drawing_units','dimension_units','measurement_units'):
        v=t.get(k)
        if isinstance(v,dict):v=v.get('value',v.get('unit'))
        if isinstance(v,str) and v.strip().lower() not in ('mm','millimeter','millimeters','millimetre','millimetres','unknown','unspecified'):
            raise RuntimeError(f'{d}: truth declares {k}={v!r}, conflicts with mm rule; do not silently relabel')

def extend_list_from_checkpoint():
    checkpoint=R/'active_drawings.json'
    if not checkpoint.is_file():return
    for d,filename in jread(checkpoint).items():
        if not re.fullmatch(r'D[4-9][0-9]*',d):continue
        if not re.fullmatch(r'drawing_[0-9]{2,}\.(png|jpg|jpeg)',filename,re.I):raise RuntimeError('Bad extra-drawing entry')
        IMAGES[d]=filename

def next_image(d):
    n=int(d[1:]);matches=[p for p in INPUT.glob(f'drawing_{n:02}.*') if p.suffix.lower() in ('.png','.jpg','.jpeg')]
    if len(matches)>1:raise RuntimeError('Multiple images for '+d+': choose one before continuing')
    if matches and (TRUTH/(d+'.truth.json')).is_file():return matches[0].name
    return None

def preflight():
    if not P.is_dir():raise RuntimeError('Existing project not found')
    if not (P/'tools/score.py').is_file():raise RuntimeError('Existing independent scorer missing')
    out={}
    for d,name in IMAGES.items():
        image=INPUT/name;truth=TRUTH/(d+'.truth.json')
        if not image.is_file() or not truth.is_file():raise RuntimeError(f'Missing original {d} image or ground truth: {image} {truth}')
        t=jread(truth);unit_check(t,d)
        out[d]={'image_sha256':sha(image),'truth_sha256':sha(truth),'units':'mm'}
    return out

def cached_ocr(d):
    # Only experiment-owned prior OCR artifacts; no guess about image identities.
    base=P/'batch_lab/scored_loop_baseline_check'
    matches=list(base.glob('*/intermediates/'+d+'/ocr/selector/selector_v2_results.json')) if base.exists() else []
    if d=='D1':
        ptr=P/'batch_lab/last_real_baseline_run.txt'
        if ptr.is_file():
            q=pathlib.Path(ptr.read_text().strip())/'ocr/selector/selector_v2_results.json'
            if q.is_file():matches.append(q)
    return max(matches,key=lambda p:p.stat().st_mtime) if matches else None

def run_owned(cmd, logfile, cwd=None):
    started=time.monotonic();last_hb=0;last_hour=0
    with pathlib.Path(logfile).open('w') as fd:
        proc=subprocess.Popen(cmd,cwd=cwd,stdout=fd,stderr=subprocess.STDOUT,start_new_session=True)
        while proc.poll() is None:
            if STOP.exists():
                os.killpg(proc.pid,signal.SIGTERM)
                try:proc.wait(timeout=15)
                except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL)
                raise KeyboardInterrupt('TERMINATE stopped owned subprocess')
            elapsed=time.monotonic()-started
            if elapsed-last_hb>=600:
                last_hb=elapsed;heartbeat('EVIDENCE_EXTRACTION',elapsed,'owned_pid='+str(proc.pid))
            if elapsed-last_hour>=3600:
                last_hour=elapsed;log('HOURLY','evidence process',proc.pid,'elapsed_min',round(elapsed/60,1))
            time.sleep(1)
        return proc.returncode

def paddle_ocr(d,image,dirpath):
    py=pathlib.Path('/mnt/shopai-data-new/cad-research/environments/paddleocr/bin/python')
    script=P/'batch_lab/baseline/ocr_selector/blind_test.py'
    if not py.is_file() or not script.is_file():return None
    work=dirpath/'paddle';work.mkdir(exist_ok=True)
    rc=run_owned([str(py),'-B',str(script),'--image',str(image),'--workdir',str(work)],dirpath/'ocr.log',cwd=script.parent)
    result=work/'selector/selector_v2_results.json'
    if rc or not result.is_file():raise RuntimeError(f'{d} OCR failed: exit={rc}; inspect {dirpath}/ocr.log')
    return result

def words_from_selector(q):
    o=jread(q);g=[r for r in o.get('rows',[]) if r.get('profiles')=='1060+1947' and r.get('plan')=='whole']
    if len(g)!=1:raise RuntimeError(f'Unexpected Selector structure in {q}')
    return [{'text':str(x.get('selected_text','')),'bbox':x.get('anchor'),'confidence':1.0} for x in g[0].get('results',[]) if x.get('selected_text')]

def words_from_tesseract(image):
    import io
    proc=subprocess.run(['tesseract',str(image),'stdout','tsv'],capture_output=True,text=True)
    if proc.returncode:raise RuntimeError('Tesseract failed: '+proc.stderr[-500:])
    return [{'text':r['text'],'bbox':[float(r['left']),float(r['top']),float(r['left'])+float(r['width']),float(r['top'])+float(r['height'])],
             'confidence':max(0,float(r['conf'])/100)} for r in csv.DictReader(io.StringIO(proc.stdout),delimiter='\t') if r.get('text','').strip() and float(r.get('conf','-1'))>=0]

def extract_geometry(image,dirpath):
    py=pathlib.Path('/mnt/shopai-data-new/cad-research/environments/common/bin/python')
    if not py.is_file():raise RuntimeError('Missing existing OpenCV environment: '+str(py))
    script=R/'cv_extract.py';result=dirpath/'geometry.json'
    rc=run_owned([str(py),'-B',str(script),str(image),str(result)],dirpath/'geometry.log')
    if rc or not result.is_file():raise RuntimeError('OpenCV failed; inspect '+str(dirpath/'geometry.log'))
    return jread(result)

def evidence(d,checks):
    root=R/'evidence'/d;result=root/'evidence.json';img=INPUT/IMAGES[d]
    if result.is_file():
        e=jread(result)
        if e['image_sha256']==checks[d]['image_sha256']:return e
        raise RuntimeError('Image changed since cached evidence; preserving old cache. New experiment version required for '+d)
    root.mkdir(parents=True,exist_ok=True)
    q=cached_ocr(d)
    if q is not None:words=words_from_selector(q);origin='verified-existing-selector:'+str(q)
    elif pathlib.Path('/mnt/shopai-data-new/cad-research/environments/paddleocr/bin/python').is_file():
        q=paddle_ocr(d,img,root)
        words=words_from_selector(q);origin='original-selector-1060+1947'
    elif shutil.which('tesseract'):
        words=words_from_tesseract(img);origin='tesseract-local'
    else:
        raise RuntimeError('Neither original PaddleOCR venv nor local Tesseract available')
    if not words:raise RuntimeError(d+' no OCR evidence; stop rather than fabricate labels')
    geo=extract_geometry(img,root)
    e={'drawing':d,'units':'mm','pixel_units':'px','image_sha256':checks[d]['image_sha256'],
       'ocr_origin':origin,'ocr':words,'features_px':geo['features_px'],'image_size_px':geo['image_size_px']}
    atomic(result,e);return e

def normal(s):return re.sub(r'\s+','',str(s)).lower().replace('⌀','ø').replace('Ø','ø')
def infer(e,compiled,params):
    readings=[];features=e['features_px']
    for word in e['ocr']:
        label=word['text'].strip();m=re.match(r'^\s*(R|Ø|⌀|DIA\.?|M)?\s*([+-]?\d+(?:\.\d+)?)',label,re.I)
        prefix=(m.group(1) or '').upper() if m else ''
        kind='radius_dimension' if prefix=='R' else 'linear_dimension' if m and not prefix else 'unclassified'
        val=float(m.group(2)) if m else None
        xy=center(word.get('bbox'));candidate=None
        if xy and features:
            scored=[]
            for ix,f in enumerate(features):
                dx=xy[0]-f['cx'];dy=xy[1]-f['cy'];dist=math.hypot(dx,dy)
                env={'dx':dx,'dy':dy,'dist':dist,'area':f['area'], 'confidence':word.get('confidence',0.5),**params}
                try:priority=float(eval(compiled,{'__builtins__':{},**FUNCS},env))
                except (ValueError,OverflowError,ZeroDivisionError,TypeError):continue
                if math.isfinite(priority):scored.append((priority,ix))
            if scored:candidate='feature_'+str(min(scored)[1]+1)
        readings.append({'text':label,'kind':kind,'value':val,'target':candidate,'evidence':{'bbox_original_px':word.get('bbox')}})
    # IMPORTANT: pixel contours are NOT physical dimensioned geometry.
    return {'drawing_id':e['drawing'],'units':'mm','readings':readings,'geometry':{},'raw_geometry_evidence':{'features_px':features},
            'provenance':{'image_sha256':e['image_sha256'],'truth_blind':True}}

def score_all(ev,code,params,scorer,truths):
    reports={};total=0;raw_total=0
    for d,e in ev.items():
        pred=infer(e,code,params)
        rep=scorer.evaluate(truths[d],pred)  # independent legacy scorer, not optimized proxy
        passed=int(rep['checks_passed']);checks=int(rep['checks_total'])
        expect=collections.Counter(normal(r['text']) for r in truths[d].get('visible_readings',[]))
        actual=collections.Counter(normal(r['text']) for r in pred['readings'])
        texts=sum((expect & actual).values());num=sum(expect.values())
        reports[d]={'checks_passed':passed,'checks_total':checks,'full_pct':float(rep['score_pct']),
                    'text_hits':texts,'text_total':num,'passed':bool(rep['passed'])}
        total+=passed;raw_total+=checks
    full=100*total/raw_total if raw_total else 0
    # Rank primarily by independent scorer; text is a secondary tie breaker.
    tie=sum(v['text_hits'] for v in reports.values())
    return (total,tie),full,reports

def heartbeat(phase,elapsed,detail=''):
    log('HEARTBEAT',phase,'elapsed_min',round(elapsed/60,1),detail)

def trial_batch(ev,truths,scorer,expression,count,iteration,db):
    compiled=check_expr(expression);rnd=random.Random(1867+iteration)
    top=[];started=time.monotonic();best=(-1,-1);best_params=None;best_reports=None;best_full=0
    for i in range(count):
        if STOP.exists():raise KeyboardInterrupt('TERMINATE requested')
        params={k:(0.0 if i==0 else rnd.uniform(-4,4) if k=='angle_weight' else rnd.uniform(-300,300) if k=='area_weight' else rnd.uniform(-100,100)) for k in PARAMS}
        rank,full,rep=score_all(ev,compiled,params,scorer,truths)
        db.execute('INSERT INTO tests(round,idx,expression,params,passed_checks,text_hits,full_pct) VALUES(?,?,?,?,?,?,?)',
                   (iteration,i,expression,json.dumps(params),rank[0],rank[1],round(full,5)))
        if rank>best:
            best=rank;best_params=params;best_reports=rep;best_full=full
        if i>0 and i%2000==0:
            db.commit();log('TEST_PROGRESS',iteration,i,'/',count,'best_checks',best[0],'full_pct',round(best_full,3))
        if i>0 and time.monotonic()-started>=600 and i%1000==0:
            heartbeat('CPU_SWEEP',time.monotonic()-started,'tested='+str(i));started=time.monotonic()
    db.commit()
    result={'round':iteration,'expression':expression,'best_params':best_params,'score_key':best,
            'full_pct':round(best_full,6),'by_drawing':best_reports,'trials':count,'utc':now()}
    atomic(R/'rounds'/f'{iteration:05}.json',result);atomic(R/'latest.json',result)
    log('BATCH_DONE',iteration,'trials',count,'full_pct',round(best_full,4),'by_drawing',best_reports)
    return result

def get_qwen_expression(last):
    # Single small engineering question. Qwen NEVER sees truth, raw scores by item, images, or truth paths.
    query=('You are improving a small engineering drawing feature-association Python formula. '
      'All physical dimensions are millimeters (mm), pixels are only image coordinates. '
      'We have three independent training drawings, and an independent scorer. '
      'Do NOT hardcode drawing IDs, texts, known targets, coordinates or dimensions. '
      'For each OCR label and geometric feature we calculate dx,dy,dist in pixels, area in pixels^2, '
      'and OCR confidence in [0,1]. The formula returns a LOWER-is-better association score. '
      'Allowed names: '+','.join(sorted(NAMES))+'. Allowed functions: abs,min,max,sqrt,log1p. '
      'Allowed Python arithmetic: +,-,*,/,%, parentheses; avoid division by zero. '
      'Prior formula: '+last['expression']+'. '
      'Most recent independent scoring aggregate: '+json.dumps(last['by_drawing'])+'. '
      'Suggest ONE mathematically sensible new formula. Return ONLY compact JSON '
      '{"expression":"...","reason":"..."}. Keep response under 180 words.')
    url='http://127.0.0.1:19097/v1/chat/completions'
    with urllib.request.urlopen('http://127.0.0.1:19097/v1/models',timeout=10) as resp:meta=json.load(resp)
    models=meta.get('data',[])
    if not models or 'Qwen3-Coder-30B-A3B' not in models[0].get('id',''):raise RuntimeError('Existing model endpoint identity mismatch: no automatic replacement')
    request={'model':models[0]['id'],'messages':[{'role':'system','content':'Return exactly valid JSON.'},{'role':'user','content':query}],
             'stream':False,'temperature':0.45}
    req=R/'qwen_request.json';out=R/'qwen_response.json';atomic(req,request)
    # curl is owned by this experiment and can be stopped without killing llama-server.
    with out.open('wb') as fd:
        proc=subprocess.Popen(['curl','--silent','--show-error','--fail-with-body','-H','Content-Type: application/json',
            '--data-binary','@'+str(req),url],stdout=fd,stderr=subprocess.PIPE,start_new_session=True)
        started=time.monotonic();last_heartbeat=0;hour=0
        while proc.poll() is None:
            if STOP.exists():
                os.killpg(proc.pid,signal.SIGTERM);proc.wait();raise KeyboardInterrupt('TERMINATE stopped owned Qwen request')
            elapsed=time.monotonic()-started
            if elapsed-last_heartbeat>=600:
                last_heartbeat=elapsed;heartbeat('QWEN',elapsed,'server remains untouched')
            if elapsed-hour>=3600:
                hour=elapsed;log('HOURLY','Qwen request',round(elapsed/60,1),'minutes')
            time.sleep(2)
        if proc.returncode:raise RuntimeError('Qwen HTTP request failed, curl exit '+str(proc.returncode))
    data=jread(out);msg=data['choices'][0]['message']['content'];m=re.search(r'\{.*\}',msg,re.S)
    if not m:raise RuntimeError('Qwen returned no JSON expression')
    proposal=json.loads(m.group());expr=proposal['expression'];check_expr(expr)
    return {'expression':expr,'reason':proposal.get('reason',''),'utc':now()}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--batch',type=int,default=10000);ap.add_argument('--preflight',action='store_true');args=ap.parse_args()
    if args.batch<1:raise RuntimeError('Batch must be positive')
    extend_list_from_checkpoint()
    checks=preflight() # validate ALL active originals BEFORE creating new experiment files
    if args.preflight:
        log('PREFLIGHT_PASS',checks);return
    R.mkdir(parents=True,exist_ok=True)
    lock=(R/'owner.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    if STOP.exists():raise RuntimeError('TERMINATE exists; refusing to override stop request')
    (R/'rounds').mkdir(exist_ok=True)
    (R/'proposals').mkdir(exist_ok=True)
    (R/'champions').mkdir(exist_ok=True)
    atomic(R/'input_manifest.json',checks)
    if not (R/'STOP_CODE').exists():
        import secrets,string
        code=''.join(secrets.choice(string.ascii_uppercase+string.ascii_lowercase+string.digits) for _ in range(24))
        (R/'STOP_CODE').write_text(code+'\n');(R/'STOP_CODE').chmod(0o600)
    log('BEGIN','CPU-only optimization; Qwen3-Coder-30B reuse; all 3 drawings; units=mm')
    ev={d:evidence(d,checks) for d in IMAGES};log('EVIDENCE_READY',{d:(len(v['ocr']),len(v['features_px'])) for d,v in ev.items()})
    sys.path.insert(0,str(P/'tools'));import score as scorer
    truths={d:jread(TRUTH/(d+'.truth.json')) for d in IMAGES}
    db=sqlite3.connect(R/'tests.sqlite3');db.execute('PRAGMA journal_mode=WAL')
    db.execute('CREATE TABLE IF NOT EXISTS tests(id INTEGER PRIMARY KEY,round INTEGER,idx INTEGER,expression TEXT,params TEXT,passed_checks INTEGER,text_hits INTEGER,full_pct REAL)')
    db.commit();completed=sorted((R/'rounds').glob('*.json'))
    iteration=int(completed[-1].stem)+1 if completed else 1
    current=jread(R/'next_expression.json')['expression'] if (R/'next_expression.json').exists() else EXPR
    stagnant=0
    while not STOP.exists():
        result=trial_batch(ev,truths,scorer,current,args.batch,iteration,db)
        champfile=R/'champions'/('D'+str(len(IMAGES))+'.json')
        champ=jread(champfile) if champfile.is_file() else None
        nonregression=not champ or all(result['by_drawing'][d]['checks_passed']>=champ['by_drawing'][d]['checks_passed'] for d in IMAGES)
        better=not champ or (nonregression and tuple(result['score_key'])>tuple(champ['score_key']))
        if better:
            champ=result;atomic(champfile,champ);stagnant=0
            log('NEW_CHAMPION',iteration,'checks',champ['score_key'][0])
        else:
            stagnant+=1
            log('NO_IMPROVEMENT',stagnant,'consecutive rounds','champion preserved')
        # Advance only on actual legacy full scorer, never a text-only proxy.
        if all(row['full_pct']>=99.9 and row['passed'] for row in champ['by_drawing'].values()):
            nxt='D'+str(len(IMAGES)+1);filename=next_image(nxt)
            if filename:
                IMAGES[nxt]=filename
                fresh=preflight();ev[nxt]=evidence(nxt,fresh);truths[nxt]=jread(TRUTH/(nxt+'.truth.json'))
                atomic(R/'active_drawings.json',IMAGES)
                log('DRAWING_ADDED',nxt,'keeping',','.join(IMAGES))
                iteration+=1;stagnant=0;continue
            atomic(R/'NEXT_DRAWING_REQUIRED.json',{'next':nxt,'previous_drawings_kept':list(IMAGES),'utc':now()})
            log('AWAITING_DRAWING',nxt,'all existing drawings kept; add image+verified truth before rerun');break
        if stagnant>=4:
            atomic(R/'NEEDS_ALGORITHM_CHANGE.json',{'reason':'4 rounds without independent scoring improvement','champion':champ,'utc':now()})
            log('NO_PROGRESS','Formula tuning inadequate; preserve champion and escalate to larger algorithm changes');break
        try:
            proposed=get_qwen_expression(champ)
            if proposed['expression']==current:
                log('NO_CHANGE','Qwen repeated formula; stopping to avoid wasted generations');break
            atomic(R/'proposals'/f'{iteration:05}.json',proposed)
            current=proposed['expression'];atomic(R/'next_expression.json',proposed)
        except Exception as exc:
            log('QWEN_PROPOSAL_FAILED',repr(exc),'preserving all test results; stopping for review');break
        iteration+=1
    log('FINAL','rounds',iteration,'workspace',R)

if __name__=='__main__':
    try:main()
    except KeyboardInterrupt as e:log('STOPPED',repr(e))
    except Exception as e:log('ERROR',repr(e));raise
