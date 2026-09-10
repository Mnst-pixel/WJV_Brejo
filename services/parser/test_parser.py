"""HTTP contract and Linux parser sandbox tests; only temporary synthetic files."""

import hashlib
import http.client
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "parser_server", Path(__file__).with_name("server.py")
)
server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(server)


class ParserHTTPTests(unittest.TestCase):
    def setUp(self):
        server.TOKEN = "synthetic-token-" * 4
        self.httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)

    def call(self, body=b"study", path="/v1/parse", token=None, digest=None):
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.httpd.server_port, timeout=5
        )
        headers = {
            "Authorization": "Bearer " + (token if token is not None else server.TOKEN),
            "Content-Type": "text/plain",
            "X-Content-SHA256": digest or hashlib.sha256(body).hexdigest(),
        }
        try:
            connection.request("POST", path, body, headers)
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def test_rejects_missing_identity_and_arbitrary_endpoints(self):
        with patch.object(
            server, "isolated_parse", side_effect=AssertionError("must not parse")
        ):
            self.assertEqual(self.call(token="wrong", body=b"")[0], 403)
            self.assertEqual(
                self.call(path="/v1/parse?path=/etc/passwd", body=b"")[0], 404
            )
            self.assertEqual(self.call(path="/exec", body=b"")[0], 404)

    def test_hash_verified_and_single_request_limit(self):
        with server.PARSE_SLOT:
            self.assertEqual(self.call()[0], 429)

    @unittest.skipUnless(os.name == "posix", "service uses private Linux /tmp")
    def test_valid_http_parsing_and_hash_mismatch(self):
        with patch.object(server, "isolated_parse", return_value="texto") as parse:
            status, body = self.call()
            self.assertEqual(status, 200)
            self.assertIn(b"texto", body)
            self.assertTrue(parse.called)
            self.assertEqual(self.call(digest="0" * 64)[0], 422)


@unittest.skipUnless(os.name == "posix", "Linux resource/seccomp sandbox")
class LinuxSandboxTests(unittest.TestCase):
    def sandboxed_python(self, code):
        child = str(Path(__file__).with_name("child.py").resolve())
        return subprocess.run(
            [
                sys.executable,
                "-I",
                "-c",
                "import runpy; m=runpy.run_path("
                + repr(child)
                + "); m['sandbox'](); "
                + code,
            ],
            capture_output=True,
            timeout=15,
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
        )

    def test_fork_and_subprocess_cannot_escape_job(self):
        for code in (
            "import os; os.fork()",
            "import subprocess; subprocess.run(['/bin/true'], check=True)",
        ):
            with self.subTest(code=code):
                result = self.sandboxed_python(code)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(b"PermissionError", result.stderr)

    def test_clone_process_and_clone3_are_denied(self):
        code = "import ctypes,platform,errno,os; libc=ctypes.CDLL(None,use_errno=True); number=56 if platform.machine()=='x86_64' else 220; result=libc.syscall(number,17,0,0,0,0); assert result==-1 and ctypes.get_errno()==errno.EPERM; result=libc.syscall(435,0,0); assert result==-1 and ctypes.get_errno()==errno.ENOSYS; print('PROCESS_CREATION_DENIED')"
        result = self.sandboxed_python(code)
        self.assertEqual(
            result.returncode, 0, result.stderr.decode(errors="replace")[-300:]
        )
        self.assertIn(b"PROCESS_CREATION_DENIED", result.stdout)

    def test_threads_remain_allowed_and_io_uring_is_denied(self):
        code = "import threading,ctypes,errno; seen=[]; thread=threading.Thread(target=lambda:seen.append(1)); thread.start(); thread.join(); assert seen==[1]; libc=ctypes.CDLL(None,use_errno=True); result=libc.syscall(425,1,0); assert result==-1 and ctypes.get_errno()==errno.EPERM; print('THREAD_OK')"
        result = self.sandboxed_python(code)
        self.assertEqual(
            result.returncode, 0, result.stderr.decode(errors="replace")[-300:]
        )
        self.assertIn(b"THREAD_OK", result.stdout)

    def test_x32_syscall_bypass_denied(self):
        code = "import ctypes,errno,platform; libc=ctypes.CDLL(None,use_errno=True); result=libc.syscall(0x40000038,17,0,0,0,0); assert result==-1 and ctypes.get_errno()==errno.EPERM"
        result = self.sandboxed_python(code)
        self.assertEqual(
            result.returncode, 0, result.stderr.decode(errors="replace")[-300:]
        )

    def test_ocr_exec_replaces_child_with_no_credentials(self):
        from PIL import Image, ImageDraw

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.png"
            image = Image.new("RGB", (800, 200), "white")
            ImageDraw.Draw(image).text((30, 70), "KAIROS TESTE", fill="black")
            image.save(path)
            result = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    str(Path(__file__).with_name("child.py")),
                    str(path),
                    "image/png",
                ],
                capture_output=True,
                timeout=95,
                env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
            )
        self.assertEqual(
            result.returncode, 0, result.stderr.decode(errors="replace")[-300:]
        )
        self.assertLessEqual(len(result.stdout), 1024**2)

    def test_plaintext_output_overflow_rejected(self):
        with tempfile.NamedTemporaryFile() as document:
            document.write(b"a" * (1024**2 + 1))
            document.flush()
            result = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    str(Path(__file__).with_name("child.py")),
                    document.name,
                    "text/plain",
                ],
                capture_output=True,
                timeout=15,
                env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertLessEqual(len(result.stdout), 1024**2)

    def test_network_creation_denied(self):
        child = str(Path(__file__).with_name("child.py").resolve())
        source = (
            "import runpy,socket; m=runpy.run_path("
            + repr(child)
            + "); m['sandbox'](); socket.socket()"
        )
        result = subprocess.run(
            [sys.executable, "-I", "-c", source], capture_output=True, timeout=10
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"PermissionError", result.stderr)

    def test_plaintext_real_child_has_bounded_output(self):
        with tempfile.NamedTemporaryFile() as document:
            document.write(b"KAIROS isolated plaintext document\n")
            document.flush()
            result = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    str(Path(__file__).with_name("child.py")),
                    document.name,
                    "text/plain",
                ],
                capture_output=True,
                timeout=15,
                env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
            )
        self.assertEqual(
            result.returncode, 0, result.stderr.decode(errors="replace")[-200:]
        )
        self.assertIn(b"KAIROS isolated plaintext", result.stdout)


if __name__ == "__main__":
    unittest.main()
