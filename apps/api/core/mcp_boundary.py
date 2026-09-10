"""Machine identity plus short human delegation for two read-only tools."""

import hashlib
import hmac
import json
import re
import secrets
import time

from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from rest_framework.exceptions import (
    AuthenticationFailed,
    PermissionDenied,
    Throttled,
    ValidationError,
)

from core.audit import record_audit
from core.models import StudyNote, User
from core.permissions import is_service_account, user_has_permission, user_requires_mfa
from core.services.ai_policy import redact
from core.services.ai_transport import AIUnavailable
from core.services.retrieval import hybrid_retrieve

TOOLS = {"corpus.search": "ai.consult", "study.notes.search": "study.use"}
AUDIENCE = "kairos-mcp-readonly-v1"
LIFETIME = 60


def _principals():
    principals = getattr(settings, "KAIROS_MCP_PRINCIPALS", {})
    if not isinstance(principals, dict):
        raise AIUnavailable()
    return principals


def _signing_key():
    key = getattr(settings, "KAIROS_MCP_DELEGATION_KEY", "")
    if not isinstance(key, str) or len(key) < 32 or key == settings.SECRET_KEY:
        raise AIUnavailable()
    if any(
        key == value.get("token")
        for value in _principals().values()
        if isinstance(value, dict)
    ):
        raise AIUnavailable()
    return key


def _principal(service_id):
    config = _principals().get(service_id)
    if (
        not isinstance(config, dict)
        or not isinstance(config.get("token"), str)
        or len(config["token"]) < 32
        or not config["token"].isascii()
    ):
        raise PermissionDenied("Identidade de serviço não disponível.")
    if not isinstance(config.get("scopes"), list) or any(
        scope not in TOOLS for scope in config["scopes"]
    ):
        raise PermissionDenied("Escopos de serviço inválidos.")
    try:
        machine = User.objects.get(pk=config.get("user_id"), is_active=True)
    except (User.DoesNotExist, ValueError, TypeError, DjangoValidationError):
        raise PermissionDenied("Identidade de serviço não disponível.") from None
    if (
        machine.is_superuser
        or machine.is_staff
        or not is_service_account(machine)
        or not all(
            user_has_permission(machine, permission)
            for permission in ("service.integrate", "mcp.query")
        )
    ):
        raise PermissionDenied("Conta de serviço sem autorização.")
    return config, machine


def authenticate_machine(header):
    if (
        not isinstance(header, str)
        or not header.isascii()
        or not header.startswith("Bearer ")
        or not 32 <= len(header[7:]) <= 256
    ):
        raise AuthenticationFailed("Credencial de serviço inválida.")
    token = header[7:]
    matches = [
        service
        for service, config in _principals().items()
        if isinstance(config, dict)
        and isinstance(config.get("token"), str)
        and config["token"].isascii()
        and hmac.compare_digest(token, config["token"])
    ]
    if len(matches) != 1:
        raise AuthenticationFailed("Credencial de serviço inválida.")
    config, machine = _principal(matches[0])
    return machine, {
        "principal_type": "service",
        "service_id": matches[0],
        "scopes": ["service.integrate", "mcp.query"],
        "tool_scopes": tuple(config["scopes"]),
    }


def _budget(key, maximum):
    bucket = int(time.time()) // 60
    key = "kairos:mcp:budget:" + hashlib.sha256(key.encode()).hexdigest() + f":{bucket}"
    try:
        cache.add(key, 0, timeout=120)
        count = cache.incr(key)
    except Exception:
        raise AIUnavailable() from None
    if count > maximum:
        raise Throttled(wait=60)


def mint_delegation(request, body):
    user = request.user
    if is_service_account(user) or not user_has_permission(user, "ai.consult"):
        raise PermissionDenied("Delegação exige uma conta humana autorizada.")
    if request.session.get("user_session_version") != user.session_version:
        raise PermissionDenied("Sessão revogada.")
    if user_requires_mfa(user) and not (
        user.mfa_enabled and request.session.get("mfa_verified") is True
    ):
        raise PermissionDenied("Segundo fator obrigatório.")
    if not isinstance(body, dict) or set(body) != {"service_id", "scopes"}:
        raise ValidationError("Delegação aceita somente serviço e escopos.")
    service_id, scopes = body["service_id"], body["scopes"]
    if not isinstance(service_id, str) or not re.fullmatch(
        r"[a-z][a-z0-9-]{0,63}", service_id
    ):
        raise ValidationError("Serviço inválido.")
    config, machine = _principal(service_id)
    if (
        not isinstance(scopes, list)
        or not scopes
        or len(scopes) > 2
        or any(not isinstance(scope, str) for scope in scopes)
    ):
        raise ValidationError("Escopos inválidos.")
    if any(
        scope not in TOOLS
        or scope not in config["scopes"]
        or not user_has_permission(user, TOOLS[scope])
        for scope in scopes
    ):
        raise PermissionDenied("Escopo não autorizado.")
    _budget(f"mint:{user.pk}", 20)
    payload = {
        "v": 1,
        "aud": AUDIENCE,
        "service_id": service_id,
        "machine_id": str(machine.pk),
        "uid": str(user.pk),
        "session_version": user.session_version,
        "mfa": user.mfa_enabled and request.session.get("mfa_verified") is True,
        "scopes": sorted(set(scopes)),
        "nonce": secrets.token_hex(24),
    }
    token = signing.dumps(payload, key=_signing_key(), salt=AUDIENCE, compress=False)
    record_audit(
        "mcp.delegation.issued",
        actor=user,
        request=request,
        metadata={"service_id": service_id, "scopes": payload["scopes"]},
    )
    return {"delegation": token, "expires_in": LIFETIME, "audience": AUDIENCE}


def call_tool(request, body):
    identity = request.auth
    if not isinstance(identity, dict) or identity.get("principal_type") != "service":
        raise PermissionDenied("Identidade de serviço obrigatória.")
    if not isinstance(body, dict) or set(body) != {"delegation", "tool", "arguments"}:
        raise ValidationError(
            "Chamada aceita somente delegação, ferramenta e argumentos."
        )
    token, tool, arguments = body["delegation"], body["tool"], body["arguments"]
    if (
        not isinstance(token, str)
        or len(token) > 4096
        or not isinstance(tool, str)
        or tool not in TOOLS
    ):
        raise PermissionDenied("Ferramenta ou delegação inválida.")
    if not isinstance(arguments, dict) or set(arguments) - {"query", "limit"}:
        raise ValidationError("Argumentos não permitidos.")
    query, limit = arguments.get("query"), arguments.get("limit", 5)
    if (
        not isinstance(query, str)
        or not query.strip()
        or len(query) > 400
        or type(limit) is not int
        or not 1 <= limit <= 5
    ):
        raise ValidationError("Consulta ou limite inválido.")
    try:
        delegation = signing.loads(
            token, key=_signing_key(), salt=AUDIENCE, max_age=LIFETIME, fallback_keys=[]
        )
    except signing.BadSignature:
        raise PermissionDenied("Delegação inválida ou expirada.") from None
    if not isinstance(delegation, dict) or set(delegation) != {
        "v",
        "aud",
        "service_id",
        "machine_id",
        "uid",
        "session_version",
        "mfa",
        "scopes",
        "nonce",
    }:
        raise PermissionDenied("Delegação inválida.")
    config, machine = _principal(identity["service_id"])
    if (
        delegation["v"] != 1
        or delegation["aud"] != AUDIENCE
        or delegation["service_id"] != identity["service_id"]
        or delegation["machine_id"] != str(machine.pk)
        or machine.pk != request.user.pk
    ):
        raise PermissionDenied("Delegação de outro destinatário.")
    if (
        not isinstance(delegation["scopes"], list)
        or tool not in delegation["scopes"]
        or tool not in config["scopes"]
    ):
        raise PermissionDenied("Ferramenta fora do escopo.")
    actor = User.objects.filter(pk=delegation["uid"], is_active=True).first()
    if (
        actor is None
        or is_service_account(actor)
        or actor.session_version != delegation["session_version"]
        or not user_has_permission(actor, "ai.consult")
        or not user_has_permission(actor, TOOLS[tool])
    ):
        raise PermissionDenied("Autorização humana revogada.")
    if user_requires_mfa(actor) and not (
        actor.mfa_enabled and delegation["mfa"] is True
    ):
        raise PermissionDenied("Segundo fator obrigatório.")
    nonce = delegation["nonce"]
    if not isinstance(nonce, str) or not re.fullmatch(r"[0-9a-f]{48}", nonce):
        raise PermissionDenied("Delegação inválida.")
    _budget(f"service:{identity['service_id']}", 60)
    _budget(f"user:{actor.pk}", 20)
    try:
        fresh = cache.add(f"kairos:mcp:used:{nonce}", True, timeout=LIFETIME * 2)
    except Exception:
        raise AIUnavailable() from None
    if not fresh:
        raise PermissionDenied("Delegação já utilizada.")
    if tool == "study.notes.search":
        notes = (
            StudyNote.objects.filter(owner=actor)
            .filter(Q(title__icontains=query) | Q(body__icontains=query))
            .order_by("id")[:limit]
        )
        items = [
            {
                "id": str(note.pk),
                "title": redact(note.title),
                "text": redact(note.body[:1200]),
                "version": note.version,
            }
            for note in notes
        ]
    else:
        chunks = hybrid_retrieve(question=redact(query), context={}, limit=limit)
        items = [
            {
                "id": str(chunk.pk),
                "text": redact(chunk.text[:1200]),
                "source": redact(chunk.source_locator[:512]),
                "source_hash": chunk.source_hash,
            }
            for chunk in chunks
        ]
    result = {
        "tool": tool,
        "items": items,
        "trust": "untrusted_data",
        "policy": AUDIENCE,
    }
    if len(json.dumps(result, ensure_ascii=False).encode()) > 32768:
        raise AIUnavailable()
    record_audit(
        "mcp.tool.completed",
        actor=actor,
        request=request,
        metadata={
            "service_id": identity["service_id"],
            "tool": tool,
            "count": len(items),
        },
    )
    return result
