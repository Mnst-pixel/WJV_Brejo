#!/usr/bin/env python3
"""Optional HTTPS S3-compatible encrypted-backup upload, using stdlib SigV4."""

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import hmac
import http.client
import json
import os
from pathlib import Path
import re
import stat
import sys
from urllib.parse import quote, urlsplit


class OffhostError(Exception):
    pass


def load_config(path):
    path = Path(path)
    if not path.exists():
        return None
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_IMODE(info.st_mode) != 0o600
        or (hasattr(os, "getuid") and info.st_uid != 0)
    ):
        raise OffhostError("protected_configuration_required")
    config = json.loads(path.read_text(encoding="utf-8"))
    allowed = {
        "endpoint",
        "bucket",
        "access_key",
        "secret_key",
        "region",
        "prefix",
        "retention_days",
    }
    if not isinstance(config, dict) or config.keys() - allowed:
        raise OffhostError("invalid_configuration")
    required = ("endpoint", "bucket", "access_key", "secret_key")
    if not any(config.get(key) for key in required):
        return None
    if not all(isinstance(config.get(key), str) and config[key] for key in required):
        raise OffhostError("incomplete_configuration")
    config.setdefault("region", "us-east-1")
    config.setdefault("prefix", "kairos/backups/")
    config.setdefault("retention_days", 90)
    endpoint = urlsplit(config["endpoint"])
    if (
        endpoint.scheme != "https"
        or not endpoint.hostname
        or endpoint.username
        or endpoint.password
        or endpoint.query
        or endpoint.fragment
        or endpoint.path not in {"", "/"}
    ):
        raise OffhostError("https_endpoint_required")
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", config["bucket"]):
        raise OffhostError("invalid_bucket")
    if (
        not re.fullmatch(r"kairos/[a-zA-Z0-9_/-]{0,180}", config["prefix"])
        or not config["prefix"].endswith("/")
        or ".." in config["prefix"]
    ):
        raise OffhostError("kairos_prefix_required")
    if not re.fullmatch(r"[a-z0-9-]{1,64}", config["region"]):
        raise OffhostError("invalid_region")
    if (
        type(config["retention_days"]) is not int
        or not 1 <= config["retention_days"] <= 3650
    ):
        raise OffhostError("invalid_retention")
    if any(ord(c) < 33 or ord(c) > 126 for c in config["access_key"]) or any(
        ord(c) < 32 for c in config["secret_key"]
    ):
        raise OffhostError("invalid_credentials")
    return config


def signed_headers(config, method, path, payload_hash, headers=None, now=None):
    now = now or datetime.now(timezone.utc)
    timestamp = now.strftime("%Y%m%dT%H%M%SZ")
    date = timestamp[:8]
    result = {
        "host": urlsplit(config["endpoint"]).netloc,
        "x-amz-date": timestamp,
        "x-amz-content-sha256": payload_hash,
    }
    result.update(headers or {})
    canonical_headers = "".join(
        f"{key}:{' '.join(value.split())}\n" for key, value in sorted(result.items())
    )
    signed = ";".join(sorted(result))
    request = "\n".join((method, path, "", canonical_headers, signed, payload_hash))
    scope = f"{date}/{config['region']}/s3/aws4_request"
    signing = (
        "AWS4-HMAC-SHA256\n"
        + timestamp
        + "\n"
        + scope
        + "\n"
        + hashlib.sha256(request.encode()).hexdigest()
    )
    key = ("AWS4" + config["secret_key"]).encode()
    for part in (date, config["region"], "s3", "aws4_request"):
        key = hmac.new(key, part.encode(), hashlib.sha256).digest()
    signature = hmac.new(key, signing.encode(), hashlib.sha256).hexdigest()
    result["authorization"] = (
        f"AWS4-HMAC-SHA256 Credential={config['access_key']}/{scope}, SignedHeaders={signed}, Signature={signature}"
    )
    return result


def request(
    config,
    method,
    key,
    payload_hash,
    body=None,
    size=0,
    metadata=None,
    connection_factory=http.client.HTTPSConnection,
):
    endpoint = urlsplit(config["endpoint"])
    path = "/" + quote(config["bucket"], safe="") + "/" + quote(key, safe="/-_.~")
    headers = dict(metadata or {})
    if method == "PUT":
        headers["content-length"] = str(size)
        # Server must validate payload checksum, not merely trust a metadata field.
        headers["x-amz-checksum-sha256"] = base64.b64encode(
            bytes.fromhex(payload_hash)
        ).decode()
    headers = signed_headers(config, method, path, payload_hash, headers)
    connection = connection_factory(endpoint.hostname, endpoint.port or 443, timeout=60)
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        result = {name.lower(): value for name, value in response.getheaders()}
        # No redirects, response bodies, credentials or provider diagnostics reach logs.
        if not 200 <= response.status < 300:
            raise OffhostError("s3_request_failed")
        return result
    finally:
        connection.close()


def upload(config, archive, transport=request):
    archive = Path(archive)
    if not re.fullmatch(
        r"kairos-predeploy-\d{8}T\d{6}Z-[a-f0-9]{12}\.tar\.gz\.enc", archive.name
    ):
        raise OffhostError("invalid_archive")
    info = archive.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_IMODE(info.st_mode) != 0o600
        or (hasattr(os, "getuid") and info.st_uid != 0)
    ):
        raise OffhostError("protected_archive_required")
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
        # file_digest may bypass the file object's position: size comes from fstat.
        size = os.fstat(stream.fileno()).st_size
        if not size or size > 4 * 1024**3:
            raise OffhostError("single_put_size_limit")
        stream.seek(0)
        key = config["prefix"] + archive.name
        transport(
            config,
            "PUT",
            key,
            digest,
            body=stream,
            size=size,
            metadata={
                "x-amz-meta-sha256": digest,
                "x-amz-meta-kairos-retention-days": str(config["retention_days"]),
            },
        )
    head = transport(config, "HEAD", key, hashlib.sha256(b"").hexdigest())
    if (
        head.get("content-length") != str(size)
        or head.get("x-amz-meta-sha256") != digest
    ):
        raise OffhostError("remote_verification_failed")
    checksum_body = (digest + "  " + archive.name + "\n").encode()
    transport(
        config,
        "PUT",
        key + ".sha256",
        hashlib.sha256(checksum_body).hexdigest(),
        body=checksum_body,
        size=len(checksum_body),
    )
    return {
        "status": "PASS",
        "sha256": digest,
        "bytes": size,
        "retention": "BUCKET_LIFECYCLE_REQUIRED",
        "retention_days": config["retention_days"],
        "scope": "encrypted_object_uploaded_and_head_verified",
        "offsite_restore": "NOT_VERIFIED",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--archive", required=True)
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        result = (
            upload(config, args.archive)
            if config
            else {
                "status": "EXTERNAL_BLOCKER",
                "reason": "offhost_destination_not_configured",
            }
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error": type(exc).__name__}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
