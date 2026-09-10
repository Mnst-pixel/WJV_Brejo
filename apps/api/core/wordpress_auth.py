"""WordPress edge authorization; WordPress credentials never replace Kairós MFA."""
import hashlib
import hmac
import re
import secrets
import time
from urllib.parse import parse_qs, unquote, urlsplit

from django.conf import settings
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.utils.crypto import constant_time_compare
from django.views.decorators.http import require_GET

from core.models import User
from core.permissions import is_service_account, request_has_permission


def request_class(method, uri, cookie="", authorization="", method_override=""):
    if method not in {"GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"}:
        return "deny"
    if not isinstance(uri, str) or not uri.startswith("/") or uri.startswith("//") or len(uri) > 8192 or any(ord(char) < 32 for char in uri):
        return "deny"
    try:
        parsed = urlsplit(uri)
        if parsed.scheme or parsed.netloc or parsed.fragment:
            return "deny"
        path = parsed.path
        for _ in range(3):
            decoded = unquote(path, errors="strict")
            if decoded == path:
                break
            path = decoded
        if "%" in path or "\\" in path or any(ord(char) < 32 for char in path):
            return "deny"
        query = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=100)
    except (ValueError, UnicodeError):
        return "deny"
    if re.search(r"(?i)(?:^|/)xmlrpc\.php(?:/|$)", path):
        return "deny"
    privileged_path = re.search(r"(?i)(?:^|/)wp-admin(?:/|$)", path) or (".php" in path.lower() and path.lower() != "/index.php")
    privileged_query = any(key.lower() in {"_method", "preview", "preview_id", "preview_nonce", "elementor-preview", "customize_changeset_uuid"} for key in query)
    edit_context = any(value.lower() == "edit" for value in query.get("context", []))
    wp_cookie = re.search(r"(?:^|;\s*)wordpress_(?:logged_in_|sec_|[a-f0-9]{32}=)", cookie, re.I)
    if method not in {"GET", "HEAD", "OPTIONS"} or privileged_path or privileged_query or edit_context or wp_cookie or authorization or method_override:
        return "admin"
    return "public"


def denied(code, status=403):
    response = JsonResponse({"error": {"code": code, "detail": "Acesso administrativo exige login Kairós atual com MFA e permissão de administração."}}, status=status)
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def attestation(request, classification, key):
    """Opaque short-lived proof, delivered only over the internal proxy hop."""
    timestamp, nonce = str(int(time.time())), secrets.token_hex(16)
    fields = [timestamp, classification, nonce, request.META["HTTP_X_FORWARDED_METHOD"],
              request.META["HTTP_X_FORWARDED_URI"]]
    for name in ("HTTP_COOKIE", "HTTP_AUTHORIZATION", "HTTP_X_HTTP_METHOD_OVERRIDE"):
        fields.append(hashlib.sha256(request.META.get(name, "").encode()).hexdigest())
    signature = hmac.new(key.encode(), "\n".join(fields).encode(), hashlib.sha256).hexdigest()
    return ".".join((timestamp, classification, nonce, signature))


@require_GET
def wordpress_auth_gate(request):
    proof = getattr(settings, "KAIROS_PROXY_TOKEN", "")
    if len(proof) < 32 or not constant_time_compare(request.META.get("HTTP_X_KAIROS_PROXY", ""), proof):
        return denied("wordpress_untrusted_edge")
    classification = request_class(request.META.get("HTTP_X_FORWARDED_METHOD", ""), request.META.get("HTTP_X_FORWARDED_URI", ""),
                                   request.META.get("HTTP_COOKIE", ""), request.META.get("HTTP_AUTHORIZATION", ""),
                                   request.META.get("HTTP_X_HTTP_METHOD_OVERRIDE", ""))
    if classification == "deny":
        return denied("wordpress_request_denied")
    gate_key = getattr(settings, "KAIROS_WORDPRESS_GATE_KEY", "")
    if len(gate_key) < 64:
        return denied("wordpress_gate_unconfigured", 503)
    if classification == "admin":
        if not request.user.is_authenticated:
            return denied("wordpress_mfa_required")
        with transaction.atomic():
            current = User.objects.select_for_update().filter(pk=request.user.pk).first()
            if (current is None or not current.is_active or not current.mfa_enabled or not current.mfa_secret_encrypted
                    or current.session_version != request.user.session_version or is_service_account(current)):
                return denied("wordpress_authority_revoked")
            request.user = current
            if not request_has_permission(request, "settings.manage"):
                return denied("wordpress_admin_permission_required")
    response = HttpResponse(status=204)
    response["Cache-Control"] = "private, no-store"
    response["X-Kairos-Wp-Gate"] = attestation(request, classification, gate_key)
    return response
