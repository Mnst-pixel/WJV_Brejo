#!/usr/bin/env python3
"""Forward migration rehearsal on an isolated restored database, never live data."""
import hashlib
import json
import os
import re

MAX_ROWS = 200_000
EXPECTED_ACL_TABLE = "core_permission_roles"


def validate_target(values):
    if (values.get("POSTGRES_DB") != "kairos_restore"
            or values.get("POSTGRES_USER") != "kairos_restore"
            or values.get("POSTGRES_HOST") != "127.0.0.1"
            or not re.fullmatch(r"\d{8}T\d{6}Z-[a-f0-9]{12}", values.get("KAIROS_RESTORE_RUN_ID", ""))):
        raise RuntimeError("isolated_restore_target_required")


def fingerprint(connection, tables=None):
    """Keep only row hashes in memory; no content, identifiers or digests are printed."""
    with connection.cursor() as cursor:
        if tables is None:
            cursor.execute("SELECT table_name, column_name FROM information_schema.columns WHERE table_schema='public' AND left(table_name,5)='core_' ORDER BY table_name, ordinal_position")
            tables = {}
            for table, column in cursor.fetchall():
                tables.setdefault(table, []).append(column)
        result = {}
        total = 0
        quote = connection.ops.quote_name
        for table, columns in tables.items():
            if "id" not in columns:
                raise RuntimeError("unsupported_restore_table_identity")
            names = ",".join(quote(column) for column in columns)
            cursor.execute(f"SELECT id, to_jsonb(original)::text FROM (SELECT {names} FROM {quote(table)}) original ORDER BY id")
            rows = {}
            while batch := cursor.fetchmany(500):
                total += len(batch)
                if total > MAX_ROWS:
                    raise RuntimeError("restore_probe_row_budget_exceeded")
                for identity, data in batch:
                    rows[str(identity)] = hashlib.sha256(data.encode()).hexdigest()
            result[table] = rows
    return tables, result


def verify_preserved(before, after):
    for table, rows in before.items():
        # 0003 intentionally replaces the foundational authorization matrix.
        # Its least-privilege semantics have separate integration tests.
        if table == EXPECTED_ACL_TABLE:
            continue
        actual = after.get(table, {})
        if any(actual.get(identity) != value for identity, value in rows.items()):
            raise RuntimeError("restored_original_rows_changed:" + table)


def run():
    validate_target(os.environ)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "kairos.settings")
    import django
    django.setup()
    from django.core.management import call_command
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor
    from core.models import Permission

    if Permission.roles.through._meta.db_table != EXPECTED_ACL_TABLE:
        raise RuntimeError("unexpected_authorization_join_table")

    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database(), current_user, host(inet_server_addr())")
        if cursor.fetchone() != ("kairos_restore", "kairos_restore", "127.0.0.1"):
            raise RuntimeError("unexpected_restore_database_connection")
        cursor.execute("SET statement_timeout='60s'")
        cursor.execute("SET lock_timeout='5s'")
    tables, original = fingerprint(connection)
    if not original.get("core_user"):
        raise RuntimeError("restored_users_required")
    executor = MigrationExecutor(connection)
    planned = len(executor.migration_plan(executor.loader.graph.leaf_nodes()))
    call_command("migrate", interactive=False, verbosity=0)
    _, migrated = fingerprint(connection, tables)
    verify_preserved(original, migrated)
    with connection.cursor() as cursor:
        cursor.execute("SELECT EXISTS(SELECT 1 FROM pg_constraint WHERE NOT convalidated) OR EXISTS(SELECT 1 FROM pg_index WHERE NOT indisvalid)")
        if cursor.fetchone()[0]:
            raise RuntimeError("invalid_migrated_database_structure")
    executor = MigrationExecutor(connection)
    if executor.migration_plan(executor.loader.graph.leaf_nodes()):
        raise RuntimeError("unapplied_migrations_remain")
    all_tables, first = fingerprint(connection)
    call_command("migrate", interactive=False, verbosity=0)
    _, second = fingerprint(connection, all_tables)
    if first != second:
        raise RuntimeError("migration_rerun_changed_application_rows")
    print(json.dumps({"status": "PASS", "planned_migrations": planned,
                      "original_tables_checked": len(original) - int(EXPECTED_ACL_TABLE in original),
                      "original_rows_checked": sum(len(rows) for table, rows in original.items() if table != EXPECTED_ACL_TABLE),
                      "idempotent_rerun": True,
                      "excluded_expected_change": EXPECTED_ACL_TABLE,
                      "not_verified": ["scoped_grants", "backward_compatibility", "application_http", "whole_release_rollback"]}))


if __name__ == "__main__":
    run()
