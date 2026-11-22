#!/usr/bin/env python3
"""ShopAI v0.1 local commissioning bridge.

Dependency-free by design. This first version proves that the Linux host can expose
controlled local tools. It binds to localhost only and does not contact OpenAI yet.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

VERSION = "0.1.0"

def safe_path(root: Path, value: str) -> Path:
    target = (root / value).resolve()
    media_root = Path("/media/shopai").resolve()

    allowed = (
        target == root
        or root in target.parents
        or target == media_root
        or media_root in target.parents
    )

    if not allowed:
        raise ValueError("path escapes allowed ShopAI storage")

    return target

def run_command(command: str, cwd: Path) -> dict:
    proc = subprocess.run(
        ["/bin/bash", "-lc", command],
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
        check=False,
    )
    return {
        "returncode": proc.returncode,
        "stdout": proc.stdout[-20000:],
        "stderr": proc.stderr[-20000:],
    }


class Handler(BaseHTTPRequestHandler):
    server_version = f"ShopAIBridge/{VERSION}"

    def _send(self, status: int, payload: dict) -> None:
        data = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1_000_000:
            raise ValueError("request too large")
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8"))

    @property
    def root(self) -> Path:
        return self.server.shopai_root  # type: ignore[attr-defined]

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/health":
            self._send(200, {
                "ok": True,
                "version": VERSION,
                "hostname": os.uname().nodename,
                "root": str(self.root),
                "mode": "commissioning-localhost",
            })
            return
        self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        try:
            body = self._body()
            path = urlparse(self.path).path

            if path == "/tool/list":
                rel = str(body.get("path", "."))
                target = safe_path(self.root, rel)
                if not target.is_dir():
                    raise ValueError("not a directory")
                items = []
                for p in sorted(target.iterdir(), key=lambda x: x.name.lower()):
                    items.append({"name": p.name, "type": "dir" if p.is_dir() else "file"})
                self._send(200, {"path": rel, "items": items})
                return

            if path == "/tool/read":
                rel = str(body["path"])
                target = safe_path(self.root, rel)
                text = target.read_text(encoding="utf-8", errors="replace")
                self._send(200, {"path": rel, "content": text[:100000]})
                return

            if path == "/tool/write":
                rel = str(body["path"])
                content = str(body.get("content", ""))
                target = safe_path(self.root, rel)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                self._send(200, {"ok": True, "path": rel, "bytes": len(content.encode("utf-8"))})
                return

            if path == "/tool/run":
                command = str(body["command"])
                cwd_rel = str(body.get("cwd", "work"))
                cwd = safe_path(self.root, cwd_rel)
                cwd.mkdir(parents=True, exist_ok=True)
                result = run_command(command, cwd)
                self._send(200, result)
                return

            self._send(404, {"error": "not found"})
        except subprocess.TimeoutExpired:
            self._send(408, {"error": "command timed out"})
        except Exception as exc:
            self._send(400, {"error": str(exc)})

    def log_message(self, fmt: str, *args) -> None:
        log_dir = self.root / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / "bridge-http.log").open("a", encoding="utf-8") as fh:
            fh.write((fmt % args) + "\n")


def self_test(root: Path) -> int:
    root.mkdir(parents=True, exist_ok=True)
    (root / "work").mkdir(exist_ok=True)
    probe = root / "work" / ".bridge-self-test"
    probe.write_text("ok\n", encoding="utf-8")
    if probe.read_text(encoding="utf-8") != "ok\n":
        print("self-test failed: file round trip")
        return 1
    result = run_command("printf shopai", root / "work")
    if result["returncode"] != 0 or result["stdout"] != "shopai":
        print("self-test failed: shell tool")
        return 1
    probe.unlink(missing_ok=True)
    print("ShopAI bridge self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(Path.home() / "ShopAI"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    if args.self_test:
        return self_test(root)

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.shopai_root = root  # type: ignore[attr-defined]
    print(f"ShopAI bridge {VERSION} listening on http://{args.host}:{args.port}")
    print(f"Root: {root}")
    print("Commissioning mode: localhost only; OpenAI connection not enabled yet.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
