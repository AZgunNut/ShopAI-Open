#!/usr/bin/env python3
"""Shared ShopAI capability launcher with persistent job monitoring."""

import datetime
import json
import os
import pathlib
import signal
import subprocess
import sys
import time
import uuid

P = pathlib.Path

HERE = P(__file__).resolve().parent
ROOT = P('/mnt/shopai-data-new/cad-research/ShopAI-Tools-and-Capabilities')
REG = ROOT / 'registry/tools.json'
JOBS = HERE / 'jobs'

def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

def info():
    return {
        x['id']: x
        for x in json.loads(REG.read_text())['tools']
    }

def check_id(value):
    if not value or any(
        ch not in '0123456789abcdef-' for ch in value
    ):
        raise ValueError('invalid job id')

    path = JOBS / value

    if not path.is_dir():
        raise ValueError('unknown job ' + value)

    return path

def atomic(path, obj):
    tmp = path.with_name(
        path.name + '.tmp-' + str(os.getpid())
    )
    tmp.write_text(json.dumps(obj, indent=2) + '\n')
    os.replace(tmp, path)

def readjob(path):
    return json.loads((path / 'state.json').read_text())

def emit(event, body):
    print(json.dumps({
        'event': event,
        **body
    }, ensure_ascii=False))

def measure(job):
    # Exclude supervisor-generated heartbeats.
    amount = 0
    newest = 0
    count = 0

    output = job / 'output'

    if output.exists():
        for path in output.rglob('*'):
            if path.is_file() and not path.is_symlink():
                try:
                    st = path.stat()
                    amount += st.st_size
                    newest = max(newest, st.st_mtime_ns)
                    count += 1
                except OSError:
                    pass

    logfile = job / 'tool_stdout.log'

    if logfile.exists():
        st = logfile.stat()
        amount += st.st_size
        newest = max(newest, st.st_mtime_ns)
        count += 1

    return amount, newest, count

def worker(job):
    state = readjob(job)

    tool = state['tool']
    image = state['image']

    command = [
        sys.executable,
        '-B',
        str(ROOT / 'shopai_tool_runner.py'),
        'run',
        tool,
        image,
        str(job / 'output')
    ]

    logfile = job / 'tool_stdout.log'

    with logfile.open('ab', buffering=0) as stream:
        child = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            cwd=str(HERE)
        )

        state.update(
            status='running',
            started_utc=now(),
            child_pid=child.pid,
            command=command
        )

        atomic(job / 'state.json', state)

        start = time.monotonic()
        last_progress = start
        previous = measure(job)

        next_heartbeat = start + 600
        next_hour = start + 3600
        last_alert = start

        stop_reason = ''

        while child.poll() is None:
            current = time.monotonic()
            metric = measure(job)

            if metric != previous:
                previous = metric
                last_progress = current

            if (job / 'TERMINATE').exists():
                stop_reason = 'TERMINATE'

                # Terminate only the process group
                # created and owned by this worker.

                os.killpg(child.pid, signal.SIGTERM)

                try:
                    child.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)

                break

            if current >= next_heartbeat:
                line = (
                    f'{now()} HEARTBEAT '
                    f'tool={tool} '
                    f'elapsed_s={int(current-start)} '
                    f'bytes={metric[0]} '
                    f'files={metric[2]} '
                    f'idle_s={int(current-last_progress)}\n'
                )

                with (job / 'heartbeat.log').open('a') as f:
                    f.write(line)

                next_heartbeat += 600

            if current >= next_hour:
                with (job / 'heartbeat.log').open('a') as f:
                    f.write(
                        f'{now()} HOURLY_PROGRESS '
                        f'elapsed_s={int(current-start)} '
                        f'bytes={metric[0]} '
                        f'files={metric[2]} '
                        f'idle_s={int(current-last_progress)}\n'
                    )

                next_hour += 3600

            # A silent program may still be computing.
            # Warn after an hour; do not impose an
            # arbitrary overall runtime cutoff.

            if (
                current - last_progress >= 3600
                and current - last_alert >= 3600
            ):
                with (job / 'heartbeat.log').open('a') as f:
                    f.write(
                        f'{now()} STALL_WARNING '
                        f'no observable output for '
                        f'{int(current-last_progress)} seconds. '
                        f'Check task-specific progress.\n'
                    )

                last_alert = current

            state.update(
                status='running',
                updated_utc=now(),
                observed_output_bytes=metric[0],
                observed_files=metric[2],
                seconds_without_output=int(
                    current-last_progress
                ),
                elapsed_seconds=int(current-start),
                stall_warning=(
                    current-last_progress >= 3600
                )
            )

            atomic(job / 'state.json', state)

            time.sleep(2)

        rc = child.wait()

        state.update(
            status=(
                'terminated' if stop_reason
                else 'completed' if rc == 0
                else 'failed'
            ),
            return_code=rc,
            finished_utc=now(),
            updated_utc=now(),
            elapsed_seconds=int(
                time.monotonic()-start
            ),
            stop_reason=stop_reason
        )

        atomic(job / 'state.json', state)

        emit('job_finished', {
            'job': job.name,
            'status': state['status'],
            'return_code': rc
        })

def main(args):
    if not args or args[0] == 'help':
        print(
            'Usage: suite_jobs.py list | describe TOOL | '
            'start TOOL /absolute/input.png | '
            'status JOB | logs JOB [lines] | stop JOB'
        )
        return 0

    command = args[0]

    if command == 'list':
        for name, item in sorted(info().items()):
            print(
                name,
                '|',
                item.get('execution_status'),
                '|',
                item.get('best_for', '')
            )
        return 0

    if command == 'describe' and len(args) == 2:
        if args[1] not in info():
            raise ValueError('unknown tool')

        print(json.dumps(info()[args[1]], indent=2))
        return 0

    if command == 'start' and len(args) == 3:
        tools = info()
        tool = args[1]

        if tool not in tools:
            raise ValueError('unknown tool ' + tool)

        launcher = tools[tool].get('launcher')

        if not launcher or not P(launcher).is_file():
            raise ValueError(
                'tool has no launcher: ' + tool
            )

        image = P(args[2]).expanduser().resolve()

        if not image.is_file():
            raise ValueError(
                'input not found: ' + str(image)
            )

        job_id = uuid.uuid4().hex
        job = JOBS / job_id
        job.mkdir(mode=0o700)

        atomic(job / 'state.json', {
            'job_id': job_id,
            'tool': tool,
            'image': str(image),
            'status': 'queued',
            'created_utc': now(),
            'archived_launcher_not_yet_reverified': True
        })

        with (job / 'worker.log').open(
            'ab', buffering=0
        ) as stream:

            process = subprocess.Popen(
                [
                    sys.executable,
                    '-B',
                    str(P(__file__).resolve()),
                    'worker',
                    job_id
                ],
                stdin=subprocess.DEVNULL,
                stdout=stream,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                cwd=str(HERE)
            )

        emit('job_accepted', {
            'job_id': job_id,
            'worker_pid': process.pid,
            'status_command': (
                f'python3 {__file__} status {job_id}'
            ),
            'stop_command': (
                f'python3 {__file__} stop {job_id}'
            )
        })

        return 0

    if command == 'worker' and len(args) == 2:
        worker(check_id(args[1]))
        return 0

    if command == 'status' and len(args) == 2:
        job = check_id(args[1])
        state = readjob(job)

        state['current_output'] = measure(job)[0]

        emit('status', state)
        return 0

    if command == 'logs' and len(args) in (2, 3):
        job = check_id(args[1])

        lines = min(
            max(
                int(args[2]) if len(args) > 2 else 35,
                1
            ),
            150
        )

        for name in (
            'heartbeat.log',
            'tool_stdout.log',
            'output/console.log'
        ):
            path = job / name

            if path.is_file():
                print('=== ' + name + ' ===')

                print('\n'.join(
                    path.read_text(
                        errors='replace'
                    ).splitlines()[-lines:]
                ))

        return 0

    if command == 'stop' and len(args) == 2:
        job = check_id(args[1])

        (job / 'TERMINATE').touch()

        emit('stop_requested', {
            'job_id': job.name,
            'note': (
                'Worker will terminate only its '
                'owned process group'
            )
        })

        return 0

    raise ValueError(
        'Unrecognized command; run help'
    )

if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv[1:]))

    except Exception as exc:
        print(
            'ERROR:',
            str(exc),
            file=sys.stderr
        )
        sys.exit(1)
