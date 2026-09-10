import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    "backup_routine", Path(__file__).resolve().parents[1] / "backup-routine.py"
)
routine = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(routine)


class BackupRoutineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = dict(routine.DEFAULTS)
        for key in ("checkout", "backup_root", "state_dir", "snapshot_root"):
            self.config[key] = str(self.root / key)
            Path(self.config[key]).mkdir()
        self.config["secret_file"] = str(self.root / "secrets")
        self.config["offhost_config"] = str(self.root / "offhost.json")
        self.config["lock_file"] = str(self.root / "operation.lock")
        Path(self.config["secret_file"]).write_text(
            "BACKUP_ENCRYPTION_PASSPHRASE=" + "synthetic" * 5
        )
        Path(self.config["secret_file"]).chmod(0o600)
        self.name = "kairos-predeploy-20260910T000000Z-aabbccddeeff.tar.gz.enc"
        self.calls = []
        self.fail_script = None
        self.pass_seen = False
        # Windows has no POSIX permission bits; the Linux-only test verifies the real guard.
        if os.name == "nt":
            self.addCleanup(patch.stopall)
            patch.object(routine, "private_file", side_effect=Path).start()

    def archive(self, name, data=b"synthetic encrypted payload"):
        path = Path(self.config["backup_root"]) / name
        path.write_bytes(data)
        path.chmod(0o600)
        checksum = Path(str(path) + ".sha256")
        checksum.write_text(hashlib.sha256(data).hexdigest() + "  " + str(path) + "\n")
        checksum.chmod(0o600)
        return path

    def runner(self, command, log, timeout):
        script = Path(command[1]).name
        self.calls.append((script, command))
        if script == self.fail_script:
            raise routine.RoutineError("synthetic failure containing secret-do-not-log")
        if script == "backup-predeploy.sh":
            path = self.archive(self.name)
            return (
                "KAIROS_PREDEPLOY_BACKUP=PASS scope=archive_created archive="
                + str(path)
                + "\n"
            )
        if script == "verify-restore-isolated.sh":
            self.assertEqual(
                command[2], str(Path(self.config["backup_root"]) / self.name)
            )
            self.assertNotIn("--latest", command)
            self.assertEqual(Path(command[3]).read_text(), "synthetic" * 5)
            self.assertNotIn("synthetic", " ".join(command))
            self.pass_seen = True
            evidence = (
                Path(self.config["backup_root"])
                / "kairos-restore-20260910T000000Z-aabbccddeeff.evidence"
            )
            evidence.mkdir()
            (evidence / "result.txt").write_text(
                "\n".join(
                    (
                        "archive=" + self.name,
                        "postgres_restore=PASS",
                        "mariadb_restore=PASS",
                        "minio_restore_and_hashes=PASS",
                        "exit_status=0",
                        "cleanup_failed=0",
                    )
                )
            )
            (evidence / "result.txt").chmod(0o600)
            return (
                "KAIROS_RESTORE_ISOLATED=PASS scope=archived_data evidence="
                + str(evidence)
                + "\n"
            )
        if script == "backup-offhost.py":
            return '{"status":"PASS"}'
        return ""

    def execute(self):
        return routine.execute(self.config, self.runner, now=2_000_000_000)

    def test_exact_archive_restored_catalogued_and_absent_offhost_nonblocking(self):
        result = self.execute()
        self.assertEqual(
            (result["result"], result["local"], result["offhost"], result["no_touch"]),
            ("PASS", "PASS", "EXTERNAL_BLOCKER", "PASS"),
        )
        self.assertTrue(self.pass_seen)
        catalog = json.loads(
            (Path(self.config["state_dir"]) / "catalog.json").read_text()
        )
        self.assertEqual([row["archive"] for row in catalog["backups"]], [self.name])
        self.assertFalse(
            list(Path(self.config["state_dir"]).rglob("restore-passphrase"))
        )
        self.assertEqual(
            [row[0] for row in self.calls],
            [
                "vps-snapshot.sh",
                "backup-predeploy.sh",
                "verify-restore-isolated.sh",
                "vps-snapshot.sh",
                "compare-vps-snapshots.sh",
            ],
        )

    def test_backup_failure_no_restore_or_retention_and_after_snapshot(self):
        self.fail_script = "backup-predeploy.sh"
        result = self.execute()
        self.assertEqual(result["result"], "FAIL")
        self.assertEqual(result["failed_phase"], "backup")
        self.assertEqual(result["no_touch"], "PASS")
        self.assertNotIn("verify-restore-isolated.sh", [row[0] for row in self.calls])
        self.assertNotIn("secret-do-not-log", json.dumps(result))

    def test_restore_failure_preserves_archive_and_does_not_catalog(self):
        self.fail_script = "verify-restore-isolated.sh"
        result = self.execute()
        self.assertEqual(result["failed_phase"], "restore")
        self.assertTrue((Path(self.config["backup_root"]) / self.name).exists())
        self.assertFalse((Path(self.config["state_dir"]) / "catalog.json").exists())
        self.assertFalse(
            list(Path(self.config["state_dir"]).rglob("restore-passphrase"))
        )

    def test_corrupted_checksum_prevents_restore(self):
        def corrupt(command, log, timeout):
            output = self.runner(command, log, timeout)
            if Path(command[1]).name == "backup-predeploy.sh":
                (Path(self.config["backup_root"]) / self.name).write_bytes(b"corrupt")
            return output

        result = routine.execute(self.config, corrupt)
        self.assertEqual(result["result"], "FAIL")
        self.assertFalse(self.pass_seen)

    def test_offhost_failure_does_not_erase_local_restore_success(self):
        Path(self.config["offhost_config"]).write_text("{}")
        self.fail_script = "backup-offhost.py"
        result = self.execute()
        self.assertEqual(
            (result["result"], result["local"], result["offhost"]),
            ("FAIL", "PASS", "FAIL"),
        )
        self.assertTrue(result["alert"])

    def test_configured_offhost_success_clears_local_alert(self):
        Path(self.config["offhost_config"]).write_text("{}")
        result = self.execute()
        self.assertEqual(result["offhost"], "PASS")
        self.assertFalse(result["alert"])

    def test_no_touch_failure_cannot_catalog_or_retain(self):
        self.fail_script = "compare-vps-snapshots.sh"
        result = self.execute()
        self.assertEqual((result["result"], result["no_touch"]), ("FAIL", "FAIL"))
        self.assertFalse((Path(self.config["state_dir"]) / "catalog.json").exists())

    def catalog(self, count):
        entries = []
        for n in range(count):
            name = f"kairos-predeploy-20260910T000000Z-{n:012x}.tar.gz.enc"
            path = self.archive(name)
            entries.append(
                {
                    "managed_by": "kairos-backup-routine-v1",
                    "archive": name,
                    "restore": "PASS",
                    "sha256": routine.archive_hash(path),
                    "verified_at": n + 1,
                }
            )
        return {"version": 1, "backups": entries}

    def test_retention_only_managed_valid_old_pairs_and_minimum_preserved(self):
        catalog = self.catalog(5)
        historical = self.archive(self.name)
        kept, deleted = routine.retained_catalog(self.config, catalog, 2_000_000_000)
        self.assertEqual(len(kept["backups"]), 3)
        self.assertEqual(len(deleted), 2)
        self.assertTrue(historical.exists())
        self.assertFalse((Path(self.config["backup_root"]) / deleted[0]).exists())

    def test_retention_rejects_corrupt_protected_backup_before_any_deletion(self):
        catalog = self.catalog(5)
        (
            Path(self.config["backup_root"]) / catalog["backups"][-1]["archive"]
        ).write_bytes(b"corrupt")
        with self.assertRaises(routine.RoutineError):
            routine.retained_catalog(self.config, catalog, 2_000_000_000)
        self.assertTrue(
            (
                Path(self.config["backup_root"]) / catalog["backups"][0]["archive"]
            ).exists()
        )

    def test_retention_recovers_interrupted_pair_deletion(self):
        catalog = self.catalog(4)
        (Path(self.config["backup_root"]) / catalog["backups"][0]["archive"]).unlink()
        kept, deleted = routine.retained_catalog(self.config, catalog, 2_000_000_000)
        self.assertEqual(len(kept["backups"]), 3)
        self.assertEqual(len(deleted), 1)

    def test_retention_cannot_delete_uncatalogued_or_unmanaged_pair(self):
        catalog = self.catalog(4)
        catalog["backups"][0]["managed_by"] = "historic"
        kept, deleted = routine.retained_catalog(self.config, catalog, 2_000_000_000)
        self.assertEqual(len(kept["backups"]), 4)
        self.assertEqual(deleted, [])

    def test_passphrase_duplicate_rejected(self):
        path = Path(self.config["secret_file"])
        path.write_text(
            "BACKUP_ENCRYPTION_PASSPHRASE="
            + "x" * 40
            + "\nBACKUP_ENCRYPTION_PASSPHRASE="
            + "y" * 40
        )
        with self.assertRaises(routine.RoutineError):
            routine.read_passphrase(path)

    def test_checksum_foreign_path_rejected(self):
        path = self.archive(self.name)
        Path(str(path) + ".sha256").write_text(
            routine.archive_hash(path) + "  /unrelated/file"
        )
        with self.assertRaises(routine.RoutineError):
            routine.verify_archive(self.config["backup_root"], self.name)

    @unittest.skipUnless(
        os.name == "posix" and os.getuid() == 0,
        "requires Linux root ownership and flock",
    )
    def test_real_posix_permission_guard_and_exclusive_lock(self):
        path = Path(self.config["secret_file"])
        path.chmod(0o644)
        with self.assertRaises(routine.RoutineError):
            routine.private_file(path)
        path.chmod(0o600)
        with routine.operation_lock(self.config["lock_file"]):
            with self.assertRaises(routine.RoutineError):
                with routine.operation_lock(self.config["lock_file"]):
                    self.fail("overlapping lock accepted")
        with routine.operation_lock(self.config["lock_file"]):
            pass
        deploy_spec = importlib.util.spec_from_file_location("backup_deploy_lock_test", Path(__file__).resolve().parents[1] / "deploy-api-p0.py")
        deploy = importlib.util.module_from_spec(deploy_spec)
        deploy_spec.loader.exec_module(deploy)
        with routine.operation_lock(self.config["lock_file"]):
            with patch.object(deploy, "Path", return_value=Path(self.config["lock_file"])), patch.object(deploy, "release") as release:
                with self.assertRaises(BlockingIOError):
                    deploy.main()
                release.assert_not_called()

    def test_production_namespace_accepts_only_kairos_resolved_paths(self):
        redirects = {}

        class SyntheticPath(PurePosixPath):
            def resolve(self, strict=False):
                return PurePosixPath(redirects.get(str(self), str(self)))

        with patch.object(routine, "Path", SyntheticPath):
            routine.validate_operational_paths(dict(routine.DEFAULTS))
            for key, value in (("state_dir", "/srv/foreign-app"), ("backup_root", "/srv/kairos-other/backups"), ("checkout", "/opt/kairos/../foreign-app"), ("lock_file", "/tmp/foreign.lock")):
                with self.subTest(key=key), self.assertRaises(routine.RoutineError):
                    routine.validate_operational_paths(dict(routine.DEFAULTS, **{key: value}))
            redirects["/opt/kairos/runtime/backup"] = "/opt/foreign-app"
            with self.assertRaises(routine.RoutineError):
                routine.validate_operational_paths(dict(routine.DEFAULTS))
            redirects.clear()
            redirects["/opt/kairos"] = "/opt/foreign-app"
            with self.assertRaises(routine.RoutineError):
                routine.validate_operational_paths(dict(routine.DEFAULTS))

    def test_default_production_execution_rejects_test_paths_before_mutation(self):
        with patch.object(routine.os, "chmod") as chmod:
            with self.assertRaises(routine.RoutineError):
                routine.execute(self.config)
            chmod.assert_not_called()
        self.assertEqual(list(Path(self.config["state_dir"]).iterdir()), [])

    def test_config_rejects_unknown_keys_and_unsafe_retention(self):
        path = self.root / "config.json"
        for data in (
            {"unexpected": True},
            {"minimum_valid_backups": 1},
            {"retention_days": 0},
            {"state_dir": "relative"},
        ):
            path.write_text(json.dumps(data))
            path.chmod(0o600)
            with self.subTest(data=data), self.assertRaises(routine.RoutineError):
                routine.load_config(path)


if __name__ == "__main__":
    unittest.main()
