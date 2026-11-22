#!/usr/bin/env python3

import json
import pathlib
import re
import shutil
import subprocess
import sys
import termios
import time
import tty
import urllib.request

ROOT = pathlib.Path.home() / "ShopAI"
BRIDGE = "http://127.0.0.1:8765"

STATE_DIR = ROOT / "state"
CHAT_STATE = STATE_DIR / "chatgpt-conversation.json"

CHROME_USE = (
    shutil.which("chrome-use")
    or str(pathlib.Path.home() / ".local/bin" / "chrome-use")
)

TOOL_RE = re.compile(
    r"SHOPAI_TOOL\s*(\{.*?\})\s*END_SHOPAI_TOOL",
    re.DOTALL,
)

CODE_BLOCK_RE = re.compile(
    r"```([^\n`]*)\n(.*?)```",
    re.DOTALL,
)

SHELL_CODE_LANGUAGES = {
    "",
    "bash",
    "sh",
    "shell",
    "zsh",
}


def run_chrome(*args):
    def call(*cmd):
        return subprocess.run(
            [CHROME_USE, "--session", "shopai", *cmd],
            text=True,
            capture_output=True,
            timeout=30,
        )

    p = call(*args)

    if p.returncode == 0:
        return p.stdout

    first_error = p.stderr.strip() or p.stdout.strip()

    print(
        "Chrome connection lost - recovering...",
        file=sys.stderr,
    )

    # First try reconnecting the existing controlled browser.
    call("reconnect")
    time.sleep(2)

    p = call(*args)

    if p.returncode == 0:
        print("Chrome connection recovered.", file=sys.stderr)
        return p.stdout

    # If Chrome itself is not running, launch the controlled
    # ShopAI browser. The authenticated Chrome profile should
    # restore the existing ChatGPT login.
    launch = subprocess.run(
        [
            CHROME_USE,
            "--session",
            "shopai",
            "--profile",
            "Default",
            "--launch",
            "open",
            "https://chatgpt.com/",
        ],
        text=True,
        capture_output=True,
        timeout=30,
    )

    time.sleep(5)

    p = call(*args)

    if p.returncode == 0:
        print("Chrome launched and connected.", file=sys.stderr)
        return p.stdout

    error = p.stderr.strip() or p.stdout.strip()
    launch_error = launch.stderr.strip() or launch.stdout.strip()

    raise RuntimeError(
        "Chrome recovery failed: "
        + (
            error
            or launch_error
            or first_error
            or "unknown chrome-use error"
        )
    )



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
    # ChatGPT may still be rendering after conversation navigation.
    # Retry instead of failing on the first unsettled snapshot.
    last_output = ""

    for attempt in range(15):
        last_output = run_chrome("snapshot", "-i")

        # Match the stable textbox role instead of its changing label.
        matches = re.findall(
            r'\btextbox(?: "[^"]*")?\s+\[ref=@?(e\d+)\]',
            last_output,
        )

        if matches:
            return matches[-1]

        time.sleep(1)

    raise RuntimeError(
        "Could not find ChatGPT composer after 15 seconds"
    )

def choose_conversation_id():
    output = run_chrome(
        "site",
        "chatgpt/conversations",
        "--json",
    )

    start = output.find("{")

    if start == -1:
        raise RuntimeError("No JSON returned by conversations adapter")

    data = json.loads(output[start:])
    result = data.get("data", {}).get("result", {})
    conversations = result.get("conversations", [])

    conversations = [
        c for c in conversations
        if not c.get("archived", False)
    ][:5]

    if not conversations:
        raise RuntimeError("No ChatGPT conversations found")

    print()
    print("Choose ChatGPT conversation (5 sec):")
    print()

    for i, conversation in enumerate(conversations, 1):
        title = conversation.get("title") or "Untitled"

        if i == 1:
            print(f"  {i}. {title}  [DEFAULT]")
        else:
            print(f"  {i}. {title}")

    print()

    # Timed input: timeout or Enter selects newest conversation.
    import select

    print("Choice [1]: ", end="", flush=True)

    ready, _, _ = select.select([sys.stdin], [], [], 5)

    if ready:
        choice = sys.stdin.readline().strip()
    else:
        choice = ""
        print()

    if not choice:
        index = 0
    else:
        try:
            index = int(choice) - 1
        except ValueError:
            index = 0

        if index < 0 or index >= len(conversations):
            index = 0

    selected = conversations[index]

    conversation_id = selected.get("id")
    url = selected.get("url")

    if not conversation_id or not url:
        raise RuntimeError("Selected conversation is missing ID or URL")

    print(
        "Using:",
        selected.get("title") or "Untitled",
        file=sys.stderr,
    )

    run_chrome("open", url)

    # Give ChatGPT a moment to load the selected conversation.
    time.sleep(2)

    return conversation_id



def save_conversation_id(conversation_id):
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    CHAT_STATE.write_text(
        json.dumps(
            {
                "conversation_id": conversation_id,
            },
            indent=2,
        )
        + "\n"
    )


def load_conversation_id():
    try:
        data = json.loads(CHAT_STATE.read_text())
        conversation_id = data.get("conversation_id")

        if conversation_id:
            return str(conversation_id)

    except Exception:
        pass

    return None


def open_conversation(conversation_id):
    run_chrome(
        "open",
        f"https://chatgpt.com/c/{conversation_id}",
    )

    time.sleep(2)


def get_conversation_id(force_choose=False):
    if not force_choose:
        saved = load_conversation_id()

        if saved:
            try:
                open_conversation(saved)
                print(
                    f"Using saved ChatGPT conversation: {saved}",
                    file=sys.stderr,
                )
                return saved

            except Exception:
                # Saved conversation became invalid/unavailable.
                # Fall through to chooser.
                pass

    conversation_id = choose_conversation_id()

    if not conversation_id:
        raise RuntimeError(
            "Could not determine ChatGPT conversation ID"
        )

    save_conversation_id(conversation_id)

    return conversation_id


def choose_and_save_conversation():
    conversation_id = choose_conversation_id()

    if not conversation_id:
        raise RuntimeError(
            "Could not determine ChatGPT conversation ID"
        )

    save_conversation_id(conversation_id)

    print()
    print("ChatGPT conversation saved.")
    print(f"Conversation ID: {conversation_id}")

    return conversation_id

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



def extract_shell_code_blocks(text):
    """Return executable shell blocks, excluding other code types."""
    blocks = []

    for language, body in CODE_BLOCK_RE.findall(text):
        language = language.strip().lower()

        if language in SHELL_CODE_LANGUAGES and body.strip():
            blocks.append(body.rstrip() + "\n")

    return blocks


def read_relay_key(prompt):
    """Read one terminal key without requiring Enter."""
    if not sys.stdin.isatty():
        raise RuntimeError("Space relay requires an interactive terminal")

    fd = sys.stdin.fileno()
    original = termios.tcgetattr(fd)

    print(prompt, end="", flush=True)

    try:
        # Discard buffered key-repeat characters before the next step.
        termios.tcflush(fd, termios.TCIFLUSH)
        tty.setcbreak(fd)
        key = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, original)

    if key == " ":
        print("<SPACE>")
    else:
        print(key)

    return key


def make_terminal_result(result):
    return (
        "SHOPAI_TERMINAL_RESULT\n"
        + json.dumps(result, ensure_ascii=False)
        + "\nEND_SHOPAI_TERMINAL_RESULT\n\n"
        + "Review the actual terminal result. If another command is needed, "
          "reply with exactly one fenced bash code block. Otherwise give the "
          "final answer normally. Do not claim success unless the result proves it."
    )


def run_space_relay():
    """Three-space human approval relay for one shell block at a time."""
    conversation_id = get_conversation_id()
    phase = "capture"
    captured = None
    source_response = None

    print()
    print("=" * 70)
    print("SHOPAI CHROME CODE RELAY")
    print("=" * 70)
    print("Space 1: capture one shell code block from ChatGPT")
    print("Space 2: stage and display it without running")
    print("Space 3: run it and return the result to ChatGPT")
    print("Q:       leave relay mode")
    print()

    while True:
        labels = {
            "capture": "CAPTURE",
            "stage": "STAGE",
            "run": "RUN",
        }
        key = read_relay_key(
            f"[{labels[phase]}] Press Space, or Q to quit: "
        )

        if key.lower() == "q":
            print("Chrome code relay stopped.")
            return 0

        if key != " ":
            print("Ignored. Press Space for the displayed step, or Q to quit.")
            continue

        if phase == "capture":
            data = get_conversation(conversation_id)
            response = extract_latest_assistant(data)

            if not response:
                print("No ChatGPT response was found. Nothing captured.")
                continue

            blocks = extract_shell_code_blocks(response)

            if not blocks:
                print("No shell code block was found. Nothing captured.")
                continue

            if len(blocks) != 1:
                print(
                    "More than one shell code block was found. "
                    "Ask ChatGPT for exactly one block."
                )
                continue

            captured = blocks[0]
            source_response = response
            phase = "stage"

            print(
                f"Captured {len(captured.encode('utf-8'))} bytes "
                f"in {len(captured.splitlines())} lines."
            )
            print("Not staged and not run.")
            continue

        if phase == "stage":
            print()
            print("-" * 70)
            print("STAGED SHELL CODE — NOT RUN")
            print("-" * 70)
            print(captured, end="")
            print("-" * 70)
            print("Review the exact block above.")
            print()
            phase = "run"
            continue

        print("Running the exact staged block...")

        result = bridge_post(
            "/tool/run",
            {
                "command": captured,
                "cwd": "work",
            },
        )

        print()
        print("SHOPAI TERMINAL RESULT")
        print(f"Exit status: {result.get('returncode', 'unknown')}")

        stdout = str(result.get("stdout", ""))
        stderr = str(result.get("stderr", ""))

        if stdout:
            print("\nSTDOUT:")
            print(stdout, end="" if stdout.endswith("\n") else "\n")

        if stderr:
            print("\nSTDERR:")
            print(stderr, end="" if stderr.endswith("\n") else "\n")

        previous = source_response
        send_message(make_terminal_result(result))
        print("Result returned to ChatGPT. Waiting for its response...")

        response = wait_for_new_response(
            conversation_id,
            previous,
        )

        print()
        print("ChatGPT>")
        print(response)
        print()

        captured = None
        source_response = None
        phase = "capture"


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "--choose-chat":
        choose_and_save_conversation()
        return 0

    if len(sys.argv) >= 2 and sys.argv[1] == "--space-relay":
        return run_space_relay()

    if len(sys.argv) < 2:
        print(
            f'Usage: {sys.argv[0]} "task"',
            file=sys.stderr,
        )
        return 2

    task = " ".join(sys.argv[1:])

    conversation_id = get_conversation_id()

    send_message(make_initial_prompt(task))

    time.sleep(2)

    after_send = get_conversation(conversation_id)
    previous = extract_latest_assistant(after_send)

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
