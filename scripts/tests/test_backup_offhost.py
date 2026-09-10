from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    "backup_offhost", Path(__file__).resolve().parents[1] / "backup-offhost.py"
)
offhost = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(offhost)


class OffhostTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config_path = self.root / "offhost.json"
        self.config = {
            "endpoint": "https://objects.example.invalid",
            "bucket": "kairos-test",
            "access_key": "SYNTHETIC",
            "secret_key": "synthetic-not-production",
            "region": "us-east-1",
            "prefix": "kairos/backups/",
            "retention_days": 90,
        }
        self.archive = (
            self.root / "kairos-predeploy-20260910T000000Z-aabbccddeeff.tar.gz.enc"
        )
        self.archive.write_bytes(b"synthetic encrypted archive")
        self.archive.chmod(0o600)
        if os.name == "nt":
            self.addCleanup(patch.stopall)
            patch.object(offhost.stat, "S_IMODE", return_value=0o600).start()

    def load(self, data):
        self.config_path.write_text(json.dumps(data))
        self.config_path.chmod(0o600)
        return offhost.load_config(self.config_path)

    def test_absent_or_blank_destination_external_blocker(self):
        self.assertIsNone(offhost.load_config(self.config_path))
        self.assertIsNone(
            self.load(
                {"endpoint": "", "bucket": "", "access_key": "", "secret_key": ""}
            )
        )

    def test_partial_or_unsafe_configuration_rejected(self):
        cases = [{"endpoint": "https://objects.example.invalid"}]
        for change in (
            {"endpoint": "http://objects.example.invalid"},
            {"endpoint": "https://user:password@objects.example.invalid"},
            {"endpoint": "https://objects.example.invalid/?redirect=x"},
            {"prefix": "other-project/"},
            {"bucket": "../other"},
            {"retention_days": 0},
            {"secret_key": "secret\nheader"},
        ):
            cases.append(self.config | change)
        for data in cases:
            with (
                self.subTest(
                    data={
                        key: value
                        for key, value in data.items()
                        if key not in {"secret_key", "access_key"}
                    }
                ),
                self.assertRaises(offhost.OffhostError),
            ):
                self.load(data)

    def test_upload_stream_checksum_and_remote_head_contract(self):
        calls = []
        expected = hashlib.sha256(self.archive.read_bytes()).hexdigest()

        def transport(config, method, key, digest, **kwargs):
            calls.append((method, key, digest))
            if method == "HEAD":
                return {
                    "content-length": str(self.archive.stat().st_size),
                    "x-amz-meta-sha256": expected,
                }
            body = kwargs["body"]
            raw = body.read() if hasattr(body, "read") else body
            self.assertEqual(hashlib.sha256(raw).hexdigest(), digest)
            self.assertEqual(len(raw), kwargs["size"])
            return {}

        report = offhost.upload(self.config, self.archive, transport)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["offsite_restore"], "NOT_VERIFIED")
        self.assertEqual(report["retention"], "BUCKET_LIFECYCLE_REQUIRED")
        self.assertEqual([item[0] for item in calls], ["PUT", "HEAD", "PUT"])
        self.assertTrue(calls[2][1].endswith(".tar.gz.enc.sha256"))

    def test_remote_size_or_hash_mismatch_fails(self):
        for headers in ({}, {"content-length": "1", "x-amz-meta-sha256": "wrong"}):
            with self.subTest(headers=headers), self.assertRaises(offhost.OffhostError):
                offhost.upload(
                    self.config, self.archive, lambda *args, **kwargs: headers
                )

    def test_redirect_not_followed_or_body_logged(self):
        class Response:
            status = 307

            def getheaders(self):
                return [("Location", "https://attacker.example.invalid")]

        class Connection:
            instances = []

            def __init__(self, *args, **kwargs):
                self.instances.append(self)
                self.closed = False

            def request(self, *args, **kwargs):
                self.arguments = args

            def getresponse(self):
                return Response()

            def close(self):
                self.closed = True

        with self.assertRaises(offhost.OffhostError):
            offhost.request(
                self.config,
                "HEAD",
                "kairos/backups/test",
                hashlib.sha256(b"").hexdigest(),
                connection_factory=Connection,
            )
        self.assertEqual(len(Connection.instances), 1)
        self.assertTrue(Connection.instances[0].closed)

    def test_payload_checksum_header_present_and_signed(self):
        observed = {}

        class Response:
            status = 200

            def getheaders(self):
                return []

        class Connection:
            def __init__(self, *args, **kwargs):
                pass

            def request(self, method, path, body, headers):
                observed.update(headers)

            def getresponse(self):
                return Response()

            def close(self):
                pass

        offhost.request(
            self.config,
            "PUT",
            "kairos/backups/test",
            hashlib.sha256(b"abc").hexdigest(),
            body=b"abc",
            size=3,
            connection_factory=Connection,
        )
        self.assertEqual(
            observed["x-amz-checksum-sha256"],
            "ungWv48Bz+pBQUDeXa4iI7ADYaOWF3qctBD/YfIAFa0=",
        )
        self.assertIn(
            "x-amz-checksum-sha256",
            observed["authorization"].split("SignedHeaders=", 1)[1],
        )

    def test_signing_deterministic_and_changes_with_method_body_and_secret(self):
        now = datetime(2026, 9, 10, tzinfo=timezone.utc)
        args = (
            self.config,
            "PUT",
            "/kairos-test/kairos/backups/test",
            hashlib.sha256(b"abc").hexdigest(),
        )
        signed = offhost.signed_headers(*args, now=now)
        self.assertEqual(signed, offhost.signed_headers(*args, now=now))
        self.assertNotIn(self.config["secret_key"], json.dumps(signed))
        changed = offhost.signed_headers(self.config, "HEAD", args[2], args[3], now=now)
        self.assertNotEqual(signed["authorization"], changed["authorization"])

    def test_signature_matches_independent_botocore_golden_vector(self):
        # Generated independently with botocore S3SigV4Auth on 2026-09-10.
        # Synthetic credential, frozen UTC clock, body b'abc', Content-Length 3.
        headers = offhost.signed_headers(
            self.config,
            "PUT",
            "/kairos-test/kairos/backups/test",
            hashlib.sha256(b"abc").hexdigest(),
            {"content-length": "3"},
            datetime(2026, 9, 10, tzinfo=timezone.utc),
        )
        self.assertEqual(
            headers["authorization"].split("Signature=")[1],
            "d7f10d75d2079afcea6e22dd8c59025cc5691218b3e8333850c58ce3953dde3e",
        )


if __name__ == "__main__":
    unittest.main()
