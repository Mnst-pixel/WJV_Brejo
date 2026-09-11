"""Synthetic API checks inside an isolated database; every inserted row rolls back."""
from uuid import uuid4
import os
import re


def run():
    from django.db import connection, transaction
    from django.test import override_settings
    from rest_framework.test import APIClient
    from core.models import Role, User, UserRole, Subject

    host = connection.settings_dict["HOST"]
    run_id = os.environ.get("KAIROS_RESTORE_RUN_ID" if host == "127.0.0.1" else "KAIROS_TEST_RUN_ID", "")
    opt_in = os.environ.get("KAIROS_RESTORE_SCOPED_ROLES" if host == "127.0.0.1" else "KAIROS_TEST_DB_ROLES")
    if host not in {"127.0.0.1", "kairos-test-postgres"} or opt_in != "1" or not re.fullmatch(r"\d{8}T\d{6}Z-[a-f0-9]{12}", run_id):
        raise RuntimeError("isolated_runtime_host_required")
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database(),current_user,(SELECT rolsuper FROM pg_roles WHERE rolname=current_user)")
        if cursor.fetchone() != ("kairos", "kairos_runtime", False):
            raise RuntimeError("isolated_runtime_identity_required")

    def expect(response, status):
        if response.status_code != status:
            # Never surface response bodies, which may include private data.
            raise RuntimeError("scoped_api_status:" + str(response.status_code) + ":expected:" + str(status))
        return response.json()

    def principal(role):
        user = User.objects.create_user(username="scoped-probe-" + uuid4().hex)
        UserRole.objects.create(user=user, role=Role.objects.get(slug=role))
        client = APIClient()
        client.force_login(user)
        session = client.session
        session["user_session_version"] = user.session_version
        session["mfa_verified"] = role != "aluno"
        session.save()
        return user, client

    with override_settings(ALLOWED_HOSTS=["testserver"], SECURE_SSL_REDIRECT=False,
            CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
            EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"), transaction.atomic():
        _, editor = principal("editor")
        _, reviewer = principal("revisor-juridico")
        _, publisher = principal("administrador-de-conteudo")
        student, learner = principal("aluno")
        _, outsider = principal("aluno")
        subject = Subject.objects.create(name="Synthetic isolated subject", slug="scoped-" + uuid4().hex)
        draft = expect(editor.post("/api/admin/content/", {
            "subject": str(subject.pk), "slug": "scoped-" + uuid4().hex, "kind": "lesson",
            "revision": {"title": "Synthetic isolated content", "body": "Not legal advice or published production content.",
                "source_url": "https://example.invalid/scoped-probe", "source_hash": "a" * 64}}, format="json"), 201)

        def transition(client, version, state, **extra):
            return client.post(f"/api/admin/content-versions/{version}/transition/", {
                "state": state, "justification": "Synthetic isolated human workflow check.", **extra}, format="json")

        expect(transition(learner, draft["id"], "review"), 403)
        expect(transition(editor, draft["id"], "review"), 200)
        expect(transition(editor, draft["id"], "approved", legal_status="current"), 403)
        approved = expect(transition(reviewer, draft["id"], "approved", legal_status="current"), 200)
        expect(transition(publisher, approved["id"], "published"), 200)
        payload = {"title": "Synthetic private note", "body": "Exact text\n\n  ",
            "creation_key": str(uuid4()), "expected_owner": str(student.pk),
            "subject": str(subject.pk), "content_version": approved["id"]}
        note = expect(learner.post("/api/notes/", payload, format="json"), 201)
        replay = expect(learner.post("/api/notes/", payload, format="json"), 201)
        if replay["id"] != note["id"] or note["body"] != payload["body"]:
            raise RuntimeError("scoped_note_identity_or_text_changed")
        url = f"/api/notes/{note['id']}/"
        expect(outsider.get(url), 404)
        changed = expect(learner.patch(url, {"body": "New exact text", "expected_version": 1}, format="json"), 200)
        if changed["version"] != 2:
            raise RuntimeError("scoped_note_version_not_incremented")
        expect(learner.patch(url, {"body": "Stale text", "expected_version": 1}, format="json"), 409)
        expect(transition(publisher, approved["id"], "archived"), 200)
        # Rollback includes sessions, audit records and immutable version inserts.
        transaction.set_rollback(True)
    return {"runtime_superuser": False, "editorial_api": "PASS", "note_api": "PASS",
        "ownership": "PASS", "idempotency": "PASS", "stale_write": "PASS", "synthetic_rows_rolled_back": True,
        "not_verified": ["edge_http", "browser", "password_login", "mfa_challenge", "whole_release_rollback"]}
