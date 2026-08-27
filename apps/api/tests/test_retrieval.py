import hashlib

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
    return SourceDocumentVersion.objects.create(
        document=document,
        version_number=1,
        state=state,
        source_hash=hashlib.sha256(f"{document.pk}".encode()).hexdigest(),
        source_url=document.canonical_url,
        retrieved_at=timezone.now(),
        published_at=timezone.now() if state == SourceDocumentVersion.PipelineState.PUBLISHED else None,
    )


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
    federal = make_version(state=SourceDocumentVersion.PipelineState.PUBLISHED, jurisdiction="Brasil")
    state = make_version(state=SourceDocumentVersion.PipelineState.PUBLISHED, jurisdiction="São Paulo")
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

    assert hybrid_retrieve(question="processo civil", context={"jurisdiction": "Brasil"}) == [expected]


@pytest.mark.django_db
def test_embedding_index_rejects_unpublished_version():
    draft = make_version(state=SourceDocumentVersion.PipelineState.APPROVED)
    with pytest.raises(ValueError, match="only published"):
        index_published_version(draft)


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
