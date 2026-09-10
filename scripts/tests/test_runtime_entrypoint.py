"""Exercise runtime dispatch with harmless executable fixtures, no database."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / "apps/api/docker-entrypoint.sh"


class RuntimeEntrypointTests(unittest.TestCase):
    def invoke(self, mode):
        with tempfile.TemporaryDirectory(prefix="kairos-entrypoint-") as directory:
            root = Path(directory)
            log = root / "calls"
            for name in ("python", "gunicorn", "celery"):
                fixture = root / name
                fixture.write_text('#!/bin/sh\nprintf "%s\\n" "' + name + ' $*" >> "$KAIROS_TEST_LOG"\n')
                fixture.chmod(0o755)
            result = subprocess.run(
                [os.environ.get("KAIROS_TEST_BASH", "bash"), str(SCRIPT), mode],
                env={**os.environ, "PATH": str(root) + os.pathsep + os.environ["PATH"], "KAIROS_TEST_LOG": str(log)},
                text=True, capture_output=True,
            )
            return result.returncode, log.read_text() if log.exists() else ""

    def test_api_never_migrates_or_bootstraps(self):
        code, calls = self.invoke("api")
        self.assertEqual(code, 0)
        self.assertNotIn("collectstatic", calls)
        self.assertIn("gunicorn", calls)
        self.assertNotIn("migrate", calls)
        self.assertNotIn("bootstrap", calls)

    def test_worker_never_bootstraps(self):
        code, calls = self.invoke("worker")
        self.assertEqual(code, 0)
        self.assertIn("celery", calls)
        self.assertNotIn("python", calls)

    def test_migrations_require_explicit_mode(self):
        code, calls = self.invoke("migrate")
        self.assertEqual(code, 0)
        self.assertEqual(calls.strip(), "python manage.py migrate --noinput")

    def test_arbitrary_mode_refused(self):
        code, calls = self.invoke("bootstrap_admin")
        self.assertEqual(code, 64)
        self.assertEqual(calls, "")


if __name__ == "__main__":
    unittest.main()
