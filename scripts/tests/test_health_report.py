import dataclasses
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "health-report.py"
SPEC = importlib.util.spec_from_file_location("kairos_health_test", SOURCE)
health = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = health
SPEC.loader.exec_module(health)


class HealthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.paths = health.Paths(**{field.name: base / field.name for field in dataclasses.fields(health.Paths)})
        for field in dataclasses.fields(health.Paths):
            if field.name != "pointer":
                getattr(self.paths, field.name).mkdir()
        self.safe = patch.object(health, "protected", side_effect=lambda path, **kwargs: Path(path))
        self.safe.start()
        self.addCleanup(self.safe.stop)
        self.now = 1900000000
        self.manifest = {"schema": 1, "commit": "a" * 40, "images": {name: "sha256:" + "b" * 64 for name in health.SERVICES}, "secrets_dir": "/opt/kairos/secrets/release-test", "configuration": {}}
        self.descriptor = self.paths.releases / "test"
        self.descriptor.mkdir()
        self.paths.pointer.write_text(str(self.descriptor))
        self.compose = {"services": {name: {"environment": {}} for name in health.SERVICES}}
        for name, text in zip(health.CONFIG_FILES, [json.dumps(self.compose), "safe config", json.dumps({"postgres": {"POSTGRES_PASSWORD": "source-name"}})]):
            path = self.paths.checkout / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
            self.manifest["configuration"][name] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.write_manifest()

    def write_manifest(self):
        (self.descriptor / "manifest.json").write_text(json.dumps(self.manifest))
        public = {"COMPOSE_PROJECT_NAME": "kairos", "KAIROS_SECRETS_DIR": self.manifest["secrets_dir"]}
        public.update({"KAIROS_IMAGE_" + key.upper(): image for key, image in self.manifest["images"].items()})
        (self.descriptor / "release.env").write_text("".join(f"{key}={item}\n" for key, item in sorted(public.items())))

    def git(self, command, **kwargs):
        self.assertEqual(command[0], "git")
        return self.manifest["commit"] if "rev-parse" in command else ""

    def backup(self):
        name = "kairos-predeploy-20300101T010101Z-abcdef123456.tar.gz.enc"
        archive = self.paths.backups / name
        archive.write_bytes(b"synthetic encrypted archive")
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        Path(str(archive) + ".sha256").write_text(digest + "  " + str(archive))
        evidence = self.paths.backups / "kairos-restore-20300101T010101Z-abcdef123456.evidence"
        evidence.mkdir()
        (evidence / "result.txt").write_text("\n".join(["archive=" + name, "postgres_restore=PASS", "mariadb_restore=PASS", "minio_restore_and_hashes=PASS", "exit_status=0", "cleanup_failed=0"]))
        row = {"archive": name, "sha256": digest, "restore_evidence": str(evidence), "verified_at": self.now - 60, "restore": "PASS", "managed_by": "kairos-backup-routine-v1"}
        status = {**row, "result": "PASS", "local": "PASS", "no_touch": "PASS", "offhost": "EXTERNAL_BLOCKER"}
        self.write_backup(status, [row])
        return status, row

    def write_backup(self, status, rows):
        (self.paths.backup_state / "status.json").write_text(json.dumps(status))
        (self.paths.backup_state / "catalog.json").write_text(json.dumps({"version": 1, "backups": rows}))

    def test_release_matches_head_hashes_and_public_env(self):
        self.assertEqual(health.active_release(self.paths, self.git)[0], self.manifest)

    def test_manifest_pointer_cannot_escape(self):
        self.paths.pointer.write_text(str(self.paths.backups))
        with self.assertRaisesRegex(health.HealthError, "namespace"):
            health.active_release(self.paths, self.git)

    def test_missing_pointer_has_no_fallback(self):
        self.paths.pointer.unlink()
        with self.assertRaises(FileNotFoundError):
            health.active_release(self.paths, self.git)

    def test_wrong_git_revision(self):
        with self.assertRaisesRegex(health.HealthError, "revision_drift"):
            health.active_release(self.paths, lambda command: "f" * 40)

    def test_dirty_git_checkout(self):
        with self.assertRaisesRegex(health.HealthError, "not_clean"):
            health.active_release(self.paths, lambda command: self.manifest["commit"] if "rev-parse" in command else " M file")

    def test_config_drift(self):
        (self.paths.checkout / health.CONFIG_FILES[1]).write_text("modified")
        with self.assertRaisesRegex(health.HealthError, "configuration_drift"):
            health.active_release(self.paths, self.git)

    def test_extra_service_rejected(self):
        self.manifest["images"]["foreign"] = "sha256:" + "b" * 64
        self.write_manifest()
        with self.assertRaisesRegex(health.HealthError, "manifest"):
            health.active_release(self.paths, self.git)

    def test_release_env_modified(self):
        (self.descriptor / "release.env").write_text("COMPOSE_PROJECT_NAME=foreign")
        with self.assertRaisesRegex(health.HealthError, "environment_drift"):
            health.active_release(self.paths, self.git)

    def docker(self, modified=None, names="PATH", extra=False):
        names_by_id = {f"{i:064x}": service for i, service in enumerate(sorted(health.SERVICES - {"migrate"}), 1)}
        def runner(command, **kwargs):
            if command[1] == "ps":
                return "\n".join(names_by_id)
            if command[1:3] == ["image", "inspect"]:
                return self.manifest["commit"]
            cid = command[-1]
            service = names_by_id[cid]
            if command[3] != health.PROJECTION:
                self.assertIn("split", command[3])
                return names
            row = {"id": cid, "name": "/kairos-" + service + "-1", "project": "kairos", "service": service, "managed": "release", "image": self.manifest["images"][service], "state": "running", "health": "healthy", "oom": False, "restarts": 0}
            if modified and service == "worker":
                row.update(modified)
            return json.dumps(row)
        return runner

    def test_containers_all_owned_and_pinned(self):
        results, trusted = health.containers(self.manifest, self.compose, {}, self.docker())
        self.assertEqual(set(trusted), health.SERVICES - {"migrate"})
        self.assertTrue(all(row["status"] == "PASS" for row in results.values()))

    def test_foreign_project_never_trusted(self):
        with self.assertRaisesRegex(health.HealthError, "ownership"):
            health.containers(self.manifest, self.compose, {}, self.docker({"project": "foreign"}))

    def test_wrong_name_even_same_project_rejected(self):
        with self.assertRaisesRegex(health.HealthError, "ownership"):
            health.containers(self.manifest, self.compose, {}, self.docker({"name": "/other-worker-1"}))

    def test_image_drift_excludes_service_from_exec(self):
        rows, trusted = health.containers(self.manifest, self.compose, {}, self.docker({"image": "sha256:" + "c" * 64}))
        self.assertEqual(rows["worker"]["status"], "FAIL")
        self.assertNotIn("worker", trusted)

    def test_shared_secret_scope_detected_without_value(self):
        rows, trusted = health.containers(self.manifest, self.compose, {}, self.docker(names="PATH\nDJANGO_SECRET_KEY"))
        self.assertFalse(rows["parser"]["checks"]["credential_scope"])
        self.assertEqual(trusted, {})

    def test_health_oom_and_crashloop_fail(self):
        rows, trusted = health.containers(self.manifest, self.compose, {}, self.docker({"health": "unhealthy", "oom": True, "restarts": 5}))
        self.assertNotIn("worker", trusted)
        self.assertFalse(rows["worker"]["checks"]["restart_budget"])

    def test_backup_restore_and_absent_offhost_pass_locally(self):
        self.backup()
        result = health.backup_health(self.paths, self.now)
        self.assertEqual((result["status"], result["offhost"]), ("PASS", "EXTERNAL_BLOCKER"))
        self.assertEqual(result["integrity"], "catalog_and_checksum_reference")

    def test_backup_stale(self):
        self.backup()
        with self.assertRaisesRegex(health.HealthError, "stale"):
            health.backup_health(self.paths, self.now + health.MAX_AGE)

    def test_backup_failed_despite_recent_archive(self):
        status, row = self.backup()
        self.write_backup({**status, "result": "FAIL"}, [row])
        with self.assertRaisesRegex(health.HealthError, "last_run_failed"):
            health.backup_health(self.paths, self.now)

    def test_running_backup_uses_previous_restored_set(self):
        _, row = self.backup()
        self.write_backup({"local": "RUNNING", "started_at": self.now - 30}, [row])
        self.assertTrue(health.backup_health(self.paths, self.now)["routine_running"])

    def test_running_backup_timeout(self):
        _, row = self.backup()
        self.write_backup({"local": "RUNNING", "started_at": self.now - 6 * 3600}, [row])
        with self.assertRaisesRegex(health.HealthError, "overdue"):
            health.backup_health(self.paths, self.now)

    def test_backup_checksum_reference_mismatch(self):
        _, row = self.backup()
        Path(str(self.paths.backups / row["archive"]) + ".sha256").write_text("0" * 64 + "  " + str(self.paths.backups / row["archive"]))
        with self.assertRaisesRegex(health.HealthError, "checksum_reference"):
            health.backup_health(self.paths, self.now)

    def test_backup_restore_failed_cleanup(self):
        _, row = self.backup()
        result = Path(row["restore_evidence"]) / "result.txt"
        result.write_text(result.read_text().replace("cleanup_failed=0", "cleanup_failed=1"))
        with self.assertRaisesRegex(health.HealthError, "proof_incomplete"):
            health.backup_health(self.paths, self.now)

    def test_backup_status_cannot_reference_another_set(self):
        status, row = self.backup()
        self.write_backup({**status, "sha256": "0" * 64}, [row])
        with self.assertRaisesRegex(health.HealthError, "catalog_mismatch"):
            health.backup_health(self.paths, self.now)

    def units(self, failed=None):
        def runner(command, **kwargs):
            if command[0] == "journalctl":
                self.assertIn("--output-fields=__REALTIME_TIMESTAMP,_SYSTEMD_UNIT,UNIT,PRIORITY", command)
                return json.dumps({"_SYSTEMD_UNIT": "kairos-backup.service", "PRIORITY": "3"})
            unit = command[2]
            return "LoadState=loaded\nActiveState=" + ("failed" if unit == failed else "active" if unit.endswith("timer") else "inactive") + "\nResult=success\nExecMainStatus=0\nUnitFileState=enabled\nNextElapseUSecMonotonic=5min"
        return runner

    def test_units_and_metadata_only_journal(self):
        result = health.unit_health(self.units())
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["error_events_24h_capped_1000"], 1)

    def test_inactive_timer_is_failure(self):
        self.assertEqual(health.unit_health(self.units("kairos-backup.timer"))["status"], "FAIL")

    def test_report_atomic_publication_and_retention_only_owned_pairs(self):
        old = self.now - 31 * 86400
        report = {"schema": 1, "managed_by": "kairos-health-v1", "timestamp": old, "status": "PASS", "alert_count": 0}
        health.publish(self.paths, report, old)
        old_pair = list(self.paths.reports.glob("health-*"))
        historical = self.paths.reports / "health-20200101T000000Z.status"
        historical.write_text("historic")
        foreign = self.paths.reports / "health-20200101T000000Z-abcdefabcdef.json"
        foreign.write_text('{"managed_by":"someone-else","timestamp":1}')
        report["timestamp"] = self.now
        health.publish(self.paths, report, self.now)
        self.assertTrue(all(not path.exists() for path in old_pair))
        self.assertTrue(historical.exists() and foreign.exists())
        self.assertEqual(json.loads((self.paths.reports / "latest.json").read_text()), report)
        self.assertIn("status=PASS", (self.paths.reports / "latest.status").read_text())

    def test_exceptions_do_not_disclose_secret_values(self):
        with patch.object(health, "active_release", side_effect=RuntimeError("synthetic-private-value")), patch.object(health, "unit_health", return_value={"status": "PASS"}):
            result = health.collect(self.paths, probe=lambda path: "PASS", now=self.now)
        self.assertEqual(result["status"], "FAIL")
        self.assertNotIn("synthetic-private-value", json.dumps(result))

    def test_http_redirect_denied_and_readiness_json_verified(self):
        class Response:
            status = 200
            body = b'{"status":"ok","checks":{"postgres":true,"redis":true}}'
            def read(self, limit):
                return self.body[:limit]
        class Connection:
            def __init__(self, host, timeout):
                self.host = host
            def request(self, *args, **kwargs):
                pass
            def getresponse(self):
                return Response()
            def close(self):
                pass
        self.assertEqual(health.http_probe("/api/health/ready", Connection), "PASS")
        Response.status = 302
        with self.assertRaises(health.HealthError):
            health.http_probe("/api/health/ready", Connection)
        Response.status = 200
        Response.body = b'{"status":"ok","checks":{"postgres":true,"redis":false}}'
        with self.assertRaises(health.HealthError):
            health.http_probe("/api/health/ready", Connection)


@unittest.skipUnless(sys.platform == "linux" and os.geteuid() == 0, "Linux root file ownership/lock fixture required")
class LinuxProtectionTests(unittest.TestCase):
    def test_permissions_symlink_and_exclusive_lock(self):
        with tempfile.TemporaryDirectory(dir="/root", prefix="kairos-health-test-") as temporary:
            root = Path(temporary)
            private = root / "private"
            private.write_text("synthetic")
            private.chmod(0o600)
            self.assertEqual(health.protected(private), private)
            private.chmod(0o644)
            with self.assertRaises(health.HealthError):
                health.protected(private)
            link = root / "link"
            link.symlink_to(private)
            with self.assertRaises(health.HealthError):
                health.protected(link, private=False)
            with health.lock(root / ".health.lock"):
                with self.assertRaises(BlockingIOError):
                    with health.lock(root / ".health.lock"):
                        pass


if __name__ == "__main__":
    unittest.main()
