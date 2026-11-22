"""ShopAI-owned inference-process lifecycle. Standard library; local PC only.

Conservative ownership: only processes launched and recorded by this module may be
terminated. File lock prevents two ShopAI menu sessions on the same PC.
No model, external service, GPU or token configuration is altered.
"""
import atexit
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time

ROOT = Path.home() / 'ShopAI'
LOGS = ROOT / 'logs'
RECORD = LOGS / 'shopai-owned-inference-v1.json'
LOCK = LOGS / 'shopai-session-v1.lock'
_lock_fd = None
_session_started = False
_session_pid = None  # PID of interactive ShopAI session; never a question worker
_current = None
_child = None


def _boot_id():
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def _proc(pid):
    """Read immutable Linux process identity without relying on its PID alone."""
    try:
        path = Path('/proc') / str(int(pid))
        stat = (path / 'stat').read_text()
        rest = stat.rsplit(')', 1)[1].split()
        # Fields: state=3 (index 0), starttime=22 (index 19).
        start = rest[19]
        state = rest[0]
        argv = (path / 'cmdline').read_bytes()
        exe = os.readlink(str(path / 'exe'))
        uid = path.stat().st_uid
        return {'start': start, 'state': state,
                'argv_hash': hashlib.sha256(argv).hexdigest(),
                'exe': exe, 'uid': uid}
    except (FileNotFoundError, ProcessLookupError, PermissionError, OSError, ValueError, IndexError):
        return None


def _identity(pid):
    state = _proc(pid)
    if not state:
        raise RuntimeError('Could not read spawned inference process identity')
    return {'pid': int(pid), 'boot': _boot_id(), **state}


def _matches(record):
    p = _proc(record['pid'])
    if p is None or p['state'] == 'Z':
        return False
    return (record.get('boot') == _boot_id()
            and p['start'] == record.get('start')
            and p['argv_hash'] == record.get('argv_hash')
            and p['exe'] == record.get('exe')
            and p['uid'] == os.getuid())


def _read_record():
    if not RECORD.exists():
        return None
    obj = json.loads(RECORD.read_text())
    if not isinstance(obj, dict) or 'pid' not in obj:
        raise RuntimeError(f'Invalid owned-model record; inspect {RECORD}')
    return obj


def _save_record(record):
    tmp = RECORD.with_suffix('.tmp')
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(record, f, indent=2, sort_keys=True)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, RECORD)
    finally:
        if tmp.exists():
            tmp.unlink()


def _forget():
    global _current, _child
    _current = None
    _child = None
    RECORD.unlink(missing_ok=True)


def _alive_processes():
    """Known local inference executables; never kill unknown or untracked ones."""
    found = []
    proc = Path('/proc')
    for item in proc.iterdir():
        if not item.name.isdigit():
            continue
        try:
            stat = item.stat()
            if stat.st_uid != os.getuid():
                continue
            comm = (item / 'comm').read_text().strip()
            if comm not in {'llama-server', 'mistralrs'}:
                continue
            info = _proc(int(item.name))
            if info and info['state'] != 'Z':
                found.append((int(item.name), comm))
        except (PermissionError, FileNotFoundError, ProcessLookupError, OSError):
            pass
    return found


def _wait_absent(record, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not _matches(record):
            return True
        if _child is not None and getattr(_child, 'pid', None) == record['pid']:
            try:
                _child.wait(timeout=0.1)
            except subprocess.TimeoutExpired:
                pass
        time.sleep(0.1)
    return not _matches(record)


def stop_owned():
    """Stop only the model whose exact process identity ShopAI recorded."""
    global _current
    # SHOPAI_SESSION_OWNER_GUARD_V1: transient qwen_agent.py workers import
    # the mistral adapter, whose atexit handler calls stop_owned(). Only
    # the interactive ShopAI process holding the session may clean up here.
    # Explicit emergency shutdown via Loaded AI Manager remains independent.
    if not _session_started or _session_pid != os.getpid() or _lock_fd is None:
        return
    record = _current or _read_record()
    if not record:
        return
    pid = record['pid']
    if not _matches(record):
        # A vanished PID or zombie is safe to forget; PID reuse is NOT.
        info = _proc(pid)
        if info and info['state'] != 'Z' and info['uid'] == os.getuid():
            raise RuntimeError(f'PID {pid} no longer matches ownership record; NOT terminating it')
        _forget()
        return
    print(f'ShopAI: stopping verified owned model PID {pid} ...', flush=True)
    try:
        if os.getpgid(pid) == pid:  # only a start_new_session=True process group
            os.killpg(pid, signal.SIGTERM)
        else:
            os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        _forget()
        return
    if not _wait_absent(record, 8):
        # A genuine runaway may need SIGKILL. Revalidate exact ownership first.
        if not _matches(record):
            _forget()
            return
        print(f'ShopAI: owned PID {pid} ignored TERM; forcing shutdown.', flush=True)
        if os.getpgid(pid) == pid:
            os.killpg(pid, signal.SIGKILL)
        else:
            os.kill(pid, signal.SIGKILL)
        if not _wait_absent(record, 5):
            raise RuntimeError(f'Owned inference PID {pid} did not terminate; manual review required')
    _forget()
    print('ShopAI: owned model stopped; RAM returned to OS.', flush=True)


def _atexit_cleanup():
    try:
        stop_owned()
    except Exception as ex:
        print(f'ShopAI shutdown warning: {ex}', flush=True)
    global _lock_fd
    if _lock_fd is not None:
        try:
            fcntl.flock(_lock_fd, fcntl.LOCK_UN)
            _lock_fd.close()
        except OSError:
            pass
        _lock_fd = None


def activate():
    """Own this PC's ShopAI interactive session and clean verified stale model."""
    global _lock_fd, _session_started, _session_pid
    if _session_started:
        return
    LOGS.mkdir(parents=True, exist_ok=True)
    fd = open(LOCK, 'a+', encoding='utf-8')
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fd.seek(0)
        text = fd.read().strip()
        fd.close()
        raise RuntimeError('Another ShopAI launcher already owns this PC session. ' + text)
    _lock_fd = fd
    fd.seek(0)
    fd.truncate(0)
    fd.write(f'Launcher PID {os.getpid()}\n')
    fd.flush()
    # Always register before recovery work so failing startup cannot leak lock.
    atexit.register(_atexit_cleanup)
    _session_started = True
    _session_pid = os.getpid()
    record = _read_record()
    if record:
        print('ShopAI: checking previous model ownership record...', flush=True)
        stop_owned()  # exact prior PID/boot/start/cmd hash required


def owns_port(port):
    record = _current or _read_record()
    if not record or not _matches(record):
        return False
    try:
        argv = (Path('/proc') / str(record['pid']) / 'cmdline').read_bytes().split(b'\x00')
        return any(argv[i] in (b'--port', b'-p') and
                   i + 1 < len(argv) and argv[i+1] == str(port).encode()
                   for i in range(len(argv)))
    except OSError:
        return False


def guard_ready(port, model):
    """Do not attach to a server the current ShopAI launcher does not own."""
    if owns_port(port):
        return True
    print(f'ShopAI: {model} port {port} already responds, but this session did not start it.')
    print('Refusing to attach to an unowned model. Inspect/stop it explicitly.')
    return False


def launch_owned(args, **kwargs):
    """Launch one inference model; persisted ownership enables safe later cleanup."""
    global _current, _child
    if not _session_started:
        raise RuntimeError('ShopAI lifecycle controller not activated')
    if not isinstance(args, (list, tuple)) or not args:
        raise ValueError('Expected executable command list')
    basename = Path(str(args[0])).name
    if basename not in {'llama-server', 'mistralrs'}:
        raise RuntimeError(f'Only inference binaries may use launch_owned: {basename}')
    stop_owned()
    active = _alive_processes()
    if active:
        raise RuntimeError('Other inference model(s) already running on THIS PC: ' +
                           ', '.join(f'{name} PID {pid}' for pid,name in active) +
                           '. No process was terminated.')
    if not kwargs.get('start_new_session', False):
        raise RuntimeError('Inference process must run in its own session')
    child = subprocess.Popen(args, **kwargs)
    try:
        # Wait until execve replaced the forked Python child. Recording identity
        # too early could fingerprint Python rather than the inference executable.
        expected_exe = os.path.realpath(str(args[0]))
        for _ in range(100):
            info = _proc(child.pid)
            if (info and os.path.realpath(info['exe']) == expected_exe
                    and info['state'] != 'Z'):
                break
            if child.poll() is not None:
                raise RuntimeError(f'{basename} exited before it could be owned')
            time.sleep(0.05)
        else:
            raise RuntimeError(f'{basename} never reached the expected executable')
        record = _identity(child.pid)
        record['name'] = basename
        record['started_by'] = os.getpid()
        record['created_utc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        _save_record(record)
    except BaseException:
        # An unrecorded process must not escape from our launcher.
        if child.poll() is None:
            child.terminate()
            try: child.wait(timeout=3)
            except subprocess.TimeoutExpired: child.kill(); child.wait(timeout=3)
        raise
    _child = child
    _current = record
    return child
