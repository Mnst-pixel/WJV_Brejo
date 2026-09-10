from uuid import uuid4
import pytest
from django.contrib import admin
from django.http import Http404
from django.test import RequestFactory
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.test import APIRequestFactory, force_authenticate
from core.content_models import ContentWorkflow, LegacyContentItem
from core.content_views import AdminContentListView, ContentTransitionView, RevisionInput
from core.content_workflow import _legacy_dataset, confirm_legacy, create_revision, preview_legacy, published_content, transition_content
from core.models import Content, ContentVersion, PublicationApproval, Question, Role, Subject, User, UserRole
from core.services.study_state import _target

pytestmark = pytest.mark.django_db


def principal(slug):
    user = User.objects.create_user(username=uuid4().hex)
    UserRole.objects.create(user=user, role=Role.objects.get(slug=slug))
    return user


@pytest.fixture
def editorial():
    author, reviewer, publisher = [principal(role) for role in ("editor", "revisor-juridico", "administrador-de-conteudo")]
    subject = Subject.objects.create(slug="etica", name="Ética")
    content = Content.objects.create(subject=subject, slug="aula", kind="lesson", created_by=author)
    version = create_revision(actor=author, content_id=content.pk, values={"title": "Aula", "body": "Texto revisável", "source_url": "https://example.invalid/oficial", "source_hash": "a" * 64})
    return author, reviewer, publisher, content, version


def transition(actor, version, state, **kwargs):
    return transition_content(actor=actor, version_id=version.pk, state=state, justification="Conferência humana fundamentada.", **kwargs)


def approve(editorial):
    transition(editorial[0], editorial[4], "review")
    return transition(editorial[1], editorial[4], "approved", legal_status="current")


def invoke(view, user, data, mfa=True, **kwargs):
    req = APIRequestFactory().post("/api/admin/content/", data, format="json")
    req.session = {"mfa_verified": mfa, "user_session_version": user.session_version}
    force_authenticate(req, user=user)
    return view.as_view()(req, **kwargs)


def test_full_workflow_preserves_immutable_versions(editorial):
    author, reviewer, publisher, content, old = editorial
    approved = approve(editorial)
    assert approved.pk != old.pk and approved.supersedes_id == old.pk
    old.refresh_from_db()
    assert old.legal_status == "legacy_unverified" and old.approved_by_id is None
    assert approved.approved_by == reviewer and approved.approval_date
    assert not published_content().exists()
    transition(publisher, approved, "published")
    assert published_content().get().pk == content.pk
    assert ContentWorkflow.objects.get(version=approved).published_by == publisher
    _target("content", content.pk)
    transition(publisher, approved, "archived")
    assert not published_content().exists()
    with pytest.raises(Http404):
        _target("content", content.pk)
    assert ContentVersion.objects.count() == 2


def test_editor_and_author_cannot_approve_or_publish(editorial):
    author, reviewer, publisher, content, version = editorial
    transition(author, version, "review")
    with pytest.raises(PermissionDenied):
        transition(author, version, "approved", legal_status="current")
    UserRole.objects.create(user=author, role=Role.objects.get(slug="administrador"))
    with pytest.raises(PermissionDenied, match="próprio"):
        transition(author, version, "approved", legal_status="current")
    with pytest.raises(ValidationError):
        transition(publisher, version, "published")


def test_new_draft_does_not_remove_published_version(editorial):
    author, reviewer, publisher, content, version = editorial
    approved = approve(editorial)
    transition(publisher, approved, "published")
    successor = create_revision(actor=author, content_id=content.pk, values={"title": "Revisão", "body": "Novo texto", "source_url": "https://example.invalid/oficial", "source_hash": "b" * 64})
    content.refresh_from_db()
    assert content.current_version_id == approved.pk and content.status == "published"
    assert successor.version_number == 3
    transition(author, successor, "review")
    next_approved = transition(reviewer, successor, "approved", legal_status="historical")
    transition(publisher, next_approved, "published")
    assert ContentWorkflow.objects.get(version=approved).state == "archived"
    assert published_content().get().current_version_id == next_approved.pk


def test_publication_rejects_tampering(editorial):
    approved = approve(editorial)
    ContentVersion.objects.filter(pk=approved.pk).update(body="Texto adulterado via DBA de teste")
    with pytest.raises(PermissionDenied, match="íntegra"):
        transition(editorial[2], approved, "published")
    assert not published_content().exists()


def test_status_pointer_alone_cannot_publish_or_create_progress(editorial):
    content = editorial[3]
    Content.objects.filter(pk=content.pk).update(status="published")
    assert not published_content().exists()
    with pytest.raises(Http404):
        _target("content", content.pk)


@pytest.mark.parametrize("role", ["aluno", "suporte", "conta-de-servico"])
def test_non_editorial_roles_denied_by_backend(role, editorial):
    actor = principal(role)
    assert invoke(ContentTransitionView, actor, {"state": "review", "justification": "Tentativa proibida"}, version_id=editorial[4].pk).status_code == 403
    assert invoke(AdminContentListView, actor, {}).status_code == 403


def test_api_mfa_and_strict_status_fields(editorial):
    author = editorial[0]
    assert invoke(ContentTransitionView, author, {"state": "review", "justification": "Conferir fonte oficial"}, mfa=False, version_id=editorial[4].pk).status_code == 403
    data = RevisionInput(data={"title": "X", "body": "Y", "source_url": "https://example.invalid/doc", "source_hash": "a" * 64, "approved_by": str(author.pk)})
    assert not data.is_valid()
    request = RequestFactory().get("/admin/")
    request.user = author
    request.session = {"mfa_verified": True, "user_session_version": author.session_version}
    assert {"status", "current_version"} <= set(admin.site._registry[Content].get_readonly_fields(request))
    assert ContentWorkflow not in admin.site._registry


def test_legacy_preview_confirm_private_idempotent_unpublished(editorial):
    author, reviewer, publisher, content, version = editorial
    batch, preview = preview_legacy(actor=author, dataset="questions", subject_id=content.subject_id)
    assert len(preview) == 101 and LegacyContentItem.objects.count() == 0
    with pytest.raises(Http404):
        confirm_legacy(actor=publisher, batch_id=batch.pk, expected_hash=batch.preview_sha256)
    with pytest.raises(ValidationError):
        confirm_legacy(actor=author, batch_id=batch.pk, expected_hash="0" * 64)
    confirmed = confirm_legacy(actor=author, batch_id=batch.pk, expected_hash=batch.preview_sha256)
    assert confirmed.result == {"created": 101, "duplicates": 0, "published": 0, "legal_status": "legacy_unverified"}
    assert confirm_legacy(actor=author, batch_id=batch.pk, expected_hash=batch.preview_sha256).result == confirmed.result
    assert LegacyContentItem.objects.count() == 101 and Question.objects.count() == 0
    assert not published_content().exists()
    legacy = LegacyContentItem.objects.first().version
    assert legacy.legal_status == "legacy_unverified" and legacy.workflow.state == "review"
    with pytest.raises(ValidationError, match="HTTPS"):
        transition(reviewer, legacy, "approved", legal_status="current")
    another, _ = preview_legacy(actor=publisher, dataset="questions", subject_id=content.subject_id)
    result = confirm_legacy(actor=publisher, batch_id=another.pk, expected_hash=another.preview_sha256)
    assert result.result["duplicates"] == 101 and result.result["created"] == 0


def test_import_rejects_changed_dataset_and_paths(editorial, monkeypatch):
    from core import content_workflow
    author, _, _, content, _ = editorial
    batch, _ = preview_legacy(actor=author, dataset="oab", subject_id=content.subject_id)
    assert batch.item_count == 95
    monkeypatch.setattr(content_workflow, "_legacy_dataset", lambda dataset: ("f" * 64, []))
    with pytest.raises(ValidationError, match="mudou"):
        confirm_legacy(actor=author, batch_id=batch.pk, expected_hash=batch.preview_sha256)
    assert not LegacyContentItem.objects.exists()
    with pytest.raises(ValidationError):
        _legacy_dataset("../../.env")


def test_approval_foreign_target_is_rejected(editorial):
    approved = approve(editorial)
    PublicationApproval.objects.filter(pk=approved.workflow.approval_id).update(object_id=uuid4())
    with pytest.raises(PermissionDenied):
        transition(editorial[2], approved, "published")


def test_api_creates_draft_and_returns_approved_successor(editorial):
    author, reviewer, publisher, content, _ = editorial
    response = invoke(AdminContentListView, author, {"subject": str(content.subject_id), "slug": "api-draft", "kind": "lesson", "revision": {"title": "API", "body": "Texto de revisão", "source_url": "https://example.invalid/doc", "source_hash": "b" * 64}})
    assert response.status_code == 201, response.data
    draft_id = response.data["id"]
    response = invoke(ContentTransitionView, author, {"state": "review", "justification": "Conferir fonte oficial"}, version_id=draft_id)
    assert response.status_code == 200
    response = invoke(ContentTransitionView, reviewer, {"state": "approved", "justification": "Fonte conferida por humano", "legal_status": "historical"}, version_id=draft_id)
    assert response.status_code == 200 and response.data["id"] != draft_id
    response = invoke(ContentTransitionView, publisher, {"state": "published", "justification": "Publicação autorizada"}, version_id=response.data["id"])
    assert response.status_code == 200 and response.data["workflow"]["state"] == "published"


def test_item_dedup_survives_dataset_reformat(editorial, monkeypatch):
    from core import content_workflow
    author, _, _, content, _ = editorial
    _, items = _legacy_dataset("questions")
    monkeypatch.setattr(content_workflow, "_legacy_dataset", lambda dataset: ("a" * 64, items[:1]))
    batch, _ = preview_legacy(actor=author, dataset="questions", subject_id=content.subject_id)
    confirm_legacy(actor=author, batch_id=batch.pk, expected_hash=batch.preview_sha256)
    monkeypatch.setattr(content_workflow, "_legacy_dataset", lambda dataset: ("b" * 64, items[:1]))
    second, _ = preview_legacy(actor=author, dataset="questions", subject_id=content.subject_id)
    confirmed = confirm_legacy(actor=author, batch_id=second.pk, expected_hash=second.preview_sha256)
    assert confirmed.result["duplicates"] == 1 and confirmed.result["created"] == 0
    assert LegacyContentItem.objects.count() == 1


def test_access_revoked_during_command(editorial):
    author, _, _, _, version = editorial
    User.objects.filter(pk=author.pk).update(session_version=author.session_version + 1)
    with pytest.raises(PermissionDenied, match="alterado"):
        transition(author, version, "review")


def test_document_publication_rechecks_exact_approved_payload(reviewer):
    from django.utils import timezone
    from core.models import SourceDocument, SourceDocumentVersion, SourceRegistry
    from core.services.documents import transition_document_version
    registry = SourceRegistry.objects.create(organization="Teste", domain="example.invalid", source_type="legislation", jurisdiction="federal", access_method="manual-test")
    document = SourceDocument.objects.create(source_registry=registry, canonical_url="https://example.invalid/doc", title="Documento", jurisdiction="federal", document_type="law")
    version = SourceDocumentVersion.objects.create(document=document, version_number=1, state="human_review", source_hash="b" * 64, source_url=document.canonical_url, retrieved_at=timezone.now(), normalized_text="Texto aprovado")
    transition_document_version(version_id=version.pk, actor=reviewer, next_state="approved", justification="Conferido com fonte oficial")
    transition_document_version(version_id=version.pk, actor=reviewer, next_state="indexed", justification="")
    SourceDocumentVersion.objects.filter(pk=version.pk).update(normalized_text="Texto diferente")
    publisher = principal("administrador-de-conteudo")
    with pytest.raises(PermissionDenied, match="íntegra"):
        transition_document_version(version_id=version.pk, actor=publisher, next_state="published", justification="Tentativa inválida")
    SourceDocumentVersion.objects.filter(pk=version.pk).update(normalized_text="Texto aprovado")
    transition_document_version(version_id=version.pk, actor=publisher, next_state="published", justification="Publicação autorizada")
    with pytest.raises(ValidationError, match="retirar"):
        transition_document_version(version_id=version.pk, actor=reviewer, next_state="failed", justification="Crawler falhou")


def test_admin_stale_draft_cannot_overwrite_new_publication(editorial):
    from django.core.exceptions import PermissionDenied as AdminDenied
    from types import SimpleNamespace
    author, _, publisher, content, _ = editorial
    stale = Content.objects.get(pk=content.pk)
    approved = approve(editorial)
    transition(publisher, approved, "published")
    author.mfa_enabled = True
    author.save(update_fields=["mfa_enabled"])
    request = RequestFactory().post("/admin/core/content/change/")
    request.user = author
    request.session = {"mfa_verified": True, "user_session_version": author.session_version}
    stale.kind = "summary"
    with pytest.raises(AdminDenied):
        admin.site._registry[Content].save_model(request, stale, SimpleNamespace(changed_data=["kind"]), True)
    content.refresh_from_db()
    assert content.current_version_id == approved.pk and content.status == "published" and content.kind == "lesson"


def test_admin_draft_edit_preserves_newer_draft_pointer(editorial):
    from types import SimpleNamespace
    author, _, _, content, _ = editorial
    stale = Content.objects.get(pk=content.pk)
    next_version = create_revision(actor=author, content_id=content.pk, values={"title": "Nova revisão", "body": "Texto novo", "source_url": "https://example.invalid/doc", "source_hash": "b" * 64})
    author.mfa_enabled = True
    author.save(update_fields=["mfa_enabled"])
    request = RequestFactory().post("/admin/core/content/change/")
    request.user = author
    request.session = {"mfa_verified": True, "user_session_version": author.session_version}
    stale.kind = "summary"
    admin.site._registry[Content].save_model(request, stale, SimpleNamespace(changed_data=["kind"]), True)
    content.refresh_from_db()
    assert content.current_version_id == next_version.pk and content.kind == "summary"


def test_published_read_gate_rejects_approval_for_wrong_model(editorial):
    from django.contrib.contenttypes.models import ContentType
    approved = approve(editorial)
    transition(editorial[2], approved, "published")
    PublicationApproval.objects.filter(pk=approved.workflow.approval_id).update(content_type=ContentType.objects.get_for_model(Question))
    assert not published_content().exists()


def _concurrent_commands(commands):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from django.db import close_old_connections, connections
    from rest_framework.exceptions import APIException
    barrier = Barrier(len(commands))

    def execute(command):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            try:
                return (200, command())
            except APIException as exc:
                return (exc.status_code, None)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=len(commands)) as pool:
        results = [pool.submit(execute, command) for command in commands]
        return [future.result(timeout=30) for future in results]


def _require_isolated_postgres():
    from django.conf import settings
    from django.db import connection
    if not getattr(settings, "KAIROS_ISOLATED_INTEGRATION_TESTS", False) or connection.vendor != "postgresql":
        pytest.skip("Concurrent content commands require isolated PostgreSQL")


@pytest.mark.django_db(transaction=True)
def test_concurrent_revisions_get_distinct_monotonic_numbers(editorial):
    _require_isolated_postgres()
    author, _, _, content, _ = editorial
    other = principal("editor")
    values = {"title": "Revisão concorrente", "body": "Texto", "source_url": "https://example.invalid/doc", "source_hash": "c" * 64}
    results = _concurrent_commands([
        lambda: create_revision(actor=author, content_id=content.pk, values=values).version_number,
        lambda: create_revision(actor=other, content_id=content.pk, values=values).version_number,
    ])
    assert sorted(results) == [(200, 2), (200, 3)]
    assert content.versions.count() == 3


@pytest.mark.django_db(transaction=True)
def test_concurrent_publication_has_one_winner(editorial):
    _require_isolated_postgres()
    approved = approve(editorial)
    other = principal("administrador-de-conteudo")
    results = _concurrent_commands([
        lambda: transition(editorial[2], approved, "published").pk,
        lambda: transition(other, approved, "published").pk,
    ])
    assert sorted(status for status, _ in results) == [200, 400]
    assert ContentWorkflow.objects.filter(state="published", version__content=editorial[3]).count() == 1
    assert published_content().get().current_version_id == approved.pk


@pytest.mark.django_db(transaction=True)
def test_concurrent_legacy_import_deduplicates_across_editors(editorial, monkeypatch):
    _require_isolated_postgres()
    from core import content_workflow
    author, _, _, content, _ = editorial
    other = principal("editor")
    _, items = _legacy_dataset("questions")
    monkeypatch.setattr(content_workflow, "_legacy_dataset", lambda dataset: ("c" * 64, items[:1]))
    batch, _ = preview_legacy(actor=author, dataset="questions", subject_id=content.subject_id)
    second, _ = preview_legacy(actor=other, dataset="questions", subject_id=content.subject_id)
    results = _concurrent_commands([
        lambda: confirm_legacy(actor=author, batch_id=batch.pk, expected_hash=batch.preview_sha256).result,
        lambda: confirm_legacy(actor=other, batch_id=second.pk, expected_hash=second.preview_sha256).result,
    ])
    assert [status for status, _ in results] == [200, 200]
    assert sorted(result["created"] for _, result in results) == [0, 1]
    assert sorted(result["duplicates"] for _, result in results) == [0, 1]
    assert LegacyContentItem.objects.count() == 1
