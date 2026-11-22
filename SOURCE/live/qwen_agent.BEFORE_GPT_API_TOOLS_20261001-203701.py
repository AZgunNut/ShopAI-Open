#!/usr/bin/env python3

import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path


BACKEND = os.environ.get("SHOPAI_LOCAL_BACKEND", "local")

BACKENDS = {
    "local": {
        "label": "Qwen 3.5 4B",
        "model": "qwen3.5:4b",
        "vision": False,
        "url": "http://127.0.0.1:11434/api/chat",
        "engine": "ollama",
    },
    "vision": {
        "label": "Qwen3-VL 30B-A3B",
        "model": (
            "/media/shopai/Extra Space/AI-Models/"
            "Qwen3-VL-30B-A3B-Instruct-Q4_K_M/"
            "Qwen3VL-30B-A3B-Instruct-Q4_K_M.gguf"
        ),
        "vision": True,
        "url": "http://127.0.0.1:18080/v1/chat/completions",
        "engine": "llama",
    },
    "mechvl": {
        "label": "MechVL-4B-RL",
        "model": (
            "/media/shopai/Extra Space/AI-Models/"
            "MechVL-4B-RL-Q8/MechVL-4B-RL.Q8_0.gguf"
        ),
        "vision": True,
        "url": "http://127.0.0.1:18081/v1/chat/completions",
        "engine": "llama",
    },
    "internvl": {
        "label": "InternVL3.5 30B-A3B",
        "model": (
            "/media/shopai/Extra Space/AI-Models/"
            "InternVL3_5-30B-A3B-Q4_K_M/"
            "InternVL3_5-30B-A3B-Q4_K_M.gguf"
        ),
        "vision": True,
        "url": "http://127.0.0.1:18082/v1/chat/completions",
        "engine": "llama",
    },
    "glm": {
        "label": "GLM-4.1V 9B",
        "model": (
            "/media/shopai/Extra Space/AI-Models/"
            "GLM-4.1V-9B-Thinking-Q4_K_M/"
            "GLM-4.1V-9B-Thinking.Q4_K_M.gguf"
        ),
        "vision": False,
        "url": "http://127.0.0.1:18083/v1/chat/completions",
        "engine": "llama",
    },
}

if BACKEND not in BACKENDS:
    raise SystemExit(f"Unknown ShopAI local backend: {BACKEND}")

BACKEND_CONFIG = BACKENDS[BACKEND]
VISION_MODE = bool(BACKEND_CONFIG["vision"])
MECHVL_MODE = BACKEND == "mechvl"
MODEL = BACKEND_CONFIG["model"]
MODEL_LABEL = BACKEND_CONFIG["label"]

OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
VISION_URL = BACKEND_CONFIG["url"]
BRIDGE_URL = "http://127.0.0.1:8765"

SHOPAI_ROOT = Path("/home/shopai/ShopAI")
MEMORY_ROOT = SHOPAI_ROOT / "local-memory"
MEMORY_DIR = MEMORY_ROOT / "memory"
SCRATCH_DIR = MEMORY_ROOT / "scratch"
LOG_DIR = MEMORY_ROOT / "logs"
CONFIG_FILE = MEMORY_ROOT / "config.json"

DEFAULT_MAX_BYTES = 500 * 1024 * 1024


BASE_SYSTEM_PROMPT = r"""
You are the LOCAL AI component of ShopAI.

You are Qwen3.5 4B running locally through Ollama on this Dell
Precision 3630.

You have real local-computer tools provided by ShopAI.

LOCAL-OFFLINE RULE

You do NOT have permission to access the Internet.

Do not use curl, wget, git, ssh, browsers, remote APIs, network
package managers, GitHub, OpenAI, ChatGPT, or other Internet services.

If Internet information is needed, tell the user that Local AI is
offline. The user can manually select another AI if desired.

LOCAL COMPUTER ACCESS

You may use ShopAI tools to:

- inspect files and directories
- read files
- create and edit files
- copy files
- rename and move files
- organize files
- inspect processes
- execute appropriate local shell commands
- inspect mounted removable media
- work with permitted local storage

ShopAI project area:

/home/shopai/ShopAI

Large storage partition:

/media/shopai/Extra Space

USB and removable drives normally appear beneath:

/media/shopai/

Do not format, repartition, erase, or perform destructive disk-level
operations unless the user explicitly approves that specific action.

PERSISTENT MEMORY

Your persistent workspace is:

/home/shopai/ShopAI/local-memory/

Important long-term information belongs in:

/home/shopai/ShopAI/local-memory/memory/

Temporary work belongs in:

/home/shopai/ShopAI/local-memory/scratch/

Logs belong in:

/home/shopai/ShopAI/local-memory/logs/

The combined workspace limit is 500 MiB.

IMPORTANT MEMORY RULES

Persistent memory is REAL FILE STORAGE, not conversational memory.

Never claim that you remembered, saved, stored, recorded, updated,
deleted, or changed persistent information unless you actually used
a ShopAI local command to perform that operation and received a
successful execution result.

When the user asks you to remember something permanently:

1. Inspect existing persistent memory when appropriate.
2. Write the information to a suitable file under memory/.
3. Read the written information back from disk.
4. Only after successful read-back may you tell the user it was saved.

When the user asks you to recall or recover information from
persistent memory:

1. Do not guess.
2. Do not say memory is empty unless you actually inspected it.
3. Use the persistent-memory inventory supplied at startup.
4. Read likely memory files using your local tools.
5. Search the memory directory if necessary.
6. Report what is actually found on disk.

The persistent-memory inventory supplied in this system prompt was
generated from the real filesystem at agent startup.

COMMAND EXECUTION

When you need ShopAI to execute LOCAL shell commands, place ONLY the
commands between lines containing exactly five asterisks.

Example:

*****
ps aux | grep python
*****

ShopAI will detect the block, show it to the user, request approval,
execute it through the local bridge, and return stdout/stderr.

Never claim a command succeeded before ShopAI returns its result.

If a command fails, use the actual error to determine the next step.

Do not claim that you lack filesystem access when the task can be
performed with ShopAI's local tools.

For routine operations, be concise.
"""


def ensure_workspace():
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def load_config():
    try:
        with CONFIG_FILE.open("r", encoding="utf-8") as f:
            config = json.load(f)
        return int(config.get("max_bytes", DEFAULT_MAX_BYTES))
    except Exception:
        return DEFAULT_MAX_BYTES


def directory_usage(path):
    total = 0
    files = 0

    if not path.exists():
        return total, files

    for root, dirs, filenames in os.walk(path):
        for filename in filenames:
            p = Path(root) / filename
            try:
                total += p.stat().st_size
                files += 1
            except OSError:
                pass

    return total, files


def memory_inventory():
    entries = []

    if not MEMORY_DIR.exists():
        return "(memory directory does not exist)"

    for root, dirs, files in os.walk(MEMORY_DIR):
        dirs.sort()
        files.sort()

        for filename in files:
            path = Path(root) / filename

            try:
                relative = path.relative_to(MEMORY_DIR)
                size = path.stat().st_size
                entries.append(f"{relative} ({size} bytes)")
            except OSError:
                pass

    if not entries:
        return "(no persistent memory files)"

    return "\n".join(entries)


def build_system_prompt():
    inventory = memory_inventory()
    vision_note = (
        "\n\nVISION CAPABILITY\n"
        "You can inspect images attached to user messages by ShopAI. "
        "The user attaches an image with /image PATH | QUESTION. "
        "If no image is attached, ask for its local path. "
        "Do not claim that you lack vision.\n"
        if VISION_MODE else ""
    )

    base_prompt = BASE_SYSTEM_PROMPT.replace("Qwen3.5 4B", MODEL_LABEL)
    if BACKEND_CONFIG["engine"] == "llama":
        base_prompt = base_prompt.replace("through Ollama", "through llama.cpp")

    return (
        base_prompt
        + vision_note
        + "\n\n"
        + "PERSISTENT MEMORY INVENTORY AT THIS STARTUP\n"
        + "-------------------------------------------\n"
        + inventory
        + "\n"
        + "-------------------------------------------\n"
        + "These filenames exist on disk now. Read relevant files with "
          "your local tools when the user asks you to recall information.\n"
    )


def show_memory_status():
    max_bytes = load_config()
    used, files = directory_usage(MEMORY_ROOT)

    used_mb = used / (1024 * 1024)
    max_mb = max_bytes / (1024 * 1024)

    percent = (used / max_bytes * 100.0) if max_bytes else 0.0
    free_mb = max(0, max_bytes - used) / (1024 * 1024)

    if percent >= 95:
        status = "CRITICAL"
    elif percent >= 80:
        status = "WARNING"
    else:
        status = "OK"

    print()
    print("Qwen Persistent Workspace")
    print(f"Used:   {used_mb:.4f} MB / {max_mb:.0f} MB ({percent:.4f}%)")
    print(f"Free:   {free_mb:.4f} MB")
    print(f"Files:  {files}")
    print(f"Status: {status}")
    print()


def check_memory_limit():
    max_bytes = load_config()
    used, _ = directory_usage(MEMORY_ROOT)

    if used > max_bytes:
        print()
        print("WARNING: Persistent workspace exceeds its 500 MiB limit.")
        print("Further persistent-memory growth should stop until space")
        print("is consolidated or removed with user approval.")
        print()
        return False

    return True


def http_json(url, payload=None, timeout=300):
    data = None
    headers = {}

    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method="POST" if payload is not None else "GET",
    )

    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw)


def bridge_health():
    try:
        result = http_json(BRIDGE_URL + "/health", timeout=5)
        return bool(result.get("ok"))
    except Exception:
        return False


def vision_user_content(text):
    if not VISION_MODE or not text.startswith("/image "):
        return text

    path_text, _, question = text[len("/image "):].partition(" | ")
    image_path = Path(path_text.strip()).expanduser()
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
    }.get(image_path.suffix.lower())

    if not mime:
        raise ValueError("Use a PNG, JPEG, GIF, or BMP image path.")
    if not image_path.is_file():
        raise ValueError(f"Image file not found: {image_path}")
    if image_path.stat().st_size > 12 * 1024 * 1024:
        raise ValueError("Image file exceeds the 12 MiB input limit.")

    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return [
        {"type": "text", "text": question.strip() or "Describe this image."},
        {
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{encoded}"},
        },
    ]


def ask_qwen(messages):
    if BACKEND_CONFIG["engine"] == "llama":
        payload = {
            "model": MODEL,
            "messages": messages,
            "stream": False,
            "temperature": 0.2,
            "max_tokens": 4096,
        }
        result = http_json(VISION_URL, payload, timeout=18000)
        return result["choices"][0]["message"]["content"]

    payload = {
        "model": MODEL,
        "messages": messages,
        "stream": False,
        "think": False,
        "options": {
            "temperature": 0.2
        }
    }

    result = http_json(OLLAMA_URL, payload, timeout=600)
    return result["message"]["content"]


def extract_command_blocks(text):
    pattern = r"(?ms)^\*{5}\s*$\n(.*?)^\*{5}\s*$"
    return [block.strip() for block in re.findall(pattern, text)]


def run_through_bridge(command):
    payload = {
        "command": command
    }

    try:
        return http_json(
            BRIDGE_URL + "/tool/run",
            payload,
            timeout=300
        )

    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8")
        except Exception:
            body = str(e)

        return {
            "ok": False,
            "error": body
        }

    except Exception as e:
        return {
            "ok": False,
            "error": str(e)
        }


def format_tool_result(command, result):
    return (
        "SHOPAI LOCAL EXECUTION RESULT\n\n"
        f"Command:\n{command}\n\n"
        f"Result:\n{json.dumps(result, indent=2)}\n\n"
        "Use only the actual result above when determining whether "
        "the operation succeeded."
    )


def approval_prompt(command):
    print()
    print("=" * 70)
    print(f"{MODEL_LABEL.upper()} REQUESTED LOCAL EXECUTION")
    print("=" * 70)
    print(command)
    print("=" * 70)

    while True:
        answer = input("Execute? [y/N]: ").strip().lower()

        if answer in ("y", "yes"):
            return True

        if answer in ("", "n", "no"):
            return False

        print("Please enter y or n.")


def main(initial_task=None):
    one_shot = initial_task is not None
    ensure_workspace()

    print()
    print("=" * 70)
    print("ShopAI Local Agent v0.3")
    print(
        f"Model: {MODEL_LABEL}"
        if VISION_MODE else f"Model: {MODEL}"
    )
    print("Mode:  LOCAL-OFFLINE")
    print("=" * 70)

    show_memory_status()

    inventory = memory_inventory()

    print("Persistent memory inventory:")
    print(inventory)
    print()

    if bridge_health():
        print("ShopAI bridge: ONLINE")
    else:
        print("ShopAI bridge: OFFLINE")
        print("Start it with:")
        print("  ~/ShopAI/start-bridge.sh")

    print()
    print(f"{MODEL_LABEL} has local ShopAI computer tools.")
    print("Internet access is NOT available to Local AI.")
    print()
    print("Commands:")
    print("  /quit     Exit")
    print("  /memory   Show persistent workspace usage")
    print("  /clear    Start a fresh conversation")
    if VISION_MODE:
        print("  /image PATH | QUESTION   Analyze a local image")
    print()

    system_prompt = build_system_prompt()

    messages = [
        {
            "role": "system",
            "content": system_prompt
        }
    ]

    while True:
        try:
            user_text = ("/quit" if one_shot and initial_task is None else initial_task if initial_task is not None else input("You> ")).strip()
            initial_task = None

        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_text:
            continue

        if user_text == "/quit":
            break

        if user_text == "/memory":
            show_memory_status()
            print("Persistent memory inventory:")
            print(memory_inventory())
            print()
            continue

        if user_text == "/clear":
            system_prompt = build_system_prompt()

            messages = [
                {
                    "role": "system",
                    "content": system_prompt
                }
            ]

            print("Conversation cleared and memory inventory refreshed.")
            continue

        try:
            content = vision_user_content(user_text)
        except (OSError, ValueError) as exc:
            print(f"\\nImage input error: {exc}\\n")
            if one_shot:
                return 1
            continue

        messages.append({
            "role": "user",
            "content": content
        })

        try:
            answer = ask_qwen(messages)

        except Exception as e:
            print(f"\nQwen/Ollama error: {e}\n")

            if one_shot:
                return 1

            continue

        print()
        print(f"{MODEL_LABEL}>")
        print(answer)

        messages.append({
            "role": "assistant",
            "content": answer
        })

        for _ in range(8):

            blocks = extract_command_blocks(answer)

            if not blocks:
                break

            tool_messages = []

            for command in blocks:

                if approval_prompt(command):

                    check_memory_limit()

                    result = run_through_bridge(command)

                    print()
                    print("ShopAI result:")
                    print(json.dumps(result, indent=2))

                    check_memory_limit()

                    tool_messages.append(
                        format_tool_result(command, result)
                    )

                else:

                    print("Execution declined.")

                    tool_messages.append(
                        "SHOPAI LOCAL EXECUTION RESULT\n\n"
                        f"Command:\n{command}\n\n"
                        "The user declined execution. "
                        "The command did not run."
                    )

            messages.append({
                "role": "user",
                "content": "\n\n".join(tool_messages)
            })

            try:
                answer = ask_qwen(messages)

            except Exception as e:
                print(f"\nQwen/Ollama error after tool result: {e}\n")

                if one_shot:
                    return 1

                break

            print()
            print(f"{MODEL_LABEL}>")
            print(answer)

            messages.append({
                "role": "assistant",
                "content": answer
            })

    print()
    print("ShopAI Local Agent stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(
        main(sys.argv[1] if len(sys.argv) > 1 else None)
    )
