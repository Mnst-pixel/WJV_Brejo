import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("restore_migration_probe", Path(__file__).resolve().parents[1] / "restore-migration-probe.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class RestoreMigrationProbeTests(unittest.TestCase):
    def test_live_or_incomplete_target_refused(self):
        valid = {"POSTGRES_DB": "kairos_restore", "POSTGRES_USER": "kairos_restore", "POSTGRES_HOST": "127.0.0.1", "KAIROS_RESTORE_RUN_ID": "20260910T220000Z-aabbccddeeff"}
        probe.validate_target(valid)
        for key in valid:
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                probe.validate_target(valid | {key: "production"})
        with self.assertRaises(RuntimeError):
            probe.validate_target({})

    def test_original_rows_cannot_change_or_disappear(self):
        before = {"core_user": {"id-a": "hash-a", "id-b": "hash-b"}}
        for after in [{}, {"core_user": {"id-a": "hash-a"}}, {"core_user": {"id-a": "changed", "id-b": "hash-b"}}]:
            with self.subTest(after=after), self.assertRaisesRegex(RuntimeError, "restored_original_rows_changed"):
                probe.verify_preserved(before, after)

    def test_new_seeded_rows_allowed_but_existing_humans_preserved(self):
        before = {"core_user": {"human": "unchanged"}}
        probe.verify_preserved(before, {"core_user": {"human": "unchanged", "service": "new"}})

    def test_only_exact_authorization_join_is_excluded(self):
        table = probe.EXPECTED_ACL_TABLE
        probe.verify_preserved({table: {"old": "hash"}}, {table: {"new": "hash"}})
        with self.assertRaises(RuntimeError):
            probe.verify_preserved({table + "_other": {"old": "hash"}}, {})


if __name__ == "__main__":
    unittest.main()
