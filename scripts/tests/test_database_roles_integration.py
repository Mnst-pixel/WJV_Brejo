"""Opt-in PostgreSQL privilege tests against the disposable integration service only.

No Docker socket, production hostname, recovery file or human credential is used.
The coordinator creates the isolated PG service before setting KAIROS_TEST_DB_ROLES=1.
"""
import contextlib
import importlib.util
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
from uuid import uuid4

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("KAIROS_TEST_DB_ROLES") != "1", reason="Opt in with KAIROS_TEST_DB_ROLES=1 inside the disposable PostgreSQL integration network")
ROOT = Path(__file__).resolve().parents[2]
HOST = "kairos-test-postgres"
ADMIN = "kairos_test"


def provisioning_module():
    spec = importlib.util.spec_from_file_location("database_roles_under_test", ROOT / "scripts" / "database-roles.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class IsolatedRoles:
    def __init__(self, psycopg, password, run_id):
        self.psycopg = psycopg
        self.admin_password = password
        self.run_id = run_id
        self.marker = "KAIROS_TEST_DB_ROLES:" + run_id
        self.module = provisioning_module()
        self.values = {"POSTGRES_DB": "kairos", "POSTGRES_USER": ADMIN}
        self.passwords = {ADMIN: password}
        for user_key, password_key, role in self.module.ROLES.values():
            credential = secrets.token_hex(48)
            self.values.update({user_key: role, password_key: credential})
            self.passwords[role] = credential
        self.user_id = uuid4()
        self.databases = []

    @contextlib.contextmanager
    def connect(self, role=ADMIN, database="kairos", *, autocommit=True):
        with self.psycopg.connect(host=HOST, port=5432, dbname=database, user=role,
                password=self.passwords[role], connect_timeout=5, sslmode="disable", autocommit=autocommit,
                application_name="kairos-dbroles-" + self.run_id,
                options="-c statement_timeout=120000 -c lock_timeout=10000") as connection:
            yield connection

    def create_database(self, name):
        sql = self.psycopg.sql
        with self.connect(database=ADMIN) as connection:
            if connection.execute("SELECT 1 FROM pg_database WHERE datname=%s", (name,)).fetchone():
                pytest.fail("Refusing to reuse an existing privilege-test database", pytrace=False)
            connection.execute(sql.SQL("CREATE DATABASE {} OWNER kairos_test").format(sql.Identifier(name)))
            self.databases.append(name)
            connection.execute(sql.SQL("COMMENT ON DATABASE {} IS {}").format(sql.Identifier(name), sql.Literal(self.marker)))

    def reconcile(self):
        # psycopg executes SQL, not psql meta-commands. Production text is otherwise unchanged.
        statement = "\n".join(line for line in self.module.render_sql(self.values).splitlines() if not line.startswith("\\set "))
        with self.connect() as connection:
            connection.execute(statement, prepare=False)

    def django(self, *, role=ADMIN, target=None, seed=False):
        env = os.environ.copy()
        env.update({"DJANGO_SETTINGS_MODULE": "kairos.settings", "DJANGO_SECRET_KEY": secrets.token_hex(48),
            "POSTGRES_HOST": HOST, "POSTGRES_PORT": "5432", "POSTGRES_DB": "kairos",
            "POSTGRES_USER": role, "POSTGRES_PASSWORD": self.passwords[role], "POSTGRES_SSLMODE": "disable",
            "KAIROS_DB_ROLES_USER_ID": str(self.user_id), "PYTHONDONTWRITEBYTECODE": "1"})
        # Read production models/settings, then explicitly disable every external adapter.
        program = '''
import os
import django
from django.conf import settings
assert settings.DATABASES['default']['HOST'] == 'kairos-test-postgres'
assert settings.DATABASES['default']['NAME'] == 'kairos'
settings.DATABASES['default']['CONN_MAX_AGE'] = 0
settings.CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
settings.STORAGES = {'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'}, 'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}}
settings.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
settings.CELERY_TASK_ALWAYS_EAGER = True
settings.CELERY_BROKER_URL = 'memory://'
settings.CELERY_RESULT_BACKEND = None
settings.LOCALAI_BASE_URL = ''
django.setup()
from django.core.management import call_command
'''
        program += f"call_command('migrate', *{list(target or [])!r}, interactive=False, verbosity=0)\n"
        if seed:
            program += "from core.models import User\nUser.objects.create(id=os.environ['KAIROS_DB_ROLES_USER_ID'], username='dbroles-synthetic', password='!unusable-synthetic', mfa_secret_encrypted='synthetic-only-no-secret')\n"
        result = subprocess.run([sys.executable, "-c", program], cwd=ROOT / "apps" / "api", env=env,
            capture_output=True, text=True, timeout=180, check=False)
        if result.returncode:
            pytest.fail("Isolated production-settings migration/seed failed (output withheld to protect credentials)", pytrace=False)

    def cleanup(self):
        sql = self.psycopg.sql
        with self.connect(database=ADMIN) as connection:
            for name in reversed(self.databases):
                row = connection.execute("SELECT shobj_description(oid,'pg_database') FROM pg_database WHERE datname=%s", (name,)).fetchone()
                if row is None:
                    continue
                if row[0] != self.marker:
                    pytest.fail("Refusing cleanup: database run marker changed", pytrace=False)
                # Only databases created by this fixture and carrying its exact marker.
                connection.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
            for _, _, role in self.module.ROLES.values():
                row = connection.execute("SELECT shobj_description(oid,'pg_authid') FROM pg_roles WHERE rolname=%s", (role,)).fetchone()
                if row and row[0] == self.marker:
                    connection.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


@pytest.fixture(scope="module")
def database_roles():
    try:
        import psycopg
    except ImportError:
        pytest.fail("Opt-in PostgreSQL privilege tests require psycopg", pytrace=False)
    # These guards run before DNS lookup or a connection attempt.
    for name, expected in {"KAIROS_TEST_POSTGRES_HOST": HOST, "KAIROS_TEST_POSTGRES_USER": ADMIN, "KAIROS_TEST_POSTGRES_DB": ADMIN, "KAIROS_TEST_POSTGRES_PORT": "5432"}.items():
        if os.environ.get(name, expected) != expected:
            pytest.fail("Privilege tests require the fixed disposable PostgreSQL identity", pytrace=False)
    password = os.environ.get("KAIROS_TEST_POSTGRES_PASSWORD", "")
    run_id = os.environ.get("KAIROS_TEST_RUN_ID", "")
    if not re.fullmatch(r"[0-9a-f]{64}", password) or not re.fullmatch(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}", run_id):
        pytest.fail("Fresh synthetic password and integration run ID are required", pytrace=False)
    state = IsolatedRoles(psycopg, password, run_id)
    with state.connect(database=ADMIN) as connection:
        identity = connection.execute("SELECT current_user,current_database(),(SELECT rolsuper FROM pg_roles WHERE rolname=current_user)").fetchone()
        assert identity == (ADMIN, ADMIN, True)
        assert connection.execute("SELECT count(*) FROM pg_roles WHERE rolname IN ('kairos_runtime','kairos_worker','kairos_migrator','kairos_backup')").fetchone()[0] == 0, "Refusing to alter existing role identities"
    try:
        state.create_database("kairos")
        state.django(seed=True)
        state.reconcile()
        with state.connect() as connection:
            for _, _, role in state.module.ROLES.values():
                connection.execute(psycopg.sql.SQL("COMMENT ON ROLE {} IS {}").format(psycopg.sql.Identifier(role), psycopg.sql.Literal(state.marker)))
        yield state
    finally:
        state.cleanup()


def denied(state, connection, statement, params=None):
    with pytest.raises(state.psycopg.errors.InsufficientPrivilege):
        connection.execute(statement, params)


def test_real_roles_cannot_escalate_or_create_schema(database_roles):
    state = database_roles
    with state.connect() as admin:
        records = admin.execute("SELECT rolname,rolsuper,rolcreatedb,rolcreaterole,rolinherit,rolreplication,rolbypassrls FROM pg_roles WHERE rolname IN ('kairos_runtime','kairos_worker','kairos_migrator','kairos_backup')").fetchall()
        assert len(records) == 4 and all(not any(row[1:]) for row in records)
    for role in ("kairos_runtime", "kairos_worker", "kairos_backup"):
        with state.connect(role) as connection:
            assert connection.execute("SELECT current_user").fetchone()[0] == role
            # Disable the backup default read-only for privilege tests: ACL still must deny writes.
            connection.execute("SET default_transaction_read_only=off")
            denied(state, connection, "CREATE TABLE public.core_forbidden_probe(id integer)")
            denied(state, connection, "CREATE TEMP TABLE forbidden_temp(id integer)")
            denied(state, connection, "SET ROLE kairos_test")
            denied(state, connection, "SET ROLE kairos_migrator")


def test_worker_can_lock_owner_id_but_cannot_read_authentication_secrets(database_roles):
    state = database_roles
    with state.connect("kairos_worker") as connection:
        with connection.transaction():
            assert connection.execute("SELECT id FROM core_user WHERE id=%s FOR UPDATE", (state.user_id,)).fetchone()[0] == state.user_id
        for column in ("password", "mfa_secret_encrypted", "email", "preferences", "is_superuser"):
            denied(state, connection, f"SELECT {column} FROM core_user WHERE id=%s", (state.user_id,))
        denied(state, connection, "SELECT * FROM core_user")
        denied(state, connection, "SELECT * FROM django_session")
        denied(state, connection, "UPDATE core_user SET is_superuser=true WHERE id=%s", (state.user_id,))
        assert connection.execute("SELECT id FROM core_fileasset LIMIT 1").fetchall() == []
        connection.execute("UPDATE core_fileasset SET processing_status=processing_status WHERE false")
        connection.execute("UPDATE core_ingestionrun SET status=status WHERE false")
        connection.execute("INSERT INTO core_auditlog(id,actor_id,action,target_type,target_id,user_agent,request_id,metadata,occurred_at) VALUES(%s,%s,'worker.synthetic','','','','','{}',now())", (uuid4(), state.user_id))
        denied(state, connection, "SELECT * FROM core_auditlog")
        denied(state, connection, "INSERT INTO core_user(id) VALUES(%s)", (uuid4(),))


def test_runtime_dml_and_immutable_table_boundary(database_roles):
    state = database_roles
    goal_id = uuid4()
    with state.connect("kairos_runtime") as connection:
        connection.execute("INSERT INTO core_goal(id,owner_id,title,description,progress,created_at,updated_at) VALUES(%s,%s,'Synthetic goal','',0,now(),now())", (goal_id, state.user_id))
        connection.execute("UPDATE core_goal SET progress=50 WHERE id=%s", (goal_id,))
        assert connection.execute("SELECT progress FROM core_goal WHERE id=%s", (goal_id,)).fetchone() == (50,)
        connection.execute("DELETE FROM core_goal WHERE id=%s", (goal_id,))
        for table in state.module.IMMUTABLE:
            denied(state, connection, f"UPDATE public.{table} SET id=id WHERE false")
            denied(state, connection, f"DELETE FROM public.{table} WHERE false")
        denied(state, connection, "DELETE FROM django_migrations WHERE false")
        denied(state, connection, "UPDATE core_sourcedocumentversion SET normalized_text='' WHERE false")
        connection.execute("UPDATE core_sourcedocumentversion SET state=state,updated_at=now() WHERE false")


def test_backup_is_read_only_even_when_session_default_is_overridden(database_roles):
    state = database_roles
    with state.connect("kairos_backup") as connection:
        assert connection.execute("SHOW default_transaction_read_only").fetchone()[0] == "on"
        assert connection.execute("SELECT count(*) FROM core_user WHERE id=%s", (state.user_id,)).fetchone()[0] == 1
        with pytest.raises(state.psycopg.errors.ReadOnlySqlTransaction):
            connection.execute("DELETE FROM core_goal WHERE false")
        connection.execute("SET default_transaction_read_only=off")
        denied(state, connection, "DELETE FROM core_goal WHERE false")
        denied(state, connection, "INSERT INTO core_auditlog(id) VALUES(%s)", (uuid4(),))


def test_migrator_ddl_is_fail_closed_until_reconciliation(database_roles):
    state = database_roles
    with state.connect("kairos_migrator") as migrator:
        migrator.execute("CREATE TABLE public.core_dbroles_new_table(id integer PRIMARY KEY,value text NOT NULL)")
        migrator.execute("INSERT INTO public.core_dbroles_new_table VALUES(1,'synthetic')")
    with state.connect("kairos_runtime") as runtime:
        denied(state, runtime, "SELECT * FROM public.core_dbroles_new_table")
        denied(state, runtime, "INSERT INTO public.core_dbroles_new_table VALUES(2,'blocked')")
    with state.connect("kairos_backup") as backup:
        assert backup.execute("SELECT value FROM public.core_dbroles_new_table WHERE id=1").fetchone()[0] == "synthetic"
    with state.connect() as admin:
        admin.execute("GRANT kairos_migrator TO kairos_runtime")
    state.reconcile()
    with state.connect("kairos_runtime") as runtime:
        assert runtime.execute("SELECT value FROM public.core_dbroles_new_table WHERE id=1").fetchone()[0] == "synthetic"
        runtime.execute("INSERT INTO public.core_dbroles_new_table VALUES(2,'allowed after reconciliation')")
        denied(state, runtime, "SET ROLE kairos_migrator")
    with state.connect("kairos_worker") as worker:
        denied(state, worker, "SELECT * FROM public.core_dbroles_new_table")
    with state.connect() as admin:
        assert admin.execute("SELECT r.rolname FROM pg_extension e JOIN pg_roles r ON r.oid=e.extowner WHERE e.extname='vector'").fetchone() == (ADMIN,)


def test_real_migration_reverse_forward_as_migrator_preserves_privileges(database_roles):
    state = database_roles
    state.django(role="kairos_migrator", target=["core", "0005"])
    state.django(role="kairos_migrator")
    with state.connect("kairos_runtime") as runtime:
        denied(state, runtime, "SELECT * FROM core_contentworkflow")
    state.reconcile()
    with state.connect("kairos_runtime") as runtime:
        assert runtime.execute("SELECT count(*) FROM core_contentworkflow").fetchone()[0] == 0
        assert runtime.execute("SELECT count(*) FROM django_migrations WHERE app='core' AND name='0006_content_workflow'").fetchone()[0] == 1
        denied(state, runtime, "DELETE FROM core_publicationapproval WHERE false")
    with state.connect("kairos_worker") as worker:
        with worker.transaction():
            assert worker.execute("SELECT id FROM core_user WHERE id=%s FOR UPDATE", (state.user_id,)).fetchone()[0] == state.user_id


def test_backup_role_pg_dump_and_restore_recover_synthetic_database(database_roles, tmp_path):
    state = database_roles
    dump_bin, restore_bin = shutil.which("pg_dump"), shutil.which("pg_restore")
    if not dump_bin or not restore_bin:
        pytest.skip("pg_dump/pg_restore client binaries unavailable in this isolated test image")
    archive = tmp_path / "synthetic-kairos.dump"
    env = os.environ.copy()
    env["PGPASSWORD"] = state.passwords["kairos_backup"]
    dumped = subprocess.run([dump_bin, "--host", HOST, "--port", "5432", "--username", "kairos_backup", "--dbname", "kairos", "--format=custom", "--no-owner", "--no-acl", "--file", str(archive)], env=env, capture_output=True, timeout=120, check=False)
    assert dumped.returncode == 0, "Backup-role pg_dump failed; credentials/output withheld"
    assert archive.is_file() and archive.stat().st_size > 0
    destination = "kairos_dbroles_restore_" + state.run_id.rsplit("-", 1)[1]
    state.create_database(destination)
    env["PGPASSWORD"] = state.admin_password
    restored = subprocess.run([restore_bin, "--host", HOST, "--port", "5432", "--username", ADMIN, "--dbname", destination, "--no-owner", "--no-acl", "--exit-on-error", str(archive)], env=env, capture_output=True, timeout=120, check=False)
    assert restored.returncode == 0, "Isolated pg_restore failed; credentials/output withheld"
    with state.connect(database=destination) as recovered, state.connect() as original:
        for table in ("core_user", "core_auditlog", "core_role", "django_migrations"):
            assert recovered.execute(f"SELECT count(*) FROM {table}").fetchone() == original.execute(f"SELECT count(*) FROM {table}").fetchone()
        assert recovered.execute("SELECT id FROM core_user WHERE username='dbroles-synthetic'").fetchone()[0] == state.user_id
        with pytest.raises(state.psycopg.errors.CheckViolation):
            recovered.execute("INSERT INTO core_goal(id,owner_id,title,description,progress,created_at,updated_at) VALUES(%s,%s,'Impossible','',101,now(),now())", (uuid4(), state.user_id))
