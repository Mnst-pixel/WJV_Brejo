"""Exercise the actual shell wrappers with a harmless executable in place of Docker."""
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "verify-restore-isolated.sh"


class RestoreDockerBoundaryTests(unittest.TestCase):
    def test_timeout_never_resolves_unwrapped_docker_from_path(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertNotRegex(source, r"\btimeout\s+\d+\s+docker\b")
        self.assertIn("if docker_timeout 5 exec", source)
        self.assertIn("quiet docker_timeout 300 start", source)

    @unittest.skipUnless(os.name == "posix" and shutil.which("bash"), "Requires Linux shell wrappers")
    def test_direct_and_timed_wrappers_strip_remote_context_and_secret_environment(self):
        source = SCRIPT.read_text(encoding="utf-8")
        functions = "\n".join(line for line in source.splitlines() if re.match(r"^docker(?:_timeout)?\(\)", line))
        self.assertEqual(len(functions.splitlines()), 2)
        with tempfile.TemporaryDirectory(prefix="kairos-docker-boundary-") as folder:
            probe = Path(folder) / "docker-probe"
            probe.write_text(f"#!{sys.executable}\nimport json,os,sys\nprint(json.dumps({{'args':sys.argv[1:], 'env':dict(os.environ)}}))\n")
            probe.chmod(0o755)
            program = functions.replace("/usr/bin/docker", shlex.quote(str(probe))) + "\ndocker version\ndocker_timeout 5 version\n"
            result = subprocess.run([shutil.which("bash"), "-c", program], capture_output=True, text=True, timeout=15,
                env={"PATH": folder, "DOCKER_HOST": "tcp://foreign.invalid:2375", "DOCKER_CONTEXT": "foreign",
                    "DOCKER_CONFIG": "/foreign", "AWS_SECRET_ACCESS_KEY": "synthetic-canary"})
            self.assertEqual(result.returncode, 0)
            records = [json.loads(line) for line in result.stdout.splitlines()]
            self.assertEqual(len(records), 2)
            for record in records:
                self.assertEqual(record["args"], ["--host", "unix:///var/run/docker.sock", "version"])
                self.assertEqual(record["env"], {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"})


if __name__ == "__main__":
    unittest.main()
