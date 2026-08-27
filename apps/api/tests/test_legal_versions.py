from datetime import date

import pytest
from django.utils import timezone

from core.models import Content, ContentVersion, PublicationApproval, SourceDocument, SourceDocumentVersion, SourceRegistry, Subject
from core.services.documents import transition_document_version


@pytest.mark.django_db
def test_legal_version_cannot_be_overwritten(student):
    subject = Subject.objects.create(slug="etica", name="Ética")
    content = Content.objects.create(subject=subject, slug="estatuto", kind="law", created_by=student)
    version = ContentVersion.objects.create(
        content=content,
        version_number=1,
        original_text="texto oficial",
        title="Estatuto",
        body="texto oficial",
        retrieved_at=timezone.now(),
        source_url="https://example.invalid/oficial",
        source_hash="a" * 64,
    )
    version.body = "sobrescrito"
    with pytest.raises(Exception):
        version.save()


@pytest.mark.django_db
def test_document_requires_human_approval_before_indexing(reviewer):
    registry = SourceRegistry.objects.create(
        organization="Órgão oficial",
        domain="example.invalid",
        source_type="legislation",
        jurisdiction="federal",
        access_method="manual-test",
    )
    document = SourceDocument.objects.create(
        source_registry=registry,
        canonical_url="https://example.invalid/doc",
        title="Documento",
        jurisdiction="federal",
        document_type="law",
    )
    version = SourceDocumentVersion.objects.create(
        document=document,
        version_number=1,
        state="human_review",
        source_hash="b" * 64,
        source_url=document.canonical_url,
        retrieved_at=timezone.now(),
        reference_date=date.today(),
    )
    approved = transition_document_version(
        version_id=version.id,
        actor=reviewer,
        next_state="approved",
        justification="Conferido com a fonte oficial.",
    )
    assert approved.approved_by == reviewer
    assert PublicationApproval.objects.filter(object_id=version.id, decision="approved").exists()
    indexed = transition_document_version(version_id=version.id, actor=reviewer, next_state="indexed", justification="")
    assert indexed.state == "indexed"
