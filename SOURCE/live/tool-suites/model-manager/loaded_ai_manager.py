#!/usr/bin/env python3
"""ShopAI loaded model manager.

Discover running inference models and allow explicitly
confirmed, graceful shutdowns.

Never terminate the ShopAI agent, bridge, SSH, RPC
infrastructure, or Ollama daemon.
"""

import json
import os
import pathlib
import signal
import subprocess
import sys
import time
import urllib.request

P = pathlib.Path
API = "http://127.0.0.1:11434"


def ollama_loaded():
    try:
        with urllib.request.urlopen(
            API + "/api/ps",
            timeout=3
        ) as response:
            data = json.load(response)

        return data.get("models", []), None

    except Exception as exc:
        return [], (
            "Ollama status unavailable: "
            f"{type(exc).__name__}: {exc}"
        )


def cmdline(pid):
    try:
        raw = (
            P("/proc") / str(pid) / "cmdline"
        ).read_bytes()

        return [
            item.decode("utf-8", "replace")
            for item in raw.split(b"\0")
            if item
        ]

    except (OSError, PermissionError):
        return []


def process_start(pid):
    try:
        text = (
            P("/proc") / str(pid) / "stat"
        ).read_text(errors="replace")

        return text.rsplit(")", 1)[1].split()[19]

    except (OSError, IndexError, ValueError):
        return None


def process_uid(pid):
    try:
        return (
            P("/proc") / str(pid)
        ).stat().st_uid

    except (OSError, PermissionError):
        return -1


def rss_mib(pid):
    try:
        lines = (
            P("/proc") / str(pid) / "status"
        ).read_text().splitlines()

        for line in lines:
            if line.startswith("VmRSS:"):
                return round(
                    int(line.split()[1]) / 1024,
                    1
                )

    except (OSError, IndexError, ValueError):
        pass

    return None


def model_arg(args):
    # mistral.rs loads ShopAI GGUF models with -f, not --model.
    if (
        len(args) > 1
        and P(args[0]).name.lower() == "mistralrs"
        and args[1] == "serve"
    ):
        for index, arg in enumerate(args):
            if arg == "-f" and index + 1 < len(args):
                return args[index + 1]
            if arg.startswith("-f="):
                return arg[3:]

    flags = (
        "--model",
        "--model-path",
        "--model_path",
        "--model-id",
        "--model_id",
        "-m"
    )

    for i, arg in enumerate(args):

        for flag in flags:
            if arg.startswith(flag + "="):
                return arg[len(flag) + 1:]

        if arg in flags and i + 1 < len(args):
            return args[i + 1]

    if "serve" in args:
        i = args.index("serve")

        if (
            i + 1 < len(args)
            and not args[i + 1].startswith("-")
        ):
            return args[i + 1]

    return ""


def model_server_type(args):
    if not args:
        return None

    # Only a real mistral.rs server, not an arbitrary program mentioning it.
    if (
        len(args) > 1
        and P(args[0]).name.lower() == "mistralrs"
        and args[1] == "serve"
    ):
        return "mistral.rs"

    heads = [
        P(item).name.lower()
        for item in args[:4]
    ]

    command = " ".join(args[:5]).lower()

    if any(
        item in (
            "llama-server",
            "llama-cli",
            "llamafile",
            "koboldcpp",
            "koboldcpp.py"
        )
        or item.startswith("llama-server-")
        for item in heads
    ):
        return "llama.cpp / llamafile"

    if (
        "vllm" in command
        and (
            "serve" in args
            or "api_server" in command
        )
    ):
        return "vLLM"

    if any(
        "text-generation-launcher" in item
        for item in heads
    ):
        return "Text Generation Inference"

    if "mlx_lm.server" in command:
        return "MLX LM"

    return None


def mistral_executable(pid, args):
    """Match the running executable to argv[0]; refuse stale or fake PIDs."""
    if (
        len(args) < 2
        or P(args[0]).name.lower() != "mistralrs"
        or args[1] != "serve"
    ):
        return None
    try:
        actual = (P("/proc") / str(pid) / "exe").resolve(strict=True)
        expected = P(args[0]).resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    return str(actual) if actual == expected else None


def mistral_managed_service(pid):
    """Don't stop a daemon or other service as a side-effect of model selection."""
    try:
        lines = (P("/proc") / str(pid) / "cgroup").read_text().splitlines()
    except OSError:
        return "unknown/unreadable cgroup"
    for line in lines:
        path = line.split(":", 2)[-1]
        for part in path.split("/"):
            if part.endswith(".service") and part != f"user@{os.getuid()}.service":
                return part
    return None


def systemd_info(pid):
    try:
        raw = (
            P("/proc") / str(pid) / "cgroup"
        ).read_text(errors="replace")

    except OSError:
        return None

    for line in raw.splitlines():
        path = line.split(":", 2)[-1]

        units = [
            item
            for item in path.split("/")
            if item.endswith(".service")
        ]

        if not units:
            continue

        unit = units[-1]

        if (
            unit == f"user@{os.getuid()}.service"
            or unit == "ollama.service"
        ):
            continue

        if unit.startswith((
            "shopai-",
            "llama-",
            "vllm-",
            "text-generation-"
        )):
            return {
                "name": unit,
                "user": not path.startswith(
                    "/system.slice/"
                )
            }

    return None


def discover():
    rows = []

    loaded, warning = ollama_loaded()

    for item in loaded:
        name = (
            item.get("name")
            or item.get("model")
        )

        if not name:
            continue

        size = item.get("size_vram")

        rows.append({
            "kind": "ollama",
            "engine": "Ollama loaded model",
            "model": name,
            "pid": None,
            "start": None,
            "rss_mib": None,
            "vram_mib": (
                round(size / 1048576, 1)
                if isinstance(size, (int, float))
                else None
            ),
            "service": None,
            "note": (
                "Unload the selected model only. "
                "Keep the Ollama daemon running."
            )
        })

    try:
        pids = sorted(
            int(entry.name)
            for entry in P("/proc").iterdir()
            if entry.name.isdigit()
        )

    except OSError:
        pids = []

    for pid in pids:

        if process_uid(pid) != os.getuid():
            continue

        args = cmdline(pid)
        engine = model_server_type(args)

        if not engine:
            continue

        model = model_arg(args)

        if not model:
            continue

        started = process_start(pid)

        if started is None:
            continue

        # Mistral must be an actual local executable, not only a matching argv.
        executable = None
        if engine == "mistral.rs":
            executable = mistral_executable(pid, args)
            if executable is None:
                continue

        row = {
            "kind": "process",
            "engine": engine,
            "model": model,
            "pid": pid,
            "start": started,
            "rss_mib": rss_mib(pid),
            "vram_mib": None,
            "service": systemd_info(pid),
            "note": (
                "Stopping this process may interrupt "
                "active requests. Current workload "
                "cannot be determined reliably."
            )
        }
        if executable is not None:
            row["executable"] = executable
            row["argv_snapshot"] = args
        rows.append(row)

    return rows, warning


def display(rows, warning):
    print()
    print("=" * 65)
    print("SHOPAI — LOADED AI MANAGER")
    print("=" * 65)

    print(
        "Identified running models only. "
        "Installed but unloaded models are excluded."
    )

    print(
        "ShopAI agents, bridge, SSH, RPC and "
        "Ollama daemon are not shutdown targets."
    )

    if warning:
        print("NOTE:", warning)

    if not rows:
        print()
        print(
            "No supported active model processes found."
        )
        print(
            "Unknown inference runtimes may not "
            "appear in this list."
        )
        return

    for number, row in enumerate(rows, 1):

        rss = (
            f"{row['rss_mib']} MiB RAM"
            if row["rss_mib"] is not None
            else ""
        )

        gpu = (
            f"{row['vram_mib']} MiB VRAM"
            if row["vram_mib"] is not None
            else ""
        )

        identity = (
            f"PID {row['pid']}"
            if row["pid"] is not None
            else "Ollama model"
        )

        service = ""

        if row["service"]:
            service = (
                " | systemd: "
                + row["service"]["name"]
            )

        print()
        print(f"{number:2}) {row['model']}")
        print(
            f"    {row['engine']} | "
            f"{identity}{service}"
        )
        print(f"    {rss} {gpu}")

    print()
    print(
        "WARNING: A running model may be processing "
        "an assignment. Confirm before shutting down."
    )


def stop_ollama(row):
    current, error = ollama_loaded()

    if error:
        print("Cannot verify Ollama:", error)
        return False

    names = {
        item.get("name") or item.get("model")
        for item in current
    }

    if row["model"] not in names:
        print("Model already unloaded.")
        return True

    try:
        result = subprocess.run(
            ["ollama", "stop", row["model"]],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=45
        )

    except (OSError, subprocess.TimeoutExpired) as exc:
        print("Ollama stop error:", exc)
        return False

    if result.returncode:
        print(
            "Ollama stop failed:",
            (result.stderr or result.stdout)[-500:]
        )
        return False

    time.sleep(0.5)

    current, error = ollama_loaded()

    if error:
        print(
            "Stop requested, but unload could "
            "not be verified:",
            error
        )
        return False

    names = {
        item.get("name") or item.get("model")
        for item in current
    }

    stopped = row["model"] not in names

    print(
        "Ollama model unloaded."
        if stopped
        else "Ollama still reports model loaded."
    )

    return stopped


def stop_process(row):
    pid = row["pid"]

    # Refuse a stale PID or different process.

    if (
        process_uid(pid) != os.getuid()
        or process_start(pid) != row["start"]
    ):
        print(
            "REFUSED: Process changed or no longer "
            "belongs to the ShopAI user."
        )
        return False

    args = cmdline(pid)

    if (
        model_server_type(args) != row["engine"]
        or model_arg(args) != row["model"]
    ):
        print(
            "REFUSED: Process arguments changed "
            "since selection."
        )
        return False

    # For mistral.rs, verify the *entire* argv and /proc executable again.
    # Never stop a service-managed mistral process through this interface.
    if row["engine"] == "mistral.rs":
        if (
            args != row.get("argv_snapshot")
            or mistral_executable(pid, args) != row.get("executable")
        ):
            print("REFUSED: mistral.rs executable or command changed.")
            return False
        managed = mistral_managed_service(pid)
        if managed is not None or row["service"] is not None:
            print("REFUSED: mistral.rs is under a service:", managed or row["service"])
            print("No service stop or signal sent.")
            return False

    service = row["service"]

    if service:
        print(
            "Stopping dedicated model service:",
            service["name"]
        )

        command = ["systemctl"]

        if service["user"]:
            command.append("--user")

        command.extend([
            "stop",
            service["name"]
        ])

        try:
            result = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=45
            )

        except (
            OSError,
            subprocess.TimeoutExpired
        ) as exc:
            print("Service stop failed:", exc)
            return False

        if result.returncode:
            print(
                "Service stop not authorized "
                "or unsuccessful.",
                result.stderr[-500:]
            )
            print("No forced shutdown attempted.")
            return False

    else:
        print(
            "Sending graceful SIGTERM to "
            f"verified model PID {pid}."
        )

        try:
            os.kill(pid, signal.SIGTERM)

        except ProcessLookupError:
            print("Model already exited.")
            return True

        except PermissionError:
            print("Permission denied.")
            return False

    # Allow graceful cleanup. Never force-kill.

    for _ in range(40):

        if process_start(pid) != row["start"]:
            print("Model process stopped.")
            return True

        try:
            status = (
                P("/proc") / str(pid) / "status"
            ).read_text()

            if any(
                line.startswith("State:")
                and (
                    "Z (zombie)" in line
                    or "X (dead)" in line
                )
                for line in status.splitlines()
            ):
                print(
                    "Model exited; awaiting "
                    "parent-process cleanup."
                )
                return True

        except OSError:
            print("Model process stopped.")
            return True

        time.sleep(0.5)

    print(
        "Graceful shutdown requested, but "
        "the process remains after 20 seconds."
    )
    print("No forced termination performed.")

    return False


def confirm_two_enters(target):
    """Two separate Enter presses; any other input cancels."""

    print(f"\nAbout to stop: {target}")
    print("Press ENTER twice to confirm. Any other input cancels.")

    for step in (1, 2):
        answer = input(f"Confirm {step}/2 (ENTER): ")

        if answer != "":
            print("Cancelled; nothing stopped.")
            return False

    return True


def main():
    action = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "manage"
    )

    if action in ("help", "-h", "--help"):
        print(
            "Usage: loaded_ai_manager.py "
            "[manage | list | list-json]"
        )
        return 0

    if action in ("list", "list-json"):
        rows, warning = discover()

        if action == "list-json":
            print(json.dumps({
                "models": rows,
                "warning": warning,
                "core_services_preserved": True
            }, indent=2))
        else:
            display(rows, warning)

        return 0

    if action != "manage":
        print("Unknown command.", file=sys.stderr)
        return 2

    if not sys.stdin.isatty():
        print(
            "Interactive terminal required for "
            "shutdown operations.",
            file=sys.stderr
        )
        return 2

    while True:
        rows, warning = discover()
        display(rows, warning)

        if not rows:
            input(
                "\nEnter to refresh; "
                "Ctrl+C to exit: "
            )
            continue

        print()
        print("NUMBER = select one model")
        print("A      = select ALL identified models")
        print("R      = refresh")
        print("Q      = quit without further changes")
        print()

        choice = input("Selection: ").strip().lower()

        if choice in ("q", "quit", "0"):
            return 0

        if choice in ("r", "refresh", ""):
            continue

        if choice == "a":

            print()
            print(
                "ALL may interrupt active model requests."
            )

            if not confirm_two_enters("ALL identified models"):
                continue

            for row in rows:
                print()
                print("Stopping:", row["model"])

                if row["kind"] == "ollama":
                    stop_ollama(row)
                else:
                    stop_process(row)

            continue

        try:
            number = int(choice)

            if not 1 <= number <= len(rows):
                raise ValueError()

        except ValueError:
            print("Invalid selection.")
            continue

        row = rows[number - 1]

        print()
        print("Selected:", row["model"])
        print(row["note"])

        if not confirm_two_enters(row["model"]):
            continue

        if row["kind"] == "ollama":
            stop_ollama(row)
        else:
            stop_process(row)


if __name__ == "__main__":
    try:
        sys.exit(main())

    except (KeyboardInterrupt, EOFError):
        print("\nExited without further changes.")
        sys.exit(0)
