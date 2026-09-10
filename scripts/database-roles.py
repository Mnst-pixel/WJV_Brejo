#!/usr/bin/env python3
"""Plan/apply Kairós PostgreSQL grants; credentials stay in protected files and SQL stdin."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

ROLES = {
    "runtime": ("KAIROS_RUNTIME_DB_USER", "KAIROS_RUNTIME_DB_PASSWORD", "kairos_runtime"),
    "worker": ("KAIROS_WORKER_DB_USER", "KAIROS_WORKER_DB_PASSWORD", "kairos_worker"),
    "migrator": ("KAIROS_MIGRATION_DB_USER", "KAIROS_MIGRATION_DB_PASSWORD", "kairos_migrator"),
    "backup": ("KAIROS_BACKUP_DB_USER", "KAIROS_BACKUP_DB_PASSWORD", "kairos_backup"),
}
CONTAINER = "kairos-postgres-1"
IMMUTABLE = ("core_auditlog", "core_publicationapproval", "core_contentversion", "core_questionversion", "core_answerkeyversion", "core_practicalcaseversion", "core_promptversion")


class ProvisionError(Exception):
    pass


def recovery_values(path):
    candidate = Path(path)
    if candidate.name != "recovery.env" or not candidate.is_absolute():
        raise ProvisionError("protected_recovery_path_required")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to("/opt/kairos/secrets") or candidate.is_symlink():
        raise ProvisionError("recovery_outside_namespace")
    info = candidate.lstat()
    if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != 0:
        raise ProvisionError("protected_recovery_owner_mode_required")
    values = {}
    for line in candidate.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or key in values or any(ord(c) < 32 for c in value):
            raise ProvisionError("invalid_recovery_format")
        values[key] = value
    validate_values(values)
    return values


def validate_values(values):
    if values.get("POSTGRES_DB") != "kairos" or not re.fullmatch(r"kairos(?:_[a-z0-9_]+)?", values.get("POSTGRES_USER", "")):
        raise ProvisionError("unexpected_database_identity")
    for user_key, password_key, expected in ROLES.values():
        if values.get(user_key) != expected:
            raise ProvisionError("unexpected_role_identity")
        # release-secrets.py generates token_hex(48); narrow alphabet excludes SQL/meta injection.
        if not re.fullmatch(r"[a-f0-9]{96}", values.get(password_key, "")):
            raise ProvisionError("invalid_internal_password_encoding")
    passwords = [values[entry[1]] for entry in ROLES.values()]
    if len(set(passwords)) != len(passwords):
        raise ProvisionError("shared_internal_database_password")
    if values["POSTGRES_USER"] in {entry[2] for entry in ROLES.values()}:
        raise ProvisionError("provisioning_principal_must_be_separate")


def render_sql(values):
    validate_values(values)
    statements = [
        "\\set ON_ERROR_STOP on", "SET log_statement = 'none';", "SET log_min_error_statement = 'panic';",
        "BEGIN;", "SET LOCAL lock_timeout = '10s';", "SET LOCAL statement_timeout = '120s';",
        "DO $$ BEGIN IF current_database() <> 'kairos' OR NOT (SELECT rolsuper FROM pg_roles WHERE rolname=current_user) THEN RAISE EXCEPTION 'invalid provisioning context'; END IF; END $$;",
        "CREATE EXTENSION IF NOT EXISTS vector;",
    ]
    for _, password_key, role in ROLES.values():
        statements.extend([
            f"DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='{role}') THEN CREATE ROLE {role}; END IF; END $$;",
            f"ALTER ROLE {role} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 30 PASSWORD '{values[password_key]}';",
            f"ALTER ROLE {role} SET search_path = public, pg_catalog;",
        ])
    statements.extend([
        # NOINHERIT alone does not prevent SET ROLE; remove all preexisting memberships.
        "DO $$ DECLARE member_row record; BEGIN FOR member_row IN SELECT parent.rolname AS parent, child.rolname AS child FROM pg_auth_members m JOIN pg_roles parent ON parent.oid=m.roleid JOIN pg_roles child ON child.oid=m.member WHERE child.rolname IN ('kairos_runtime','kairos_worker','kairos_migrator','kairos_backup') LOOP EXECUTE format('REVOKE %I FROM %I',member_row.parent,member_row.child); END LOOP; END $$;",
        "REVOKE ALL ON DATABASE kairos FROM PUBLIC;",
        "REVOKE ALL ON DATABASE kairos FROM kairos_runtime, kairos_worker, kairos_migrator, kairos_backup;",
        "GRANT CONNECT ON DATABASE kairos TO kairos_runtime, kairos_worker, kairos_migrator, kairos_backup;",
        "REVOKE ALL ON SCHEMA public FROM PUBLIC;",
        "ALTER SCHEMA public OWNER TO kairos_migrator;",
        "GRANT USAGE ON SCHEMA public TO kairos_runtime, kairos_worker, kairos_backup;",
        # Only application relations transfer ownership. Extension-owned objects remain intact.
        """DO $$ DECLARE relation record; BEGIN
FOR relation IN SELECT c.oid,c.relname,c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='public' AND c.relkind IN ('r','p','S','v','m') AND c.relname ~ '^(core_|auth_|django_)'
AND NOT EXISTS (SELECT FROM pg_depend d WHERE d.classid='pg_class'::regclass AND d.objid=c.oid AND d.deptype='e')
ORDER BY CASE WHEN c.relkind='S' THEN 1 ELSE 0 END,c.relname LOOP
EXECUTE format('ALTER %s public.%I OWNER TO kairos_migrator',CASE relation.relkind WHEN 'S' THEN 'SEQUENCE' WHEN 'v' THEN 'VIEW' WHEN 'm' THEN 'MATERIALIZED VIEW' ELSE 'TABLE' END,relation.relname);
END LOOP; END $$;""",
        "REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC,kairos_runtime,kairos_worker,kairos_backup;",
        "REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC,kairos_runtime,kairos_worker,kairos_backup;",
        """DO $$ DECLARE relation record; BEGIN
FOR relation IN SELECT c.relname,string_agg(quote_ident(a.attname),',' ORDER BY a.attnum) AS columns FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_attribute a ON a.attrelid=c.oid
WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m') AND a.attnum>0 AND NOT a.attisdropped GROUP BY c.relname LOOP
EXECUTE format('REVOKE ALL (%s) ON TABLE public.%I FROM PUBLIC,kairos_runtime,kairos_worker,kairos_backup',relation.columns,relation.relname);
END LOOP; END $$;""",
        "GRANT SELECT ON ALL TABLES IN SCHEMA public TO kairos_backup;",
        "GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO kairos_backup;",
        """DO $$ DECLARE relation record; BEGIN
FOR relation IN SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind IN ('r','p') AND c.relname ~ '^(core_|auth_|django_)' LOOP
EXECUTE format('GRANT SELECT,INSERT,UPDATE,DELETE ON TABLE public.%I TO kairos_runtime',relation.relname);
END LOOP; END $$;""",
        "GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO kairos_runtime;",
        # No write defaults: new tables fail closed until this reconciliation runs after migrations.
        "ALTER DEFAULT PRIVILEGES FOR ROLE kairos_migrator IN SCHEMA public REVOKE ALL ON TABLES FROM PUBLIC,kairos_runtime,kairos_worker;",
        "ALTER DEFAULT PRIVILEGES FOR ROLE kairos_migrator IN SCHEMA public GRANT SELECT ON TABLES TO kairos_backup;",
        "ALTER DEFAULT PRIVILEGES FOR ROLE kairos_migrator IN SCHEMA public GRANT SELECT ON SEQUENCES TO kairos_backup;",
        "REVOKE INSERT,UPDATE,DELETE ON public.django_migrations FROM kairos_runtime;",
    ])
    for table in IMMUTABLE:
        statements.append(f"REVOKE UPDATE,DELETE ON public.{table} FROM kairos_runtime;")
    statements.extend([
        "REVOKE UPDATE,DELETE ON public.core_sourcedocumentversion FROM kairos_runtime;",
        "GRANT UPDATE(state,approved_by_id,approval_date,published_at,updated_at) ON public.core_sourcedocumentversion TO kairos_runtime;",
        "GRANT SELECT,UPDATE ON public.core_fileasset,public.core_ingestionrun TO kairos_worker;",
        "GRANT INSERT ON public.core_auditlog TO kairos_worker;",
        "GRANT SELECT(id),UPDATE(updated_at) ON public.core_user TO kairos_worker;",
        "ALTER ROLE kairos_backup SET default_transaction_read_only = on;",
        "ALTER ROLE kairos_runtime SET idle_in_transaction_session_timeout = '60s';",
        "ALTER ROLE kairos_worker SET idle_in_transaction_session_timeout = '60s';",
        "COMMIT;",
    ])
    return "\n".join(statements) + "\n"


def plan(values):
    sql = render_sql(values)
    return {"status": "PLAN", "database": "kairos", "container": CONTAINER,
            "roles": {key: entry[2] for key, entry in ROLES.items()}, "plan_sha256": hashlib.sha256(sql.encode()).hexdigest(),
            "schema_owner": "kairos_migrator", "application_superuser": False,
            "extensions": "preserved", "post_migration_reconciliation": "required"}


def apply(values, expected_plan_hash, runner=subprocess.run):
    report = plan(values)
    if not expected_plan_hash or report["plan_sha256"] != expected_plan_hash:
        raise ProvisionError("plan_changed")
    inspection = runner(["docker", "container", "inspect", "--format", '{{json .Config.Labels}}', CONTAINER], capture_output=True, text=True, timeout=20, check=False)
    if inspection.returncode:
        raise ProvisionError("container_inspection_failed")
    labels = json.loads(inspection.stdout)
    if labels.get("com.docker.compose.project") != "kairos" or labels.get("com.docker.compose.service") != "postgres":
        raise ProvisionError("container_identity_mismatch")
    command = ["docker", "exec", "-i", CONTAINER, "psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-U", values["POSTGRES_USER"], "-d", "kairos"]
    result = runner(command, input=render_sql(values), capture_output=True, text=True, timeout=300, check=False)
    if result.returncode:
        # PostgreSQL diagnostics can include SQL literals. Never forward them to caller or journal.
        raise ProvisionError("database_reconciliation_failed")
    return report | {"status": "APPLIED"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("plan", "apply"))
    parser.add_argument("--recovery", required=True)
    parser.add_argument("--expected-plan-hash")
    args = parser.parse_args()
    try:
        if os.geteuid() != 0:
            raise ProvisionError("root_required")
        values = recovery_values(args.recovery)
        if args.mode == "plan":
            report = plan(values)
        else:
            import fcntl
            lock_path = Path("/opt/kairos/runtime/.operation.lock")
            if not lock_path.parent.resolve(strict=True).is_relative_to("/opt/kairos/runtime"):
                raise ProvisionError("unsafe_operation_lock_parent")
            descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            try:
                if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                    raise ProvisionError("unsafe_operation_lock")
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                report = apply(values, args.expected_plan_hash)
            finally:
                os.close(descriptor)
        print(json.dumps(report, sort_keys=True))
        return 0
    except Exception as error:
        print(json.dumps({"status": "FAIL", "error": type(error).__name__}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
