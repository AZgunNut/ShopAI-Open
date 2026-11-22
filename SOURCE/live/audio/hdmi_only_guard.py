#!/usr/bin/env python3

import json
import subprocess
import time
from datetime import datetime
from pathlib import Path


DEVICE_NAME = "alsa_card.pci-0000_00_1f.3"
HDMI_NODE = "alsa_output.pci-0000_00_1f.3.hdmi-stereo"
OUTPUT_PREFIX = "alsa_output.pci-0000_00_1f.3."
HDMI_PROFILE = "3"
OFF_PROFILE = "0"

POLL_SECONDS = 0.25
VERIFY_SECONDS = 2.0


def log(message):
    print(
        f"{datetime.now().isoformat(timespec='seconds')} "
        f"{message}",
        flush=True,
    )


def run(*command):
    return subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
        check=False,
    )


def pipewire_objects():
    result = run("pw-dump")

    if result.returncode != 0:
        return []

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return []


def properties(obj):
    return obj.get("info", {}).get("props", {})


def find_device_id(objects):
    for obj in objects:
        if properties(obj).get("device.name") == DEVICE_NAME:
            return str(obj["id"])

    return None


def find_hdmi_sink_id(objects):
    for obj in objects:
        if properties(obj).get("node.name") == HDMI_NODE:
            return str(obj["id"])

    return None


def output_nodes(objects):
    found = []

    for obj in objects:
        name = properties(obj).get("node.name", "")

        if name.startswith(OUTPUT_PREFIX):
            found.append(name)

    return found


def hdmi_connected():
    for path in Path("/proc/asound").glob("card*/eld#2.0"):
        try:
            text = path.read_text(
                encoding="utf-8",
                errors="replace",
            )
        except OSError:
            continue

        present = False
        valid = False

        for line in text.splitlines():
            fields = line.split()

            if fields[:1] == ["monitor_present"]:
                present = fields[-1:] == ["1"]

            if fields[:1] == ["eld_valid"]:
                valid = fields[-1:] == ["1"]

        if present and valid:
            return True

    return False


def activate_hdmi(unmute=False):
    objects = pipewire_objects()
    device_id = find_device_id(objects)

    if device_id is None:
        return False

    sink_id = find_hdmi_sink_id(objects)

    if sink_id is None:
        result = run(
            "wpctl",
            "set-profile",
            device_id,
            HDMI_PROFILE,
        )

        if result.returncode != 0:
            return False

        for _ in range(40):
            time.sleep(0.125)
            objects = pipewire_objects()
            sink_id = find_hdmi_sink_id(objects)

            if sink_id is not None:
                break

    if sink_id is None:
        return False

    run("wpctl", "set-default", sink_id)

    if unmute:
        run("wpctl", "set-mute", sink_id, "0")

    return True


def disable_all_output():
    objects = pipewire_objects()
    device_id = find_device_id(objects)

    if device_id is None:
        return False

    result = run(
        "wpctl",
        "set-profile",
        device_id,
        OFF_PROFILE,
    )

    return result.returncode == 0


def main():
    previous = None
    last_verification = 0.0

    log("ShopAI HDMI-only guard started.")

    while True:
        connected = hdmi_connected()
        now = time.monotonic()
        changed = connected != previous
        verify = now - last_verification >= VERIFY_SECONDS

        if changed or verify:
            objects = pipewire_objects()

            if connected:
                sink_missing = (
                    find_hdmi_sink_id(objects) is None
                )

                if changed or sink_missing:
                    if activate_hdmi(unmute=changed):
                        log("HDMI connected — HDMI audio active.")
                    else:
                        log("HDMI detected — waiting for audio device.")
                else:
                    sink_id = find_hdmi_sink_id(objects)

                    if sink_id is not None:
                        run("wpctl", "set-default", sink_id)

            else:
                outputs = output_nodes(objects)

                if changed or outputs:
                    if disable_all_output():
                        log(
                            "HDMI disconnected — "
                            "all audio output disabled."
                        )
                    else:
                        log(
                            "HDMI disconnected — "
                            "waiting to disable audio."
                        )

            last_verification = now

        previous = connected
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
