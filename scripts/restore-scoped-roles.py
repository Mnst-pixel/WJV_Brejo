"""Grant rehearsal on a fresh isolated restore, using only synthetic role secrets."""
import importlib.util
from pathlib import Path
import secrets


def module(name):
    # Fixed callers below, never a user-provided path or module name.
    path = Path(__file__).with_name(name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def switch(connection, user, password):
    connection.close()
    connection.settings_dict.update(USER=user, PASSWORD=password)
    connection.ensure_connection()


def reconcile(connection, state):
    switch(connection, "kairos_restore", state["admin_password"])
    # Same SQL as production, with psql's client directive removed.
    statement = "\n".join(line for line in state["provisioner"].render_sql(state["values"]).splitlines() if not line.startswith("\\set "))
    with connection.cursor() as cursor:
        cursor.execute(statement)


def prepare(connection):
    provisioner = module("database-roles")
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database(),current_user,(SELECT rolsuper FROM pg_roles WHERE rolname=current_user),(SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=current_database())")
        if cursor.fetchone() != ("kairos", "kairos_restore", True, "kairos_restore"):
            raise RuntimeError("fresh_isolated_scoped_restore_required")
        cursor.execute("SELECT count(*) FROM pg_roles WHERE rolname IN ('kairos_runtime','kairos_worker','kairos_migrator','kairos_backup')")
        if cursor.fetchone()[0]:
            raise RuntimeError("refusing_existing_scoped_roles")
    state = {"admin_password": connection.settings_dict["PASSWORD"], "provisioner": provisioner,
        "values": {"POSTGRES_DB": "kairos", "POSTGRES_USER": "kairos_restore"}, "passwords": {}}
    for user_key, password_key, role in provisioner.ROLES.values():
        password = secrets.token_hex(48)
        state["passwords"][role] = password
        state["values"].update({user_key: role, password_key: password})
    reconcile(connection, state)
    switch(connection, "kairos_migrator", state["passwords"]["kairos_migrator"])
    return state


def finish(connection, state):
    from django.db import ProgrammingError

    def denied(statement):
        try:
            with connection.cursor() as cursor:
                cursor.execute(statement)
        except ProgrammingError as error:
            if getattr(error.__cause__, "sqlstate", None) != "42501":
                raise RuntimeError("unexpected_scoped_denial") from None
        else:
            raise RuntimeError("missing_scoped_permission_boundary")

    # Migrator-created relations have no runtime grant until explicit reconciliation.
    with connection.cursor() as cursor:
        cursor.execute("CREATE TABLE public.core_restore_grant_probe(id integer PRIMARY KEY)")
    switch(connection, "kairos_runtime", state["passwords"]["kairos_runtime"])
    denied("SELECT * FROM public.core_restore_grant_probe")
    reconcile(connection, state)
    for role, password in state["passwords"].items():
        switch(connection, role, password)
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_user,rolsuper,rolcreatedb,rolcreaterole,rolinherit,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=current_user")
            row = cursor.fetchone()
            if row[0] != role or any(row[1:]):
                raise RuntimeError("scoped_role_attributes_invalid")
            # Test actual ACLs even if the backup session default is disabled.
            cursor.execute("SET default_transaction_read_only=off")
        if role != "kairos_migrator":
            denied("SET ROLE kairos_migrator")
            denied("CREATE TABLE public.core_forbidden_probe(id integer)")
        if role == "kairos_backup":
            with connection.cursor() as cursor:
                cursor.execute("SELECT count(*) FROM core_user")
            denied("DELETE FROM core_user WHERE false")
        elif role == "kairos_worker":
            denied("SELECT password FROM core_user")
            with connection.cursor() as cursor:
                cursor.execute("SELECT id FROM core_user LIMIT 0")
        elif role == "kairos_runtime":
            denied("DELETE FROM django_migrations WHERE false")
            for table in state["provisioner"].IMMUTABLE:
                denied(f"UPDATE public.{table} SET id=id WHERE false")
                denied(f"DELETE FROM public.{table} WHERE false")
            with connection.cursor() as cursor:
                cursor.execute("SELECT * FROM public.core_restore_grant_probe")
    switch(connection, "kairos_migrator", state["passwords"]["kairos_migrator"])
    with connection.cursor() as cursor:
        cursor.execute("DROP TABLE public.core_restore_grant_probe")
    switch(connection, "kairos_runtime", state["passwords"]["kairos_runtime"])
    return module("scoped-runtime-probe").run()
