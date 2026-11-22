#!/usr/bin/env python3
"""ShopAI scored Qwen batch loop; additive to existing three-drawing experiment.

Uses verified copied OCR 1060+1947 Selector v2 and v5 geometry. Every candidate
is an immutable one-Python-file variation registered using the preinstalled
fingerprint ledger. Scores a candidate only after saving truth-blind predictions.
Generated programs execute inside a read-only, networkless bubblewrap sandbox
that masks the experiment's truth and feedback directories.
"""
from __future__ import annotations
import argparse, collections, datetime as dt, fcntl, hashlib, importlib.util, json, os
from pathlib import Path
import re, shutil, signal, sqlite3, subprocess, sys, tempfile, threading, time, traceback, uuid

HERE=Path(__file__).resolve().parent
P=HERE.parent
LAB=P/'batch_lab'
TOOL_DIR=HERE

def import_tool(name):
    spec=importlib.util.spec_from_file_location('shopai_live_'+name,TOOL_DIR/(name+'.py'))
    obj=importlib.util.module_from_spec(spec);spec.loader.exec_module(obj)
    return obj

mgr=import_tool('qwen_batch_lab')
gen=import_tool('qwen_batch_generate')
score=import_tool('score')

def utc():return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
def sha(b):return hashlib.sha256(b).hexdigest()
def printlog(*args):print(utc(),*args,flush=True)
def read_json(f):return json.loads(Path(f).read_text(encoding='utf8'))

def source_files(folder):
    return mgr.inventory(mgr.safe_source(folder))

def verify_sandbox():
    path=shutil.which('bwrap')
    if not path:raise RuntimeError('Bubblewrap is required; refusing to run AI-edited Python without sandbox')
    # Test real executable isolation, not just presence.
    t=subprocess.run([path,'--unshare-net','--ro-bind','/','/','--dev-bind','/dev','/dev',
        '--proc','/proc','--tmpfs','/tmp','--','/usr/bin/true'],capture_output=True,text=True,timeout=30)
    if t.returncode:raise RuntimeError('Bubblewrap isolation test failed: '+t.stderr[-800:])
    return path

def sandbox_cmd(bwrap,src_dir,output_dir,program,args,python_path):
    """Only candidate source, drawing images and its output are visible inside P.
    The rest of P is tmpfs; truth, feedback, other attempts cannot be inspected.
    All other host paths are read-only, and network is unshared.
    """
    src_dir=src_dir.resolve();output_dir=output_dir.resolve();
    image_dir=(P/'images').resolve()
    assert P.resolve() in src_dir.parents and P.resolve() in output_dir.parents
    if not (src_dir/'ocr_selector/blind_test.py').is_file():raise RuntimeError('Candidate missing OCR')
    if not (src_dir/'outline_v5/autotune.py').is_file():raise RuntimeError('Candidate missing geometry')
    sandbox=[bwrap,'--unshare-net','--ro-bind','/','/',
        '--dev-bind','/dev','/dev','--proc','/proc','--tmpfs','/tmp',
        '--tmpfs',str(P),
        '--dir',str(src_dir),'--ro-bind',str(src_dir),str(src_dir),
        '--dir',str(image_dir),'--ro-bind',str(image_dir),str(image_dir),
        '--dir',str(output_dir),'--bind',str(output_dir),str(output_dir),
        '--setenv','HOME',str(output_dir),'--setenv','XDG_CACHE_HOME',str(output_dir),
        '--setenv','TMPDIR','/tmp',
        '--setenv','OPENBLAS_NUM_THREADS','1','--setenv','OMP_NUM_THREADS','1',
        '--setenv','PYTHONUNBUFFERED','1','--chdir',str(src_dir),'--',
        str(python_path),'-B','-u',str(program),*map(str,args)]
    return sandbox

class StopRequested(Exception):pass

def run_owned(argv, cwd, log_path, label, last_good, last_progress, proc_record):
    log_path.parent.mkdir(parents=True,exist_ok=True)
    with log_path.open('x',encoding='utf8') as log:
        log.write('COMMAND: '+repr(argv)+'\n');log.flush()
        p=subprocess.Popen(argv,cwd=cwd,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        proc_record['pid']=p.pid;proc_record['label']=label
        mgr.json_atomic(last_good,{'pid':p.pid,'label':label,'started_utc':utc(),'owned_process':True})
        prior_size=log_path.stat().st_size
        while p.poll() is None:
            if mgr.TERMINATE.exists():
                os.killpg(p.pid,signal.SIGTERM)
                try:p.wait(timeout=15)
                except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL)
                raise StopRequested('TERMINATE: stopped only experiment-owned '+label)
            now_size=log_path.stat().st_size
            if now_size>prior_size:
                prior_size=now_size  # logs retained; log chatter does NOT reset the stall timer
            if time.monotonic()-last_progress[0]>=3600:
                os.killpg(p.pid,signal.SIGTERM)
                try:p.wait(timeout=15)
                except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL)
                raise StopRequested('60 minutes without output or verified completion: stopped owned '+label)
            time.sleep(1)
        proc_record.clear()
        return p.returncode

def image_for(drawing):
    mapping={'D1':'drawing_01.png','D2':'drawing_02.jpeg','D3':'drawing_03.jpg'}
    return P/'images'/mapping[drawing]

def inference_to_prediction(ocr_path,geo_path,drawing):
    """Generic evidence adapter. Never reads truth or drawing-specific coordinates.
    Added fields produced by improved candidate Python are retained verbatim.
    """
    result=read_json(ocr_path)
    groups=[x for x in result.get('rows',[]) if x.get('profiles')=='1060+1947' and x.get('plan')=='whole']
    if len(groups)!=1:raise RuntimeError('Expected exactly one 1060+1947 selector result')
    geometry_output=read_json(geo_path)
    readings=[]
    for r in groups[0].get('results',[]):
        label=str(r.get('selected_text','')).strip()
        match=re.fullmatch(r'\s*(R|Ø|⌀|DIA\.?|M)?\s*([+-]?\d+(?:\.\d+)?)\s*',label,re.I)
        tag=(match.group(1) or '').upper() if match else ''
        # If candidate added semantic classification, use it.
        kind=r.get('dimension_kind') or r.get('semantic_kind')
        if not kind:kind='radius_dimension' if tag=='R' else 'linear_dimension' if match and not tag else 'unclassified'
        value=r.get('dimension_value',float(match.group(2)) if match else None)
        target=r.get('target') or r.get('associated_feature')
        readings.append({'text':label,'kind':kind,'value':value,'target':target,
                         'evidence':{'bbox_original_px':r.get('anchor'),'ocr_kind':r.get('kind'),
                                     'ocr_state':r.get('state'),'source_profiles':'1060+1947'}})
    # Candidate needs to produce real drawing-coordinate geometry; pixel-only
    # contours are kept as evidence, not invented world-coordinate geometry.
    geom=geometry_output.get('dimensioned_geometry') or geometry_output.get('normalized_geometry') or {}
    # Explicit candidate geometry checks in physical/drawing units only.
    if not isinstance(geom,dict):geom={}
    return {'drawing_id':drawing,'readings':readings,'geometry':geom,
            'raw_geometry_evidence':geometry_output,
            'provenance':{'ocr_sha256':sha(ocr_path.read_bytes()),'geometry_sha256':sha(geo_path.read_bytes()),
                          'image_sha256':sha(image_for(drawing).read_bytes()),'truth_blind':True}}

def component_key(src, image, names):
    """Content-addressed, image-specific cache for the UNCHANGED component only.

    A candidate modifying geometry still gets fresh geometry inference, but can
    reuse exact results from the identical OCR source + image. Vice versa for OCR.
    This cache never contains reference/truth data, only blind tool outputs.
    """
    h=hashlib.sha256(b'shopai_truth_blind_components_v1\0')
    h.update(hashlib.sha256(image.read_bytes()).digest())
    for name in names:
        b=(src/name).read_bytes()
        h.update(name.encode('utf8')+b'\0'+hashlib.sha256(b).digest())
    return h.hexdigest()

def component_cache_key(src, image, which):
    if which=='ocr':
        names=['ocr_selector/legacy_lab.py','ocr_selector/selector_v2.py',
               'ocr_selector/blind_test.py','ocr_selector/tile_study.py']
    elif which=='geometry':
        names=['outline_v5/autotune.py']
    else:raise ValueError(which)
    return component_key(src,image,names)

def restore_cache(which,key,dest,expected,logfile):
    cache=LAB/'blind_component_cache'/which/key
    if not (cache/'COMPLETE').is_file() or not (cache/expected).is_file():return False
    # Copy only from a finalized cache. Destination is a fresh candidate output.
    shutil.copytree(cache,dest,dirs_exist_ok=True,ignore=shutil.ignore_patterns('COMPLETE'))
    with logfile.open('x',encoding='utf8') as f:
        f.write('CACHE_HIT blind component '+which+' SHA256 '+key+'\n')
    printlog('CACHE_HIT',which,key[:14])
    return True

def publish_cache(which,key,src,expected):
    parent=LAB/'blind_component_cache'/which
    parent.mkdir(parents=True,exist_ok=True)
    cache=parent/key
    if cache.exists():return
    temp=parent/('.tmp.'+uuid.uuid4().hex)
    try:
        shutil.copytree(src,temp)
        assert (temp/expected).is_file()
        (temp/'COMPLETE').write_text(utc()+'\n',encoding='utf8')
        temp.rename(cache)
    finally:
        if temp.exists():shutil.rmtree(temp,ignore_errors=True)

def score_candidate(bwrap,attempt,drawings,progress_file,last_progress,proc_record):
    src=attempt/'source'; scratch=attempt/'intermediates'
    first=True
    for d in drawings:
        if mgr.TERMINATE.exists():raise StopRequested('TERMINATE while scoring')
        image=image_for(d);assert image.is_file()
        work=scratch/d;work.mkdir(parents=True,exist_ok=True)
        ocr_dir=work/'ocr';geo_dir=work/'geometry'
        ocr_dir.mkdir(exist_ok=True);geo_dir.mkdir(exist_ok=True)
        ocr_script=src/'ocr_selector/blind_test.py'
        geom_script=src/'outline_v5/autotune.py'
        paddle=Path('/mnt/shopai-data-new/cad-research/environments/paddleocr/bin/python')
        common=Path('/mnt/shopai-data-new/cad-research/environments/common/bin/python')
        for bin in [paddle,common]:
            if not bin.is_file():raise RuntimeError('Missing required local Python: '+str(bin))
        ocr_key=component_cache_key(src,image,'ocr')
        ocr_expected='selector/selector_v2_results.json'
        if not restore_cache('ocr',ocr_key,ocr_dir,ocr_expected,attempt/'logs'/f'{d}.ocr.log'):
            code=run_owned(sandbox_cmd(bwrap,src,work,ocr_script,
                ['--image',image,'--workdir',ocr_dir],paddle),src,attempt/'logs'/f'{d}.ocr.log',
                d+' OCR',progress_file,last_progress,proc_record)
            if code:raise RuntimeError(f'{d} OCR returned {code}; inspect logs')
            if not (ocr_dir/ocr_expected).is_file():raise RuntimeError(f'{d} missing selector JSON')
            publish_cache('ocr',ocr_key,ocr_dir,ocr_expected)
        selected=ocr_dir/ocr_expected
        geo_key=component_cache_key(src,image,'geometry')
        geo_expected='winner_geometry.json'
        if not restore_cache('geometry',geo_key,geo_dir,geo_expected,attempt/'logs'/f'{d}.geometry.log'):
            code=run_owned(sandbox_cmd(bwrap,src,work,geom_script,
                ['--image',image,'--out',geo_dir,'--registry',geo_dir/'registry.json','--trials','5000'],common),
                src,attempt/'logs'/f'{d}.geometry.log',d+' geometry',progress_file,last_progress,proc_record)
            if code:raise RuntimeError(f'{d} geometry returned {code}; inspect logs')
            if not (geo_dir/geo_expected).is_file():raise RuntimeError(f'{d} missing winner_geometry.json')
            publish_cache('geometry',geo_key,geo_dir,geo_expected)
        geom=geo_dir/geo_expected
        prediction=inference_to_prediction(selected,geom,d)
        pred_file=attempt/'predictions'/f'{d}.json'
        mgr.json_write_new(pred_file,prediction)
        printlog('TRUTH-BLIND prediction saved',pred_file)
        # Only the evaluator reads truth, AFTER prediction has been saved.
        reference=P/'truth'/f'{d}.truth.json'
        report=score.evaluate(read_json(reference),prediction)
        report['prediction_sha256']=sha(pred_file.read_bytes())
        report['truth_sha256']=sha(reference.read_bytes())
        report_file=attempt/'evaluation'/f'{d}.report.json'
        mgr.json_write_new(report_file,report)
        printlog('SCORED',attempt.name,d,report['checks_passed'], '/',report['checks_total'],
                 'full',report['score_pct'],'%', 'pass',report['passed'])
        last_progress[0]=time.monotonic()
        mgr.json_atomic(progress_file,{'latest_scored':attempt.name,'drawing':d,'score_pct':report['score_pct'],
                                       'time_utc':utc(),'progress_unit':'completed_candidate_drawing_test'})
        first=False
    return True

def make_feedback(completed_drawings=None):
    # This tool deliberately excludes truth for untested drawings.
    feedback={'source':'actual OCR + v5 geometry results, truth revealed after image tests',
         'active_drawings':mgr.control()['active_drawings'],
         'already_tested_truth':{},'recent_tested_candidates':[],
         'directive':'Fix generalizable code. No drawing ID, filename, truth, or absolute image coordinate hardcodes. '
                     'The original 5 visible OCR labels may be correct while target associations and dimensioned geometry are missing.'}
    attempts=sorted((q for q in (P/'attempts').iterdir() if q.is_dir() and q.name.isdigit()),reverse=True)
    tested_drawings=set()
    for a in attempts:
        reps=[]
        for rep in sorted((a/'evaluation').glob('*.report.json')):
            report=read_json(rep)
            reps.append(report);tested_drawings.add(report['drawing_id'])
        if reps:
            feedback['recent_tested_candidates'].append({'attempt':a.name,'results':reps})
        if len(feedback['recent_tested_candidates'])>=5:break
    # Include the existing D1 truth as soon as the existing baseline was actually tested.
    initial=LAB/'feedback_for_qwen.json'
    if initial.exists():
        old=read_json(initial)
        tested_drawings.update(old.get('already_tested_truth',{}))
        if not feedback['recent_tested_candidates']:
            feedback['baseline_report']=old.get('baseline_report')
    for d in tested_drawings:
        ref=P/'truth'/f'{d}.truth.json'
        if ref.exists():feedback['already_tested_truth'][d]=read_json(ref)
    return feedback

def best_parent_hint():
    return mgr.control().get('active_parent','batch_lab/baseline')

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--server-url',required=True)
    ap.add_argument('--model')
    ap.add_argument('--batch',type=int,default=200,help='number of unique candidates before testing the batch')
    ap.add_argument('--temperature',type=float,default=.65)
    ap.add_argument('--smoke',action='store_true',help='run baseline and stop before any Qwen modifications')
    args=ap.parse_args()
    if args.batch<1:ap.error('--batch must be >=1')
    bwrap=verify_sandbox()
    if mgr.TERMINATE.exists():raise SystemExit('STOP: experiment TERMINATE requested')
    if mgr.control().get('generation_enabled'):
        raise SystemExit('STOP: controller indicates generation already running')
    lock=(LAB/'scored_loop.lock').open('a+')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise SystemExit('STOP: scored loop is already running')
    status=LAB/'scored_loop_status.json'
    proc_record={};last_progress=[time.monotonic(),time.monotonic()]
    stop_mon=threading.Event()
    def monitor():
        start=time.monotonic();hb=0;hour=0
        while not stop_mon.wait(2):
            elapsed=time.monotonic()-start
            if elapsed-hb>=600:
                hb=elapsed;printlog('HEARTBEAT elapsed',round(elapsed/60,1),'min; latest useful work',
                    round((time.monotonic()-last_progress[0])/60,1),'min ago; owned child',proc_record)
            if elapsed-hour>=3600:
                hour=elapsed;printlog('HOURLY',read_json(status) if status.exists() else 'starting')
    thread=threading.Thread(target=monitor,daemon=True);thread.start()
    model=None
    try:
        base=P/best_parent_hint();mgr.safe_source(base)
        # Verify real pipeline against user-supplied D1 BEFORE enabling edits.
        stage=mgr.control()['active_drawings']
        if not args.smoke:
            model=gen.get_model(args.server_url,args.model)
            printlog('QWEN READY',model, 'persistent endpoint',args.server_url)
        verified_stage=LAB/('scored_loop_baseline_verified_'+''.join(stage)+'.json')
        if not verified_stage.exists():
            # Baseline run is retained distinctly for each curriculum stage.
            trial=LAB/'scored_loop_baseline_check'/str(uuid.uuid4())
            for d in ['source','logs','predictions','evaluation','intermediates']:(trial/d).mkdir(parents=True,exist_ok=True)
            shutil.copytree(base,trial/'source',dirs_exist_ok=True)
            score_candidate(bwrap,trial,stage,status,last_progress,proc_record)
            mgr.json_write_new(verified_stage,{
                'verified_utc':utc(),'baseline_path':str(base),'real_ocr_and_geometry_ran':True,
                'scored_predictions':{d:str(trial/'predictions'/f'{d}.json') for d in stage},
                'caveat':'Not a claim of correct drawing interpretation'})
        if args.smoke:
            printlog('SMOKE COMPLETE — no Qwen modification requested')
            return
        # Stage changes require re-evaluating any newly introduced drawing
        # against the selected parent without modifying its source code.
        active_parent_path=P/mgr.control().get('active_parent','batch_lab/baseline')
        if active_parent_path.name=='source' and active_parent_path.parent.name.isdigit():
            parent_attempt=active_parent_path.parent
            missing=[d for d in stage if not (parent_attempt/'evaluation'/f'{d}.report.json').exists()]
            if missing:
                printlog('NEW STAGE parent missing drawing scores; testing',missing)
                score_candidate(bwrap,parent_attempt,missing,status,last_progress,proc_record)
        c=mgr.control();c['test_integration_verified']=True;c['generation_enabled']=True
        c['updated_utc']=utc();mgr.json_atomic(mgr.CONTROL,c)
        start_accepted=gen.query_count()
        generated_this_session=0
        printlog('START SCORED LOOP; already accepted',start_accepted,'target TOTAL unique',c['target_unique_runs'],
                 'batch',args.batch)
        feedback=make_feedback()
        rejected_in_row=0
        while True:
            if mgr.TERMINATE.exists():raise StopRequested('TERMINATE requested')
            live=mgr.control();target=live['target_unique_runs']
            if gen.query_count()>=target:
                printlog('TOTAL UNIQUE-CANDIDATE TARGET REACHED',target);break
            source=P/live.get('active_parent','batch_lab/baseline')
            frozen=source_files(source)
            batch_ids=[]
            batch_started=time.monotonic()
            while len(batch_ids)<min(args.batch,target-gen.query_count()):
                if mgr.TERMINATE.exists():raise StopRequested('TERMINATE requested')
                proposal_id,prop_dir=gen.create_proposal_id()
                progress={'generated_unique_this_session':generated_this_session,
                    'target_unique_runs':target,'proposal':proposal_id,'stage':live['active_drawings'],
                    'started_utc':utc(),'state':'GENERATING'}
                mgr.json_atomic(status,progress)
                addon='''\nSTRICT SCORER OUTPUT CONTRACT, from independently tested image results:\n- ocr_selector/blind_test.py generates selector_v2_results.json. On the\n  combined 1060+1947 row each results[] entry MUST contain observed text,\n  and you may improve the selector algorithm to infer real semantic association\n  under `target` (feature name), `dimension_kind`, and `dimension_value`.\n- outline_v5/autotune.py generates winner_geometry.json. A true solver may add\n  `normalized_geometry` containing exact, constrained drawing-coordinate geometry\n  derived generically from detected contours and printed dimensions, NOT a\n  hardcoded screenshot template. Pixel-only estimates do not count as exact mm.\n- These are NOT requests to fake scores. Missing fields are scored as missing.\n- Current baseline has already read all five D1 text annotations correctly;\n  work on feature association, geometry constraints and reliable generalization.\n- Do not modify test code, truth, provenance, file paths, or runtime permissions.\n\n'''
                lines=[{'role':'system','content':'You are improving general-purpose engineering drawing Python code. Reply only with JSON {file,old,new,reason}.'},
                    {'role':'user','content':gen.prompt(frozen,gen.history(),proposal_id,feedback)+addon}]
                try:
                    model_text=gen.request_stream(args.server_url,model,lines,args.temperature,
                         prop_dir/'stream.jsonl',last_progress,threading.Event())
                    (prop_dir/'qwen_answer.txt').write_text(model_text,encoding='utf8')
                    patch=gen.parse_model_json(model_text)
                    permitted={'ocr_selector/legacy_lab.py','ocr_selector/selector_v2.py',
                               'ocr_selector/blind_test.py','ocr_selector/tile_study.py',
                               'outline_v5/autotune.py'}
                    if patch['file'] not in permitted:
                        raise ValueError('Only working OCR, selector, or v5 geometry source may change: '+patch['file'])
                    mgr.json_write_new(prop_dir/'proposal.json',patch)
                    candidate=prop_dir/'source';shutil.copytree(source,candidate)
                    gen.apply_proposal(source,candidate,patch)
                    from argparse import Namespace
                    accepted=mgr.cmd_register(Namespace(source=str(candidate),parent=str(source),reason=patch['reason']))
                    if accepted==0:
                        rejected_in_row=0
                        generated_this_session+=1
                        attempt_number=gen.query_count()
                        # Attempt number isn't guaranteed to match accepted count in an external repo;
                        # use highest created immutable attempt folder.
                        attempt=P/'attempts'/f'{mgr.next_attempt()-1:04d}'
                        batch_ids.append(attempt)
                        printlog('ACCEPTED',attempt.name,'batch',len(batch_ids),'of',args.batch)
                    else:
                        rejected_in_row+=1
                except (ValueError,KeyError,json.JSONDecodeError,SyntaxError) as exc:
                    rejected_in_row+=1
                    (prop_dir/'ERROR.txt').write_text(str(exc)+'\n',encoding='utf8')
                    printlog('REJECTED/INVALID',proposal_id,exc)
                if rejected_in_row and rejected_in_row%10==0:
                    printlog('ALERT',rejected_in_row,'consecutive duplicate/invalid proposals; all preserved; keep generating until new code or real watchdog stop')
                live=mgr.control();target=live['target_unique_runs']
                if gen.query_count()>=target:break
            # Score the actual accepted snapshots in a batch, with NO truth visible
            # to their execution. Qwen gets reports before next generation batch.
            for ix,attempt in enumerate(batch_ids,1):
                mgr.json_atomic(status,{'phase':'SCORING','attempt':attempt.name,
                    'batch_index':ix,'batch_size':len(batch_ids),'utc':utc(),
                    'target_unique_runs':target})
                try:score_candidate(bwrap,attempt,live['active_drawings'],status,last_progress,proc_record)
                except (StopRequested,KeyboardInterrupt):raise
                except Exception as exc:
                    (attempt/'logs'/'test_failure.txt').write_text(traceback.format_exc(),encoding='utf8')
                    printlog('FAILED candidate test',attempt.name,repr(exc))
            # Choose a demonstrably better experimental parent, preserving ALL
            # old baselines and every candidate. Never promote regressions.
            old_parent=live.get('active_parent','batch_lab/baseline')
            if old_parent=='batch_lab/baseline':
                baseline_reports=list((LAB/'scored_loop_baseline_check').glob('*/evaluation/*.report.json'))
                parent_scores={d:0 for d in live['active_drawings']}
                for report_file in baseline_reports:
                    r=read_json(report_file)
                    if r['drawing_id'] in parent_scores:parent_scores[r['drawing_id']]=r['checks_passed']
            else:
                parent_attempt=(P/old_parent).parent
                parent_scores={d:read_json(parent_attempt/'evaluation'/f'{d}.report.json')['checks_passed']
                               for d in live['active_drawings']}
            qualified=[]
            for a in batch_ids:
                report_files={d:a/'evaluation'/f'{d}.report.json' for d in live['active_drawings']}
                if not all(p.exists() for p in report_files.values()):continue
                current_scores={d:read_json(p)['checks_passed'] for d,p in report_files.items()}
                if all(current_scores[d]>=parent_scores[d] for d in current_scores) and any(
                    current_scores[d]>parent_scores[d] for d in current_scores):
                    qualified.append((sum(current_scores.values()),a,current_scores))
            if qualified:
                _,next_parent,scores=sorted(qualified,key=lambda r:r[0],reverse=True)[0]
                from argparse import Namespace
                mgr.cmd_select_parent(Namespace(attempt=int(next_parent.name),approve_partial=True))
                printlog('PROMOTED BETTER EXPERIMENTAL PARENT',next_parent.name,scores,'previous',parent_scores)
            feedback=make_feedback()
            mgr.json_atomic(LAB/'feedback_for_qwen.json',feedback)
            elapsed=time.monotonic()-batch_started
            prior_size=args.batch
            # Measured rate only: grow batch when the completed batch was faster
            # than 10 minutes. Never introduce a fixed upper code-count cap.
            if elapsed<600 and batch_ids:
                per_candidate=elapsed/len(batch_ids)
                desired=max(prior_size+1,int(600/max(per_candidate,0.001)))
                args.batch=desired
            mgr.json_atomic(LAB/'latest_batch_runtime.json',{
                'utc':utc(),'tested':len(batch_ids),'seconds':round(elapsed,3),
                'previous_batch_size':prior_size,'next_batch_size':args.batch,
                'target_unique_runs':mgr.control()['target_unique_runs']})
            printlog('BATCH SCORED',len(batch_ids),'in',round(elapsed,1),'seconds; next batch',args.batch,
                     'Qwen feedback updated; model stays loaded')
            passing=[]
            for a in batch_ids:
                rep_files=[a/'evaluation'/f'{d}.report.json' for d in live['active_drawings']]
                if all(r.exists() and read_json(r).get('passed') for r in rep_files):passing.append(a)
            if passing:
                # Advance cumulative curriculum automatically without reloading
                # Qwen: D1 -> D1+D2 -> D1+D2+D3. The active parent is not
                # replaced until independent scoring verifies an improvement.
                active=list(mgr.control()['active_drawings'])
                if len(active)<3:
                    from argparse import Namespace
                    next_drawing='D'+str(len(active)+1)
                    mgr.cmd_stage(Namespace(stage=str(len(active)+1)))
                    printlog('CURRICULUM ADVANCED',active,'->',mgr.control()['active_drawings'],
                             'new draw',next_drawing)
                    parent_path=P/mgr.control()['active_parent']
                    if parent_path.name=='source' and parent_path.parent.name.isdigit():
                        candidate_parent=parent_path.parent
                        if not (candidate_parent/'evaluation'/f'{next_drawing}.report.json').exists():
                            score_candidate(bwrap,candidate_parent,[next_drawing],status,last_progress,proc_record)
                    else:
                        trial=LAB/'scored_loop_stage_check'/str(uuid.uuid4())
                        for sub in ['source','logs','predictions','evaluation','intermediates']:
                            (trial/sub).mkdir(parents=True,exist_ok=True)
                        shutil.copytree(parent_path,trial/'source',dirs_exist_ok=True)
                        score_candidate(bwrap,trial,[next_drawing],status,last_progress,proc_record)
                    feedback=make_feedback()
                    mgr.json_atomic(LAB/'feedback_for_qwen.json',feedback)
                    continue
                printlog('100% ALL THREE DRAWINGS PASS — save checkpoint for human overlay review',passing[0]);break
        printlog('SCORING CYCLE COMPLETE')
    finally:
        stop_mon.set();thread.join(timeout=3)
        c=mgr.control();c['generation_enabled']=False;c['updated_utc']=utc();mgr.json_atomic(mgr.CONTROL,c)
        fcntl.flock(lock,fcntl.LOCK_UN);lock.close()

if __name__=='__main__':
    try:main()
    except KeyboardInterrupt:raise SystemExit('Keyboard interrupt; owned process only')
    except StopRequested as exc:raise SystemExit('STOPPED: '+str(exc))
