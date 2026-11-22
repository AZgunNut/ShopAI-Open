#!/usr/bin/env python3

import select
import sys
from job_state import find_unfinished_jobs, update_job


def choose_recovery_action(job, timeout_seconds=180):
    print()
    print("=" * 70)
    print("UNFINISHED SHOPAI JOB FOUND")
    print("=" * 70)
    print(f"Job ID:  {job.get('job_id', 'unknown')}")
    print(f"AI:      {job.get('selected_ai', 'unknown')}")
    print(f"Stage:   {job.get('stage', 'unknown')}")
    print(f"Status:  {job.get('status', 'unknown')}")
    print(f"Request: {job.get('request', '')}")
    print()
    print("r = retry now")
    print("s = skip for this session")
    print("a = abandon this job")
    print()
    print(
        f"Auto-retry in {timeout_seconds} seconds "
        "if no choice is entered."
    )
    print()
    print("Recovery choice [r/s/a]: ", end="", flush=True)

    ready, _, _ = select.select(
        [sys.stdin],
        [],
        [],
        timeout_seconds,
    )

    if not ready:
        print()
        print("Recovery timer expired. Retrying automatically.")
        return "retry", "timeout"

    choice = sys.stdin.readline().strip().lower()

    if choice in ("a", "abandon"):
        return "abandon", "user"

    if choice in ("s", "skip"):
        return "skip", "user"

    return "retry", "user"


def prepare_recovery_job(timeout_seconds=180):
    unfinished = find_unfinished_jobs()

    if not unfinished:
        return None

    job = unfinished[0]
    action, trigger = choose_recovery_action(job, timeout_seconds)

    if action == "skip":
        return None

    if action == "abandon":
        update_job(job, "abandoned", "abandoned")
        print("Job marked abandoned.")
        return None

    attempt_count = int(job.get("attempt_count", 0)) + 1
    update_job(
        job,
        "retrying",
        "retrying",
        attempt_count=attempt_count,
        recovery_trigger=trigger,
    )
    return job
