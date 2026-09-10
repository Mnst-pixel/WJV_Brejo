from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Exists, OuterRef
from django.db.models.fields.json import KeyTextTransform
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from core.audit import record_audit
from core.models import PublicationApproval, SourceDocumentVersion
from core.content_workflow import authorize, fingerprint


STATE_FLOW = {
    "discovered": "downloaded",
    "downloaded": "quarantined",
    "quarantined": "parsed",
    "parsed": "normalized",
    "normalized": "classified",
    "classified": "verified",
    "verified": "human_review",
    "human_review": "approved",
    "approved": "indexed",
    "indexed": "published",
}


@transaction.atomic
def transition_document_version(*, version_id, actor, next_state: str, justification: str, request=None):
    permission = {"approved": "corpus.approve", "indexed": "corpus.review", "published": "publication.publish", "human_review": "corpus.review"}.get(next_state, "corpus.update")
    authorize(actor, permission, request)
    version = get_object_or_404(SourceDocumentVersion.objects.select_for_update(), pk=version_id)
    expected = STATE_FLOW.get(version.state)
    if next_state == SourceDocumentVersion.PipelineState.FAILED:
        if version.state == "published":
            raise ValidationError("Falha de atualização não pode retirar uma versão publicada de operação.")
        if not justification:
            raise ValidationError("Falhas exigem justificativa.")
    elif next_state != expected:
        raise ValidationError({"state": f"Transição inválida: {version.state} -> {next_state}. Esperada: {expected}."})

    digest = fingerprint({key: getattr(version, key) for key in ("document_id", "version_number", "source_hash", "source_url", "valid_from", "valid_to", "reference_date", "normalized_text", "parsed_structure")})

    if next_state == "approved":
        if not justification or len(justification.strip()) < 8:
            raise ValidationError("A aprovação exige justificativa humana.")
        if version.file_asset_id and version.file_asset.owner_id == actor.pk:
            raise PermissionDenied("O responsável pelo upload não pode aprovar o próprio documento.")
        PublicationApproval.objects.create(
            content_type=ContentType.objects.get_for_model(version),
            object_id=version.id,
            decision=PublicationApproval.Decision.APPROVED,
            reviewer=actor,
            justification=justification,
            evidence={"previous_state": version.state, "source_hash": version.source_hash, "version_sha256": digest},
        )
        version.approved_by = actor
        version.approval_date = timezone.now()

    if next_state in {"indexed", "published"} and not PublicationApproval.objects.filter(
        content_type=ContentType.objects.get_for_model(version), object_id=version.id,
        reviewer_id=version.approved_by_id, decision=PublicationApproval.Decision.APPROVED,
        evidence__version_sha256=digest,
    ).exists():
        raise PermissionDenied("Não há aprovação humana íntegra da versão exata.")

    if next_state == "published":
        if not version.approved_by_id or not version.approval_date:
            raise PermissionDenied("Publicação rejeitada: versão não aprovada.")
        version.published_at = timezone.now()

    previous = version.state
    version.state = next_state
    update_fields = ["state", "updated_at"]
    if next_state == "approved":
        update_fields += ["approved_by", "approval_date"]
    if next_state == "published":
        update_fields.append("published_at")
    version.save(update_fields=update_fields)
    record_audit(
        "legal.document.transition",
        actor=actor,
        request=request,
        target=version,
        metadata={"from": previous, "to": next_state, "justification": justification},
    )
    return version


def published_document_versions():
    """Shared read gate: flags cannot replace a matching human approval receipt."""
    approval = PublicationApproval.objects.annotate(
        receipt_source_hash=KeyTextTransform("source_hash", "evidence"),
    ).filter(
        content_type=ContentType.objects.get_for_model(SourceDocumentVersion),
        object_id=OuterRef("pk"), reviewer_id=OuterRef("approved_by_id"), decision="approved",
        receipt_source_hash=OuterRef("source_hash"), evidence__has_key="version_sha256",
    ).exclude(evidence__version_sha256="")
    now = timezone.now()
    return SourceDocumentVersion.objects.filter(state="published", approved_by__isnull=False,
        approval_date__lte=now, published_at__lte=now).filter(Exists(approval))
