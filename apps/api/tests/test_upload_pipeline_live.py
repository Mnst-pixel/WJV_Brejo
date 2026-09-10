"""Opt-in live isolated upload pipeline. Never point this fixture at production."""
import hashlib
import io
import os
import re
from uuid import uuid4
import zipfile

import clamd
import httpx
import pytest
from botocore.exceptions import ClientError
from django.conf import settings
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework.exceptions import PermissionDenied, ValidationError

from core.models import FileAsset, User
from core.services import uploads
from core.upload_models import UploadPolicy

pytestmark = [
    pytest.mark.skipif(os.getenv("KAIROS_TEST_LIVE_UPLOAD") != "1", reason="explicit isolated live upload fixtures required"),
    pytest.mark.django_db(transaction=True),
]

MINIO = "http://kairos-test-minio:9000"
CLAMAV = "kairos-test-clamav"
PARSER = "http://parser:8090"
TEXT = "Kairos synthetic legal study. Private fixture only."
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def live_secret():
    value = os.getenv("KAIROS_TEST_POSTGRES_PASSWORD", "")
    if not re.fullmatch(r"[a-f0-9]{64}", value) or os.getenv("PARSER_API_TOKEN") != value:
        raise RuntimeError("live upload requires matching synthetic 64-hex fixture credentials")
    return value


@pytest.fixture
def live_upload(monkeypatch):
    secret = live_secret()
    # All network destinations are literals. No URL/host override is accepted.
    database = settings.DATABASES["default"]
    if (database.get("HOST") != "kairos-test-postgres" or database.get("USER") != "kairos_test"
            or database.get("NAME") not in {"kairos_test", "kairos_test_transactions"}
            or database.get("ENGINE") != "django.db.backends.postgresql"):
        raise RuntimeError("live upload database must be isolated")
    prefix = "live-pipeline/" + uuid4().hex
    options = {
        "endpoint_url": MINIO, "bucket_name": "documents", "access_key": "kairos_test",
        "secret_key": secret, "region_name": "us-east-1", "addressing_style": "path",
        "default_acl": None, "querystring_auth": True, "location": prefix,
        "file_overwrite": False, "max_memory_size": settings.AWS_S3_MAX_MEMORY_SIZE,
        "client_config": settings.AWS_S3_CLIENT_CONFIG,
        "transfer_config": settings.AWS_S3_TRANSFER_CONFIG,
    }
    with override_settings(
        STORAGES={"default": {"BACKEND": "storages.backends.s3.S3Storage", "OPTIONS": options},
                  "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}},
        CLAMAV_HOST=CLAMAV, CLAMAV_PORT=3310, PARSER_BASE_URL=PARSER, PARSER_API_TOKEN=secret,
    ):
        # Only dispatch is controlled. Scanner, magic, HTTP parser and S3 stay real.
        monkeypatch.setattr(uploads, "enqueue_asset", lambda asset_id: None)
        client = default_storage.connection.meta.client
        if client.meta.endpoint_url != MINIO or default_storage.location != prefix:
            raise RuntimeError("unexpected storage destination")
        try:
            client.create_bucket(Bucket="documents")
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") not in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
                raise RuntimeError("isolated bucket unavailable") from None
        try:
            yield prefix
        finally:
            # Never delete a bucket or unknown prefix. Clean only this random test prefix.
            paginator = client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket="documents", Prefix=prefix + "/"):
                keys = [row["Key"] for row in page.get("Contents", [])]
                if any(not key.startswith(prefix + "/") for key in keys):
                    raise RuntimeError("isolated cleanup prefix mismatch")
                if keys:
                    result = client.delete_objects(Bucket="documents", Delete={"Objects": [{"Key": key} for key in keys], "Quiet": True})
                    if result.get("Errors"):
                        raise RuntimeError("isolated object cleanup failed")


def docx_bytes(text=TEXT):
    from docx import Document
    document = Document()
    document.add_paragraph(text)
    output = io.BytesIO()
    document.save(output)
    return output.getvalue()


def pdf_bytes():
    import pymupdf
    with pymupdf.open() as document:
        page = document.new_page(width=400, height=200)
        page.insert_text((10, 100), TEXT, fontsize=10)
        return document.tobytes()


@pytest.mark.parametrize("kind", ["txt", "docx", "pdf"])
def test_live_clean_pipeline_owner_bytes_private_storage_and_revocation(live_upload, student, other_student, client_for, kind):
    data = TEXT.encode() if kind == "txt" else docx_bytes() if kind == "docx" else pdf_bytes()
    mime = {"txt": "text/plain", "docx": DOCX_MIME, "pdf": "application/pdf"}[kind]
    client = client_for(student)
    response = client.post("/api/files/upload/", {"file": SimpleUploadedFile("synthetic." + kind, data, content_type=mime)}, format="multipart")
    assert response.status_code == 202, response.data
    asset = FileAsset.objects.get(pk=response.data["id"])
    assert asset.mime_type == mime and asset.sha256 == hashlib.sha256(data).hexdigest()
    assert asset.processing_status == "quarantined"
    assert default_storage.exists(asset.quarantine_key)
    with pytest.raises(PermissionDenied):
        uploads.download_upload(owner=student, asset_id=asset.pk)

    uploads.process_upload(str(asset.pk))
    asset.refresh_from_db()
    assert asset.processing_status == "processed_pending_review", asset.processing_status
    assert asset.scan_status == "clean" and asset.metadata["retry_count"] == 1
    with default_storage.open(asset.metadata["text_key"], "rb") as text:
        assert TEXT in text.read().decode()
    assert not default_storage.exists(asset.quarantine_key)
    key_before = asset.storage_key
    uploads.process_upload(str(asset.pk))
    asset.refresh_from_db()
    assert asset.storage_key == key_before and asset.metadata["retry_count"] == 1

    result = client.get(f"/api/files/{asset.pk}/download/")
    assert result.status_code == 200
    url = result.data["url"]
    assert url == f"/api/files/{asset.pk}/content/"
    assert client_for(other_student).get(url).status_code == 404
    result = client.get(url)
    assert result.status_code == 200 and b"".join(result.streaming_content) == data
    assert result["Cache-Control"] == "private, no-store"
    assert result["Content-Disposition"].startswith("attachment;")
    result.close()
    from rest_framework.test import APIClient
    assert APIClient().get(url).status_code == 403

    # The MinIO network endpoint itself must deny an unsigned object read.
    from urllib.parse import quote
    with httpx.Client(timeout=10, trust_env=False, follow_redirects=False) as anonymous:
        unsigned = anonymous.get(MINIO + "/documents/" + quote(live_upload + "/" + asset.storage_key, safe="/"))
        assert unsigned.status_code == 403
    User.objects.filter(pk=student.pk).update(session_version=student.session_version + 1)
    assert client.get(url).status_code == 401
    with pytest.raises(PermissionDenied):
        uploads.open_download(owner=student, asset_id=asset.pk)
    student.refresh_from_db()
    client = client_for(student)
    assert client.delete(f"/api/files/{asset.pk}/").status_code == 204
    assert client.get(url).status_code == 404
    asset.refresh_from_db()
    assert asset.processing_status == "deleted"
    assert not default_storage.exists(asset.storage_key)
    assert not default_storage.exists(asset.metadata["text_key"])


def test_live_clamav_accepts_clean_and_identifies_eicar(live_upload):
    scanner = clamd.ClamdNetworkSocket(CLAMAV, 3310, timeout=60)
    assert list(scanner.instream(io.BytesIO(TEXT.encode())).values())[0][0] == "OK"
    # Standard inert antivirus fixture, directly scanned; no production object is created.
    eicar = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
    assert list(scanner.instream(io.BytesIO(eicar)).values())[0][0] == "FOUND"


def test_live_quota_reservation_is_per_owner_and_release_after_delete(live_upload, student, other_student):
    UploadPolicy.objects.create(max_upload_bytes=100, default_storage_quota_bytes=100)
    body = b"Synthetic study material " * 3
    first = uploads.create_upload(owner=student, upload=SimpleUploadedFile("a.txt", body))
    with pytest.raises(ValidationError, match="Quota"):
        uploads.create_upload(owner=student, upload=SimpleUploadedFile("second.txt", body))
    other = uploads.create_upload(owner=other_student, upload=SimpleUploadedFile("b.txt", body))
    assert default_storage.exists(other.quarantine_key)
    uploads.delete_upload(owner=student, asset_id=first.pk)
    first.refresh_from_db()
    assert first.processing_status == "deleted" and not default_storage.exists(first.quarantine_key)
    assert default_storage.exists(other.quarantine_key)
    replacement = uploads.create_upload(owner=student, upload=SimpleUploadedFile("replacement.txt", body))
    assert replacement.processing_status == "quarantined"


def test_live_zip_bomb_rejected_by_real_parser_and_never_released(live_upload, student, tmp_path):
    data = docx_bytes("Z" * (5 * 1024**2))
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert sum(row.file_size for row in archive.infolist()) / sum(row.compress_size for row in archive.infolist()) > 100
    assert uploads.detect_mime(data[:8192]) == DOCX_MIME
    source = tmp_path / "synthetic-bomb.docx"
    source.write_bytes(data)
    with pytest.raises(uploads.UnsafeUpload, match="parser_rejected"):
        uploads.parse_remote(str(source), DOCX_MIME, hashlib.sha256(data).hexdigest())
    asset = uploads.create_upload(owner=student, upload=SimpleUploadedFile("synthetic-bomb.docx", data))
    uploads.process_upload(str(asset.pk))
    asset.refresh_from_db()
    assert asset.processing_status in {"retry_pending", "rejected"}
    assert not default_storage.exists(asset.storage_key)
    if asset.processing_status == "retry_pending":
        assert default_storage.exists(asset.quarantine_key)
    with pytest.raises(PermissionDenied):
        uploads.download_upload(owner=student, asset_id=asset.pk)
