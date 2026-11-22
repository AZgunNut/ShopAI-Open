#!/usr/bin/env python3

import json
import pathlib
import re
import shutil
import subprocess
import sys
import time
import urllib.request

ROOT = pathlib.Path.home() / "ShopAI"
BRIDGE = "http://127.0.0.1:8765"

CHROME_USE = (
    shutil.which("chrome-use")
    or str(pathlib.Path.home() / ".local/bin" / "chrome-use")
)

TOOL_RE = re.compile(
    r"SHOPAI_TOOL\s*(\{.*?\})\s*END_SHOPAI_TOOL",
    re.DOTALL,
)


def run_chrome(*args):
    p = subprocess.run(
        [CHROME_USE, *args],
        text=True,
        capture_output=True,
    )

    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip() or p.stdout.strip())

    return p.stdout


def bridge_post(endpoint, body):
    data = json.dumps(body).encode("utf-8")

    req = urllib.request.Request(
        BRIDGE + endpoint,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=130) as response:
        return json.loads(response.read().decode("utf-8"))


def get_composer_ref():
    output = run_chrome("snapshot", "-i")

    match = re.search(
        r'textbox "Chat with ChatGPT" \[ref=(e\d+)\]',
        output,
    )

    if not match:
        raise RuntimeError("Could not find ChatGPT composer")

    return match.group(1)


def get_conversation_id():
    output = run_chrome("tabs")

    match = re.search(
        r"chatgpt\.com/c/([0-9a-fA-F-]+)",
        output,
    )

    if not match:
        output = run_chrome("snapshot", "-i")
        match = re.search(
            r"chatgpt\.com/c/([0-9a-fA-F-]+)",
            output,
        )

    if not match:
        raise RuntimeError("Could not determine ChatGPT conversation ID")

    return match.group(1)


def get_conversation(conversation_id):
    output = run_chrome(
        "site",
        "chatgpt/conversation",
        conversation_id,
        "--json",
    )

    start = output.find("{")

    if start == -1:
        raise RuntimeError("No JSON returned by ChatGPT adapter")

    return json.loads(output[start:])


def extract_latest_assistant(data):
    result = data.get("data", {}).get("result", data)
    found = []

    def walk(obj):
        if isinstance(obj, dict):
            role = obj.get("role")

            if role == "assistant":
                for key in ("text", "content", "message"):
                    value = obj.get(key)

                    if isinstance(value, str) and value.strip():
                        found.append(value.strip())

            author = obj.get("author")

            if isinstance(author, dict) and author.get("role") == "assistant":
                content = obj.get("content", {})

                if isinstance(content, dict):
                    parts = content.get("parts")

                    if isinstance(parts, list):
                        text = "\n".join(
                            x for x in parts if isinstance(x, str)
                        ).strip()

                        if text:
                            found.append(text)

            for value in obj.values():
                walk(value)

        elif isinstance(obj, list):
            for value in obj:
                walk(value)

    walk(result)

    return found[-1] if found else None


def send_message(text):
    composer = get_composer_ref()
    run_chrome("fill", composer, text)
    run_chrome("press", "Enter", "--selector", composer)


def wait_for_new_response(conversation_id, previous, timeout=180):
    deadline = time.time() + timeout

    while time.time() < deadline:
        time.sleep(2)

        try:
            current = get_conversation(conversation_id)
            latest = extract_latest_assistant(current)

            if latest and latest != previous:
                # Give a short response time to settle.
                time.sleep(2)

                current2 = get_conversation(conversation_id)
                latest2 = extract_latest_assistant(current2)

                if latest2:
                    return latest2

                return latest

        except Exception:
            pass

    raise RuntimeError("Timed out waiting for ChatGPT response")


def parse_tool_request(text):
    match = TOOL_RE.search(text)

    if not match:
        return None

    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid SHOPAI tool JSON: {exc}")


def execute_tool(request):
    tool = request.get("tool")
    args = request.get("args", {})

    if tool == "list":
        return bridge_post("/tool/list", args)

    if tool == "read":
        return bridge_post("/tool/read", args)

    if tool == "write":
        print()
        print("=" * 60)
        print("CHATGPT REQUESTED WRITE")
        print(json.dumps(args, indent=2))
        print("=" * 60)

        answer = input("Execute? [y/N]: ").strip().lower()

        if answer != "y":
            return {
                "ok": False,
                "denied": True,
                "message": "User denied write request.",
            }

        return bridge_post("/tool/write", args)

    if tool == "run":
        print()
        print("=" * 60)
        print("CHATGPT REQUESTED COMMAND")
        print(json.dumps(args, indent=2))
        print("=" * 60)

        answer = input("Execute? [y/N]: ").strip().lower()

        if answer != "y":
            return {
                "ok": False,
                "denied": True,
                "message": "User denied command request.",
            }

        return bridge_post("/tool/run", args)

    return {
        "ok": False,
        "error": f"Unknown ShopAI tool: {tool}",
    }


def make_initial_prompt(task):
    return f"""You are connected to ShopAI on my local Linux workstation.

You may request local ShopAI tools when they are useful.

Available tools:

1. list
   args: {{"path":"."}}

2. read
   args: {{"path":"relative/or/allowed/path"}}

3. write
   args: {{"path":"relative/or/allowed/path","content":"text"}}

4. run
   args: {{"command":"shell command","cwd":"work"}}

LIST and READ are automatically allowed.

WRITE and RUN require my approval at the ShopAI terminal before
they execute.

To request EXACTLY ONE tool operation, your entire response must be:

SHOPAI_TOOL
{{"tool":"read","args":{{"path":"PROGRESS.txt"}}}}
END_SHOPAI_TOOL

Use valid JSON with double quotes.

Do not put markdown fences around a tool request.
Do not add explanation before or after a tool request.
Request only one tool operation at a time.

After ShopAI returns the tool result, either request another tool
operation using the same format or give the final answer normally.

USER TASK:
{task}"""


def make_tool_result(result):
    return (
        "SHOPAI_TOOL_RESULT\n"
        + json.dumps(result, ensure_ascii=False)
        + "\nEND_SHOPAI_TOOL_RESULT\n\n"
        + "Continue the task. Request another ShopAI tool if needed, "
          "otherwise give the final answer."
    )


def main():
    if len(sys.argv) < 2:
        print(
            f'Usage: {sys.argv[0]} "task"',
            file=sys.stderr,
        )
        return 2

    task = " ".join(sys.argv[1:])

    conversation_id = get_conversation_id()

    before = get_conversation(conversation_id)
    previous = extract_latest_assistant(before)

    send_message(make_initial_prompt(task))

    print("Sent. Waiting for ChatGPT...", file=sys.stderr)

    max_tool_rounds = 25
    tool_rounds = 0

    while True:
        response = wait_for_new_response(
            conversation_id,
            previous,
        )

        request = parse_tool_request(response)

        if request is None:
            print(response)
            print()
            print(f"Tool rounds: {tool_rounds}")
            print("API cost: $0")
            return 0

        tool_rounds += 1

        if tool_rounds > max_tool_rounds:
            raise RuntimeError("Maximum ShopAI tool rounds reached")

        print()
        print(f"Tool request #{tool_rounds}: {request.get('tool')}")

        result = execute_tool(request)

        previous = response

        send_message(make_tool_result(result))

        print("Result returned to ChatGPT. Waiting...", file=sys.stderr)


if __name__ == "__main__":
    try:
        raise SystemExit(main())

    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        raise SystemExit(130)

    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
