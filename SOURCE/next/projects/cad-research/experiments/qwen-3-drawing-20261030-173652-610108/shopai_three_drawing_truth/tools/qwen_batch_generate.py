#!/usr/bin/env python3
"""Local Qwen persistent-server candidate generator; does not execute candidates.

One generation = one Python change in an EXPERIMENTAL copy. Each unique
candidate is registered by qwen_batch_lab.py; duplicates are never retested.
Requires confirmed image predictor/test integration before a scored experiment.
The Qwen server is an existing, explicitly selected LOCAL service and is NEVER
spawned, reloaded, killed or reconfigured by this script.
"""
from __future__ import annotations
import argparse
import datetime as dt
import fcntl
import http.client
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import sqlite3
import sys
import threading
import time
import urllib.parse

TOOLS=Path(__file__).resolve().parent
PROJECT=TOOLS.parent
LAB=PROJECT/'batch_lab'
spec=importlib.util.spec_from_file_location('shopai_qwen_batch_lab',TOOLS/'qwen_batch_lab.py')
manager=importlib.util.module_from_spec(spec)
spec.loader.exec_module(manager)

class Stall(Exception):pass
class Protocol(Exception):pass


def utc():return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')

def query_count():
    with manager.open_db() as db:
        return db.execute('SELECT COUNT(*) FROM accepted').fetchone()[0]


def history():
    with manager.open_db() as db:
        return db.execute('SELECT attempt,file,rationale FROM accepted ORDER BY attempt DESC LIMIT 60').fetchall()


def get_model(server, requested):
    if requested:return requested
    url=urllib.parse.urlparse(server)
    conn=http.client.HTTPConnection(url.hostname,url.port or 80,timeout=20)
    try:
        conn.request('GET','/v1/models')
        resp=conn.getresponse()
        if resp.status!=200:raise Protocol('Model listing returned '+str(resp.status))
        data=json.loads(resp.read())['data']
        if len(data)!=1:raise Protocol('Specify --model; server has '+str(len(data))+' model entries')
        return data[0]['id']
    finally:conn.close()


def prompt(files, archive_history, proposal_no, feedback=None):
    section=[]
    for name,data in sorted(files.items()):
        if name.endswith('.py'):
            section.append('\n### FILE '+name+'\n'+data.decode('utf8')+'\n')
    if not section:raise ValueError('No Python in baseline')
    past='\n'.join(f'  {n:04d} | {path} | {rationale}' for n,path,rationale in archive_history)
    feedback_text=json.dumps(feedback,ensure_ascii=False) if feedback is not None else 'No tests have been scored yet. Do NOT pretend accuracy.'
    return ('''MISSION: Improve general-purpose engineering drawing recognition Python code.
These are experimental copies of the proven OCR 1060+1947, selector v2 and v5 outline
pipeline (only if present in the actual verified source copy). More drawings will follow,
some without truth; generalize, do not memorize any drawing or truth values.
This session is generating INDEPENDENT candidate changes against ONE fixed baseline.
Each proposal changes exactly ONE localized algorithmic thing in ONE .py file.
Candidates are compared later against ALL active raw images by an independent evaluator.
Do not touch production programs, truth sets, evaluator code, network or other files.

Return ONLY one valid JSON object with exactly these keys:
  {"file":"existing/relative_path.py", "old":"exact UTF-8 substring from file",
   "new":"replacement UTF-8 source", "reason":"precise algorithmic hypothesis"}
The old text must appear EXACTLY ONCE in the specified file. New code MUST be valid
Python after replacement. Prefer localized correction of faulty vision/interpretation
logic, not variable renaming, formatting, comments or no-ops. Never add branches
based on filenames, drawing IDs, known truth, or fixed coordinates/dimensions.
Do not reproduce code from previous proposals. Change ONE thing. Keep compatibility.
Do not include markdown code fences. Never add or delete source files.

Previous ACCEPTED distinct changes (avoid repeating these ideas):
'''+past+'\n\nFeedback available from COMPLETED tests only:\n'+feedback_text+
'\n\nProposal sequence ID (diversity cue, not drawing identifier): '+str(proposal_no)+
'\n\nVERIFIED EXPERIMENTAL SOURCE FILES:\n'+''.join(section))


def request_stream(url, model, messages, temperature, output, last_progress, stop_event):
    parsed=urllib.parse.urlparse(url)
    if parsed.scheme!='http' or parsed.hostname not in {'127.0.0.1','localhost','::1'}:
        raise ValueError('Only loopback HTTP Qwen endpoints permitted; no external requests')
    path=(parsed.path.rstrip('/') or '') + '/v1/chat/completions'
    body=json.dumps({'model':model,'messages':messages,'temperature':temperature,'stream':True}).encode('utf8')
    conn=http.client.HTTPConnection(parsed.hostname, parsed.port or 80, timeout=3600)
    response_holder=[None]
    bytes_received=0
    content=[]
    errs=[]
    def monitor():
        last_heartbeat=0
        last_hour=0
        while not stop_event.wait(2):
            nowm=time.monotonic()
            delta=nowm-last_progress[0]
            elapsed=nowm-last_progress[1]
            if elapsed-last_heartbeat>=600:
                last_heartbeat=elapsed
                print(f'HEARTBEAT elapsed={elapsed/60:.1f}m last-new-token={delta:.0f}s streamed-characters={bytes_received}',flush=True)
            if elapsed-last_hour>=3600:
                last_hour=elapsed
                print(f'HOURLY MODEL PROGRESS elapsed={elapsed/60:.1f}m streamed-characters={bytes_received}',flush=True)
            if manager.TERMINATE.exists():
                errs.append('Explicit TERMINATE: closing experiment-owned Qwen HTTP request')
                try:conn.close()
                except OSError:pass
                stop_event.set()
                break
            if delta>=3600:
                errs.append('No NEW model output for 60 minutes; canceling owned HTTP request, preserving model server')
                try:conn.close()
                except OSError:pass
                stop_event.set()
    heartbeat=threading.Thread(target=monitor,daemon=True)
    heartbeat.start()
    try:
        conn.request('POST',path,body,headers={'Content-Type':'application/json','Accept':'text/event-stream'})
        resp=conn.getresponse()
        response_holder[0]=resp
        if resp.status!=200:
            raise Protocol('Qwen request returned HTTP '+str(resp.status)+': '+resp.read(2000).decode('utf8','replace'))
        with output.open('x',encoding='utf8') as log:
            while not stop_event.is_set():
                line=resp.readline()
                if not line:break
                if not line.startswith(b'data:'):continue
                payload=line[5:].strip()
                if payload == b'[DONE]':break
                try:
                    item=json.loads(payload)
                except json.JSONDecodeError:continue
                for choice in item.get('choices',[]):
                    delta=choice.get('delta',{})
                    for key in ('content','reasoning_content'):
                        add=delta.get(key)
                        if isinstance(add,str) and add:
                            # Only NEW token content counts as model progress.
                            last_progress[0]=time.monotonic()
                            bytes_received+=len(add)
                            if key=='content':content.append(add)
                            log.write(json.dumps({'time':utc(),'channel':key,'text':add},ensure_ascii=False)+'\n')
                            log.flush()
                if 'error' in item:
                    raise Protocol('Server streaming error: '+str(item['error']))
    except (ConnectionError,TimeoutError,OSError) as exc:
        if errs:raise Stall(errs[-1]) from exc
        raise
    finally:
        stop_event.set()
        conn.close()
        heartbeat.join(timeout=3)
    if errs:raise Stall(errs[-1])
    return ''.join(content)


def parse_model_json(raw):
    data=raw.strip()
    if data.startswith('```'):
        lines=data.splitlines()
        if lines[-1].strip()=='```':data='\n'.join(lines[1:-1])
    obj=json.loads(data)
    if not isinstance(obj,dict) or not {'file','old','new','reason'}.issubset(obj):
        raise ValueError('Qwen did not return required JSON keys')
    for key in ('file','old','new','reason'):
        if not isinstance(obj[key],str):raise ValueError('Proposal field must be string: '+key)
    return obj


def apply_proposal(baseline, dest, obj):
    rel=Path(obj['file'])
    if rel.is_absolute() or '..' in rel.parts or len(rel.parts)==0 or rel.suffix!='.py':
        raise ValueError('Illegal proposed path')
    target=dest/rel
    if not target.is_file() or target.is_symlink():
        raise ValueError('Proposed file not in baseline: '+str(rel))
    before=target.read_text(encoding='utf8')
    old=obj['old'];new=obj['new']
    if not old or before.count(old)!=1:
        raise ValueError('Find substring must be nonempty and occur EXACTLY ONCE')
    if old==new:
        raise ValueError('Qwen returned identical code')
    candidate=before.replace(old,new,1)
    import ast
    ast.parse(candidate,filename=str(rel))
    target.write_text(candidate,encoding='utf8')


def create_proposal_id():
    root=LAB/'proposals';root.mkdir(exist_ok=True)
    nums=[int(p.name) for p in root.iterdir() if p.is_dir() and p.name.isdigit()]
    n=max(nums,default=0)+1
    dest=root/f'{n:06d}';dest.mkdir(exist_ok=False)
    return n,dest


def main():
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument('--server-url',required=True,help='Pre-existing local llama-server URL e.g. http://127.0.0.1:18987')
    a.add_argument('--model',help='Model alias; auto-detect if server exposes exactly one model')
    a.add_argument('--temperature',type=float,default=0.65)
    a.add_argument('--max-consecutive-rejections',type=int,default=10,help='Stop after this many consecutive rejected edits; 0 disables (not recommended)')
    a.add_argument('--allow-unscored',action='store_true',help='Explicitly allow generating source WITHOUT image tests (NOT recommended for a real experiment)')
    args=a.parse_args()
    if args.temperature<0 or args.temperature>2:raise SystemExit('Temperature must be 0..2')
    if args.max_consecutive_rejections<0:raise SystemExit('--max-consecutive-rejections must be >=0')
    c=manager.control()
    if not c.get('test_integration_verified') and not args.allow_unscored:
        raise SystemExit('STOP: actual vision+selector prediction command is not verified. Fingerprinting is ready, but cannot run an unscored optimization as a real experiment. --allow-unscored explicitly overrides generation-only, never testing.')
    if manager.TERMINATE.exists():raise SystemExit('STOP: TERMINATE requested. Clear only after explicit authorization.')
    parent_folder=PROJECT/manager.control().get('active_parent','batch_lab/baseline')
    if not parent_folder.exists():raise SystemExit('STOP: selected parent source missing')
    lock=(LAB/'generator.lock').open('a+')
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise SystemExit('STOP: another Qwen batch generator is already running')
    baseline=manager.safe_source(parent_folder)
    files=manager.inventory(baseline)
    server=args.server_url.rstrip('/')
    model=get_model(server,args.model)
    print('PERSISTENT QWEN SERVER:',server,'model:',model,flush=True)
    print('Service not reloaded; ONLY the experiment copies may be changed',flush=True)
    starting_count=query_count()
    run_no=(max([int(p.stem) for p in (LAB/'runs').glob('*.json') if p.stem.isdigit()],default=0)+1) if (LAB/'runs').exists() else 1
    run_dir=LAB/'runs';run_dir.mkdir(exist_ok=True)
    run_record=run_dir/f'{run_no:05d}.json'
    manager.json_write_new(run_record,{'session':run_no,'started_utc':utc(),'baseline_sha':manager.fingerprints(files)[1],
                                       'accepted_at_start':starting_count,'model':model,'endpoint':'local loopback',
                                       'status':'RUNNING'})
    last_progress=[time.monotonic(),time.monotonic()]
    feedback_file=LAB/'feedback_for_qwen.json'
    feedback=json.loads(feedback_file.read_text()) if feedback_file.exists() else None
    consecutive_rejections=0
    try:
        while True:
            if manager.TERMINATE.exists():
                print('TERMINATE requested; leaving persistent model server untouched',flush=True)
                break
            current=manager.control() # permits live changes via set-runs
            achieved=query_count()-starting_count
            target=current['target_unique_runs']
            if achieved>=target:
                print('SESSION TARGET MET:',achieved,'/',target,flush=True)
                break
            proposal_number, proposal_dir=create_proposal_id()
            (proposal_dir/'status.txt').write_text('REQUESTED '+utc()+'\n')
            sys.stdout.write(f'\nQWEN PROPOSAL {proposal_number:06d}: unique {achieved}/{target} | ') ;sys.stdout.flush()
            messages=[{'role':'system','content':'You are a meticulous local engineering Python programmer. Return strict JSON only.'},
                {'role':'user','content':prompt(files,history(),proposal_number,feedback)}]
            request_path=proposal_dir/'stream.jsonl'
            try:
                response=request_stream(server,model,messages,args.temperature,request_path,last_progress,threading.Event())
                (proposal_dir/'qwen_answer.txt').write_text(response,encoding='utf8')
                proposal=parse_model_json(response)
                manager.json_write_new(proposal_dir/'proposal.json',proposal)
                candidate=proposal_dir/'source'
                shutil.copytree(baseline,candidate)
                apply_proposal(baseline,candidate,proposal)
                from argparse import Namespace
                status=manager.cmd_register(Namespace(source=str(candidate),parent=str(baseline),reason=proposal['reason']))
                if status != 0:
                    consecutive_rejections+=1
                    (proposal_dir/'status.txt').write_text('DUPLICATE_OR_INVALID '+utc()+'\n')
                else:
                    consecutive_rejections=0
                    last_progress[0]=time.monotonic()  # verified completion advance
                    (proposal_dir/'status.txt').write_text('ACCEPTED '+utc()+'\n')
            except (ValueError,KeyError,json.JSONDecodeError,SyntaxError) as exc:
                consecutive_rejections+=1
                (proposal_dir/'status.txt').write_text('INVALID '+utc()+': '+str(exc)+'\n')
                (proposal_dir/'error.txt').write_text(repr(exc)+'\n')
                print('INVALID QWEN PROPOSAL:',exc,flush=True)
            if args.max_consecutive_rejections and consecutive_rejections>=args.max_consecutive_rejections:
                print(f'STOP: {consecutive_rejections} consecutive rejected proposals; Qwen is not making distinct useful code changes. See proposal logs.',flush=True)
                break
    finally:
        current=json.loads(run_record.read_text())
        current.update({'ended_utc':utc(),'accepted_in_session':query_count()-starting_count,'status':'CANDIDATES SAVED / TESTS NOT YET RUN'})
        manager.json_atomic(run_record,current)
        fcntl.flock(lock,fcntl.LOCK_UN)
        lock.close()
    print('GENERATION ONLY: candidates NOT yet tested against images. Do not promote.',flush=True)

if __name__=='__main__':
    try:main()
    except KeyboardInterrupt:raise SystemExit('Stopped; Qwen service left untouched')
