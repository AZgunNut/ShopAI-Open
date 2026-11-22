#!/usr/bin/env python3

import json
import time
from datetime import datetime, timezone
from pathlib import Path


GIB = 1024 ** 3

RESUME_GIB = 12.0
CHECKPOINT_GIB = 10.0
HARD_FLOOR_GIB = 8.0

ROOT = Path.home() / "ShopAI"
EVENT_LOG = ROOT / "logs" / "memory-guard.jsonl"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def read_meminfo(path=Path("/proc/meminfo")):
    values = {}

    for line in path.read_text(encoding="utf-8").splitlines():
        name, raw = line.split(":", 1)
        fields = raw.strip().split()

        if not fields:
            continue

        value = int(fields[0])

        if len(fields) > 1 and fields[1].lower() == "kb":
            value *= 1024

        values[name] = value

    required = {
        "MemTotal",
        "MemAvailable",
        "SwapTotal",
        "SwapFree",
    }

    missing = required.difference(values)

    if missing:
        raise RuntimeError(
            "Missing /proc/meminfo fields: "
            + ", ".join(sorted(missing))
        )

    return values


def available_gib(meminfo=None):
    values = meminfo if meminfo is not None else read_meminfo()
    return values["MemAvailable"] / GIB


def memory_decision(available, already_paused=False):
    if available <= HARD_FLOOR_GIB:
        return "emergency_stop"

    if available <= CHECKPOINT_GIB:
        return "checkpoint_and_pause"

    if already_paused and available < RESUME_GIB:
        return "remain_paused"

    if available < RESUME_GIB:
        return "hold_new_work"

    return "run"


def snapshot(already_paused=False):
    values = read_meminfo()
    available = values["MemAvailable"] / GIB
    swap_used = (
        values["SwapTotal"] - values["SwapFree"]
    ) / GIB

    return {
        "timestamp": utc_now(),
        "available_gib": round(available, 3),
        "swap_used_gib": round(swap_used, 3),
        "decision": memory_decision(
            available,
            already_paused=already_paused,
        ),
        "resume_gib": RESUME_GIB,
        "checkpoint_gib": CHECKPOINT_GIB,
        "hard_floor_gib": HARD_FLOOR_GIB,
    }


def record_event(event, **details):
    record = {
        "timestamp": utc_now(),
        "event": event,
    }
    record.update(details)

    EVENT_LOG.parent.mkdir(parents=True, exist_ok=True)

    with EVENT_LOG.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(record, sort_keys=True) + "\n"
        )


def can_start_new_work():
    state = snapshot()
    allowed = state["decision"] == "run"

    if not allowed:
        record_event(
            "new_work_held",
            **state,
        )

    return allowed, state


def wait_for_safe_start(poll_seconds=5):
    announced = False
    last_report = 0.0

    while True:
        state = snapshot(
            already_paused=announced,
        )

        if state["available_gib"] >= RESUME_GIB:
            if announced:
                print()
                print(
                    "Memory recovered to "
                    f"{state['available_gib']:.2f} GiB available."
                )
                print("ShopAI task resuming.")
                print()

                record_event(
                    "task_resumed",
                    **state,
                )

            return state

        now = time.monotonic()

        if not announced:
            record_event(
                "task_held",
                **state,
            )

        if not announced or now - last_report >= 60:
            print()
            print(
                "MEMORY GUARD: task held with "
                f"{state['available_gib']:.2f} GiB available."
            )
            print(
                "Waiting for at least "
                f"{RESUME_GIB:.0f} GiB before starting."
            )
            print()

            last_report = now

        announced = True
        time.sleep(poll_seconds)
