#!/usr/bin/env python3
"""ShopAI selector-only evolutionary test: archived OCR alternatives, fixed D1-D3 truth.
No OCR or outline code modified. Qwen proposes safe scoring recipes; never sees truth.
"""
import ast,collections,datetime,fcntl,gzip,hashlib,json,math,os,pathlib,random,re,signal,socket,subprocess,sys,time,urllib.request,unicodedata
P=pathlib.Path('/mnt/shopai-data-new/cad-research/experiments/qwen-3-drawing-20261030-173652-610108/shopai_three_drawing_truth')
R=P/'batch_lab/selector_evolution_v2'
STOP=R/'TERMINATE'
IMAGES={'D1':'drawing_01.png','D2':'drawing_02.jpeg','D3':'drawing_03.jpg'}
FIELDS=['vote','conf','grammar','bad','decimal','radius','diameter','angle','tail','spaces','letters','digits','length','punct','count','note','selected']
DEFAULT={'bias':0.0,'vote':0.2,'conf':0.2,'grammar':0.8,'bad':-1.0,'decimal':0.2,'radius':0.15,'diameter':0.15,'angle':0.15,'tail':-0.8,'spaces':-0.01,'letters':0.0,'digits':0.0,'length':0.02,'punct':-0.05,'count':0.0,'note':0.0,'selected':0.0}
REGEXNUM=r'(?:\d+(?:\.\d*)?|\.\d+)'
def utc():return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
def say(*args):print(utc(),*args,flush=True)
def readj(p):return json.loads(pathlib.Path(p).read_text())
def writej(p,obj):
    p=pathlib.Path(p);p.parent.mkdir(parents=True,exist_ok=True);q=p.with_name(p.name+'.tmp.'+str(os.getpid()));q.write_text(json.dumps(obj,indent=2,ensure_ascii=False)+'\n');os.replace(q,p)
def digest(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def norm(t):return ' '.join(unicodedata.normalize('NFKC',str(t)).upper().strip().split()).replace('⌀','Ø')
def bbox(v):
    if isinstance(v,dict):v=v.get('bbox',v.get('box',v.get('anchor')))
    if isinstance(v,(list,tuple)) and len(v)>=4 and all(isinstance(x,(float,int)) for x in v[:4]):return list(v[:4])
    return None

def alt_rows(item):
    """Unpack live Selector v2 JSON conservatively, without manufacturing OCR readings."""
    options=[]
    def add(raw, fallback=0.0, origin='alternative'):
        if isinstance(raw,str): txt=raw;val=fallback
        elif isinstance(raw,(tuple,list)) and raw and isinstance(raw[0],str):
            txt=raw[0];val=raw[1] if len(raw)>1 and isinstance(raw[1],(int,float)) else fallback
        elif isinstance(raw,dict):
            txt=raw.get('text',raw.get('selected_text',raw.get('candidate',raw.get('value'))))
            val=raw.get('score',raw.get('weight',raw.get('support',raw.get('confidence',fallback))))
        else:return
        if not isinstance(txt,str) or not txt.strip():return
        try:val=float(val)
        except (TypeError,ValueError):val=float(fallback)
        if not math.isfinite(val):val=0.0
        options.append({'text':txt.strip(),'vote':max(-50,min(50,val)),'origin':origin,'confidence':max(0.0,min(1.0,float(raw.get('confidence_peak',raw.get('confidence',0.0))))) if isinstance(raw,dict) and isinstance(raw.get('confidence_peak',raw.get('confidence',0.0)),(int,float)) else 0.0})
    add(item.get('selected_text',''),0.0,'original_selected')
    raw=item.get('alternatives',[])
    if isinstance(raw,dict):
        for k,v in raw.items():
            if isinstance(v,(int,float)):add(k,v)
            elif isinstance(v,dict):add({'text':k,**v})
            else:add(v)
    elif isinstance(raw,list):
        for a in raw:add(a)
    # Direct field names vary by Selector version. Preserve source-supplied alternatives only.
    for field in ('candidates','competing_candidates','hypotheses'):
        v=item.get(field,[])
        if isinstance(v,list):
            for a in v:add(a)
    if not options:return []
    unique={}
    for c in options:
        k=norm(c['text'])
        if k not in unique or c['vote']>unique[k]['vote']:unique[k]=c
    out=list(unique.values())
    # Preserve original selected alternative as a fallback, even if lower-ranked.
    for c in out:c['selected']=int(norm(c['text'])==norm(item.get('selected_text','')))
    return out

def candidate_files(d):
    old=P/'batch_lab/evolution_mm_v1/evidence'/d/'paddle/selector/selector_v2_results.json'
    base=P/'batch_lab/scored_loop_baseline_check'
    possibilities=[]
    if old.is_file():possibilities.append(old)
    if base.is_dir():possibilities+=list(base.glob('*/intermediates/'+d+'/ocr/selector/selector_v2_results.json'))
    if d=='D1':
        ptr=P/'batch_lab/last_real_baseline_run.txt'
        if ptr.is_file():
            q=pathlib.Path(ptr.read_text().strip())/'ocr/selector/selector_v2_results.json'
            if q.is_file():possibilities.append(q)
    return list(dict.fromkeys(possibilities))

def evidence(d):
    possibilities=candidate_files(d)
    if not possibilities:raise RuntimeError(f'{d}: No original Selector v2 JSON found.')
    for f in possibilities:
        try:
            src=readj(f)
            rows=[x for x in src.get('rows',[]) if x.get('profiles')=='1060+1947' and x.get('plan')=='whole']
            if len(rows)!=1:continue
            groups=[]
            for item in rows[0].get('results',[]):
                alts=alt_rows(item)
                if alts:groups.append({'bbox':bbox(item.get('anchor')),'alternatives':alts})
            if groups:
                return {'source':str(f),'sha256':digest(f),'groups':groups}
        except (OSError,ValueError,KeyError,TypeError):continue
    raise RuntimeError(f'{d}: No valid combined OCR groups found.')

def truth_text(d):
    p=P/'truth'/(d+'.truth.json')
    if not p.is_file():raise RuntimeError(f'Missing {p}')
    obj=readj(p)
    for key in ('units','drawing_units','dimension_units','measurement_units'):
        v=obj.get(key)
        if isinstance(v,dict):v=v.get('value',v.get('unit'))
        if isinstance(v,str) and v.strip().lower() not in ('mm','millimeter','millimeters','millimetre','millimetres','unknown','unspecified'):
            raise RuntimeError(f'{d} unexpected unit {key}={v}; originals unchanged')
    vals=obj.get('visible_readings',[])
    if not isinstance(vals,list) or not vals:raise RuntimeError(f'{d}: no visible_readings truth; cannot score text')
    text=[{'text':norm(x['text']),'bbox':bbox(x.get('bbox',x.get('anchor',x.get('bbox_px'))))} for x in vals if isinstance(x,dict) and x.get('text')]
    if not text:raise RuntimeError(f'{d}: no usable labeled text')
    return text,digest(p)

def feat(c):
    s=norm(c['text']);flat=re.sub(r'\s+','',s)
    radius=bool(re.fullmatch(r'(?:R'+REGEXNUM+'|'+REGEXNUM+'R)',flat))
    diameter=bool(re.fullmatch(r'(?:Ø'+REGEXNUM+'|'+REGEXNUM+'(?:DIA|Ø))',flat))
    angle=bool(re.fullmatch(REGEXNUM+r'°',flat))
    linear=bool(re.fullmatch(r'[+-]?'+REGEXNUM,flat))
    count=bool(re.search(r'(?:\d+\s*(?:PLACES|X)|HOLES?)',s))
    note=bool(re.search(r'[A-Z]{3,}',s))
    bad=sum(ch not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.°Ø+-,/ :()_±×' for ch in s)
    bad+=int(bool(re.search(r'\d\.[A-Z](?:R|$)',flat)))
    # A trailing '-' can be a legitimate negative sign elsewhere, but is suspicious after R.
    tail=int(bool(re.search(r'[A-Z0-9°]-$',flat)))
    decimal=int(bool(re.search(r'\d\.\d',flat)))
    v={'vote':c['vote'],'conf':c.get('confidence',0.0),
       'grammar':int(radius or diameter or angle or linear or count or note),
       'bad':bad,'decimal':decimal,'radius':int(radius),'diameter':int(diameter),
       'angle':int(angle),'tail':tail,'spaces':len(s)-len(flat),
       'letters':sum(x.isalpha() for x in flat),'digits':sum(x.isdigit() for x in flat),
       'length':len(flat),'punct':sum(x in '.,:;/-' for x in flat),
       'count':int(count),'note':int(note),'selected':c.get('selected',0)}
    return v

def safe_formula(formula):
    if not isinstance(formula,str) or len(formula)>750:raise ValueError('bad formula length')
    tree=ast.parse(formula,mode='eval')
    if len(list(ast.walk(tree)))>220:raise ValueError('formula too complex')
    allowed=(ast.Expression,ast.BinOp,ast.UnaryOp,ast.Name,ast.Load,ast.Constant,ast.Add,ast.Sub,ast.Mult,ast.Div,ast.USub,ast.UAdd,ast.Mod,ast.Pow,ast.IfExp,ast.Compare,ast.Gt,ast.Lt,ast.GtE,ast.LtE,ast.Eq,ast.NotEq,ast.BoolOp,ast.And,ast.Or,ast.Call)
    for n in ast.walk(tree):
        if not isinstance(n,allowed):raise ValueError('forbidden expression '+type(n).__name__)
        if isinstance(n,ast.Name) and n.id not in set(FIELDS)|{'abs','min','max'}:raise ValueError('unknown feature '+n.id)
        if isinstance(n,ast.Call) and (not isinstance(n.func,ast.Name) or n.func.id not in ('abs','min','max') or n.keywords):raise ValueError('forbidden function')
        if isinstance(n,ast.Constant) and (not isinstance(n.value,(int,float,bool)) or isinstance(n.value,(int,float)) and abs(n.value)>1e5):raise ValueError('bad constant')
        if isinstance(n,ast.Pow) and not (isinstance(n.right,ast.Constant) and isinstance(n.right.value,int) and abs(n.right.value)<=3):raise ValueError('exponent unsafe')
    return compile(tree,'<safe-qwen-selector-expression>','eval')

def validate_recipe(r):
    if not isinstance(r,dict):raise ValueError('recipe must be object')
    w=r.get('weights',{})
    if not isinstance(w,dict):raise ValueError('weights must be object')
    for k,v in w.items():
        if k not in DEFAULT or not isinstance(v,(int,float)) or not math.isfinite(v) or abs(v)>100:raise ValueError('bad weight')
    terms=r.get('rules',[])
    if not isinstance(terms,list) or len(terms)>32:raise ValueError('bad rules')
    for line in terms:
        if not isinstance(line,dict) or line.get('feature') not in FIELDS or not isinstance(line.get('weight'),(int,float)) or not math.isfinite(line['weight']) or abs(line['weight'])>100:raise ValueError('bad rule')
    code=safe_formula(r.get('formula','0'))
    return code

def sig(r):return json.dumps(r,sort_keys=True,separators=(',',':'))
def select(groups,r,code=None):
    if code is None:code=validate_recipe(r)
    weights=DEFAULT.copy();weights.update(r.get('weights',{}));rules=r.get('rules',[])
    chosen=[]
    for g in groups:
        scored=[]
        for c in g['alternatives']:
            f=feat(c)
            try:
                value=sum(float(weights[k])*float(f[k]) for k in FIELDS)
                value+=sum(float(t['weight'])*float(f[t['feature']]) for t in rules)
                value+=float(eval(code,{'__builtins__':{},'abs':abs,'min':min,'max':max},f))
            except (ZeroDivisionError,ValueError,TypeError,OverflowError):value=-1e9
            if not math.isfinite(value):value=-1e9
            scored.append((value, c['text']))
        chosen.append(max(scored,key=lambda z:(z[0],z[1]))[1])
    return chosen

def spatial_match(truth_rows, group_rows, options):
    """Count one-to-one exact texts at approximately corresponding annotated regions.
    Requires every truth and OCR group to have valid original-image boxes.
    No truth locations are exposed to the selector or to Qwen.
    """
    if not truth_rows or any(not r.get('bbox') for r in truth_rows) or any(not r.get('bbox') for r in group_rows):
        return None
    edges=[]
    for i,t in enumerate(truth_rows):
        a=t['bbox'];ac=((a[0]+a[2])/2,(a[1]+a[3])/2)
        for j,g in enumerate(group_rows):
            if t['text'] not in options[j]:continue
            b=g['bbox'];bc=((b[0]+b[2])/2,(b[1]+b[3])/2)
            dist=math.hypot(ac[0]-bc[0],ac[1]-bc[1])
            tolerance=max(8.0,math.hypot(a[2]-a[0],a[3]-a[1])*.75)
            if dist<=tolerance:edges.append((dist,i,j))
    used_t=set();used_g=set()
    for _,i,j in sorted(edges):
        if i not in used_t and j not in used_g:used_t.add(i);used_g.add(j)
    return len(used_t)

def evaluate(ds,r):
    code=validate_recipe(r); reports={}; tot_hit=tot_expected=tot_pred=0; predictions=[]
    for d in IMAGES:
        chosen=select(ds[d]['groups'],r,code)
        truth=collections.Counter(z['text'] for z in ds[d]['truth'])
        predicted=collections.Counter(norm(s) for s in chosen)
        text_only_matches=sum((truth&predicted).values())
        spatial_hits=spatial_match(ds[d]['truth'],ds[d]['groups'],[[norm(s)] for s in chosen])
        matches=spatial_hits if spatial_hits is not None else text_only_matches
        expected=sum(truth.values()); emitted=sum(predicted.values())
        p=matches/max(1,emitted);rec=matches/max(1,expected)
        f1=2*p*rec/(p+rec) if p+rec else 0
        oracle=collections.Counter()
        for g in ds[d]['groups']:
            for s in set(norm(x['text']) for x in g['alternatives']):oracle[s]+=1
        oracle_text=sum((oracle&truth).values())
        oracle_spatial=spatial_match(ds[d]['truth'],ds[d]['groups'],[
            [norm(x['text']) for x in g['alternatives']] for g in ds[d]['groups']])
        avail=oracle_spatial if oracle_spatial is not None else oracle_text
        reports[d]={'exact_selected':matches,'expected':expected,'emitted':emitted,'f1':round(f1,6),'candidate_coverage':f'{avail}/{expected}',
                    'text_only_hits':text_only_matches,'spatially_verified':spatial_hits is not None}
        tot_hit+=matches;tot_expected+=expected;tot_pred+=emitted
        predictions.append((d,tuple(norm(x) for x in chosen)))
    precision=tot_hit/max(1,tot_pred);recall=tot_hit/max(1,tot_expected)
    f1=2*precision*recall/(precision+recall) if precision+recall else 0
    macro=sum(r['f1'] for r in reports.values())/3
    worst=min(r['f1'] for r in reports.values())
    return {'reports':reports,'exact_hits':tot_hit,'expected':tot_expected,'false_or_extra':tot_pred-tot_hit,
            'f1':round(f1,8),'macro':round(macro,8),'worst':round(worst,8),
            'signature':hashlib.sha256(repr(predictions).encode()).hexdigest()[:16],
            'score_key':(round(worst,6),round(macro,6),round(f1,6),tot_hit,-(tot_pred-tot_hit))}

def mutate(r,rng):
    q=json.loads(json.dumps(r));w=q.setdefault('weights',{});k=rng.choice(FIELDS)
    w[k]=round(max(-60,min(60,float(w.get(k,DEFAULT[k]))+rng.gauss(0,rng.choice([0.03,0.15,0.8,2.0,8.0])))),5)
    if rng.random()<.22:
        k2=rng.choice(FIELDS);w[k2]=round(max(-60,min(60,float(w.get(k2,DEFAULT[k2]))+rng.gauss(0,2))),5)
    if rng.random()<.08:
        lines=q.setdefault('rules',[])
        if len(lines)<32:lines.append({'feature':rng.choice(FIELDS),'weight':round(rng.uniform(-4,4),4)})
    if rng.random()<.06 and q.get('rules'):
        q['rules'].pop(rng.randrange(len(q['rules'])))
    return q

def elite_insert(elites,candidate,score,limit=5):
    keyed={sig(x['recipe']):x for x in elites}
    entry={'recipe':candidate,'score':score}
    keyed[sig(candidate)]=entry
    sorted_rows=sorted(keyed.values(),key=lambda x:tuple(x['score']['score_key']),reverse=True)
    # Prefer diverse prediction signatures, then fill remaining slots with distinct recipes.
    selected=[];seen=set()
    for x in sorted_rows:
        s=x['score']['signature']
        if s not in seen:
            selected.append(x);seen.add(s)
        if len(selected)==limit:break
    for x in sorted_rows:
        if len(selected)==limit:break
        if x not in selected:selected.append(x)
    return selected

def qwen_task(elites,roundnum,output):
    # No truth content, image pixels, labels, coordinates or target list included.
    concise=[]
    for e in elites[:5]:
        concise.append({'weights':e['recipe'].get('weights',{}),'rules':e['recipe'].get('rules',[]),
            'formula':e['recipe'].get('formula','0'),'scores':{d:{'selected':x['exact_selected'],'total':x['expected'],'f1':x['f1']} for d,x in e['score']['reports'].items()}})
    msg=('Improve an OFFLINE OCR selector, choosing the correct raw OCR text candidate at each detected text position. '
       'Never generate new text values, guessing missing characters, or drawing-specific rules. All physical dimensions are mm, OCR boxes are pixels. '
       'You may ADD rule lines, MODIFY weights or ADD safe arithmetic expression terms. '
       'Feature names: '+','.join(FIELDS)+'. Higher scores WIN. Formula can use feature names, arithmetic, min,max,abs and simple ternary. '
       'Each recipe object: {"weights":{"grammar":1.0,"bad":-1.0,...},"rules":[{"feature":"tail","weight":-2.0}],"formula":"0"}. '
       'Each numeric weight <=100 absolute. No imports, functions, Python scripts, paths, external calls or hardcoded known answers. '
       'Return ONLY JSON {"revisions":[5 distinct recipe objects]}, all five distinct. '
       'Avoid high rewards for OCR engine confidence, which was often wrong. '
       'These are the five current best candidate structures and ONLY aggregate scores: '+json.dumps(concise,separators=(',',':')))
    with urllib.request.urlopen('http://127.0.0.1:19097/v1/models',timeout=15) as resp:info=json.load(resp)
    names=[m.get('id','') for m in info.get('data',[])]
    names=[n for n in names if 'qwen3-coder-30b-a3b' in n.lower()]
    if not names:raise RuntimeError('Existing Qwen3-Coder-30B endpoint not found; model untouched')
    data={'model':names[0],'messages':[{'role':'system','content':'Return minimal valid JSON only; no commentary.'},{'role':'user','content':msg}],
          'temperature':0.6,'stream':False}
    req=urllib.request.Request('http://127.0.0.1:19097/v1/chat/completions',data=json.dumps(data).encode(),headers={'Content-Type':'application/json'})
    # This is a local-model request; experiment owner can interrupt owned helper without stopping Qwen server.
    with urllib.request.urlopen(req,timeout=None) as resp:obj=json.load(resp)
    content=obj['choices'][0]['message'].get('content') or ''
    txt=content.strip()
    if txt.startswith('```'):txt=re.sub(r'^```(?:json)?\s*|\s*```$','',txt)
    try:parsed=json.loads(txt)
    except json.JSONDecodeError:
        a=txt.find('{');b=txt.rfind('}')+1
        if a<0 or b<a:raise RuntimeError('No JSON returned from model')
        parsed=json.loads(txt[a:b])
    revisions=parsed.get('revisions',[])
    if not isinstance(revisions,list):raise RuntimeError('No revisions list')
    good=[]
    for q in revisions:
        try:validate_recipe(q);good.append(q)
        except (ValueError,SyntaxError):continue
    writej(output,{'round':roundnum,'revisions':good,'raw_count':len(revisions),'utc':utc()})
    say('QWEN_RESULT','accepted_revisions',len(good),'requested',5)

def main():
    R.mkdir(parents=True,exist_ok=True)
    lockfd=(R/'selector.pid.lock').open('a+')
    try:fcntl.flock(lockfd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise SystemExit('Already running selector_evolution_v1')
    if STOP.exists():raise SystemExit('TERMINATE exists; no new experiment started')
    say('PREPARING','selector-only; all D1,D2,D3; no image or model downloads')
    ds={};inventory={}
    for d,name in IMAGES.items():
        image=P/'images'/name
        if not image.is_file():raise RuntimeError(f'Missing image {image}')
        e=evidence(d); t,th=truth_text(d)
        e['truth']=t;ds[d]=e
        inventory[d]={'image_sha256':digest(image),'ocr_sha256':e['sha256'],'ocr_source':e['source'],'groups':len(e['groups']),
                      'multi_candidate_groups':sum(len(g['alternatives'])>1 for g in e['groups']),
                      'truth_sha256':th,'truth_labels':len(t),'physical_units':'mm','coordinates':'px'}
    writej(R/'inventory.json',inventory)
    say('PREFLIGHT_PASS',json.dumps(inventory,separators=(',',':')))
    if sum(v['multi_candidate_groups'] for v in inventory.values())<2:raise RuntimeError('Too few alternatives for selector optimization; must inspect original raw OCR')
    # Selector training receives ONLY OCR evidence. Truth remains local to evaluate(), never Qwen.
    base={'weights':DEFAULT.copy(),'rules':[],'formula':'0'}
    saved=R/'best_five.json';elites=readj(saved) if saved.exists() else []
    for e in elites:validate_recipe(e['recipe'])
    for r in [base,{'weights':{**DEFAULT,'vote':1.5,'grammar':.2},'formula':'0','rules':[]},
              {'weights':{**DEFAULT,'bad':-6,'tail':-5,'grammar':1.5},'formula':'0','rules':[]},
              {'weights':{**DEFAULT,'decimal':3.0,'radius':2,'angle':2},'formula':'0','rules':[]},
              {'weights':{**DEFAULT,'selected':2.0},'formula':'0','rules':[]}]:
        elites=elite_insert(elites,r,evaluate(ds,r))
    writej(saved,elites)
    rounds=sorted(R.glob('round_*.json'));roundnum=len(rounds)+1
    rng=random.Random(450719+roundnum)
    lastbest=max([e['score']['score_key'] for e in elites],default=(0,0,0,0,0));stall=0
    while not STOP.exists():
        t0=time.monotonic();count=20000;results=[]
        ledger=R/f'tests_{roundnum:05d}.jsonl.gz'
        if ledger.exists():raise RuntimeError(f'Refusing to overwrite existing ledger {ledger}; inspect interrupted run first')
        tested=0
        with gzip.open(ledger,'xt',encoding='utf-8',compresslevel=4) as audit:
                # Explicit batch size chosen as 20k per round; no model inference per variant.
            for i in range(count):
                if STOP.exists():break
                seed=elites[i%len(elites)]['recipe'] if i<50 else rng.choice(elites)['recipe']
                recipe=mutate(seed,rng)
                if i%200==0 and len(elites)>1:
                    a,b=rng.sample(elites,2);recipe=json.loads(json.dumps(a['recipe']))
                    for k,v in b['recipe'].get('weights',{}).items():
                        if rng.random()<.5:recipe.setdefault('weights',{})[k]=v
                try:score=evaluate(ds,recipe)
                except (ValueError,SyntaxError):continue
                elites=elite_insert(elites,recipe,score)
                audit.write(json.dumps({'index':i,'recipe':recipe,'score':score},separators=(',',':'),ensure_ascii=False)+'\n')
                tested+=1
                if (i+1)%2000==0:
                    say('TEST_PROGRESS','round',roundnum,i+1,'/',count,'best',elites[0]['score']['exact_hits'],'/',elites[0]['score']['expected'],
                        'worst_f1',elites[0]['score']['worst'])
                    writej(saved,elites)
                if time.monotonic()-t0>=600 and (i+1)%500==0:
                    say('HEARTBEAT','round',roundnum,'tests',i+1,'elapsed_seconds',round(time.monotonic()-t0))
                    t0=time.monotonic()
        best=elites[0]['score'];
        writej(R/f'round_{roundnum:05d}.json',{'round':roundnum,'tests_target':count,'tests_completed':tested,'ledger':str(ledger),'best_five':elites,'utc':utc()})
        writej(saved,elites)
        say('BATCH_DONE','round',roundnum,'exact_selected',best['exact_hits'],'/',best['expected'],'full_f1',best['f1'],'tested',tested)
        if STOP.exists():break
        # Correct selection across this known training set is not enough to certify future drawings.
        if all(z['exact_selected']==z['expected'] and z['false_or_extra']==0 for z in [best]):
            say('TRAINING_TEXT_100_PERCENT','Stop for independent new-drawing verification; no auto-promotion to phase 2')
            break
        if tuple(best['score_key'])>tuple(lastbest):lastbest=best['score_key'];stall=0
        else:stall+=1
        if stall>=4:
            say('PLATEAU','Four rounds without improvement; preserve checkpoint, stop rather than repeat futile work')
            break
        # Qwen refines current five. Local request only; no new model loaded, no outbound data.
        qpath=R/f'qwen_{roundnum:05d}.json';ql=R/f'qwen_{roundnum:05d}.log'
        with ql.open('w') as fd:
            p=subprocess.Popen([sys.executable,'-u',str(pathlib.Path(__file__).resolve()),'--qwen',str(roundnum),str(qpath)],
                              stdout=fd,stderr=subprocess.STDOUT,start_new_session=True)
        started=time.monotonic();lastbeat=0
        while p.poll() is None:
            if STOP.exists():
                os.killpg(p.pid,signal.SIGTERM)
                try:p.wait(timeout=20)
                except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL)
                break
            if time.monotonic()-lastbeat>=600:
                if time.monotonic()-started>=3600:say('HOURLY_PROGRESS','QWEN_PROPOSING','round',roundnum)
                say('HEARTBEAT','QWEN_PROPOSING','round',roundnum,'elapsed_seconds',round(time.monotonic()-started))
                lastbeat=time.monotonic()
            time.sleep(4)
        if STOP.exists():break
        if p.returncode or not qpath.exists():
            say('QWEN_UNAVAILABLE','Preserving best five and pausing, see',ql)
            break
        proposals=readj(qpath)['revisions'];accepted=0
        for r in proposals:
            try:
                e=evaluate(ds,r)
                elites=elite_insert(elites,r,e);accepted+=1
            except (ValueError,SyntaxError):pass
        writej(saved,elites)
        say('QWEN_ROUND','proposals',len(proposals),'valid',accepted,'new_best',elites[0]['score']['exact_hits'])
        if not accepted:
            say('STOP','No valid revisions; preserve experiment for review')
            break
        roundnum+=1
    say('FINAL','round',roundnum,'best_five',saved,'STOP_requested',STOP.exists())

if __name__=='__main__':
    try:
        if len(sys.argv)>1 and sys.argv[1]=='--qwen':qwen_task(readj(R/'best_five.json'),int(sys.argv[2]),pathlib.Path(sys.argv[3]))
        else:main()
    except (Exception,KeyboardInterrupt) as e:
        say('EXPERIMENT_STOP',type(e).__name__,str(e));sys.exit(2)
