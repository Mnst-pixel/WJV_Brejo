import hashlib
import logging
import tempfile
import uuid
from datetime import timedelta
from pathlib import PurePosixPath

import clamd
import httpx
from django.conf import settings
from django.core.files.base import ContentFile, File
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.urls import reverse
from rest_framework.exceptions import PermissionDenied, ValidationError

from core.audit import record_audit
from core.models import FileAsset, User
from core.upload_models import Enrollment, UploadPolicy
from core.permissions import lock_study_user


MIMES = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "text/plain": ".txt",
}
MAX_RETRIES = 3


class UnsafeUpload(Exception):
    pass


def _authorized_owner(owner):
    return lock_study_user(owner)


def detect_mime(data):
    import magic

    return magic.from_buffer(data, mime=True)


def limits(owner):
    policy = UploadPolicy.objects.first() or UploadPolicy()
    if not policy.enabled:
        raise PermissionDenied("Uploads temporariamente indisponíveis.")
    maximum = min(policy.max_upload_bytes, settings.KAIROS_MAX_UPLOAD_BYTES)
    quota = policy.default_storage_quota_bytes
    enrollment = Enrollment.objects.select_related("plan").filter(owner=owner).first()
    if enrollment:
        now = timezone.now()
        if (
            enrollment.status != "active"
            or not enrollment.plan.active
            or enrollment.valid_from > now
            or (enrollment.valid_to and enrollment.valid_to <= now)
        ):
            raise PermissionDenied("Plano indisponível para uploads.")
        maximum = min(maximum, enrollment.plan.max_upload_bytes)
        quota = enrollment.plan.storage_quota_bytes
    return maximum, quota


def _clean_keys(keys):
    success = True
    for key in set(filter(None, keys)):
        try:
            default_storage.delete(key)
        except Exception:
            success = False
            logging.getLogger(__name__).warning("upload_storage_cleanup_failed")
    return success


def create_upload(*, owner, upload, request=None):
    if getattr(request, "kairos_upload_rejected", False):
        raise ValidationError({"file": "Arquivo excede o limite permitido."})
    maximum, _ = limits(owner)
    if not upload or not 0 < upload.size <= maximum:
        raise ValidationError({"file": "Tamanho de arquivo inválido."})
    first = upload.read(8192)
    upload.seek(0)
    mime = detect_mime(first)
    if mime not in MIMES:
        raise ValidationError({"file": "Tipo de conteúdo não permitido."})
    digest = hashlib.sha256()
    size = 0
    for chunk in upload.chunks():
        size += len(chunk)
        if size > maximum:
            raise ValidationError({"file": "Arquivo excede o limite permitido."})
        digest.update(chunk)
    if size != upload.size:
        raise ValidationError({"file": "Tamanho inconsistente."})
    upload.seek(0)
    asset_id = uuid.uuid4()
    with transaction.atomic():
        _authorized_owner(owner)
        maximum, quota = limits(owner)
        used = (
            FileAsset.objects.filter(owner=owner)
            .exclude(processing_status="deleted")
            .aggregate(total=Sum("size_bytes"))["total"]
            or 0
        )
        if size > maximum or used + size > quota:
            raise ValidationError({"file": "Quota de armazenamento excedida."})
        asset = FileAsset.objects.create(
            id=asset_id,
            owner=owner,
            original_name=PurePosixPath(upload.name.replace("\\", "/")).name[:255],
            mime_type=mime,
            size_bytes=size,
            sha256=digest.hexdigest(),
            quarantine_key=f"quarantine/{owner.pk}/{asset_id}{MIMES[mime]}",
            storage_key=f"private/{owner.pk}/{asset_id}{MIMES[mime]}",
            processing_status="receiving",
        )
    stored = None
    try:
        stored = default_storage.save(asset.quarantine_key, upload)
        with transaction.atomic():
            _authorized_owner(owner)
            asset = FileAsset.objects.select_for_update().get(pk=asset.pk)
            if asset.processing_status != "receiving":
                raise UnsafeUpload("upload_deleted")
            asset.quarantine_key = stored
            asset.processing_status = "quarantined"
            asset.save(
                update_fields=["quarantine_key", "processing_status", "updated_at"]
            )
            record_audit(
                "file.uploaded",
                actor=owner,
                request=request,
                target=asset,
                metadata={"mime": mime, "bytes": size},
            )
            transaction.on_commit(lambda: enqueue_asset(str(asset.pk)))
        return asset
    except Exception:
        _clean_keys([stored])
        FileAsset.objects.filter(pk=asset.pk).exclude(
            processing_status__in=["deleted", "delete_pending"]
        ).update(processing_status="upload_failed")
        raise


def enqueue_asset(asset_id):
    from core.tasks import scan_and_process_file

    try:
        scan_and_process_file.delay(asset_id)
    except Exception:
        # Durable quarantined row is the outbox; periodic recovery retries dispatch.
        logging.getLogger(__name__).warning("upload_dispatch_pending")


def delete_upload(*, owner, asset_id, request=None):
    with transaction.atomic():
        _authorized_owner(owner)
        asset = FileAsset.objects.select_for_update().get(pk=asset_id, owner=owner)
        asset.processing_status = "delete_pending"
        asset.metadata = {**asset.metadata, "claim_token": None}
        asset.save(update_fields=["processing_status", "metadata", "updated_at"])
        record_audit("file.deleted", actor=owner, request=request, target=asset)
        transaction.on_commit(lambda: cleanup_deleted(asset))


def cleanup_deleted(asset):
    if asset.metadata.get("claim_until", 0) > timezone.now().timestamp():
        return
    if _clean_keys(
        [
            asset.quarantine_key,
            asset.storage_key,
            asset.metadata.get("text_key"),
            *asset.metadata.get("output_keys", []),
        ]
    ):
        FileAsset.objects.filter(
            pk=asset.pk, processing_status="delete_pending"
        ).update(processing_status="deleted")


@transaction.atomic
def released_asset(*, owner, asset_id):
    _authorized_owner(owner)
    asset = FileAsset.objects.select_for_update().get(pk=asset_id, owner=owner)
    if (
        asset.scan_status != "clean"
        or asset.processing_status != "processed_pending_review"
        or not default_storage.exists(asset.storage_key)
    ):
        raise PermissionDenied("O arquivo ainda não está liberado.")
    return asset


def download_upload(*, owner, asset_id):
    asset = released_asset(owner=owner, asset_id=asset_id)
    # The object store remains private on the Docker network. Every actual read
    # repeats session/ownership/scan checks rather than exposing internal S3 URLs.
    return {"url": reverse("file-content", kwargs={"pk": asset.pk}), "requires_session": True}


def open_download(*, owner, asset_id):
    from django.http import FileResponse

    asset = released_asset(owner=owner, asset_id=asset_id)
    source = default_storage.open(asset.storage_key, "rb")
    if source.size != asset.size_bytes:
        source.close()
        raise PermissionDenied("Integridade do arquivo indisponível.")
    response = FileResponse(source,
        as_attachment=True, filename=asset.original_name, content_type="application/octet-stream")
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def parse_remote(path, mime, digest):
    token = getattr(settings, "PARSER_API_TOKEN", "")
    endpoint = getattr(settings, "PARSER_BASE_URL", "http://parser:8090")
    if len(token) < 32 or endpoint != "http://parser:8090":
        raise UnsafeUpload("parser_configuration_unavailable")
    with (
        open(path, "rb") as source,
        httpx.Client(timeout=120, follow_redirects=False, trust_env=False) as client,
    ):
        with client.stream(
            "POST",
            endpoint + "/v1/parse",
            headers={
                "Authorization": "Bearer " + token,
                "Content-Type": mime,
                "X-Content-SHA256": digest,
                "Content-Length": str(source.seek(0, 2)),
            },
            content=_rewind_chunks(source),
        ) as response:
            if response.status_code != 200:
                raise UnsafeUpload("parser_rejected")
            chunks = []
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > 2 * 1024**2:
                    raise UnsafeUpload("parser_output_limit")
                chunks.append(chunk)
            import json

            result = json.loads(b"".join(chunks))
        if (
            set(result) != {"text", "sha256"}
            or result["sha256"] != digest
            or not isinstance(result["text"], str)
            or len(result["text"].encode()) > 1024**2
        ):
            raise UnsafeUpload("parser_response_invalid")
        return result["text"]


def _rewind_chunks(source):
    source.seek(0)
    while chunk := source.read(65536):
        yield chunk


def process_upload(asset_id):
    token = uuid.uuid4().hex
    with transaction.atomic():
        asset = FileAsset.objects.select_for_update().filter(pk=asset_id).first()
        if not asset or asset.processing_status not in {
            "quarantined",
            "retry_pending",
            "processing",
        }:
            return
        now = timezone.now().timestamp()
        if (
            asset.metadata.get("claim_until", 0) > now
            or asset.metadata.get("retry_at", 0) > now
        ):
            return
        attempts = int(asset.metadata.get("retry_count", 0))
        if attempts >= MAX_RETRIES:
            asset.processing_status = "processing_failed"
            asset.save(update_fields=["processing_status", "updated_at"])
            return
        stale_outputs = asset.metadata.get("output_keys", [])
        planned_private = (
            f"private/{asset.owner_id}/{asset.id}-{token}{MIMES[asset.mime_type]}"
        )
        planned_text = f"processed/{asset.owner_id}/{asset.id}-{token}.txt"
        asset.metadata = {
            **asset.metadata,
            "claim_token": token,
            "claim_until": now + 300,
            "retry_count": attempts + 1,
            "output_keys": [*stale_outputs, planned_private, planned_text],
        }
        asset.processing_status = "processing"
        asset.save(update_fields=["metadata", "processing_status", "updated_at"])
    created = []
    terminal = False
    try:
        if not _clean_keys(stale_outputs):
            raise UnsafeUpload("previous_output_cleanup_failed")
        with tempfile.NamedTemporaryFile() as temporary:
            digest = hashlib.sha256()
            total = 0
            with default_storage.open(asset.quarantine_key, "rb") as source:
                while chunk := source.read(65536):
                    total += len(chunk)
                    if total > min(settings.KAIROS_MAX_UPLOAD_BYTES, asset.size_bytes):
                        terminal = True
                        raise UnsafeUpload("size_mismatch")
                    temporary.write(chunk)
                    digest.update(chunk)
            temporary.flush()
            temporary.seek(0)
            if (
                total != asset.size_bytes
                or digest.hexdigest() != asset.sha256
                or detect_mime(temporary.read(8192)) != asset.mime_type
            ):
                terminal = True
                raise UnsafeUpload("content_mismatch")
            temporary.seek(0)
            scanner = clamd.ClamdNetworkSocket(
                settings.CLAMAV_HOST, settings.CLAMAV_PORT, timeout=60
            )
            result = scanner.instream(temporary)
            values = list(result.values()) if isinstance(result, dict) else []
            scan = values[0][0] if len(values) == 1 else "ERROR"
            if scan == "FOUND":
                terminal = True
                raise UnsafeUpload("infected")
            if scan != "OK":
                raise UnsafeUpload("scanner_unavailable")
            text = parse_remote(temporary.name, asset.mime_type, asset.sha256)
            temporary.seek(0)
            # Per-claim output names prevent an expired worker overwriting a successor.
            private = default_storage.save(
                planned_private,
                File(temporary),
            )
            created.append(private)
            text_key = default_storage.save(
                planned_text,
                ContentFile(text.encode()),
            )
            created.append(text_key)
            with transaction.atomic():
                actor = (
                    User.objects.only("id").select_for_update().get(pk=asset.owner_id)
                )
                current = FileAsset.objects.select_for_update().get(pk=asset.pk)
                if (
                    current.processing_status != "processing"
                    or current.metadata.get("claim_token") != token
                ):
                    raise UnsafeUpload("claim_superseded")
                current.storage_key = private
                current.scan_status = "clean"
                current.scanned_at = timezone.now()
                current.processing_status = "processed_pending_review"
                current.metadata = {
                    **current.metadata,
                    "text_key": text_key,
                    "claim_token": None,
                    "claim_until": 0,
                    "extracted_characters": len(text),
                    "output_keys": [private, text_key],
                }
                current.save()
                record_audit(
                    "file.scan.completed",
                    actor=actor,
                    target=current,
                    metadata={"status": current.processing_status},
                )
            created.clear()
            _clean_keys([asset.quarantine_key])
    except Exception as exc:
        _clean_keys(created)
        with transaction.atomic():
            current = FileAsset.objects.select_for_update().filter(pk=asset.pk).first()
            if (
                current
                and current.processing_status == "processing"
                and current.metadata.get("claim_token") == token
            ):
                current.scan_status = (
                    "infected" if terminal and str(exc) == "infected" else "error"
                )
                current.processing_status = "rejected" if terminal else "retry_pending"
                current.metadata = {
                    **current.metadata,
                    "claim_token": None,
                    "claim_until": 0,
                    "retry_at": timezone.now().timestamp() + 60 * 2**attempts,
                    "processing_error": type(exc).__name__,
                }
                current.save()
                record_audit(
                    "file.scan.rejected" if terminal else "file.scan.retry",
                    actor=User.objects.only("id").get(pk=current.owner_id),
                    target=current,
                    metadata={"status": current.processing_status},
                )
        if terminal:
            _clean_keys([asset.quarantine_key])


def recover_uploads():
    cutoff = timezone.now() - timedelta(minutes=10)
    # Queue is bounded; claims and backoff make duplicate scheduler delivery harmless.
    for asset in FileAsset.objects.filter(
        processing_status__in=["quarantined", "retry_pending", "processing"]
    ).order_by("updated_at")[:100]:
        enqueue_asset(str(asset.pk))
    for asset in FileAsset.objects.filter(
        processing_status__in=[
            "delete_pending",
            "receiving",
            "upload_failed",
            "rejected",
            "processed_pending_review",
        ],
        updated_at__lt=cutoff,
    ).order_by("updated_at")[:100]:
        if asset.processing_status == "delete_pending":
            cleanup_deleted(asset)
            continue
        if asset.processing_status == "receiving":
            changed = FileAsset.objects.filter(
                pk=asset.pk, processing_status="receiving", updated_at__lt=cutoff
            ).update(processing_status="upload_failed")
            if not changed:
                continue
        if asset.processing_status == "processed_pending_review":
            _clean_keys([asset.quarantine_key])
        else:
            _clean_keys(
                [
                    asset.quarantine_key,
                    asset.storage_key,
                    asset.metadata.get("text_key"),
                    *asset.metadata.get("output_keys", []),
                ]
            )
        FileAsset.objects.filter(pk=asset.pk).update(updated_at=timezone.now())
