import hashlib
import io
import importlib.util
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading
from datetime import timedelta
from types import SimpleNamespace
import zipfile

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.files.storage import default_storage
from django.core.files.uploadhandler import StopUpload
from django.db import IntegrityError, transaction
from django.test import override_settings
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from core.models import FileAsset, User
from core.upload_handlers import BoundedUploadHandler
from core.upload_models import Plan, Enrollment, UploadPolicy
from core.services import uploads

REAL_CLAMD = uploads.clamd.ClamdNetworkSocket


@pytest.fixture(autouse=True)
def upload_boundaries(monkeypatch):
    monkeypatch.setattr(uploads, "detect_mime", lambda data: "text/plain")
    monkeypatch.setattr(uploads, "enqueue_asset", lambda asset_id: None)
    monkeypatch.setattr(uploads, "parse_remote", lambda *args: "Texto extraído")
    monkeypatch.setattr(
        uploads.clamd,
        "ClamdNetworkSocket",
        lambda *args, **kwargs: SimpleNamespace(
            instream=lambda source: {"stream": ("OK", None)}
        ),
    )


def upload_for(owner, data=b"texto de estudo", name="documento.txt"):
    return uploads.create_upload(owner=owner, upload=SimpleUploadedFile(name, data))


def test_upload_hash_random_internal_name_and_quarantine(student):
    asset = upload_for(student, name="../../secret.env.txt")
    assert asset.sha256 == hashlib.sha256(b"texto de estudo").hexdigest()
    assert asset.original_name == "secret.env.txt"
    assert "secret" not in asset.quarantine_key
    assert str(student.pk) in asset.quarantine_key
    assert asset.processing_status == "quarantined"
    with pytest.raises(PermissionDenied):
        uploads.download_upload(owner=student, asset_id=asset.pk)


def test_disallowed_magic_rejected_before_storage(student, monkeypatch):
    monkeypatch.setattr(uploads, "detect_mime", lambda _: "application/x-executable")
    with pytest.raises(ValidationError):
        upload_for(student)
    assert FileAsset.objects.count() == 0


def test_size_and_global_policy_enforced(student):
    UploadPolicy.objects.create(max_upload_bytes=3, default_storage_quota_bytes=30)
    with pytest.raises(ValidationError):
        upload_for(student, b"four")


def test_stream_limit_stops_before_downstream_handlers():
    request = SimpleNamespace()
    handler = BoundedUploadHandler(request)
    with override_settings(KAIROS_MAX_UPLOAD_BYTES=5):
        assert handler.receive_data_chunk(b"123", 0) == b"123"
        with pytest.raises(StopUpload):
            handler.receive_data_chunk(b"456", 3)
    assert request.kairos_upload_rejected


def test_quota_counts_only_owner_and_cannot_overbook(student, other_student):
    UploadPolicy.objects.create(max_upload_bytes=10, default_storage_quota_bytes=10)
    upload_for(other_student, b"1234567890")
    upload_for(student, b"123456")
    with pytest.raises(ValidationError):
        upload_for(student, b"12345")
    assert FileAsset.objects.filter(owner=student).count() == 1


def test_suspended_enrollment_denies_upload(student):
    plan = Plan.objects.create(code="study", name="Estudo")
    Enrollment.objects.create(owner=student, plan=plan, status="suspended")
    with pytest.raises(PermissionDenied):
        upload_for(student)


def test_revoked_session_cannot_start_upload_or_delete_existing_asset(student):
    asset = upload_for(student)
    User.objects.filter(pk=student.pk).update(session_version=student.session_version + 1)
    with pytest.raises(PermissionDenied):
        upload_for(student)
    with pytest.raises(PermissionDenied):
        uploads.delete_upload(owner=student, asset_id=asset.pk)
    asset.refresh_from_db()
    assert asset.processing_status == "quarantined"


def test_plan_constraint_rejects_impossible_quota():
    with pytest.raises(IntegrityError), transaction.atomic():
        Plan.objects.create(
            code="bad", name="Bad", max_upload_bytes=100, storage_quota_bytes=10
        )


def test_storage_save_renamed_result_is_persisted(student, monkeypatch):
    save = default_storage.save
    monkeypatch.setattr(
        default_storage, "save", lambda key, content: save(key + ".renamed", content)
    )
    asset = upload_for(student)
    assert asset.quarantine_key.endswith(".renamed")
    assert default_storage.exists(asset.quarantine_key)


def test_clean_scan_process_releases_once_and_cleans_quarantine(student, monkeypatch):
    asset = upload_for(student)
    uploads.process_upload(str(asset.pk))
    asset.refresh_from_db()
    assert asset.scan_status == "clean"
    assert asset.processing_status == "processed_pending_review"
    assert default_storage.exists(asset.storage_key)
    assert not default_storage.exists(asset.quarantine_key)
    original_key = asset.storage_key
    monkeypatch.setattr(
        uploads, "parse_remote", lambda *args: pytest.fail("duplicate parse")
    )
    uploads.process_upload(str(asset.pk))
    asset.refresh_from_db()
    assert asset.storage_key == original_key


def test_scanner_error_preserves_quarantine_for_bounded_retry(student, monkeypatch):
    asset = upload_for(student)
    monkeypatch.setattr(
        uploads.clamd,
        "ClamdNetworkSocket",
        lambda *args, **kwargs: SimpleNamespace(
            instream=lambda _: {"stream": ("ERROR", "unavailable")}
        ),
    )
    uploads.process_upload(str(asset.pk))
    asset.refresh_from_db()
    assert asset.processing_status == "retry_pending"
    assert asset.scan_status == "error"
    assert default_storage.exists(asset.quarantine_key)
    assert not default_storage.exists(asset.storage_key)
    uploads.process_upload(str(asset.pk))
    asset.refresh_from_db()
    assert asset.metadata["retry_count"] == 1


def test_infection_rejected_without_parser_or_public_copy(student, monkeypatch):
    asset = upload_for(student)
    monkeypatch.setattr(
        uploads.clamd,
        "ClamdNetworkSocket",
        lambda *args, **kwargs: SimpleNamespace(
            instream=lambda _: {"stream": ("FOUND", "Eicar-Test-Signature")}
        ),
    )
    monkeypatch.setattr(
        uploads, "parse_remote", lambda *args: pytest.fail("infected parser call")
    )
    uploads.process_upload(str(asset.pk))
    asset.refresh_from_db()
    assert (asset.scan_status, asset.processing_status) == ("infected", "rejected")
    assert not default_storage.exists(asset.quarantine_key)


def test_quarantine_tampering_rejected(student):
    asset = upload_for(student)
    default_storage.delete(asset.quarantine_key)
    default_storage.save(
        asset.quarantine_key, SimpleUploadedFile("file.txt", b"tampered")
    )
    uploads.process_upload(str(asset.pk))
    asset.refresh_from_db()
    assert asset.processing_status == "rejected"


def test_other_owner_cannot_download_or_delete(student, other_student):
    asset = upload_for(student)
    uploads.process_upload(str(asset.pk))
    with pytest.raises(FileAsset.DoesNotExist):
        uploads.download_upload(owner=other_student, asset_id=asset.pk)
    with pytest.raises(FileAsset.DoesNotExist):
        uploads.delete_upload(owner=other_student, asset_id=asset.pk)
    asset.refresh_from_db()
    assert asset.processing_status == "processed_pending_review"


def test_delete_during_processing_prevents_resurrection(student, monkeypatch):
    asset = upload_for(student)

    def delete_while_parsing(*args):
        uploads.delete_upload(owner=student, asset_id=asset.pk)
        return "safe text"

    monkeypatch.setattr(uploads, "parse_remote", delete_while_parsing)
    uploads.process_upload(str(asset.pk))
    asset.refresh_from_db()
    assert asset.processing_status in {"deleted", "delete_pending"}
    assert asset.scan_status != "clean"
    assert not default_storage.exists(asset.storage_key)


def test_delete_cleanup_failure_does_not_release_quota(student, monkeypatch):
    UploadPolicy.objects.create(max_upload_bytes=10, default_storage_quota_bytes=10)
    asset = upload_for(student, b"1234567890")
    uploads.delete_upload(owner=student, asset_id=asset.pk)
    monkeypatch.setattr(
        default_storage,
        "delete",
        lambda key: (_ for _ in ()).throw(OSError("synthetic")),
    )
    uploads.cleanup_deleted(asset)
    with pytest.raises(ValidationError):
        upload_for(student, b"1")


def test_parser_failure_never_releases_clean_download(student, monkeypatch):
    asset = upload_for(student)
    monkeypatch.setattr(
        uploads,
        "parse_remote",
        lambda *args: (_ for _ in ()).throw(uploads.UnsafeUpload("parser unavailable")),
    )
    uploads.process_upload(str(asset.pk))
    asset.refresh_from_db()
    assert asset.scan_status != "clean"
    assert asset.processing_status == "retry_pending"
    with pytest.raises(PermissionDenied):
        uploads.download_upload(owner=student, asset_id=asset.pk)


def test_retry_limit_stops_poison_task(student):
    asset = upload_for(student)
    asset.metadata = {"retry_count": 3}
    asset.save()
    uploads.process_upload(str(asset.pk))
    asset.refresh_from_db()
    assert asset.processing_status == "processing_failed"


def test_recovery_prevents_expired_receiving_upload_resurrection(student, monkeypatch):
    save = default_storage.save
    def recover_before_upload_finishes(key, content):
        stored = save(key, content)
        FileAsset.objects.filter(owner=student, processing_status="receiving").update(updated_at=timezone.now() - timedelta(minutes=20))
        uploads.recover_uploads()
        return stored
    monkeypatch.setattr(default_storage, "save", recover_before_upload_finishes)
    with pytest.raises(uploads.UnsafeUpload):
        upload_for(student)
    asset = FileAsset.objects.get(owner=student)
    assert asset.processing_status == "upload_failed"
    assert not default_storage.exists(asset.quarantine_key)


def test_expired_claim_cleans_recorded_orphan_before_retry(student):
    asset = upload_for(student)
    orphan = default_storage.save(f"private/{student.pk}/old-claim.txt", SimpleUploadedFile("old.txt", b"old"))
    asset.processing_status = "processing"
    asset.metadata = {"claim_until": 0, "retry_count": 1, "output_keys": [orphan]}
    asset.save()
    uploads.process_upload(str(asset.pk))
    asset.refresh_from_db()
    assert asset.processing_status == "processed_pending_review"
    assert not default_storage.exists(orphan)


def parser_module():
    root = Path(os.getenv("KAIROS_TEST_REPOSITORY") or Path(__file__).resolve().parents[3])
    path = root / "services" / "parser" / "child.py"
    spec = importlib.util.spec_from_file_location("parser_child_fixture", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "bad", ["../escape", "\\escape", "/absolute", "C:drive", "word/../../escape"]
)
def test_docx_path_traversal_rejected(tmp_path, bad):
    archive = tmp_path / "bad.docx"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("[Content_Types].xml", "<Types/>")
        output.writestr("word/document.xml", "<document/>")
        output.writestr(bad, "unsafe")
    with pytest.raises(ValueError):
        parser_module().validate_docx(archive)


def test_docx_expansion_and_external_xml_rejected(tmp_path):
    for data in (
        b"0" * 100000,
        b'<!DOCTYPE document [<!ENTITY x SYSTEM "file:///etc/passwd">]><document/>',
    ):
        archive = tmp_path / "bad.docx"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
            output.writestr("[Content_Types].xml", "<Types/>")
            output.writestr("word/document.xml", data)
        with pytest.raises(ValueError):
            parser_module().validate_docx(archive)


def test_api_owner_boundary_and_private_metadata(student, other_student, client_for):
    client = client_for(student)
    response = client.post(
        "/api/files/upload/",
        {"file": SimpleUploadedFile("study.txt", b"study notes")},
        format="multipart",
    )
    assert response.status_code == 202
    asset = FileAsset.objects.get(pk=response.data["id"])
    asset.metadata = {
        "claim_token": "internal-only",
        "text_key": "processed/private.txt",
        "extracted_characters": 5,
    }
    asset.save()
    other = client_for(other_student)
    for action in ("", "download/", "content/"):
        assert other.get(f"/api/files/{asset.pk}/{action}").status_code == 404
    assert other.delete(f"/api/files/{asset.pk}/").status_code == 404
    data = client.get(f"/api/files/{asset.pk}/").json()
    assert "internal-only" not in str(data)
    assert "processed/private.txt" not in str(data)


@pytest.mark.django_db(transaction=True)
def test_download_is_same_origin_private_and_rechecks_release(student, other_student, client_for):
    asset = upload_for(student, data=b"private study bytes")
    uploads.process_upload(str(asset.pk))
    client = client_for(student)
    result = client.get(f"/api/files/{asset.pk}/download/")
    assert result.status_code == 200
    url = result.json()["url"]
    assert url == f"/api/files/{asset.pk}/content/"
    assert client_for(other_student).get(url).status_code == 404
    response = client.get(url)
    assert response.status_code == 200
    assert b"".join(response.streaming_content) == b"private study bytes"
    assert response["Cache-Control"] == "private, no-store"
    assert response["Content-Disposition"].startswith("attachment;")
    response.close()
    FileAsset.objects.filter(pk=asset.pk).update(scan_status="error")
    assert client.get(url).status_code == 403


@pytest.mark.django_db(transaction=True)
def test_postgres_concurrent_quota_reservations(student):
    from django.db import connection, close_old_connections

    if connection.vendor != "postgresql":
        pytest.skip("requires isolated PostgreSQL row locks")
    UploadPolicy.objects.create(max_upload_bytes=10, default_storage_quota_bytes=10)
    barrier = threading.Barrier(2)

    def reserve():
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            try:
                upload_for(student, b"1234567890")
                return "accepted"
            except ValidationError:
                return "quota"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: reserve(), range(2)))
    assert sorted(results) == ["accepted", "quota"]
    assert FileAsset.objects.filter(owner=student).count() == 1


def test_real_isolated_clamav_clean_and_eicar():
    host = os.getenv("KAIROS_TEST_CLAMAV_HOST", "")
    if not host:
        pytest.skip("requires explicit isolated ClamAV service")
    assert host == "kairos-test-clamav", (
        "never test malware signatures against production services"
    )
    scanner = REAL_CLAMD(host, 3310, timeout=60)
    clean = scanner.instream(io.BytesIO(b"KAIROS isolated clean document"))
    eicar = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
    infected = scanner.instream(io.BytesIO(eicar))
    assert next(iter(clean.values()))[0] == "OK"
    assert next(iter(infected.values()))[0] == "FOUND"
