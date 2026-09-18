import json
from copy import deepcopy

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from core.content_workflow import published_content
from core.editorial_forms import RevisionForm
from core.editorial_views import revision_values
from core.models import ContentVersion, Role, Subject, User, UserRole
from core.rich_text import SCHEMA, document_text, normalize_document, render_document
from core.templatetags.editorial_text import version_text

pytestmark = pytest.mark.django_db


def document():
    return {"schema": SCHEMA, "blocks": [
        {"type": "heading2", "content": [{"text": "Princípios"}]},
        {"type": "paragraph", "content": [{"text": "Texto ", "bold": True}, {"text": "revisado", "italic": True}]},
        {"type": "bullet_list", "items": [[{"text": "Regra"}], [{"text": "Exceção"}]]},
        {"type": "quote", "content": [{"text": "Fonte humana"}]},
    ]}


def test_rich_ast_plain_projection_and_escaped_rendering():
    doc = normalize_document(document())
    assert document_text(doc) == "Princípios\n\nTexto revisado\n\nRegra\nExceção\n\nFonte humana"
    output = str(render_document(doc))
    assert "<strong>Texto </strong>" in output and "<em>revisado</em>" in output
    assert "<ul><li>Regra</li><li>Exceção</li></ul>" in output
    doc["blocks"][0]["content"] = [{"text": '<img src=x onerror="alert(1)"><script>unsafe</script>'}]
    output = str(render_document(doc))
    assert "<img" not in output and "<script>" not in output
    assert "&lt;img" in output


@pytest.mark.parametrize("value", [None, [], {}, {"schema": SCHEMA, "blocks": []},
    {"schema": SCHEMA, "blocks": [{"type": "iframe", "content": []}]},
    {"schema": SCHEMA, "blocks": [{"type": [], "content": []}]},
    {"schema": SCHEMA, "blocks": [{"type": "paragraph", "content": [{"text": "a", "href": "javascript:alert(1)"}]}]},
    {"schema": SCHEMA, "blocks": [{"type": "paragraph", "content": [{"text": "a", "bold": "true"}]}]},
    {"schema": SCHEMA, "blocks": [{"type": "paragraph", "content": [{"text": "\x00"}]}]},
    {"schema": SCHEMA, "blocks": [{"type": "bullet_list", "items": []}]},
    {"schema": SCHEMA, "blocks": [{"type": "ordered_list", "items": [[{"text": "a"}]]}] * 1001},
    {"schema": SCHEMA, "blocks": [{"type": "paragraph", "content": [{"text": "x" * 100001}]}]},
    {"schema": SCHEMA, "blocks": [{"type": "paragraph", "content": [{"text": "a"}] * 5001}]}])
def test_rich_ast_rejects_executable_unknown_or_unbounded_shapes(value):
    with pytest.raises(ValidationError):
        normalize_document(value)


def test_form_plain_fallback_and_server_projection_consistency():
    doc = document()
    values = {"title": "Revisão", "body": document_text(doc), "source_url": "https://example.invalid/fonte", "rich_document": json.dumps(doc)}
    form = RevisionForm(values)
    assert form.is_valid(), form.errors
    saved = revision_values(form.cleaned_data)
    assert saved["body"] == values["body"] and saved["structured_data"]["rich_text"] == doc
    windows = RevisionForm({**values, "body": values["body"].replace("\n", "\r\n")})
    assert windows.is_valid(), windows.errors
    assert windows.cleaned_data["body"] == values["body"]
    assert "rich_document" not in saved
    changed = RevisionForm({**values, "body": "Different visible text"})
    assert not changed.is_valid() and "body" in changed.errors
    for malformed in ("{" * 2000, '{"blocks":', '"not a document"'):
        assert not RevisionForm({**values, "rich_document": malformed}).is_valid()
    fallback = RevisionForm({**values, "rich_document": ""})
    assert fallback.is_valid()
    assert "rich_text" not in revision_values(fallback.cleaned_data)["structured_data"]


def test_seed_not_submitted_without_running_editor():
    doc = document()
    form = RevisionForm(initial={"body": document_text(doc), "rich_document": json.dumps(doc)})
    assert form["rich_document"].value() == ""
    assert json.loads(form.fields["body"].widget.attrs["data-rich-seed"]) == doc


def test_visual_document_preserved_through_independent_review_and_revision(client_for):
    clients = {}
    for role in ("editor", "revisor-juridico", "administrador-de-conteudo", "aluno"):
        user = User.objects.create_user(username="rich-" + role, is_staff=role != "aluno", mfa_enabled=role != "aluno")
        UserRole.objects.create(user=user, role=Role.objects.get(slug=role), granted_by=user)
        clients[role] = client_for(user)
    doc = document()
    subject = Subject.objects.create(name="Ética", slug="rich-ethics")
    data = {"subject": subject.pk, "kind": "lesson", "title": "Documento visual", "body": document_text(doc), "rich_document": json.dumps(doc), "source_url": "https://example.invalid/fonte"}
    assert clients["aluno"].post(reverse("editorial:content-create"), data).status_code == 403
    assert clients["editor"].post(reverse("editorial:content-create"), data).status_code == 302
    original = ContentVersion.objects.latest("created_at")
    def decision(role, version, state):
        return clients[role].post(reverse("editorial:version", args=[version.pk]), {"state": state, "legal_status": "current", "justification": "Conferência humana independente do texto."})
    assert decision("editor", original, "review").status_code == 302
    assert decision("editor", original, "approved").status_code == 403
    assert decision("revisor-juridico", original, "approved").status_code == 302
    approved = ContentVersion.objects.get(legal_status="current")
    assert approved.structured_data["rich_text"] == doc
    assert decision("administrador-de-conteudo", approved, "published").status_code == 302
    preview = clients["editor"].get(reverse("editorial:version", args=[approved.pk])).content.decode()
    assert "<strong>Texto </strong>" in preview
    reading = clients["aluno"].get(f"/api/study/reading/{approved.content_id}/")
    assert reading.status_code == 200 and reading.json()["content"]["current_version"]["structured_data"]["rich_text"] == doc
    revise = clients["editor"].get(reverse("editorial:revise", args=[approved.pk]))
    assert json.loads(revise.context["form"].fields["body"].widget.attrs["data-rich-seed"]) == doc
    assert clients["editor"].post(reverse("editorial:revise", args=[approved.pk]), data).status_code == 302
    assert published_content().get().current_version_id == approved.pk
    successor = ContentVersion.objects.latest("created_at")
    assert successor.workflow.state == "draft" and successor.structured_data["rich_text"] == doc
    mutated = deepcopy(doc)
    mutated["blocks"][0]["content"][0]["bold"] = True
    ContentVersion.objects.filter(pk=approved.pk).update(structured_data={**approved.structured_data, "rich_text": mutated})
    assert clients["aluno"].get(f"/api/study/reading/{approved.content_id}/").status_code == 403


def test_invalid_stored_formatting_falls_back_to_escaped_plain_text():
    from types import SimpleNamespace
    for rich in (None, {"schema": "unknown"}, document()):
        version = SimpleNamespace(body="<script>private text</script>", structured_data={"rich_text": rich})
        result = str(version_text(version))
        assert "<script>" not in result and "&lt;script&gt;private text&lt;/script&gt;" in result


def test_api_cannot_bypass_rich_document_validation(client_for):
    user = User.objects.create_user(username="rich-api-editor", mfa_enabled=True, is_staff=True)
    UserRole.objects.create(user=user, role=Role.objects.get(slug="editor"), granted_by=user)
    subject = Subject.objects.create(name="Ética API", slug="rich-api-ethics")
    invalid = {"schema": SCHEMA, "blocks": [{"type": "iframe", "src": "javascript:alert(1)"}]}
    payload = {"subject": str(subject.pk), "slug": "invalid-rich-api", "kind": "lesson", "revision": {
        "title": "Invalid rich structure", "body": "Plain text", "source_url": "https://example.invalid/fonte", "source_hash": "a" * 64,
        "structured_data": {"rich_text": invalid}}}
    response = client_for(user).post("/api/admin/content/", payload, format="json")
    assert response.status_code == 400
    assert not ContentVersion.objects.exists()


def test_old_invalid_rich_draft_cannot_be_approved_or_silently_repaired(client_for):
    from core.content_workflow import create_revision, transition_content
    from core.models import Content
    from rest_framework.exceptions import ValidationError as APIValidationError
    author = User.objects.create_user(username="rich-old-author")
    reviewer = User.objects.create_user(username="rich-old-reviewer")
    UserRole.objects.create(user=author, role=Role.objects.get(slug="editor"), granted_by=author)
    UserRole.objects.create(user=reviewer, role=Role.objects.get(slug="revisor-juridico"), granted_by=reviewer)
    subject = Subject.objects.create(name="Ética antiga", slug="old-rich")
    content = Content.objects.create(subject=subject, slug="old-rich", kind="lesson", created_by=author)
    version = create_revision(actor=author, content_id=content.pk, values={"title": "Old draft", "body": "Plain text", "source_url": "https://example.invalid/fonte", "source_hash": "a" * 64})
    invalid = {"rich_text": {"schema": SCHEMA, "blocks": [{"type": "iframe", "src": "javascript:alert(1)"}]}}
    ContentVersion.objects.filter(pk=version.pk).update(structured_data=invalid)
    transition_content(actor=author, version_id=version.pk, state="review", justification="Submeter para conferência humana.")
    with pytest.raises(APIValidationError):
        transition_content(actor=reviewer, version_id=version.pk, state="approved", justification="Conferência humana independente.", legal_status="current")
    version.refresh_from_db()
    assert version.structured_data == invalid and version.workflow.state == "review"
    assert ContentVersion.objects.count() == 1
