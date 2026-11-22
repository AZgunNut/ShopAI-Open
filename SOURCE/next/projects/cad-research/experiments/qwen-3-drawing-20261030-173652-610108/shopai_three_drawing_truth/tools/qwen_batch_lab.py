#!/usr/bin/env python3
"""ShopAI additive batch source-variation ledger (stdlib only).

PRECONDITION: install as tools/qwen_batch_lab.py under the existing three-drawing project.
This tool NEVER executes generated code or modifies production. Candidate source
must be an experiment copy, not a live service tree.

Runs are numbers of UNIQUE candidates, not Qwen prompts. Distinct proposed
candidate programs receive unique immutable numbered attempt directories;
rejected proposed edits are preserved in the rejection ledger.
"""
from __future__ import annotations
import argparse
import ast
import contextlib
import datetime as dt
import difflib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import secrets
import string
import hmac
import getpass
import sys
import tempfile
import time

PROJECT = Path(__file__).resolve().parent.parent
LAB = PROJECT / 'batch_lab'
CONTROL = LAB / 'control.json'
DB = LAB / 'fingerprints.sqlite3'
LOCK = LAB / 'manager.lock'
KILL_CODE = LAB / '.stop_code'
TERMINATE = LAB / 'TERMINATE'
IGNORE_DIRS = {'.git', '__pycache__', '.venv', 'venv', 'node_modules', '.pytest_cache'}
IGNORED_SUFFIXES = {'.pyc', '.pyo', '.gguf', '.safetensors', '.bin', '.pt', '.pth', '.onnx', '.sqlite3', '.db'}


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')


def digest(b):
    return hashlib.sha256(b).hexdigest()


def json_write_new(path, item):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as f:
        json.dump(item, f, indent=2, ensure_ascii=False)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())


def json_atomic(path, item):
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name + '.')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(item, f, indent=2, ensure_ascii=False)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def safe_source(directory, require_experiment=True):
    original = Path(directory).expanduser().absolute()
    if original.is_symlink():
        raise ValueError('Refusing symlink source root')
    src = original.resolve(strict=True)
    if not src.is_dir():
        raise ValueError('Source is not a directory: ' + str(src))
    if require_experiment and PROJECT.resolve() not in src.parents:
        raise ValueError('Source must be INSIDE this installed experiment. Make copies here first; never read live originals as a mutation target. Got ' + str(src))
    if src == PROJECT.resolve() or src == (PROJECT/'attempts').resolve() or src == LAB.resolve():
        raise ValueError('Source cannot be entire experiment or an output root')
    for p in src.rglob('*'):
        if p.is_symlink():
            raise ValueError('Symlink found in candidate source: '+str(p))
    return src


def inventory(src):
    files={}
    for p in sorted(src.rglob('*')):
        if not p.is_file():
            continue
        rel=p.relative_to(src)
        if set(rel.parts) & IGNORE_DIRS or p.suffix in IGNORED_SUFFIXES:
            continue
        # Allow all small reproducibility assets; no silent truncation.
        files[rel.as_posix()]=p.read_bytes()
    if not files or not any(k.endswith('.py') for k in files):
        raise ValueError('Need a source copy containing Python scripts')
    return files


def structural(path, content):
    if path.endswith('.py'):
        # AST removes formatting, whitespace and comments; code-sensitive.
        tree=ast.parse(content.decode('utf-8'),filename=path)
        return ast.dump(tree,annotate_fields=True,include_attributes=False).encode()
    return content


def fingerprints(files):
    raw = []
    canonical=[]
    for path, data in sorted(files.items()):
        path_bytes=path.encode('utf8')
        raw.append(path_bytes+b'\0'+digest(data).encode())
        canonical.append(path_bytes+b'\0'+digest(structural(path,data)).encode())
    return digest(b'\n'.join(raw)),digest(b'\n'.join(canonical))


def delta(base, cand):
    if set(base) != set(cand):
        missing=sorted(set(base)-set(cand)); extra=sorted(set(cand)-set(base))
        raise ValueError('No adding/deleting files in a single-change trial; missing='+str(missing)+' extra='+str(extra))
    changed=[name for name in sorted(base) if base[name] != cand[name]]
    semantic=[name for name in changed if structural(name,base[name]) != structural(name,cand[name])]
    if len(semantic) != 1:
        raise ValueError('Must have exactly ONE structural file change. Changed='+str(changed)+' structural='+str(semantic))
    if len(changed) != 1:
        raise ValueError('Must change only ONE source file; changed='+str(changed))
    name=semantic[0]
    if not name.endswith('.py'):
        raise ValueError('One-change proposals must edit a Python source file')
    # Edit key is independent of the unchanged rest of the source tree.
    before=digest(structural(name,base[name]))
    after=digest(structural(name,cand[name]))
    edit_sig=digest((name+'\0'+before+'\0'+after).encode())
    return name,edit_sig


def open_db():
    cx=sqlite3.connect(DB)
    cx.execute('PRAGMA busy_timeout=30000')
    cx.executescript('''
       CREATE TABLE IF NOT EXISTS accepted (
           attempt INTEGER PRIMARY KEY, created_utc TEXT NOT NULL,
           parent TEXT NOT NULL, file TEXT NOT NULL,
           raw_sha TEXT NOT NULL UNIQUE, structural_sha TEXT NOT NULL UNIQUE,
           edit_sha TEXT NOT NULL UNIQUE, rationale TEXT NOT NULL);
       CREATE TABLE IF NOT EXISTS rejected (
           proposal INTEGER PRIMARY KEY, created_utc TEXT NOT NULL,
           reason TEXT NOT NULL, raw_sha TEXT, structural_sha TEXT,
           edit_sha TEXT, file TEXT, rationale TEXT NOT NULL);
       CREATE TABLE IF NOT EXISTS seeded (
           id INTEGER PRIMARY KEY CHECK(id=1), raw_sha TEXT NOT NULL,
           structural_sha TEXT NOT NULL, created_utc TEXT NOT NULL);
    ''')
    return cx


@contextlib.contextmanager
def locked():
    LAB.mkdir(parents=True,exist_ok=True)
    with LOCK.open('a+') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def control():
    if not CONTROL.exists():
        raise ValueError('Not initialized. Run init with a verified EXPERIMENTAL source copy.')
    return json.loads(CONTROL.read_text(encoding='utf-8'))


def next_attempt():
    dest=PROJECT/'attempts'
    dest.mkdir(exist_ok=True)
    nums=[int(p.name) for p in dest.iterdir() if p.is_dir() and p.name.isdigit()]
    return max(nums,default=0)+1


def next_rejection():
    base=LAB/'rejections'
    base.mkdir(exist_ok=True)
    nums=[int(p.stem) for p in base.glob('*.json') if p.stem.isdigit()]
    return max(nums,default=0)+1


def rejection(cx, reason, rationale, source=None, extra=None):
    n=next_rejection()
    item={'proposal':n,'time_utc':now(),'reason':reason,'rationale':rationale}
    if extra:
        item.update(extra)
    # only proposal metadata; source remains at its original experimental location.
    json_write_new(LAB/'rejections'/f'{n:06d}.json',item)
    cx.execute('INSERT INTO rejected(proposal,created_utc,reason,raw_sha,structural_sha,edit_sha,file,rationale) VALUES(?,?,?,?,?,?,?,?)',
       (n,item['time_utc'],reason,item.get('raw_sha'),item.get('structural_sha'),item.get('edit_sha'),item.get('file'),rationale))
    cx.commit()
    print(f'REJECTED proposal {n:06d}: {reason}',flush=True)
    return 3


def cmd_init(args):
    if not isinstance(args.runs,int) or args.runs<1:
        raise ValueError('--runs must be a positive integer')
    with locked():
        if CONTROL.exists() or (LAB/'baseline').exists():
            raise ValueError('Already initialized; no overwrite. Use set-runs/status.')
        src=safe_source(args.baseline)
        if LAB in src.parents:
            raise ValueError('Put your verified experimental source in a folder OUTSIDE batch_lab/')
        files=inventory(src)
        raw,semantic=fingerprints(files)
        # Copy into temp dir, then atomically publish.
        temp=LAB/('.baseline.tmp.'+str(os.getpid()))
        shutil.copytree(src,temp,ignore=shutil.ignore_patterns('__pycache__','.git','*.pyc','.venv','venv','node_modules','*.gguf','*.safetensors'))
        copied=inventory(temp)
        if fingerprints(copied)!=(raw,semantic):
            raise ValueError('Baseline copy does not match source fingerprints')
        os.rename(temp,LAB/'baseline')
        with open_db() as cx:
            cx.execute('INSERT INTO seeded(id,raw_sha,structural_sha,created_utc) VALUES(1,?,?,?)',(raw,semantic,now()))
        code=''.join(secrets.choice(string.ascii_letters+string.digits) for _ in range(24))
        with os.fdopen(os.open(KILL_CODE,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w',encoding='ascii') as f:
            f.write(code+'\n')
        json_write_new(CONTROL,{
            'schema':1, 'target_unique_runs':args.runs, 'active_drawings':['D1'],
            'created_utc':now(),'updated_utc':now(),
            'initial_baseline_raw_sha256':raw,
            'initial_baseline_structural_sha256':semantic,
            'generation_enabled':False,
            'test_integration_verified':False,
            'active_parent':'batch_lab/baseline'
        })
        print('INITIALIZED (no Qwen run):',LAB)
        print('COPIED BASELINE:', LAB/'baseline')
        print('TARGET UNIQUE CANDIDATES:',args.runs)
        print('BASELINE STRUCTURAL FINGERPRINT:',semantic)
        print('EMERGENCY STOP CODE (save privately):',code)
        print('To request graceful stop: python3 tools/qwen_batch_lab.py terminate')
        print('Tests DISABLED until the actual OCR/selector/geometry entrypoint is confirmed.')


def cmd_set_runs(args):
    if args.runs<1:
        raise ValueError('Runs must be >=1')
    with locked():
        c=control()
        old=c['target_unique_runs'];c['target_unique_runs']=args.runs;c['updated_utc']=now()
        json_atomic(CONTROL,c)
    print('Unique candidate target:',old,'->',args.runs,'(applies when a running controller rereads the control file)')


def cmd_stage(args):
    stages={'1':['D1'],'2':['D1','D2'],'3':['D1','D2','D3']}
    # Stage changes require explicit action; do not auto-advance without verified tests.
    with locked():
        c=control();c['active_drawings']=stages[args.stage];c['updated_utc']=now()
        json_atomic(CONTROL,c)
    print('Active drawings:',','.join(stages[args.stage]),'— manual stage change, not verification')



def cmd_select_parent(args):
    """Explicitly choose a scored candidate as next batch's starting source.
    Never rewrites the original baseline or any attempt.
    """
    with locked():
        c=control()
        attempt=PROJECT/'attempts'/f'{args.attempt:04d}'
        src=safe_source(attempt/'source')
        if not (attempt/'metadata.json').exists():
            raise ValueError('Attempt does not have a finalized source manifest')
        stage=c['active_drawings']
        reports=[]
        for d in stage:
            report=attempt/'evaluation'/f'{d}.report.json'
            if not report.exists():
                raise ValueError('Attempt has not been independently scored for '+d)
            rep=json.loads(report.read_text())
            if rep.get('drawing_id')!=d or rep.get('score_pct') is None:
                raise ValueError('Invalid/missing evaluation: '+d)
            prediction=attempt/'predictions'/f'{d}.json'
            if not prediction.is_file() or rep.get('prediction_sha256')!=digest(prediction.read_bytes()):
                raise ValueError('Prediction missing/changed since scoring: '+d)
            reports.append(rep)
        if not all(r.get('passed') is True for r in reports) and not args.approve_partial:
            raise ValueError('Candidate is not 100% on all active drawings; explicit --approve-partial needed')
        c['active_parent']=str(src.relative_to(PROJECT))
        c['updated_utc']=now()
        json_atomic(CONTROL,c)
        records=LAB/'parent_selections';records.mkdir(exist_ok=True)
        n=max([int(x.stem) for x in records.glob('*.json') if x.stem.isdigit()],default=0)+1
        json_write_new(records/f'{n:05d}.json',{'time_utc':now(),'selected_attempt':args.attempt,
           'active_parent':c['active_parent'],'drawings':stage,
           'scores':[r.get('score_pct') for r in reports],
           'explicit_approved_partial':args.approve_partial})
        print('NEXT BATCH PARENT:',src)
        print('All attempts and original baseline preserved. No code executed.')



def cmd_terminate(args):
    """24-character stop authorization; leaves Qwen server/services untouched."""
    supplied = args.code if args.code is not None else getpass.getpass('24-character experiment stop code: ')
    if not KILL_CODE.exists():
        raise ValueError('No initialized stop code')
    actual=KILL_CODE.read_text(encoding='ascii').strip()
    if len(supplied)!=24 or not hmac.compare_digest(supplied,actual):
        raise ValueError('Invalid emergency code; not requesting termination')
    with locked():
        if args.clear:
            if TERMINATE.exists():
                TERMINATE.unlink()
                print('Stop flag cleared; verify previous generator has stopped before restarting')
        elif not TERMINATE.exists():
            json_write_new(TERMINATE,{'sentinel':'TERMINATE','requested_utc':now(),
                    'scope':'experiment-owned generator / HTTP request only'})
            print('TERMINATE requested; generator checks flag and stops owned request; server untouched')
        else:
            print('TERMINATE already requested')


def cmd_status(args):
    c=control()
    with open_db() as cx:
        accepted=cx.execute('SELECT COUNT(*) FROM accepted').fetchone()[0]
        rejected=cx.execute('SELECT COUNT(*) FROM rejected').fetchone()[0]
        recent=cx.execute('SELECT attempt,file,substr(structural_sha,1,18) FROM accepted ORDER BY attempt DESC LIMIT 5').fetchall()
    print(json.dumps({'project':str(PROJECT),'target_unique_runs':c['target_unique_runs'],
         'active_drawings':c['active_drawings'],'accepted_unique':accepted,
         'duplicate_or_invalid_rejected':rejected,'latest_accepted':recent,
         'generation_enabled':c['generation_enabled'],
         'test_integration_verified':c['test_integration_verified'],
         'active_parent':c.get('active_parent','batch_lab/baseline'),
         'terminate_requested':TERMINATE.exists()},indent=2))


def cmd_register(args):
    with locked():
        c=control()
        src=safe_source(args.source)
        if src == (LAB/'baseline').resolve():
            raise ValueError('Cannot register the baseline as a candidate')
        baseline=safe_source(args.parent or LAB/'baseline')
        base=inventory(baseline)
        cand=inventory(src)
        c_raw,c_struct=fingerprints(cand)
        b_raw,b_struct=fingerprints(base)
        with open_db() as cx:
            prior=cx.execute('SELECT id FROM seeded WHERE raw_sha=? OR structural_sha=?',(c_raw,c_struct)).fetchone()
            if prior:
                return rejection(cx,'identical to original baseline',args.reason,extra={'raw_sha':c_raw,'structural_sha':c_struct})
            same=cx.execute('SELECT attempt FROM accepted WHERE raw_sha=? OR structural_sha=?',(c_raw,c_struct)).fetchone()
            if same:
                return rejection(cx,f'duplicate whole-code combination: attempt {same[0]:04d}',args.reason,extra={'raw_sha':c_raw,'structural_sha':c_struct})
            try:
                file,edit_sig=delta(base,cand)
            except (ValueError,SyntaxError,UnicodeError) as e:
                return rejection(cx,'invalid/non-unique modification: '+str(e),args.reason,extra={'raw_sha':c_raw,'structural_sha':c_struct})
            same_edit=cx.execute('SELECT attempt FROM accepted WHERE edit_sha=?',(edit_sig,)).fetchone()
            if same_edit:
                return rejection(cx,f'duplicate code edit: attempt {same_edit[0]:04d}',args.reason,extra={'raw_sha':c_raw,'structural_sha':c_struct,'edit_sha':edit_sig,'file':file})
            n=next_attempt()
            folder=PROJECT/'attempts'/f'{n:04d}'
            folder.mkdir(exist_ok=False)
            try:
                shutil.copytree(src,folder/'source',ignore=shutil.ignore_patterns('__pycache__','.git','*.pyc','.venv','venv','node_modules','*.gguf','*.safetensors'))
                if fingerprints(inventory(folder/'source')) != (c_raw,c_struct):
                    raise ValueError('Source changed during copy. Reject incomplete attempt for review.')
                for name in ['predictions','evaluation','logs','overlays','intermediates']:
                    (folder/name).mkdir()
                before=base[file].decode('utf-8')
                after=cand[file].decode('utf-8')
                diff=''.join(difflib.unified_diff(before.splitlines(keepends=True),after.splitlines(keepends=True),
                          fromfile='baseline/'+file,tofile='candidate/'+file))
                (folder/'code_diff.patch').write_text(diff,encoding='utf-8')
                (folder/'source_hashes.sha256').write_text(''.join(
                    digest(data)+'  source/'+name+'\n' for name,data in sorted(cand.items())),encoding='utf-8')
                json_write_new(folder/'metadata.json',{'attempt':n,'created_utc':now(),
                    'parent_source_raw_sha256':b_raw,'parent_source_structural_sha256':b_struct,
                    'changed_file':file,'changed_file_edit_fingerprint':edit_sig,
                    'source_raw_sha256':c_raw,'source_structural_sha256':c_struct,
                    'rationale':args.reason,'status':'registered; NOT TESTED',
                    'qwen_temperature':None,'active_drawings_at_registration':c['active_drawings']})
                cx.execute('INSERT INTO accepted(attempt,created_utc,parent,file,raw_sha,structural_sha,edit_sha,rationale) VALUES(?,?,?,?,?,?,?,?)',
                    (n,now(),str(baseline),file,c_raw,c_struct,edit_sig,args.reason))
                cx.commit()
            except Exception:
                (folder/'INCOMPLETE_REGISTRATION.txt').write_text('Registration failed; inspect before reuse. Do not overwrite.\n')
                raise
            print('ACCEPTED UNIQUE:',f'{n:04d}', 'FILE:',file)
            print('STRUCTURAL FINGERPRINT:',c_struct)
            print('SAVED:',folder)
        return 0


def main():
    p=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    sp=p.add_subparsers(dest='command',required=True)
    a=sp.add_parser('init',help='Snapshot verified experimental source; seed duplicate registry')
    a.add_argument('--baseline',required=True,help='Path to a copy of the working scripts INSIDE the installed experiment')
    a.add_argument('--runs',type=int,default=200)
    a.set_defaults(fn=cmd_init)
    a=sp.add_parser('set-runs',help='Change unique-candidate target without restarting Qwen')
    a.add_argument('runs',type=int);a.set_defaults(fn=cmd_set_runs)
    a=sp.add_parser('stage',help='Select active stage manually after verified passes')
    a.add_argument('stage',choices=['1','2','3']);a.set_defaults(fn=cmd_stage)
    a=sp.add_parser('status');a.set_defaults(fn=cmd_status)
    a=sp.add_parser('terminate',help='Stop only experiment-owned work using the saved 24-character code')
    a.add_argument('--code',help='Not recommended: appears in shell history; omit to prompt securely')
    a.add_argument('--clear',action='store_true',help='Clear old stop request before deliberate restart')
    a.set_defaults(fn=cmd_terminate)
    a=sp.add_parser('select-parent',help='Choose independently scored candidate as next batch parent without overwriting original')
    a.add_argument('--attempt',type=int,required=True)
    a.add_argument('--approve-partial',action='store_true',help='Explicitly allow choosing partially scoring candidate')
    a.set_defaults(fn=cmd_select_parent)
    a=sp.add_parser('register',help='Uniqueness-check candidate source, create immutable numbered attempt or reject')
    a.add_argument('--source',required=True,help='Proposed full source combination, experimental path')
    a.add_argument('--parent',help='Parent SOURCE directory; defaults to original experiment baseline')
    a.add_argument('--reason',default='single code modification')
    a.set_defaults(fn=cmd_register)
    args=p.parse_args()
    try:
        return args.fn(args) or 0
    except (ValueError,OSError,sqlite3.DatabaseError, SyntaxError, UnicodeError) as exc:
        print('STOP:',exc,file=sys.stderr)
        return 2

if __name__=='__main__':
    sys.exit(main())
