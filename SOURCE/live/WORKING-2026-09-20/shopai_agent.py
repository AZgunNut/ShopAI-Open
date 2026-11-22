#!/usr/bin/env python3

import pathlib
import subprocess
import sys

ROOT = pathlib.Path.home() / "ShopAI"


def chatgpt_web(task):
    """Use the authenticated ChatGPT Web session through chrome-use."""
    script = ROOT / "chatgpt_browser.py"

    if not script.exists():
        print(f"ERROR: Missing {script}")
        return 1

    print()
    print("AI: ChatGPT Web")
    print("API cost: $0")
    print()

    result = subprocess.run(
        [sys.executable, str(script), task]
    )

    return result.returncode


def openai_api(task):
    """Run the checkpointed OpenAI API agent."""
    script = ROOT / "checkpoints" / "shopai_agent_API_WORKING.py"

    if not script.exists():
        print(f"ERROR: Missing {script}")
        return 1

    print()
    print("AI: OpenAI API")
    print("API cost: PAID - usage shown when finished")
    print()

    result = subprocess.run(
        [sys.executable, str(script), task]
    )

    return result.returncode


def local_qwen(task):
    """Run the existing offline Qwen agent."""
    script = ROOT / "qwen_agent.py"

    if not script.exists():
        print(f"ERROR: Missing {script}")
        return 1

    print()
    print("AI: Local Qwen")
    print("API cost: $0")
    print()

    result = subprocess.run(
        [sys.executable, str(script), task]
    )

    return result.returncode


def choose_ai():
    print()
    print("========================================")
    print("                ShopAI")
    print("========================================")
    print()
    print("  1. ChatGPT Web     DEFAULT   $0 API")
    print("  2. OpenAI API                PAID")
    print("  3. Local Qwen                OFFLINE")
    print()

    choice = input("AI [1]: ").strip()

    if not choice:
        choice = "1"

    return choice


def main():
    choice = choose_ai()

    print()

    if len(sys.argv) > 1:
        task = " ".join(sys.argv[1:]).strip()
    else:
        task = input("SHOPAI TASK: ").strip()

    if not task:
        print("No task supplied.")
        return 1

    if choice == "1":
        return chatgpt_web(task)

    if choice == "2":
        return openai_api(task)

    if choice == "3":
        return local_qwen(task)

    print(f"Unknown selection: {choice}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
