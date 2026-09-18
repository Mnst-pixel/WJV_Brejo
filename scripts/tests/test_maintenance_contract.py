"""Exercise the HTTP verifier against loopback failures; real Caddy is a separate gate."""
import ast
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading

import pytest

ROOT = Path(__file__).resolve().parents[2]
TREE = ast.parse((ROOT / "scripts/verify-maintenance-isolated.py").read_text(encoding="utf-8"))
CONSTANTS = {node.targets[0].id: ast.literal_eval(node.value) for node in TREE.body
             if isinstance(node, ast.Assign)}
BODY = "Kairós está em manutenção. Os dados já salvos permanecem preservados. Tente novamente em alguns minutos."
HEADERS = {"Retry-After": "60", "Cache-Control": "private, no-store", "X-Kairos-Maintenance": "1",
           "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
           "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
           "Content-Type": "text/plain; charset=utf-8"}


def node_binary():
    candidate = shutil.which("node")
    if not candidate and os.name == "nt":
        candidate = str(Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe")
    if not candidate or not Path(candidate).is_file():
        pytest.skip("Node runtime required for actual HTTP verifier")
    return candidate


@pytest.mark.parametrize("fault", [None, "status", "body", "private-echo", "Server", "X-Powered-By", "Set-Cookie", "Location", *HEADERS])
def test_real_http_client_accepts_only_complete_maintenance_contract(fault):
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def respond(self):
            seen.append((self.command, self.path))
            self.send_response_only(200 if fault == "status" else 503)
            for key, value in HEADERS.items():
                if key != fault:
                    self.send_header(key, value)
            if fault in {"Server", "X-Powered-By", "Set-Cookie", "Location"}:
                self.send_header(fault, "canary")
            body = ("canary" if fault in {"body", "private-echo"} else BODY).encode()
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        do_GET = do_POST = do_HEAD = do_OPTIONS = do_PUT = do_DELETE = respond

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        code = CONSTANTS["CLIENT"].replace("http://127.0.0.1:80", f"http://127.0.0.1:{server.server_port}").replace("i<20", "i<1")
        value = subprocess.run([node_binary(), "-e", code], capture_output=True, timeout=15)
        result = json.loads(value.stdout)
        if fault is None:
            assert value.returncode == 0 and result == {"status": "PASS", "cases": 36}
            assert len(seen) == 37
            assert {method for method, _ in seen} == {"GET", "POST", "HEAD", "OPTIONS", "PUT", "DELETE"}
        else:
            assert value.returncode == 1 and result == {"status": "FAIL"}
        assert b"canary" not in value.stdout + value.stderr
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_maintenance_config_has_no_upstreams_or_dynamic_content():
    text = (ROOT / "infra/caddy/maintenance.Caddyfile").read_text(encoding="utf-8")
    assert 'respond "' + BODY + '" 503' in text
    assert "admin off" in text and "auto_https off" in text
    for forbidden in ["reverse_proxy", "file_server", "php_fastcgi", "handle", "route", "import", "{env.", "{$"]:
        assert forbidden not in text


def test_cleanup_template_is_complete_json_even_with_escaped_metadata():
    import re
    template = CONSTANTS["IDENTITY"]
    for value in [None, 'quote" newline\n', "kairos"]:
        decoded = json.loads(re.sub(r"\{\{json .*?\}\}", lambda _: json.dumps(value), template))
        assert decoded == dict.fromkeys(["name", "image", "project", "run"], value)
