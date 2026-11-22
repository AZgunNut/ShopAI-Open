#!/usr/bin/env python3

import base64
import json
import itertools
import os
import re
import subprocess
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
    'qwen25coder': {
        "label": 'Qwen 2.5 Coder 7B',
        "model": '/media/shopai/Extra Space/AI-Models/12-qwen25-coder-7b/qwen2.5-coder-7b-instruct-q8_0.gguf',
        "vision": False,
        "url": "http://127.0.0.1:18084/v1/chat/completions",
        "engine": "llama",
    },
    'glm47flash': {
        "label": 'GLM-4.7 Flash 64x2.6B',
        "model": '/media/shopai/Extra Space/AI-Models/13-glm47-flash/GLM-4.7-Flash-64x2.6B-Q4_K_M.gguf',
        "vision": False,
        "url": "http://127.0.0.1:18085/v1/chat/completions",
        "engine": "llama",
    },
    'magistral': {
        "label": 'Magistral Small 24B',
        "model": '/media/shopai/Extra Space/AI-Models/10-magistral-small-24b/Magistral-Small-2509-Q4_K_M.gguf',
        "vision": False,
        "url": "http://127.0.0.1:18086/v1/chat/completions",
        "engine": "llama",
    },
    'qwen38': {
        "label": 'Qwen 3.8 27B',
        "model": '/media/shopai/Extra Space/AI-Models/03-qwen3.8-27b/Qwen3.8-27B-Q4_K_M.gguf',
        "vision": True,
        "url": "http://127.0.0.1:18087/v1/chat/completions",
        "engine": "llama",
    },
    'qwen3thinking': {
        "label": 'Qwen 3 Thinking 30B',
        "model": '/media/shopai/Extra Space/AI-Models/08-qwen3-thinking-30b/Qwen3-30B-A3B-Thinking-2507-Q4_K_M.gguf',
        "vision": False,
        "url": "http://127.0.0.1:18088/v1/chat/completions",
        "engine": "llama",
    },
    'qwencoder30': {
        "label": 'Qwen 3 Coder 30B',
        "model": '/media/shopai/Extra Space/AI-Models/11-qwen3-coder-30b/Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf',
        "vision": False,
        "url": "http://127.0.0.1:18089/v1/chat/completions",
        "engine": "llama",
    },
    'deepseekr1': {
        "label": 'DeepSeek R1 Distill Qwen 32B',
        "model": '/media/shopai/Extra Space/AI-Models/09-deepseek-r1-32b/DeepSeek-R1-Distill-Qwen-32B-Q4_K_M.gguf',
        "vision": False,
        "url": "http://127.0.0.1:18090/v1/chat/completions",
        "engine": "llama",
    },
    'amthinking': {
        "label": 'AM-Thinking v1 32B',
        "model": '/media/shopai/Extra Space/AI-Models/06-am-thinking-32b/AM-Thinking-v1.Q4_K_M.gguf',
        "vision": False,
        "url": "http://127.0.0.1:18091/v1/chat/completions",
        "engine": "llama",
    },
    'skyworkor1': {
        "label": 'Skywork OR1 32B',
        "model": '/media/shopai/Extra Space/AI-Models/07-skywork-or1-32b/Skywork_Skywork-OR1-32B-Q4_K_M.gguf',
        "vision": False,
        "url": "http://127.0.0.1:18092/v1/chat/completions",
        "engine": "llama",
    },
    'qwen36': {
        "label": 'Qwen 3.6 35B-A3B',
        "model": '/media/shopai/Extra Space/AI-Models/02-qwen3.6-35b/Qwen3.6-35B-A3B-Q4_K_M.gguf',
        "vision": False,
        "url": "http://127.0.0.1:18093/v1/chat/completions",
        "engine": "llama",
    },
    'nemotron': {
        "label": 'Nemotron 3 Nano Omni 30B-A3B',
        "model": '/media/shopai/Extra Space/AI-Models/01-nemotron-30b/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-text-only.Q4_K_M.gguf',
        "vision": False,
        "url": "http://127.0.0.1:18094/v1/chat/completions",
        "engine": "llama",
    },
    'gptoss120': {
        "label": 'GPT-OSS 120B',
        "model": '/media/shopai/Extra Space/AI-Models/14-gpt-oss-120b/openai_gpt-oss-120b-Q4_K_M/openai_gpt-oss-120b-Q4_K_M-00001-of-00002.gguf',
        "vision": False,
        "url": "http://127.0.0.1:18095/v1/chat/completions",
        "engine": "llama",
    },
}

# Three additional ShopAI models.
BACKENDS.update({'qwen25coder32': {'label': 'Qwen2.5 Coder 32B',
                   'model': '/mnt/shopai-data-new/AI-Models/21-future-agentic/Qwen2.5-Coder-32B/Qwen2.5-Coder-32B-Instruct-Q4_K_M.gguf',
                   'vision': False,
                   'url': 'http://127.0.0.1:18096/v1/chat/completions',
                   'engine': 'llama'},
 'qwen25vl7': {'label': 'Qwen2.5 VL 7B',
               'model': '/mnt/shopai-data-new/AI-Models/21-future-agentic/Qwen2.5-VL-7B/Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf',
               'vision': True,
               'url': 'http://127.0.0.1:18097/v1/chat/completions',
               'engine': 'llama'},
 'llama32vision11': {'label': 'Llama 3.2 Vision 11B',
                     'model': '/mnt/shopai-data-new/AI-Models/21-future-agentic/Llama-3.2-Vision-11B/Llama-3.2-11B-Vision-Instruct.Q4_K_M.gguf',
                     'vision': True,
                     'url': 'http://127.0.0.1:18098/v1/chat/completions',
                     'engine': 'llama'}})

# --- ZOO MODELS 21-32 (2026-10) ---
ZOO_BACKENDS = set(('zoo_spark', 'zoo_lfm', 'zoo_phi', 'zoo_qwen2', 'zoo_coder3', 'zoo_unc4', 'zoo_vl4', 'zoo_candor9', 'zoo_dolphin', 'zoo_root14', 'zoo_venice', 'zoo_candor27'))
BACKENDS.update({'zoo_spark': {'label': 'Spark-X2.6 4B Q8', 'model': 'zoo_spark', 'vision': False, 'url': 'http://127.0.0.1:18100/v1/chat/completions', 'engine': 'llama'}, 'zoo_lfm': {'label': 'LFM2.5 8B-A1B Q8', 'model': 'zoo_lfm', 'vision': False, 'url': 'http://127.0.0.1:18101/v1/chat/completions', 'engine': 'llama'}, 'zoo_phi': {'label': 'Phi-4 Mini Q8', 'model': 'zoo_phi', 'vision': False, 'url': 'http://127.0.0.1:18102/v1/chat/completions', 'engine': 'llama'}, 'zoo_qwen2': {'label': 'Qwen3.5 2B Q8', 'model': 'zoo_qwen2', 'vision': True, 'url': 'http://127.0.0.1:18103/v1/chat/completions', 'engine': 'llama'}, 'zoo_coder3': {'label': 'Qwen2.5 Coder 3B Q8', 'model': 'zoo_coder3', 'vision': False, 'url': 'http://127.0.0.1:18104/v1/chat/completions', 'engine': 'llama'}, 'zoo_unc4': {'label': 'Qwen3.5 4B Uncensored Q8', 'model': 'zoo_unc4', 'vision': True, 'url': 'http://127.0.0.1:18105/v1/chat/completions', 'engine': 'llama'}, 'zoo_vl4': {'label': 'Qwen3-VL 4B Thinking Q8', 'model': 'zoo_vl4', 'vision': True, 'url': 'http://127.0.0.1:18106/v1/chat/completions', 'engine': 'llama'}, 'zoo_candor9': {'label': 'Qwen3.5 9B Candor Q4', 'model': 'zoo_candor9', 'vision': False, 'url': 'http://127.0.0.1:18107/v1/chat/completions', 'engine': 'llama'}, 'zoo_dolphin': {'label': 'Dolphin3 8B Q6', 'model': 'zoo_dolphin', 'vision': False, 'url': 'http://127.0.0.1:18108/v1/chat/completions', 'engine': 'llama'}, 'zoo_root14': {'label': 'Qwen3 14B Abliterated Q5', 'model': 'zoo_root14', 'vision': False, 'url': 'http://127.0.0.1:18109/v1/chat/completions', 'engine': 'llama'}, 'zoo_venice': {'label': 'Dolphin Mistral 24B Venice Q5', 'model': 'zoo_venice', 'vision': False, 'url': 'http://127.0.0.1:18110/v1/chat/completions', 'engine': 'llama'}, 'zoo_candor27': {'label': 'Qwen3.8 27B Candor Q4', 'model': 'zoo_candor27', 'vision': False, 'url': 'http://127.0.0.1:18111/v1/chat/completions', 'engine': 'llama'}})


# SHOPAI_UNCHAINED_17_V1_START — all new models share existing local bridge/tool prompt.
UNCHAINED_BACKENDS = {'unc_01': {'label': 'Qwen2.5 3B Abliterated SFT', 'model': 'unc_01', 'vision': False, 'url': 'http://127.0.0.1:18112/v1/chat/completions', 'engine': 'llama'}, 'unc_02': {'label': 'Qwen3 4B Instruct Abliterated', 'model': 'unc_02', 'vision': False, 'url': 'http://127.0.0.1:18113/v1/chat/completions', 'engine': 'llama'}, 'unc_03': {'label': 'Gemma 3 4B Abliterated', 'model': 'unc_03', 'vision': True, 'url': 'http://127.0.0.1:18114/v1/chat/completions', 'engine': 'llama'}, 'unc_04': {'label': 'MedGemma 4B Abliterated', 'model': 'unc_04', 'vision': True, 'url': 'http://127.0.0.1:18115/v1/chat/completions', 'engine': 'llama'}, 'unc_05': {'label': 'Qwen2.5 Coder 7B Abliterated', 'model': 'unc_05', 'vision': False, 'url': 'http://127.0.0.1:18116/v1/chat/completions', 'engine': 'llama'}, 'unc_06': {'label': 'Dolphin 3.0 Llama 3.1 8B', 'model': 'unc_06', 'vision': False, 'url': 'http://127.0.0.1:18117/v1/chat/completions', 'engine': 'llama'}, 'unc_07': {'label': 'Qwen3 8B Abliterated v2', 'model': 'unc_07', 'vision': False, 'url': 'http://127.0.0.1:18118/v1/chat/completions', 'engine': 'llama'}, 'unc_08': {'label': 'Dolphin 2.9.3 Mistral Nemo 12B', 'model': 'unc_08', 'vision': False, 'url': 'http://127.0.0.1:18119/v1/chat/completions', 'engine': 'llama'}, 'unc_09': {'label': 'Gemma 3 12B Abliterated', 'model': 'unc_09', 'vision': True, 'url': 'http://127.0.0.1:18120/v1/chat/completions', 'engine': 'llama'}, 'unc_10': {'label': 'Qwen3 14B Abliterated v2', 'model': 'unc_10', 'vision': False, 'url': 'http://127.0.0.1:18121/v1/chat/completions', 'engine': 'llama'}, 'unc_11': {'label': 'DeepSeek R1 Qwen 14B Abliterated', 'model': 'unc_11', 'vision': False, 'url': 'http://127.0.0.1:18122/v1/chat/completions', 'engine': 'llama'}, 'unc_12': {'label': 'GPT-OSS 20B Abliterated', 'model': 'unc_12', 'vision': False, 'url': 'http://127.0.0.1:18123/v1/chat/completions', 'engine': 'llama'}, 'unc_13': {'label': 'Dolphin 3.0 Mistral 24B', 'model': 'unc_13', 'vision': False, 'url': 'http://127.0.0.1:18124/v1/chat/completions', 'engine': 'llama'}, 'unc_14': {'label': 'Dolphin 3.0 R1 Mistral 24B', 'model': 'unc_14', 'vision': False, 'url': 'http://127.0.0.1:18125/v1/chat/completions', 'engine': 'llama'}, 'unc_15': {'label': 'Gemma 3 27B Abliterated', 'model': 'unc_15', 'vision': True, 'url': 'http://127.0.0.1:18126/v1/chat/completions', 'engine': 'llama'}, 'unc_16': {'label': 'Qwen3 Coder 30B-A3B Abliterated', 'model': 'unc_16', 'vision': False, 'url': 'http://127.0.0.1:18127/v1/chat/completions', 'engine': 'llama'}, 'unc_17': {'label': 'Qwen3 30B-A3B Instruct Abliterated', 'model': 'unc_17', 'vision': False, 'url': 'http://127.0.0.1:18128/v1/chat/completions', 'engine': 'llama'}}
BACKENDS.update(UNCHAINED_BACKENDS)
# Three modes, same local tool access, no 4096-output cap for the new models.
ZOO_BACKENDS.update(UNCHAINED_BACKENDS)
# SHOPAI_UNCHAINED_17_V1_END

if BACKEND not in BACKENDS:
    raise SystemExit(f"Unknown ShopAI local backend: {BACKEND}")

BACKEND_CONFIG = BACKENDS[BACKEND]
# SHOPAI_MISTRAL_BACKEND_V1: retain tool agent and model key; redirect inference only.
import shopai_mistral_backend_v1 as _shopai_mistral
BACKEND_CONFIG = _shopai_mistral.configure_qwen_backend(BACKEND_CONFIG)
IS_ZOO = BACKEND in ZOO_BACKENDS
RESOURCE_MODE = os.environ.get("SHOPAI_RESOURCE_MODE", "local") if IS_ZOO else "legacy"
if IS_ZOO and RESOURCE_MODE not in ("local", "chatgpt", "api"):
    raise SystemExit("Invalid ShopAI resource mode. Expected local, chatgpt, or api.")
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

NETWORK AND AI RESOURCE RULE

You run locally and must NOT directly access the Internet with curl,
wget, git, ssh, browsers, remote APIs, network package managers, or
similar commands.

However, ShopAI provides controlled broker resources that you MAY use
when useful:

CHATGPT WEB RESOURCE - $0 API COST

To ask ChatGPT Web for help, place ONLY the request between these
markers:

[[GPT]]
your question or task for ChatGPT
[[/GPT]]

ShopAI will send the request through its authenticated Chrome/ChatGPT
bridge and return the actual response to you.

OPENAI API RESOURCE - PAID

To request the OpenAI API, place ONLY the request between these
markers:

[[API]]
your question or task for the OpenAI API
[[/API]]

Because this resource costs money, ShopAI will show the request to the
user and require approval before sending it.

Use ChatGPT Web before the paid API when either can reasonably perform
the job.

Do not claim that either resource answered until ShopAI returns its
actual result.

Do not put [[GPT]] or [[API]] around local shell commands.

You may combine local tools and AI resources over multiple rounds to
complete a task.

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

    if IS_ZOO:
        mode_instructions = {
            "local": "Only local ShopAI tools are authorized. Do not request external AI brokers.",
            "chatgpt": "Local ShopAI tools and ChatGPT Web broker are authorized, with per-request approval. Do not request the paid API.",
            "api": "Local ShopAI tools and paid OpenAI API broker are authorized, with per-request approval. Do not request ChatGPT Web."
        }
        base_prompt += "\n\nUSER-SELECTED RESOURCE MODE\n" + mode_instructions[RESOURCE_MODE]
        base_prompt += "\nAll ordinary ShopAI local tool commands remain available with user approval."
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


# SHOPAI_SHARED_TOOL_SUITE_V1_START
_shopai_tool_suite_original_prompt_builder = build_system_prompt

def build_system_prompt():
    original = _shopai_tool_suite_original_prompt_builder()

    try:
        from pathlib import Path as _ShopAIToolPath

        catalog = _ShopAIToolPath(
            '/home/shopai/ShopAI/tool-suites/CATALOG_FOR_AGENTS.md'
        ).read_text(encoding='utf-8')

        return original + "\n\n" + catalog

    except (OSError, UnicodeError):
        return original

# SHOPAI_SHARED_TOOL_SUITE_V1_END

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
        if IS_ZOO:
            payload.pop("max_tokens", None)  # No arbitrary 4096-token cap on new models.
        result = http_json(VISION_URL, payload, timeout=(None if os.environ.get("SHOPAI_MISTRAL_PROXY_URL") else 18000))
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



def extract_gpt_blocks(text):
    pattern = r"(?ms)^\[\[GPT\]\]\s*$\n(.*?)^\[\[/GPT\]\]\s*$"
    return [block.strip() for block in re.findall(pattern, text)]


def extract_api_blocks(text):
    pattern = r"(?ms)^\[\[API\]\]\s*$\n(.*?)^\[\[/API\]\]\s*$"
    return [block.strip() for block in re.findall(pattern, text)]


def run_chatgpt_resource(request_text):
    ensure_script = SHOPAI_ROOT / "ensure-chrome.sh"
    browser_script = SHOPAI_ROOT / "chatgpt_browser.py"

    if not ensure_script.is_file():
        return {
            "ok": False,
            "error": f"Missing {ensure_script}",
        }

    if not browser_script.is_file():
        return {
            "ok": False,
            "error": f"Missing {browser_script}",
        }

    ready = subprocess.run(
        ["/bin/bash", str(ensure_script), "60"],
        capture_output=True,
        text=True,
    )

    if ready.returncode != 0:
        return {
            "ok": False,
            "error": "Authenticated ChatGPT Chrome is unavailable.",
            "startup_stdout": ready.stdout[-4000:],
            "startup_stderr": ready.stderr[-4000:],
        }

    result = subprocess.run(
        [sys.executable, str(browser_script), request_text],
        capture_output=True,
        text=True,
    )

    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "response": result.stdout[-30000:],
        "stderr": result.stderr[-8000:],
    }


def api_approval_prompt(request_text):
    print()
    print("=" * 70)
    print(f"{MODEL_LABEL.upper()} REQUESTED PAID OPENAI API")
    print("=" * 70)
    print(request_text)
    print("=" * 70)
    print("This request may consume prepaid OpenAI API credit.")

    while True:
        answer = input("Send paid API request? [y/N]: ").strip().lower()

        if answer in ("y", "yes"):
            return True

        if answer in ("", "n", "no"):
            return False

        print("Please enter y or n.")


def chatgpt_approval_prompt(request_text):
    print("\nEXTERNAL CHATGPT WEB REQUEST (may transmit task data):")
    print(request_text)
    while True:
        answer = input("Send to ChatGPT Web? [y/N]: ").strip().lower()
        if answer in ("y", "yes"):
            return True
        if answer in ("", "n", "no"):
            return False
        print("Please enter y or n.")


def run_openai_api_resource(request_text):
    script = (
        SHOPAI_ROOT
        / "checkpoints"
        / "shopai_agent_API_WORKING.py"
    )

    if not script.is_file():
        return {
            "ok": False,
            "error": f"Missing {script}",
        }

    result = subprocess.run(
        [sys.executable, str(script), request_text],
        capture_output=True,
        text=True,
    )

    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "response": result.stdout[-30000:],
        "stderr": result.stderr[-8000:],
    }


def format_gpt_result(request_text, result):
    return (
        "SHOPAI CHATGPT WEB RESULT\n\n"
        f"Request:\n{request_text}\n\n"
        f"Result:\n{json.dumps(result, indent=2)}\n\n"
        "This is the actual broker result. Use it as evidence, "
        "but independently reconcile it with the user's task."
    )


def format_api_result(request_text, result):
    return (
        "SHOPAI OPENAI API RESULT\n\n"
        f"Request:\n{request_text}\n\n"
        f"Result:\n{json.dumps(result, indent=2)}\n\n"
        "This is the actual paid API result. Use it as evidence, "
        "but independently reconcile it with the user's task."
    )



def main(initial_task=None):
    one_shot = initial_task is not None
    ensure_workspace()

    print()
    print("=" * 70)
    print("ShopAI Local Agent v0.3")
    print(
        f"Model: {MODEL_LABEL}"
        if VISION_MODE or IS_ZOO else f"Model: {MODEL}"
    )
    print("Mode:  LOCAL + CONTROLLED SHOPAI RESOURCES")
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
    print("Direct Internet access: BLOCKED")
    print("ChatGPT Web broker:     AVAILABLE / $0 API")
    print("OpenAI API broker:      AVAILABLE / PAID + APPROVAL")
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

        for _ in (range(8) if not IS_ZOO else itertools.count()):

            command_blocks = extract_command_blocks(answer)
            gpt_blocks = extract_gpt_blocks(answer)
            api_blocks = extract_api_blocks(answer)

            if not command_blocks and not gpt_blocks and not api_blocks:
                break

            tool_messages = []

            # ------------------------------------------------
            # LOCAL COMPUTER TOOLS
            # ------------------------------------------------

            for command in command_blocks:

                if approval_prompt(command):

                    check_memory_limit()

                    result = run_through_bridge(command)

                    print()
                    print("ShopAI local result:")
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


            # ------------------------------------------------
            # CHATGPT WEB BROKER
            # ------------------------------------------------

            for request_text in gpt_blocks:

                print()
                print("=" * 70)
                print(
                    f"{MODEL_LABEL.upper()} -> CHATGPT WEB"
                )
                print("=" * 70)
                print(request_text)
                print("=" * 70)

                if IS_ZOO and RESOURCE_MODE != "chatgpt":
                    result = {"ok": False, "error": "ChatGPT Web broker not enabled in selected session mode"}
                elif IS_ZOO and not chatgpt_approval_prompt(request_text):
                    result = {"ok": False, "error": "User declined external ChatGPT Web request"}
                else:
                    result = run_chatgpt_resource(request_text)

                print()
                print("ChatGPT Web result:")

                if result.get("response"):
                    print(result["response"])
                else:
                    print(json.dumps(result, indent=2))

                tool_messages.append(
                    format_gpt_result(request_text, result)
                )


            # ------------------------------------------------
            # PAID OPENAI API BROKER
            # ------------------------------------------------

            for request_text in api_blocks:

                if (not IS_ZOO or RESOURCE_MODE == "api") and api_approval_prompt(request_text):

                    result = run_openai_api_resource(
                        request_text
                    )

                    print()
                    print("OpenAI API result:")

                    if result.get("response"):
                        print(result["response"])
                    else:
                        print(json.dumps(result, indent=2))

                    tool_messages.append(
                        format_api_result(
                            request_text,
                            result,
                        )
                    )

                else:

                    print("Paid API request declined.")

                    tool_messages.append(
                        "SHOPAI OPENAI API RESULT\n\n"
                        f"Request:\n{request_text}\n\n"
                        "The user declined the paid API request. "
                        "No API call was made and no API cost "
                        "was incurred."
                    )


            messages.append({
                "role": "user",
                "content": "\n\n".join(tool_messages)
            })

            try:
                answer = ask_qwen(messages)

            except Exception as e:
                print(
                    f"\n{MODEL_LABEL} error after "
                    f"ShopAI resource result: {e}\n"
                )

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
