"""Human content workflow and bounded, unverified legacy import."""
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError as DocumentValidationError
from django.db import IntegrityError, transaction
from django.db.models import Max
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError

from core.audit import record_audit
from core.content_models import ContentWorkflow, LegacyContentImport, LegacyContentItem
from core.models import Content, ContentSource, ContentVersion, PublicationApproval, ReviewTask, Subject, User
from core.permissions import is_service_account, request_has_permission, user_has_permission
from core.rich_text import document_text, normalize_document

DATASETS = {"questions": "questions.json", "oab": "oab-data.json"}
MAX_DATASET_BYTES = 2 * 1024 * 1024
MAX_ITEMS = 500


def authorize(actor, permission, request=None):
    current = User.objects.select_for_update().filter(pk=actor.pk).first()
    if current is None or not current.is_active or current.session_version != actor.session_version:
        raise PermissionDenied("O acesso foi alterado durante a operação.")
    if request is not None:
        if request.user.pk != actor.pk:
            raise PermissionDenied("Ação editorial não autorizada.")
        request.user = current
    allowed = request_has_permission(request, permission) if request is not None else user_has_permission(current, permission)
    if is_service_account(current) or not allowed:
        raise PermissionDenied("Ação editorial não autorizada.")


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def version_fingerprint(version):
    return fingerprint({key: getattr(version, key) for key in ("id", "content_id", "version_number", "title", "body", "structured_data", "original_text", "source_url", "source_hash", "legal_status", "valid_from", "valid_to", "reference_date", "published_at", "retrieved_at", "created_at", "approved_by_id", "approval_date", "changes_summary", "current_legal_situation", "exam_date_situation", "supersedes_id")})


def _source_url(value):
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValidationError("A revisão exige referência HTTPS sem credenciais na URL.")


def _mirror_pending(content, version, state):
    # A new draft/review never removes an already published version from service.
    if content.status != "published":
        content.status = state
        content.current_version = version
        content.save(update_fields=["status", "current_version", "updated_at"])


def rich_values(body, data):
    if not isinstance(data, dict) or "rich_text" not in data:
        return body, data
    try:
        document = normalize_document(data["rich_text"])
    except DocumentValidationError:
        raise ValidationError("A estrutura visual é inválida. Crie uma revisão válida antes de continuar.") from None
    plain = body.replace("\r\n", "\n").replace("\r", "\n").strip()
    if document_text(document) != plain:
        raise ValidationError("Texto e formatação divergem. Crie uma revisão válida antes de continuar.")
    return plain, {**data, "rich_text": document}


@transaction.atomic
def create_revision(*, actor, content_id, values, request=None):
    authorize(actor, "content.edit", request)
    values = dict(values)
    values["body"], values["structured_data"] = rich_values(values["body"], values.get("structured_data", {}))
    content = get_object_or_404(Content.objects.select_for_update(), pk=content_id)
    previous = content.current_version
    number = (content.versions.aggregate(maximum=Max("version_number"))["maximum"] or 0) + 1
    version = ContentVersion.objects.create(content=content, version_number=number, retrieved_at=timezone.now(),
        supersedes=previous, original_text=values["body"], legal_status="legacy_unverified", **values)
    ContentWorkflow.objects.create(version=version, author=actor)
    _mirror_pending(content, version, "draft")
    record_audit("content.revision.created", actor=actor, request=request, target=version, metadata={"version_sha256": version_fingerprint(version)})
    return version


@transaction.atomic
def transition_content(*, actor, version_id, state, justification, legal_status=None, request=None):
    permission = {"review": "content.edit", "approved": "content.approve", "published": "publication.publish", "archived": "publication.publish"}.get(state)
    if not permission:
        raise ValidationError("Estado de destino inválido.")
    authorize(actor, permission, request)
    if not justification or len(justification.strip()) < 8 or len(justification) > 2000:
        raise ValidationError("A transição exige justificativa de 8 a 2000 caracteres.")
    base = get_object_or_404(ContentVersion, pk=version_id)
    content = Content.objects.select_for_update().get(pk=base.content_id)
    workflow = get_object_or_404(ContentWorkflow.objects.select_for_update().select_related("version"), version=base)
    version = workflow.version
    if state in {"approved", "published"}:
        body, data = rich_values(version.body, version.structured_data)
        if body != version.body or data != version.structured_data:
            raise ValidationError("A formatação exige uma nova revisão; a versão anterior será preservada.")
    expected = {"draft": "review", "review": "approved", "approved": "published", "published": "archived"}.get(workflow.state)
    if state != expected:
        raise ValidationError("Transição fora do workflow permitido.")
    now = timezone.now()
    if state == "review":
        workflow.submitted_by = actor
        workflow.submitted_at = now
        workflow.state = "review"
        workflow.save(update_fields=["submitted_by", "submitted_at", "state", "updated_at"])
        ReviewTask.objects.create(content_type=ContentType.objects.get_for_model(version), object_id=version.pk, notes=justification)
        _mirror_pending(content, version, "review")
    elif state == "approved":
        if actor.pk in {workflow.author_id, workflow.submitted_by_id}:
            raise PermissionDenied("Autor e responsável pela submissão não podem aprovar o próprio conteúdo.")
        if legal_status not in {"current", "historical", "revoked", "superseded"}:
            raise ValidationError("Declare explicitamente a situação jurídica verificada.")
        _source_url(version.source_url)
        # New immutable version records the actual human verification; legacy remains intact.
        copied = {field.attname: getattr(version, field.attname) for field in ContentVersion._meta.fields if field.name not in {"id", "created_at", "version_number", "approved_by", "approval_date", "supersedes"}}
        copied["legal_status"] = legal_status
        number = (content.versions.aggregate(maximum=Max("version_number"))["maximum"] or 0) + 1
        approved = ContentVersion.objects.create(**copied, version_number=number, approved_by=actor, approval_date=now, supersedes=version)
        for source in version.content_sources.all():
            ContentSource.objects.create(content_version=approved, source=source.source, locator=source.locator, relevance=source.relevance)
        approval = PublicationApproval.objects.create(content_type=ContentType.objects.get_for_model(approved), object_id=approved.pk,
            decision="approved", reviewer=actor, justification=justification,
            evidence={"reviewed_version": str(version.pk), "version_sha256": version_fingerprint(approved), "source_hash": approved.source_hash})
        ContentWorkflow.objects.create(version=approved, author=workflow.author, submitted_by=workflow.submitted_by,
            submitted_at=workflow.submitted_at, state="approved", approval=approval)
        workflow.state = "archived"
        workflow.archived_by = actor
        workflow.archived_at = now
        workflow.save(update_fields=["state", "archived_by", "archived_at", "updated_at"])
        ReviewTask.objects.filter(content_type=ContentType.objects.get_for_model(version), object_id=version.pk).update(status="approved", assigned_to=actor)
        version = approved
        _mirror_pending(content, version, "approved")
    elif state == "published":
        approval = workflow.approval
        if (not approval or approval.object_id != version.pk or approval.content_type_id != ContentType.objects.get_for_model(version).pk or approval.decision != "approved" or
                approval.evidence.get("version_sha256") != version_fingerprint(version) or
                version.legal_status == "legacy_unverified" or version.approved_by_id != approval.reviewer_id):
            raise PermissionDenied("Não existe aprovação íntegra para esta versão exata.")
        ContentWorkflow.objects.filter(version__content=content, state="published").exclude(pk=workflow.pk).update(state="archived", archived_by=actor, archived_at=now)
        workflow.state = "published"
        workflow.published_by = actor
        workflow.published_at = now
        workflow.save(update_fields=["state", "published_by", "published_at", "updated_at"])
        content.status = "published"
        content.current_version = version
        content.save(update_fields=["status", "current_version", "updated_at"])
    else:
        workflow.state = "archived"
        workflow.archived_by = actor
        workflow.archived_at = now
        workflow.save(update_fields=["state", "archived_by", "archived_at", "updated_at"])
        if content.current_version_id == version.pk:
            content.status = "archived"
            content.save(update_fields=["status", "updated_at"])
    record_audit("content.workflow.transition", actor=actor, request=request, target=version,
                 metadata={"state": state, "justification": justification, "version_sha256": version_fingerprint(version)})
    return version


def _legacy_dataset(dataset):
    if dataset not in DATASETS:
        raise ValidationError("Dataset legado não permitido.")
    default_root = Path(settings.BASE_DIR).parent.parent / "legacy" / "extracted"
    root = Path(getattr(settings, "KAIROS_LEGACY_DATA_DIR", default_root))
    if not root.is_dir():
        error = APIException("Acervo legado não instalado nesta instância.")
        error.status_code = 503
        raise error
    path = root / DATASETS[dataset]
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValidationError("Origem legada inválida.")
    if path.stat().st_size > MAX_DATASET_BYTES:
        raise ValidationError("Dataset excede o limite.")
    with path.open("rb") as stream:
        raw = stream.read(MAX_DATASET_BYTES + 1)
    if len(raw) > MAX_DATASET_BYTES:
        raise ValidationError("Dataset excede o limite.")
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise ValidationError("Dataset JSON inválido.") from exc
    items = []
    if dataset == "questions":
        if not isinstance(data, list):
            raise ValidationError("Lista de questões inválida.")
        for item in data:
            if not isinstance(item, dict) or not all(key in item for key in ("question", "legacy_dataset", "legacy_position")) or not isinstance(item["question"], str):
                raise ValidationError("Questão legada inválida.")
            alternatives = item.get("alternatives", [])
            index = item.get("answer_index")
            if not isinstance(alternatives, list) or not 2 <= len(alternatives) <= 8 or type(index) is not int or not 0 <= index < len(alternatives):
                raise ValidationError("Alternativas ou gabarito legado inválidos.")
            items.append({"locator": f"{item['legacy_dataset']}:{item['legacy_position']}", "title": item["question"][:300],
                "body": item["question"], "kind": "legacy_question", "data": item})
    else:
        if not isinstance(data, dict):
            raise ValidationError("Resumo legado inválido.")
        for topic, section in data.items():
            if not isinstance(section, dict) or not isinstance(section.get("items"), list):
                raise ValidationError("Seção legada inválida.")
            for index, item in enumerate(section["items"]):
                if not isinstance(item, dict) or not isinstance(item.get("t"), str) or not isinstance(item.get("d"), str):
                    raise ValidationError("Resumo legado inválido.")
                items.append({"locator": f"{topic}:{index}", "title": item["t"], "body": item["d"], "kind": "legacy_summary", "data": {"topic": topic, "item": item}})
    if not items or len(items) > MAX_ITEMS or any(not isinstance(item["body"], str) or len(item["body"]) > 100_000 for item in items):
        raise ValidationError("Quantidade ou texto legado inválido.")
    return hashlib.sha256(raw).hexdigest(), items


@transaction.atomic
def preview_legacy(*, actor, dataset, subject_id, request=None):
    authorize(actor, "content.create", request)
    subject = get_object_or_404(Subject, pk=subject_id)
    source_hash, items = _legacy_dataset(dataset)
    preview_hash = fingerprint({"dataset": dataset, "source_sha256": source_hash, "subject": str(subject.pk)})
    batch, _ = LegacyContentImport.objects.get_or_create(actor=actor, preview_sha256=preview_hash,
        defaults={"subject": subject, "dataset": dataset, "source_sha256": source_hash, "item_count": len(items)})
    return batch, [{"title": item["title"], "locator": item["locator"], "legal_status": "legacy_unverified"} for item in items]


@transaction.atomic
def confirm_legacy(*, actor, batch_id, expected_hash, request=None):
    authorize(actor, "content.create", request)
    batch = get_object_or_404(LegacyContentImport.objects.select_for_update(), pk=batch_id, actor=actor)
    if expected_hash != batch.preview_sha256:
        raise ValidationError("Confirmação não corresponde ao preview.")
    if batch.status == "confirmed":
        return batch
    source_hash, items = _legacy_dataset(batch.dataset)
    if source_hash != batch.source_sha256:
        raise ValidationError("O arquivo mudou após o preview. Gere um novo preview.")
    created = duplicates = 0
    for item in items:
        item_hash = fingerprint(item)
        if LegacyContentItem.objects.filter(item_sha256=item_hash).exists():
            duplicates += 1
            continue
        try:
            with transaction.atomic():
                content = Content.objects.create(subject=batch.subject, slug="legacy-" + item_hash, kind=item["kind"], created_by=actor, status="review")
                version = ContentVersion.objects.create(content=content, version_number=1, title=item["title"], body=item["body"], original_text=item["body"],
                    structured_data=item["data"], retrieved_at=timezone.now(), source_url=f"legacy://{batch.dataset}/{item['locator']}", source_hash=source_hash, legal_status="legacy_unverified")
                content.current_version = version
                content.save(update_fields=["current_version", "updated_at"])
                ContentWorkflow.objects.create(version=version, author=actor, submitted_by=actor, submitted_at=timezone.now(), state="review")
                ReviewTask.objects.create(content_type=ContentType.objects.get_for_model(version), object_id=version.pk, notes="Legado não verificado. Conferir fonte e criar revisão antes de aprovação.")
                LegacyContentItem.objects.create(batch=batch, source_sha256=source_hash, item_sha256=item_hash, locator=item["locator"], version=version)
            created += 1
        except IntegrityError:
            if not LegacyContentItem.objects.filter(item_sha256=item_hash).exists():
                raise
            duplicates += 1
    batch.status = "confirmed"
    batch.confirmed_at = timezone.now()
    batch.result = {"created": created, "duplicates": duplicates, "legal_status": "legacy_unverified", "published": 0}
    batch.save(update_fields=["status", "confirmed_at", "result", "updated_at"])
    record_audit("content.legacy.imported", actor=actor, request=request, target=batch, metadata=batch.result | {"source_sha256": source_hash})
    return batch


def published_content():
    """Single read gate shared by student content and study commands."""
    from django.db.models import F
    now = timezone.now()
    return Content.objects.filter(status="published", current_version__approved_by__isnull=False,
        current_version__approval_date__lte=now, current_version__workflow__state="published",
        current_version__workflow__published_by__isnull=False, current_version__workflow__published_at__lte=now,
        current_version__workflow__approval__content_type=ContentType.objects.get_for_model(ContentVersion),
        current_version__workflow__approval__decision="approved",
        current_version__workflow__approval__object_id=F("current_version_id"),
        current_version__workflow__approval__reviewer_id=F("current_version__approved_by_id"),
        current_version__content_id=F("id")).exclude(current_version__legal_status="legacy_unverified")
