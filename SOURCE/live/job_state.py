#!/usr/bin/env python3

import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path.home() / "ShopAI"
JOBS_DIR = ROOT / "state" / "jobs"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def save_job(job):
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    destination = JOBS_DIR / f"{job['job_id']}.json"
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(job, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)


def create_job(job_id, request, ai_mode):
    now = utc_now()
    job = {
        "schema_version": 1,
        "job_id": job_id,
        "request": request,
        "selected_ai": ai_mode,
        "stage": "created",
        "status": "pending",
        "created_at": now,
        "updated_at": now,
    }
    save_job(job)
    return job


def update_job(job, stage, status, **details):
    job["stage"] = stage
    job["status"] = status
    job["updated_at"] = utc_now()
    job.update(details)
    save_job(job)


def find_unfinished_jobs():
    if not JOBS_DIR.exists():
        return []

    unfinished = []

    for path in sorted(JOBS_DIR.glob("*.json")):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        if job.get("status") in {"pending", "running", "retrying", "interrupted"}:
            unfinished.append(job)

    unfinished.sort(key=lambda job: job.get("created_at", ""))
    return unfinished
