"""Optional mistral.rs inference adapter for ShopAI v1.

Only activated when SHOPAI_INFERENCE_BACKEND=mistralrs. Existing llama.cpp code
paths and file trees are not modified. No remote model downloads are allowed.
"""
import atexit
import ast
import http.client
import http.server
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

ROOT = Path.home() / "ShopAI"
MISTRAL_ROOT = Path("/mnt/shopai-data-new/AI-Tools/mistralrs/v0.9.5-cpu")
_selected_env = "SHOPAI_INFERENCE_BACKEND"
import shopai_inference_lifecycle_v1 as _shopai_life

_state = {"process": None, "key": None, "upstream_port": None,
          "proxy": None, "proxy_thread": None}


def is_selected():
    return os.environ.get(_selected_env) == "mistralrs"


def choose_backend():
    """First-level choice. Non-interactive launch stays on legacy backend."""
    preset = os.environ.get(_selected_env)
    if preset in ("llama", "mistralrs"):
        choice = preset
    elif not sys.stdin.isatty():
        choice = "llama"
    else:
        print("\n========================================")
        print(" SHOPAI INFERENCE BACKEND")
        print("========================================")
        print(" 1. llama.cpp   (existing/default)")
        print(" 2. mistral.rs  (growing CPU KV cache; experimental on ShopAI)")
        while True:
            try:
                ans = input("Backend [1]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\nUsing existing llama.cpp backend.")
                ans = "1"
            if ans in ("", "1", "llama", "llama.cpp"):
                choice = "llama"
                break
            if ans in ("2", "mistral", "mistral.rs", "mistralrs"):
                choice = "mistralrs"
                break
            print("Select 1 or 2.")
    os.environ[_selected_env] = choice
    print("Inference backend:", "mistral.rs" if choice == "mistralrs" else "llama.cpp")
    return choice


def _decode_literal_backends(path):
    """Read literals from the existing backend catalog without importing its agent."""
    result = {}
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError):
        return result
    for statement in tree.body:
        value = None
        if isinstance(statement, (ast.Assign, ast.AnnAssign)):
            targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
            if any(isinstance(t, ast.Name) and t.id == "BACKENDS" for t in targets):
                value = statement.value
        elif isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
            c = statement.value
            if (isinstance(c.func, ast.Attribute) and c.func.attr == "update"
                    and isinstance(c.func.value, ast.Name)
                    and c.func.value.id == "BACKENDS" and c.args):
                value = c.args[0]
        if not isinstance(value, ast.Dict):
            continue
        for key_node, val_node in zip(value.keys, value.values):
            try:
                key = ast.literal_eval(key_node)
                val = ast.literal_eval(val_node)
                if isinstance(key, str) and isinstance(val, dict):
                    result[key] = val
            except (ValueError, TypeError, SyntaxError, MemoryError):
                continue
    return result


def _resolve_spec(key, catalog):
    if not isinstance(key, str) or not key:
        raise ValueError("No model key passed from the existing ShopAI menu")
    if key in catalog:
        return dict(catalog[key])
    legacy = _decode_literal_backends(ROOT / "qwen_agent.py")
    if key in legacy:
        return dict(legacy[key])
    raise ValueError(f"Model '{key}' is not in a compatible local GGUF catalog")


def _model_files(spec):
    raw = str(spec.get("model", ""))
    if not raw.endswith(".gguf"):
        raise ValueError(f"No local GGUF file in model configuration: {raw!r}")
    first = Path(raw)
    if not first.is_file():
        raise FileNotFoundError(f"GGUF missing: {first}")
    split = re.search(r"-(\d{5})-of-(\d{5})\.gguf$", first.name)
    if not split:
        return str(first)
    total = int(split.group(2))
    if total < 2 or total > 200:
        raise ValueError("Unexpected GGUF split count")
    name_prefix = first.name[:split.start()]
    names = [first.with_name(f"{name_prefix}-{n:05d}-of-{total:05d}.gguf")
             for n in range(1, total + 1)]
    missing = [str(p) for p in names if not p.is_file()]
    if missing:
        raise FileNotFoundError("Missing GGUF split file(s): " + ", ".join(missing))
    return ";".join(str(p) for p in names)


def _executable():
    candidates = sorted(p for p in MISTRAL_ROOT.rglob("mistralrs")
                        if p.is_file() and os.access(p, os.X_OK))
    if not candidates:
        raise FileNotFoundError(f"No runnable mistralrs binary under {MISTRAL_ROOT}")
    return candidates[0]


def _unused_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _request_json(port, path="/v1/models"):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=2) as r:
        return json.load(r)


# SHOPAI_MISTRAL_STREAM_V2
class _ForwardProxy(http.server.BaseHTTPRequestHandler):
    """Local GGUF alias proxy. Stream from mistral.rs; return agent-compatible JSON.

    No response deadline during CPU prefill/generation. Emits live visible model
    output, heartbeat/progress, and repeat warnings to the existing ShopAI console.
    A non-streaming upstream error is passed through with its original status.
    """
    protocol_version = "HTTP/1.0"
    upstream_port = None

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        self._forward(False)

    def do_POST(self):
        self._forward(True)

    def _send_bytes(self, status, data, content_type="application/json; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)
        self.wfile.flush()

    @staticmethod
    def _cpu_ticks(pid):
        if not pid:
            return None
        try:
            raw = Path(f"/proc/{pid}/stat").read_text()
            after_comm = raw.rsplit(") ", 1)[1].split()
            # Field 14,15 (utime/stime) -> offset 11,12 after pid/comm.
            return int(after_comm[11]) + int(after_comm[12])
        except (OSError, ValueError, IndexError):
            return None

    @staticmethod
    def _save_partial(content, why):
        if not content:
            return
        path = ROOT / "logs" / f"mistralrs-partial-{time.time_ns()}.txt"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(f"INCOMPLETE RESPONSE: {why}\n\n{content}")
            print(f"\nmistral.rs: partial text preserved: {path}", flush=True)
        except OSError as exc:
            print(f"\nmistral.rs: unable to save partial: {exc}", flush=True)

    def _stream_to_complete_response(self, response):
        status = {"chunks": 0, "chars": 0, "last_token": time.monotonic(),
                  "started": time.monotonic(), "done": False, "seen": False}
        pid = None
        child = _state.get("process")
        if child is not None and child.poll() is None:
            pid = child.pid
        stop = threading.Event()
        ticks_before = [self._cpu_ticks(pid)]
        elapsed_last_alert = [0.0]

        def heartbeat():
            while not stop.wait(30):
                elapsed = time.monotonic() - status["started"]
                idle = time.monotonic() - status["last_token"]
                ticks = self._cpu_ticks(pid)
                old = ticks_before[0]
                ticks_before[0] = ticks
                cpu_delta = None if old is None or ticks is None else max(0, ticks - old)
                phase = "GENERATING" if status["seen"] else "PREFILL / AWAITING FIRST TOKEN"
                active = "CPU active" if cpu_delta and cpu_delta > 0 else "no CPU tick increase detected"
                print(f"\nmistral.rs {phase}: {elapsed:.0f}s elapsed; "
                      f"{status['chunks']} text chunks, {status['chars']} chars; "
                      f"last text {idle:.0f}s ago; {active}", flush=True)
                # Warn rather than destroying legitimate long CPU-only computations.
                if idle >= 600 and (cpu_delta is None or cpu_delta == 0):
                    if elapsed - elapsed_last_alert[0] >= 600:
                        elapsed_last_alert[0] = elapsed
                        print("mistral.rs WARNING: no text or measurable CPU progress "
                              "for 10+ minutes; check process or interrupt manually.",
                              flush=True)

        monitor = threading.Thread(target=heartbeat, name="mistral-progress", daemon=True)
        monitor.start()
        answer = []
        repeated = 0
        previous = None
        finish_reason = None
        usage = None
        emitted = False
        done = False
        try:
            while True:
                raw = response.readline()
                if not raw:
                    break
                line = raw.strip()
                if not line.startswith(b"data:"):
                    continue
                data = line[5:].strip()
                if data == b"[DONE]":
                    done = True
                    break
                if not data:
                    continue
                try:
                    event = json.loads(data)
                except (ValueError, UnicodeDecodeError):
                    raise ValueError("Invalid mistral.rs streaming JSON")
                if not isinstance(event, dict):
                    continue
                if event.get("error"):
                    raise ValueError("mistral.rs stream error: " + str(event["error"])[:350])
                if isinstance(event.get("usage"), dict):
                    usage = event["usage"]
                for choice in event.get("choices", []):
                    if not isinstance(choice, dict):
                        continue
                    if choice.get("finish_reason") is not None:
                        finish_reason = choice["finish_reason"]
                        done = True
                    delta = choice.get("delta") or {}
                    if not isinstance(delta, dict):
                        continue
                    content = delta.get("content")
                    if not isinstance(content, str) or not content:
                        continue
                    if not emitted:
                        print("\nmistral.rs LIVE MODEL OUTPUT (final answer follows):\n", flush=True)
                        emitted = True
                    sys.stdout.write(content)
                    sys.stdout.flush()
                    answer.append(content)
                    status["seen"] = True
                    status["chunks"] += 1
                    status["chars"] += len(content)
                    status["last_token"] = time.monotonic()
                    # SSE deltas usually represent token chunks, not guaranteed token IDs.
                    if content == previous and content.strip():
                        repeated += 1
                        if repeated == 5:
                            print("\n[mistral.rs repeated identical text chunk 5 times; "
                                  "warning only, no auto-kill]", flush=True)
                    else:
                        repeated = 1
                    previous = content
            if not done:
                raise http.client.IncompleteRead(b"", None)
            if emitted:
                print("\n[mistral.rs live generation finished]", flush=True)
            result = {"id": "shopai-mistral-stream", "object": "chat.completion",
                      "choices": [{"index": 0, "message": {
                          "role": "assistant", "content": "".join(answer)},
                          "finish_reason": finish_reason or "stop"}]}
            if usage is not None:
                result["usage"] = usage
            return result
        except Exception as exc:
            self._save_partial("".join(answer), f"{type(exc).__name__}: {exc}")
            raise
        finally:
            stop.set()
            monitor.join(timeout=1)

    def _forward(self, is_post):
        if not self.path.startswith("/v1/"):
            self.send_error(404)
            return
        upstream = None
        try:
            body = None
            should_stream = False
            if is_post:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 0 or length > 100 * 1024 * 1024:
                    self.send_error(413)
                    return
                body = self.rfile.read(length)
                if (self.path.startswith("/v1/chat/completions")
                        or self.path.startswith("/v1/completions")):
                    payload = json.loads(body)
                    if isinstance(payload, dict):
                        payload["model"] = "default"
                        # Retain existing client's JSON protocol; upstream streams.
                        if not payload.get("stream") and self.path.startswith("/v1/chat/completions"):
                            payload["stream"] = True
                            should_stream = True
                        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers = {}
            for k, v in self.headers.items():
                if k.lower() not in ("host", "connection", "transfer-encoding",
                                     "content-length", "accept-encoding"):
                    headers[k] = v
            if is_post:
                headers["Content-Length"] = str(len(body))
            if should_stream:
                headers["Accept"] = "text/event-stream"
            # No generation socket timer. Progress is monitored, not time-capped.
            upstream = http.client.HTTPConnection("127.0.0.1", self.upstream_port,
                                                  timeout=None if should_stream else 30)
            upstream.request("POST" if is_post else "GET", self.path,
                             body=body, headers=headers)
            # Many inference servers delay HTTP response headers until the
            # CPU finishes prompt processing. Monitor that prefill period too.
            headers_stop = threading.Event()
            header_monitor = None
            if should_stream:
                child = _state.get("process")
                pid = child.pid if child is not None and child.poll() is None else None
                prefill_started = time.monotonic()
                previous_ticks = [self._cpu_ticks(pid)]
                print("mistral.rs: prompt accepted by local proxy; awaiting "
                      "upstream response / first tokens (no 120s deadline).",
                      flush=True)

                def report_header_wait():
                    while not headers_stop.wait(30):
                        now_ticks = self._cpu_ticks(pid)
                        before = previous_ticks[0]
                        previous_ticks[0] = now_ticks
                        active = ("CPU active" if before is not None and
                                  now_ticks is not None and now_ticks > before
                                  else "no increase in CPU ticks detected")
                        print(f"mistral.rs PREFILL: "
                              f"{time.monotonic()-prefill_started:.0f}s "
                              f"awaiting first response; {active}; "
                              "no automatic termination.", flush=True)
                header_monitor = threading.Thread(
                    target=report_header_wait, name="mistral-prefill", daemon=True)
                header_monitor.start()
            try:
                response = upstream.getresponse()
            finally:
                headers_stop.set()
                if header_monitor is not None:
                    header_monitor.join(timeout=1)
            ct = response.getheader("Content-Type", "application/json")
            if response.status >= 400:
                raw = response.read()
                print(f"mistral.rs upstream HTTP {response.status}: "
                      f"{raw[:300].decode('utf-8', 'replace')}", flush=True)
                self._send_bytes(response.status, raw, ct)
                return
            if should_stream and "text/event-stream" in ct.lower():
                result = self._stream_to_complete_response(response)
                data = json.dumps(result, ensure_ascii=False).encode("utf-8")
                self._send_bytes(200, data)
                return
            # Compatible fallback if a backend responds with ordinary JSON.
            raw = response.read()
            self._send_bytes(response.status, raw, ct)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except (OSError, ValueError, http.client.HTTPException) as exc:
            print("mistral.rs proxy:", type(exc).__name__, str(exc)[:250],
                  file=sys.stderr, flush=True)
            try:
                data = json.dumps({"error": {"message":
                    f"Local mistral.rs proxy failure: {type(exc).__name__}: {exc}"}}).encode()
                self._send_bytes(502, data)
            except (BrokenPipeError, OSError):
                pass
        finally:
            if upstream is not None:
                upstream.close()


def _start_proxy(upstream_port):
    class Handler(_ForwardProxy):
        pass
    Handler.upstream_port = upstream_port
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, name="shopai-mistral-proxy", daemon=True)
    thread.start()
    return server, thread


def _stop_own_process():
    # SHOPAI_INFERENCE_LIFECYCLE_V1: release verified owned model before proxy.
    _shopai_life.stop_owned()
    proxy = _state.get("proxy")
    if proxy is not None:
        try:
            proxy.shutdown()
            proxy.server_close()
        except OSError:
            pass
    _state["proxy"] = None
    _state["proxy_thread"] = None
    p = _state.get("process")
    if p is not None and p.poll() is None:
        # Terminate only the child this ShopAI process created; never kill by name/port.
        try:
            p.terminate()
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            if p.poll() is None:
                p.kill()
                p.wait(timeout=5)
        except (OSError, ChildProcessError):
            pass
    _state["process"] = None
    _state["key"] = None
    _state["upstream_port"] = None
    os.environ.pop("SHOPAI_MISTRAL_PROXY_URL", None)


atexit.register(_stop_own_process)


def ensure_server(key, catalog):
    """Start independent CPU-only mistral.rs server for the selected GGUF."""
    if not is_selected():
        return True
    if (_state.get("key") == key and _state.get("process") is not None
            and _state["process"].poll() is None and _state.get("proxy") is not None):
        return True
    _stop_own_process()
    try:
        spec = _resolve_spec(key, catalog)
        gguf = _model_files(spec)
        binary = _executable()
        cmd = [str(binary), "serve", "--host", "127.0.0.1",
               "--port", str(_unused_port()), "--cpu", "--paged-attn", "off",
               "--prefix-cache-n", "0", "--token-source", "none",
               "-f", gguf]
        port = int(cmd[cmd.index("--port") + 1])
        if spec.get("projector"):
            projector = Path(str(spec["projector"]))
            if not projector.is_file():
                raise FileNotFoundError(f"Projector missing: {projector}")
            cmd.extend(["--mmproj", str(projector)])
        env = os.environ.copy()
        env["HF_HUB_OFFLINE"] = "1"
        env["HF_HUB_DISABLE_TELEMETRY"] = "1"
        env["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
        log = ROOT / "logs" / f"mistralrs-{key}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        print(f"mistral.rs CPU: loading {spec.get('label', key)}")
        print(f"Separate log: {log}")
        print("Offline mode: enforced. No fixed KV capacity or output cap added.")
        with log.open("a", encoding="utf-8") as handle:
            handle.write("\n=== ShopAI mistral.rs invocation ===\n" +
                         " ".join(repr(s) for s in cmd) + "\n")
            handle.flush()
            process = _shopai_life.launch_owned(cmd, stdin=subprocess.DEVNULL,
                                       stdout=handle, stderr=subprocess.STDOUT,
                                       env=env, start_new_session=True)
        _state["process"] = process
        _state["key"] = key
        _state["upstream_port"] = port
        attempts = 0
        while process.poll() is None:
            try:
                models = _request_json(port)
                if isinstance(models, dict) and "data" in models:
                    proxy, thread = _start_proxy(port)
                    _state["proxy"] = proxy
                    _state["proxy_thread"] = thread
                    proxy_url = f"http://127.0.0.1:{proxy.server_address[1]}"
                    os.environ["SHOPAI_MISTRAL_PROXY_URL"] = proxy_url
                    print(f"mistral.rs READY; local adapter: {proxy_url}")
                    return True
            except (urllib.error.URLError, TimeoutError, ValueError, ConnectionError, OSError):
                pass
            attempts += 1
            if attempts % 15 == 0:
                print(f"mistral.rs loading ... ({attempts}s); Ctrl+C interrupts; {log}")
            time.sleep(1)
        print(f"mistral.rs exited with code {process.returncode}. Inspect {log}")
    except KeyboardInterrupt:
        print("\nInterrupted mistral.rs loading; shutting down only owned process.")
    except Exception as exc:
        print(f"mistral.rs cannot load model {key!r}: {type(exc).__name__}: {exc}")
    _stop_own_process()
    return False


def configure_qwen_backend(original):
    """Change only the local inference URL; retain the existing ShopAI tools."""
    if not is_selected():
        return original
    proxy_url = os.environ.get("SHOPAI_MISTRAL_PROXY_URL")
    if not proxy_url:
        raise SystemExit("mistral.rs was chosen but its local proxy is not running")
    adapted = dict(original)
    adapted["url"] = proxy_url + "/v1/chat/completions"
    # The local proxy rewrites model aliases in outgoing JSON to 'default'.
    return adapted


def self_test():
    """Offline proxy protocol test with a fake server; loads no GGUF/model."""
    captured = {}
    class Fake(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            captured.update(body)
            data = json.dumps({"id": "ok", "choices": [{"message": {"content": "test"}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
    fake = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    thread = threading.Thread(target=fake.serve_forever, daemon=True)
    thread.start()
    proxy, pthread = _start_proxy(fake.server_address[1])
    try:
        payload = {"model": "unc_02", "messages": [{"role": "user", "content": "hello"}],
                   "tools": [{"type": "function", "function": {"name": "shopai_tool"}}]}
        req = urllib.request.Request(
            f"http://127.0.0.1:{proxy.server_address[1]}/v1/chat/completions",
            data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 200
            assert json.load(resp)["choices"][0]["message"]["content"] == "test"
        assert captured["model"] == "default" and captured["tools"] == payload["tools"]
        print("MISTRAL_PROXY_SELF_TEST: PASS (alias mapping, tool payload, local HTTP)")
    finally:
        proxy.shutdown(); proxy.server_close()
        fake.shutdown(); fake.server_close()


if __name__ == "__main__":
    self_test()
