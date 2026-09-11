from uuid import uuid4

import pytest
from django.test import Client
from django.urls import reverse

from core.content_workflow import published_content
from core.models import Content, ContentVersion, Role, Subject, Topic, User, UserRole

pytestmark = pytest.mark.django_db


def operator(role, mfa=True):
    user = User.objects.create_user(username=uuid4().hex, mfa_enabled=mfa)
    UserRole.objects.create(user=user, role=Role.objects.get(slug=role))
    client = Client()
    client.force_login(user)
    session = client.session
    session["user_session_version"] = user.session_version
    session["mfa_verified"] = mfa
    session.save()
    return client, user


def draft(client):
    subject = Subject.objects.create(name="Direito Constitucional", slug=uuid4().hex)
    response = client.post(reverse("editorial:content-create"), {
        "subject": str(subject.pk), "kind": "lesson", "title": "Direitos fundamentais",
        "body": "Texto jurídico para conferência humana.", "source_url": "https://www.planalto.gov.br/constituicao",
        "reference_date": "2026-09-10", "changes_summary": "Versão inicial",
    })
    assert response.status_code == 302
    return ContentVersion.objects.latest("created_at")


def decision(client, version, state):
    return client.post(reverse("editorial:version", args=[version.pk]), {
        "state": state, "justification": "Conferência humana da fonte e do texto.", "legal_status": "current",
    })


def test_editorial_complete_human_workflow_and_restore():
    editor, author = operator("editor")
    reviewer, _ = operator("revisor-juridico")
    publisher, _ = operator("administrador-de-conteudo")
    assert editor.post(reverse("editorial:subject-create"), {"name": "Ética"}).status_code == 302
    version = draft(editor)
    assert version.workflow.author == author
    assert not published_content().exists()
    assert decision(editor, version, "review").status_code == 302
    assert decision(reviewer, version, "approved").status_code == 302
    approved = ContentVersion.objects.get(legal_status="current")
    assert decision(publisher, approved, "published").status_code == 302
    assert published_content().get().current_version_id == approved.pk
    response = editor.post(reverse("editorial:revise", args=[version.pk]), {
        "title": "Texto restaurado", "body": version.body, "source_url": version.source_url,
        "changes_summary": "Restauração consciente para nova revisão.",
    })
    assert response.status_code == 302
    assert published_content().get().current_version_id == approved.pk
    restored = ContentVersion.objects.get(title="Texto restaurado")
    assert restored.workflow.state == "draft" and restored.approved_by_id is None
    assert restored.structured_data["provenance"]["restored_from_version"] == str(version.pk)
    assert editor.get(reverse("editorial:content", args=[version.content_id])).status_code == 200


@pytest.mark.parametrize("role", ["aluno", "suporte", "conta-de-servico"])
def test_student_support_and_machine_cannot_enter_or_create(role):
    client, _ = operator(role)
    for route in ["dashboard", "contents", "content-create", "subject-create", "legacy"]:
        status = 200 if role == "suporte" and route == "dashboard" else 403
        assert client.get(reverse("editorial:" + route)).status_code == status
        assert client.post(reverse("editorial:" + route), {"name": "Ataque"}).status_code == status
    assert Subject.objects.count() == 0


def test_editor_without_mfa_rejected_even_without_staff_flag():
    client, user = operator("editor", mfa=False)
    assert not user.is_staff
    assert client.get(reverse("editorial:dashboard")).status_code == 403
    session = client.session
    session["mfa_verified"] = True
    session.save()
    assert client.get(reverse("editorial:dashboard")).status_code == 403


def test_author_cannot_approve_and_editor_cannot_publish():
    editor, author = operator("editor")
    version = draft(editor)
    assert decision(editor, version, "published").status_code == 200  # readable stale-decision error
    assert version.workflow.state == "draft"
    decision(editor, version, "review")
    assert decision(editor, version, "approved").status_code == 403
    UserRole.objects.create(user=author, role=Role.objects.get(slug="administrador"))
    assert decision(editor, version, "approved").status_code == 403
    assert not published_content().exists()


def test_duplicate_publication_never_archives_approved_version():
    editor, _ = operator("editor")
    reviewer, _ = operator("revisor-juridico")
    publisher, _ = operator("administrador-de-conteudo")
    version = draft(editor)
    decision(editor, version, "review")
    decision(reviewer, version, "approved")
    approved = ContentVersion.objects.get(legal_status="current")
    decision(publisher, approved, "published")
    response = decision(publisher, approved, "published")
    assert response.status_code == 200 and "A situação mudou" in response.content.decode()
    assert published_content().get().current_version_id == approved.pk


def test_csrf_is_required():
    client, _ = operator("editor")
    protected = Client(enforce_csrf_checks=True)
    protected.cookies = client.cookies
    assert protected.post(reverse("editorial:subject-create"), {"name": "Ataque CSRF"}).status_code == 403
    assert not Subject.objects.exists()


def test_revoked_role_and_session_cannot_mutate():
    client, user = operator("editor")
    UserRole.objects.filter(user=user).delete()
    assert client.post(reverse("editorial:subject-create"), {"name": "Revogado"}).status_code == 403
    UserRole.objects.create(user=user, role=Role.objects.get(slug="editor"))
    User.objects.filter(pk=user.pk).update(session_version=user.session_version + 1)
    assert client.post(reverse("editorial:subject-create"), {"name": "Sessão antiga"}).status_code == 401
    assert not Subject.objects.exists()


def test_preview_escapes_untrusted_html_and_cannot_inject_permissions():
    client, _ = operator("editor")
    version = draft(client)
    response = client.post(reverse("editorial:revise", args=[version.pk]), {
        "title": "<script>alert(1)</script>", "body": "<img src=x onerror=alert(2)>", "source_url": version.source_url,
        "status": "published", "legal_status": "current", "is_superuser": "true",
    }, follow=True)
    html = response.content.decode()
    assert response.status_code == 200
    assert "<script>" not in html and "<img src=x" not in html
    assert "&lt;script&gt;" in html and "&lt;img" in html
    assert "private, no-store" == response["Cache-Control"]
    assert not published_content().exists()


def test_invalid_dates_source_and_parent_are_readable():
    client, _ = operator("editor")
    version = draft(client)
    response = client.post(reverse("editorial:revise", args=[version.pk]), {
        "title": "Inválido", "body": "Texto", "source_url": "https://user:password@example.invalid/",
        "valid_from": "2026-09-10", "valid_to": "2020-01-01",
    })
    assert response.status_code == 200 and "sem credenciais" in response.content.decode()
    assert ContentVersion.objects.count() == 1
    other = Subject.objects.create(name="Direito Penal", slug="penal")
    parent = Topic.objects.create(subject=other, name="Tema", slug="tema")
    response = client.post(reverse("editorial:topic-create"), {"subject": version.content.subject_id, "parent": parent.pk, "name": "Subtema"})
    assert "pertencer à disciplina" in response.content.decode()
    assert Topic.objects.count() == 1


def test_taxonomy_hierarchy_and_pagination():
    client, _ = operator("editor")
    subject = Subject.objects.create(name="Ética", slug="etica")
    assert client.post(reverse("editorial:topic-create"), {"subject": subject.pk, "name": "Advocacia"}).status_code == 302
    parent = Topic.objects.get()
    assert client.post(reverse("editorial:topic-create"), {"subject": subject.pk, "parent": parent.pk, "name": "Prerrogativas"}).status_code == 302
    child = Topic.objects.get(parent=parent)
    response = client.post(reverse("editorial:topic-create"), {"subject": subject.pk, "parent": child.pk, "name": "Quarto nível"})
    assert response.status_code == 200 and Topic.objects.count() == 2
    assert "Prerrogativas" in client.get(reverse("editorial:taxonomy")).content.decode()


def test_anonymous_redirect_is_local():
    response = Client().get(reverse("editorial:dashboard"))
    assert response.status_code == 302 and response.url == "/app/entrar/?editorial=1"


def test_taxonomy_respects_postgresql_column_lengths():
    client, _ = operator("editor")
    response = client.post(reverse("editorial:subject-create"), {"name": "a" * 160})
    assert response.status_code == 302
    subject = Subject.objects.get()
    subject.full_clean()
    assert len(subject.slug) <= Subject._meta.get_field("slug").max_length
    response = client.post(reverse("editorial:subject-create"), {"name": "b" * 161})
    assert response.status_code == 200 and Subject.objects.count() == 1


def test_parent_changed_after_validation_is_rejected(monkeypatch):
    from core import editorial_views
    client, _ = operator("editor")
    subject = Subject.objects.create(name="Ética", slug="etica")
    other = Subject.objects.create(name="Penal", slug="penal")
    parent = Topic.objects.create(subject=subject, name="Tema", slug="tema")
    authorize = editorial_views.authorize

    def changed(*args, **kwargs):
        authorize(*args, **kwargs)
        Topic.objects.filter(pk=parent.pk).update(subject=other)

    monkeypatch.setattr(editorial_views, "authorize", changed)
    response = client.post(reverse("editorial:topic-create"), {"subject": subject.pk, "parent": parent.pk, "name": "Subtema"})
    assert response.status_code == 400 and "tema principal mudou" in response.content.decode()
    assert Topic.objects.count() == 1


def test_specialist_admin_cannot_reparent_or_bypass_topic_creation():
    from django.contrib import admin
    from django.test import RequestFactory
    _, user = operator("editor")
    req = RequestFactory().get("/admin/core/topic/")
    req.user = user
    req.session = {"mfa_verified": True, "user_session_version": user.session_version}
    model_admin = admin.site._registry[Topic]
    assert not model_admin.has_add_permission(req)
    form = model_admin.get_form(req)
    assert not {"subject", "parent", "slug"} & form.base_fields.keys()


def test_invalid_list_filter_does_not_return_all_content():
    client, _ = operator("editor")
    draft(client)
    response = client.get(reverse("editorial:contents"), {"state": "invalid"})
    assert response.status_code == 200 and response.context["page"].paginator.count == 0
    assert Content.objects.count() == 1
