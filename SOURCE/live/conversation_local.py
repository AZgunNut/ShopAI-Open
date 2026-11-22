#!/usr/bin/env python3
import os
import re
import subprocess
import sys
from pathlib import Path

from conversation_runtime import append, continued_request, new

ROOT = Path.home() / "ShopAI"
ORIGINAL = ROOT / "qwen_agent.py"

def answer_from(output):
    output = output.replace("\nShopAI Local Agent stopped.\n", "\n").strip()
    matches = list(re.finditer(r"\n[A-Za-z0-9 ._-]{2,80}>\n", output))
    return output[matches[-1].end():].strip() if matches else output

def main():
    task = " ".join(sys.argv[1:]).strip()
    if not task:
        return 2

    if task == "/clear":
        new("New ShopAI conversation")
        print("New shared conversation started; earlier transcript remains saved.")
        return 0

    # SHOPAI_CONVERSATION_MODES_V1: snapshot prior history BEFORE saving new user message.
    # This prevents the current question from appearing twice in model input.
    model_prompt = continued_request(task)
    model_key = os.environ.get("SHOPAI_SELECTED_MODEL", "local")
    provenance = {
        "inference_backend": os.environ.get("SHOPAI_SELECTED_INFERENCE",
                                           os.environ.get("SHOPAI_INFERENCE_BACKEND", "llama")),
        "resource_mode": os.environ.get("SHOPAI_RESOURCE_MODE", "local"),
    }
    append("user", task, "local", model=model_key, metadata=provenance)
    result = subprocess.run(
        [sys.executable, str(ORIGINAL), model_prompt],
        text=True,
        capture_output=True,
        env=os.environ.copy(),
    )

    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(result.stderr, file=sys.stderr,
              end="" if result.stderr.endswith("\n") else "\n")

    reply = answer_from(result.stdout)
    if reply:
        append("assistant", reply, "local", model=model_key, metadata=provenance)
    return result.returncode

raise SystemExit(main())
