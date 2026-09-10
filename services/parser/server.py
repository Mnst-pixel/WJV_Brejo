"""One request at a time; fixed parse endpoint, private temporary files, no Django."""

import ctypes
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import threading

MAX_BYTES = 25 * 1024**2
MAX_OUTPUT = 1024**2
MIMES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "image/jpeg",
    "image/png",
    "text/plain",
}
TOKEN = ""
PARSE_SLOT = threading.BoundedSemaphore(1)


def isolated_parse(path, mime):
    with tempfile.TemporaryFile() as output:
        process = subprocess.Popen(
            [
                sys.executable,
                "-I",
                str(Path(__file__).with_name("child.py")),
                path,
                mime,
            ],
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.DEVNULL,
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": "/nonexistent"},
            start_new_session=True,
        )
        try:
            code = process.wait(timeout=95)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            raise ValueError("parser_timeout") from None
        finally:
            # Only signal a still-owned, unreaped child, never a recycled PID.
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
        if code:
            raise ValueError("parser_failed")
        output.seek(0)
        text = output.read(MAX_OUTPUT + 1)
        if len(text) > MAX_OUTPUT:
            raise ValueError("parser_output_limit")
        return text.decode("utf-8", errors="strict")


class Handler(BaseHTTPRequestHandler):
    server_version = "Kairós"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(30)

    def log_message(self, *args):
        pass

    def reply(self, code, payload):
        data = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)
        self.close_connection = True

    def do_GET(self):
        self.reply(
            200 if self.path == "/healthz" else 404,
            {"status": "ok" if self.path == "/healthz" else "not_found"},
        )

    def do_POST(self):
        if self.path != "/v1/parse":
            return self.reply(404, {"error": "not_found"})
        if not TOKEN or not hmac.compare_digest(
            self.headers.get("Authorization", ""), "Bearer " + TOKEN
        ):
            return self.reply(403, {"error": "forbidden"})
        mime = self.headers.get("Content-Type", "")
        digest = self.headers.get("X-Content-SHA256", "")
        length = self.headers.get("Content-Length", "")
        if (
            self.headers.get("Transfer-Encoding")
            or not length.isdecimal()
            or not 0 < int(length) <= MAX_BYTES
            or mime not in MIMES
            or not re.fullmatch(r"[a-f0-9]{64}", digest)
        ):
            return self.reply(400, {"error": "invalid_input"})
        if not PARSE_SLOT.acquire(blocking=False):
            return self.reply(429, {"error": "parser_busy"})
        try:
            with tempfile.NamedTemporaryFile(dir="/tmp") as document:
                remaining = int(length)
                calculated = hashlib.sha256()
                while remaining:
                    chunk = self.rfile.read(min(remaining, 65536))
                    if not chunk:
                        raise ValueError("incomplete_body")
                    document.write(chunk)
                    calculated.update(chunk)
                    remaining -= len(chunk)
                document.flush()
                if calculated.hexdigest() != digest:
                    raise ValueError("hash_mismatch")
                text = isolated_parse(document.name, mime)
            self.reply(200, {"text": text, "sha256": digest})
        except Exception:
            self.reply(422, {"error": "document_rejected"})
        finally:
            PARSE_SLOT.release()


def main():
    global TOKEN
    os.umask(0o077)
    TOKEN = os.environ.pop("PARSER_API_TOKEN", "")
    if len(TOKEN) < 32:
        raise SystemExit("parser token missing")
    # A parser exploit cannot inspect the server's credential via /proc/PID/environ.
    if ctypes.CDLL(None).prctl(4, 0, 0, 0, 0) != 0:
        raise SystemExit("process protection unavailable")
    server = ThreadingHTTPServer(("0.0.0.0", 8090), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
