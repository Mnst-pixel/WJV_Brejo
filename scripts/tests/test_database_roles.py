import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

SPEC = importlib.util.spec_from_file_location("database_roles", Path(__file__).resolve().parents[1] / "database-roles.py")
db = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(db)


def values():
    result = {"POSTGRES_DB": "kairos", "POSTGRES_USER": "kairos_app"}
    for index, (user_key, password_key, expected) in enumerate(db.ROLES.values(), 1):
        result[user_key] = expected
        result[password_key] = str(index) * 96
    return result


class DatabaseRolesTests(unittest.TestCase):
    def test_plan_is_deterministic_and_never_exposes_passwords(self):
        credentials = values()
        report = db.plan(credentials)
        self.assertEqual(report, db.plan(credentials))
        for _, key, _ in db.ROLES.values():
            self.assertNotIn(credentials[key], json.dumps(report))
        self.assertEqual(report["plan_sha256"], hashlib.sha256(db.render_sql(credentials).encode()).hexdigest())

    def test_fixed_database_role_names_and_password_alphabet(self):
        changes = [{"POSTGRES_DB": "other"}, {"POSTGRES_USER": "postgres;SELECT"}, {"KAIROS_RUNTIME_DB_USER": "superuser"}, {"KAIROS_RUNTIME_DB_PASSWORD": "' OR 1=1"}, {"KAIROS_WORKER_DB_PASSWORD": "1" * 96}]
        for changed in changes:
            with self.subTest(keys=list(changed)), self.assertRaises(db.ProvisionError):
                db.render_sql(values() | changed)

    def test_sql_revokes_escalation_memberships_and_default_public_grants(self):
        sql = db.render_sql(values())
        for role in ("kairos_runtime", "kairos_worker", "kairos_migrator", "kairos_backup"):
            self.assertIn(f"ALTER ROLE {role} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS", sql)
        self.assertIn("REVOKE %I FROM %I", sql)
        self.assertIn("REVOKE ALL ON DATABASE kairos FROM PUBLIC", sql)
        self.assertIn("REVOKE ALL ON SCHEMA public FROM PUBLIC", sql)
        self.assertIn("REVOKE ALL (%s) ON TABLE", sql)
        self.assertNotIn("GRANT pg_read_all_data", sql)
        self.assertNotIn("CREATE DATABASE", sql)
        self.assertNotIn("DROP DATABASE", sql)

    def test_worker_cannot_receive_full_user_or_authentication_table_access(self):
        sql = db.render_sql(values())
        self.assertIn("GRANT SELECT(id),UPDATE(updated_at) ON public.core_user TO kairos_worker", sql)
        self.assertNotIn("GRANT SELECT ON public.core_user TO kairos_worker", sql)
        self.assertIn("GRANT SELECT,UPDATE ON public.core_fileasset,public.core_ingestionrun TO kairos_worker", sql)
        self.assertIn("GRANT INSERT ON public.core_auditlog TO kairos_worker", sql)

    def test_extensions_preserved_and_new_tables_fail_closed(self):
        sql = db.render_sql(values())
        self.assertIn("d.deptype='e'", sql)
        self.assertNotIn("ALTER EXTENSION", sql)
        self.assertNotIn("DROP EXTENSION", sql)
        self.assertIn("REVOKE ALL ON TABLES FROM PUBLIC,kairos_runtime,kairos_worker", sql)
        self.assertIn("REVOKE INSERT,UPDATE,DELETE ON public.django_migrations FROM kairos_runtime", sql)
        self.assertIn("REVOKE UPDATE,DELETE ON public.core_auditlog FROM kairos_runtime", sql)
        self.assertIn("REVOKE UPDATE,DELETE ON public.core_alternative FROM kairos_runtime", sql)
        self.assertIn("REVOKE UPDATE,DELETE ON public.core_questionmetadata FROM kairos_runtime", sql)

    def test_changed_plan_refused_without_any_command(self):
        def fail(*args, **kwargs):
            self.fail("should not execute commands")
        with self.assertRaises(db.ProvisionError):
            db.apply(values(), "changed", runner=fail)

    def test_foreign_container_label_refuses_sql(self):
        calls = []
        def runner(command, **kwargs):
            calls.append(command)
            return SimpleNamespace(returncode=0, stdout=json.dumps({"com.docker.compose.project": "foreign", "com.docker.compose.service": "postgres"}))
        with self.assertRaises(db.ProvisionError):
            db.apply(values(), db.plan(values())["plan_sha256"], runner)
        self.assertEqual(len(calls), 1)

    def test_sql_passes_only_stdin_and_server_errors_are_not_forwarded(self):
        calls = []
        def runner(command, **kwargs):
            calls.append((command, kwargs))
            if command[:3] == ["docker", "container", "inspect"]:
                return SimpleNamespace(returncode=0, stdout=json.dumps({"com.docker.compose.project": "kairos", "com.docker.compose.service": "postgres"}))
            return SimpleNamespace(returncode=1, stdout="", stderr="secret SQL text " + values()["KAIROS_RUNTIME_DB_PASSWORD"])
        with self.assertRaises(db.ProvisionError) as caught:
            db.apply(values(), db.plan(values())["plan_sha256"], runner)
        self.assertNotIn(values()["KAIROS_RUNTIME_DB_PASSWORD"], str(caught.exception))
        for command, _ in calls:
            for _, key, _ in db.ROLES.values():
                self.assertNotIn(values()[key], " ".join(command))
        self.assertIn("ALTER ROLE", calls[1][1]["input"])
        self.assertEqual(calls[1][0][:4], ["docker", "exec", "-i", "kairos-postgres-1"])

    def test_success_reports_only_plan_metadata(self):
        def runner(command, **kwargs):
            output = json.dumps({"com.docker.compose.project": "kairos", "com.docker.compose.service": "postgres"}) if "inspect" in command else "ignored stdout"
            return SimpleNamespace(returncode=0, stdout=output, stderr="")
        report = db.apply(values(), db.plan(values())["plan_sha256"], runner)
        self.assertEqual(report["status"], "APPLIED")
        self.assertNotIn("ignored stdout", json.dumps(report))


if __name__ == "__main__":
    unittest.main()
