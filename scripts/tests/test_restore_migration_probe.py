import importlib.util
import contextlib
import io
import json
import logging
import sys
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("restore_migration_probe", Path(__file__).resolve().parents[1] / "restore-migration-probe.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class RestoreMigrationProbeTests(unittest.TestCase):
    def test_receipt_is_one_json_document_despite_expected_application_logs(self):
        def operation():
            handler = logging.StreamHandler(sys.stdout)
            try:
                handler.emit(logging.LogRecord("probe", logging.WARNING, "", 0, "synthetic-private-canary", (), None))
                print("synthetic output")
                print("synthetic diagnostics", file=sys.stderr)
                return {"status": "PASS", "scoped_grants": "PASS"}
            finally:
                handler.close()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            probe.emit_report(operation)
        self.assertEqual(json.loads(output.getvalue()), {"status": "PASS", "scoped_grants": "PASS"})
        self.assertEqual(len(output.getvalue().splitlines()), 1)
        self.assertNotIn("synthetic", output.getvalue())

    def test_failed_probe_cannot_emit_a_partial_pass_receipt(self):
        def operation():
            print('{"status":"PASS"}')
            raise RuntimeError("synthetic-failure")
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaisesRegex(RuntimeError, "synthetic-failure"):
            probe.emit_report(operation)
        self.assertEqual(output.getvalue(), "")

    def test_scoped_mode_requires_explicit_flag_and_fresh_restore_principal(self):
        valid = {"POSTGRES_DB": "kairos", "POSTGRES_USER": "kairos_restore", "POSTGRES_HOST": "127.0.0.1", "KAIROS_RESTORE_RUN_ID": "20260910T220000Z-aabbccddeeff", "KAIROS_RESTORE_SCOPED_ROLES": "1"}
        probe.validate_target(valid)
        for change in [{"KAIROS_RESTORE_SCOPED_ROLES": "0"}, {"KAIROS_RESTORE_SCOPED_ROLES": "true"},
                {"POSTGRES_USER": "kairos_app"}, {"POSTGRES_USER": "kairos_runtime"}, {"POSTGRES_DB": "kairos_restore"},
                {"POSTGRES_HOST": "kairos-postgres-1"}, {"KAIROS_RESTORE_RUN_ID": ""}]:
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                probe.validate_target(valid | change)

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
