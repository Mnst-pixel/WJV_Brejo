import hashlib
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.utils import timezone

from core.models import (
    Agent,
    DocumentChunk,
    PromptTemplate,
    PromptVersion,
    SourceDocument,
    SourceDocumentVersion,
    SourceRegistry,
    User,
)
from core.services.retrieval import hybrid_retrieve, index_published_version


def make_version(*, state: str, jurisdiction: str = "Brasil") -> SourceDocumentVersion:
    approved = state == SourceDocumentVersion.PipelineState.PUBLISHED
    reviewer, _ = User.objects.get_or_create(username="synthetic-corpus-reviewer")
    registry, _ = SourceRegistry.objects.get_or_create(
        organization="Fonte oficial de teste",
        domain="example.invalid",
        jurisdiction=jurisdiction,
        defaults={"source_type": "legislation", "access_method": "HTTPS"},
    )
    document = SourceDocument.objects.create(
        source_registry=registry,
        canonical_url=f"https://example.invalid/{state}/{SourceDocument.objects.count()}",
        title="Documento oficial de teste",
        jurisdiction=jurisdiction,
        document_type="lei",
    )
    version = SourceDocumentVersion.objects.create(
        document=document,
        version_number=1,
        state=state,
        source_hash=hashlib.sha256(f"{document.pk}".encode()).hexdigest(),
        source_url=document.canonical_url,
        retrieved_at=timezone.now(),
        published_at=timezone.now()
        if state == SourceDocumentVersion.PipelineState.PUBLISHED
        else None,
        approved_by=reviewer if approved else None,
        approval_date=timezone.now() if approved else None,
    )
    if approved:
        from django.contrib.contenttypes.models import ContentType
        from core.models import PublicationApproval
        from core.content_workflow import fingerprint
        digest = fingerprint({key: getattr(version, key) for key in ("document_id", "version_number", "source_hash", "source_url", "valid_from", "valid_to", "reference_date", "normalized_text", "parsed_structure")})
        PublicationApproval.objects.create(content_type=ContentType.objects.get_for_model(version), object_id=version.pk,
            reviewer=reviewer, decision="approved", justification="Aprovação sintética explícita de teste",
            evidence={"source_hash": version.source_hash, "version_sha256": digest})
    return version


@pytest.mark.django_db
def test_retrieval_is_fail_closed_to_published_content():
    published = make_version(state=SourceDocumentVersion.PipelineState.PUBLISHED)
    draft = make_version(state=SourceDocumentVersion.PipelineState.HUMAN_REVIEW)
    approved_chunk = DocumentChunk.objects.create(
        document_version=published,
        ordinal=1,
        text="A liberdade profissional depende das qualificações estabelecidas em lei.",
        source_locator="Constituição, art. 5º, XIII",
        source_hash=published.source_hash,
    )
    DocumentChunk.objects.create(
        document_version=draft,
        ordinal=1,
        text="A liberdade profissional depende das qualificações estabelecidas em lei.",
        source_locator="Rascunho não aprovado",
        source_hash=draft.source_hash,
    )

    results = hybrid_retrieve(question="liberdade profissional", context={}, limit=6)

    assert results == [approved_chunk]


@pytest.mark.django_db
def test_retrieval_applies_jurisdiction_filter():
    federal = make_version(
        state=SourceDocumentVersion.PipelineState.PUBLISHED, jurisdiction="Brasil"
    )
    state = make_version(
        state=SourceDocumentVersion.PipelineState.PUBLISHED, jurisdiction="São Paulo"
    )
    expected = DocumentChunk.objects.create(
        document_version=federal,
        ordinal=1,
        text="regra nacional de processo civil",
        source_locator="fonte federal",
        source_hash=federal.source_hash,
    )
    DocumentChunk.objects.create(
        document_version=state,
        ordinal=1,
        text="regra nacional de processo civil",
        source_locator="fonte estadual",
        source_hash=state.source_hash,
    )

    assert hybrid_retrieve(
        question="processo civil", context={"jurisdiction": "Brasil"}
    ) == [expected]


@pytest.mark.django_db
def test_embedding_index_rejects_unpublished_version():
    draft = make_version(state=SourceDocumentVersion.PipelineState.APPROVED)
    with pytest.raises(ValueError, match="only published"):
        index_published_version(draft)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "changed",
    [
        {"approved_by_id": None},
        {"approval_date": None},
        {"published_at": None},
        {"published_at": "future"},
        {"approval_date": "future"},
    ],
)
def test_state_flag_alone_cannot_release_corpus_or_create_embeddings(changed):
    version = make_version(state=SourceDocumentVersion.PipelineState.PUBLISHED)
    DocumentChunk.objects.create(
        document_version=version,
        ordinal=1,
        text="corpus confidencial",
        source_locator="fixture",
        source_hash=version.source_hash,
    )
    values = {
        key: timezone.now() + timedelta(days=1) if value == "future" else value
        for key, value in changed.items()
    }
    SourceDocumentVersion.objects.filter(pk=version.pk).update(**values)
    assert hybrid_retrieve(question="corpus confidencial", context={}) == []
    # The caller retains a previously valid stale object: the gate must re-read DB.
    with patch(
        "core.services.retrieval.localai_json",
        side_effect=AssertionError("unapproved document sent to model"),
    ):
        with pytest.raises(ValueError, match="human-approved"):
            index_published_version(version)


@pytest.mark.django_db
def test_approval_revoked_during_embedding_creates_no_index_rows():
    version = make_version(state=SourceDocumentVersion.PipelineState.PUBLISHED)
    chunk = DocumentChunk.objects.create(
        document_version=version,
        ordinal=1,
        text="corpus fixture",
        source_locator="fixture",
        source_hash=version.source_hash,
    )

    def embedding(*args, **kwargs):
        SourceDocumentVersion.objects.filter(pk=version.pk).update(
            state=SourceDocumentVersion.PipelineState.HUMAN_REVIEW
        )
        return {"data": [{"embedding": [0.1] * 384}]}

    with patch("core.services.retrieval.localai_json", side_effect=embedding):
        with pytest.raises(ValueError, match="changed during indexing"):
            index_published_version(version)
    assert not hasattr(chunk, "embedding")


@pytest.mark.django_db
def test_ai_bootstrap_is_idempotent_and_preserves_reviewed_prompt():
    User.objects.create_superuser(username="owner", password="safe-test-password")
    call_command("bootstrap_ai", verbosity=0)
    template = PromptTemplate.objects.get(agent__slug="consultor-kairos")
    original_prompt = template.current_version.system_prompt
    call_command("bootstrap_ai", verbosity=0)

    assert Agent.objects.filter(slug="consultor-kairos", enabled=True).count() == 1
    assert PromptVersion.objects.filter(template=template).count() == 1
    template.refresh_from_db()
    assert template.current_version.system_prompt == original_prompt


@pytest.mark.django_db
@pytest.mark.parametrize("change", ["missing", "wrong_reviewer", "wrong_source", "wrong_model", "rejected"])
def test_retrieval_requires_matching_human_approval_receipt(change):
    from django.contrib.contenttypes.models import ContentType
    from core.models import ContentVersion, PublicationApproval
    version = make_version(state=SourceDocumentVersion.PipelineState.PUBLISHED)
    DocumentChunk.objects.create(document_version=version, ordinal=1, text="recibo obrigatório", source_locator="fixture", source_hash=version.source_hash)
    approval = PublicationApproval.objects.filter(object_id=version.pk)
    if change == "missing":
        approval.delete()
    elif change == "wrong_reviewer":
        approval.update(reviewer=User.objects.create(username="wrong-reviewer"))
    elif change == "wrong_source":
        approval.update(evidence={"source_hash": "x" * 64, "version_sha256": "a" * 64})
    elif change == "wrong_model":
        approval.update(content_type=ContentType.objects.get_for_model(ContentVersion))
    else:
        approval.update(decision="rejected")
    assert hybrid_retrieve(question="recibo obrigatório", context={}) == []
    with pytest.raises(ValueError, match="human-approved"):
        index_published_version(version)
