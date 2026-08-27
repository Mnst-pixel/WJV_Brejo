from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from core.audit import record_audit
from core.models import PublicationApproval, SourceDocumentVersion
from core.permissions import user_has_permission


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
    version = SourceDocumentVersion.objects.select_for_update().get(pk=version_id)
    expected = STATE_FLOW.get(version.state)
    if next_state == SourceDocumentVersion.PipelineState.FAILED:
        if not justification:
            raise ValidationError("Falhas exigem justificativa.")
    elif next_state != expected:
        raise ValidationError({"state": f"Transição inválida: {version.state} -> {next_state}. Esperada: {expected}."})

    if next_state in {"human_review", "approved", "indexed", "published"} and not user_has_permission(actor, "legal.review"):
        raise PermissionDenied("A revisão jurídica exige o papel apropriado.")
    if next_state in {"approved", "published"} and not user_has_permission(actor, "legal.publish"):
        raise PermissionDenied("A aprovação/publicação exige permissão explícita.")

    if next_state == "approved":
        if not justification:
            raise ValidationError("A aprovação exige justificativa humana.")
        PublicationApproval.objects.create(
            content_type=ContentType.objects.get_for_model(version),
            object_id=version.id,
            decision=PublicationApproval.Decision.APPROVED,
            reviewer=actor,
            justification=justification,
            evidence={"previous_state": version.state, "source_hash": version.source_hash},
        )
        version.approved_by = actor
        version.approval_date = timezone.now()

    if next_state == "indexed" and not PublicationApproval.objects.filter(
        content_type=ContentType.objects.get_for_model(version),
        object_id=version.id,
        decision=PublicationApproval.Decision.APPROVED,
    ).exists():
        raise PermissionDenied("Indexação rejeitada: não há aprovação humana registrada.")

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
