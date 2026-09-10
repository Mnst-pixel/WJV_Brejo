"""Server-owned consultation policy. Retrieved text cannot grant authority."""

import re
from datetime import date
from uuid import UUID
from urllib.parse import unquote, urlsplit

from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from core.models import Attempt, Simulation
from core.permissions import user_has_permission

ALLOWED_ACTIONS = frozenset(
    {
        "hint",
        "explain",
        "compare_alternatives",
        "legal_basis",
        "why_wrong",
        "create_flashcard",
        "create_similar_question",
        "add_to_review",
        "consult",
    }
)
CONTEXT_FIELDS = frozenset(
    {
        "jurisdiction",
        "document_type",
        "source_type",
        "reference_date",
        "attempt_id",
        "page",
    }
)


def validated_context(context):
    if not isinstance(context, dict) or set(context) - CONTEXT_FIELDS:
        raise ValidationError("Contexto do assistente contém campos não permitidos.")
    result = {}
    for key, value in context.items():
        if not isinstance(value, str) or len(value) > 160:
            raise ValidationError("Contexto do assistente inválido.")
        result[key] = value.strip()
    if "page" in result:
        if result.pop("page") != "consultor":
            raise ValidationError("Página do assistente inválida.")
    try:
        result["reference_date"] = (
            date.fromisoformat(result["reference_date"]).isoformat()
            if result.get("reference_date")
            else timezone.localdate().isoformat()
        )
        if "attempt_id" in result:
            result["attempt_id"] = str(UUID(result["attempt_id"]))
    except ValueError:
        raise ValidationError("Data de referência ou tentativa inválida.") from None
    return result


def authorize_consultation(*, user, question, action, context, conversation):
    if not user_has_permission(user, "ai.consult"):
        raise PermissionDenied("Consulta de IA não autorizada.")
    if (
        action not in ALLOWED_ACTIONS
        or not isinstance(question, str)
        or not question.strip()
        or len(question) > 8000
    ):
        raise ValidationError("Ação ou pergunta do assistente inválida.")
    context = validated_context(context)
    if conversation is not None and conversation.owner_id != user.pk:
        raise PermissionDenied("Conversa não autorizada.")
    if attempt_id := context.get("attempt_id"):
        attempt = (
            Attempt.objects.select_related("simulation")
            .filter(pk=attempt_id, owner=user)
            .first()
        )
        if attempt is None:
            raise PermissionDenied("Tentativa não autorizada.")
        if attempt.status == Attempt.Status.ACTIVE and (
            attempt.simulation.mode == Simulation.Mode.FORMAL
            or action not in {"hint", "add_to_review"}
        ):
            raise PermissionDenied("Assistente não permitido durante esta tentativa.")
    return context


def redact(text):
    """Remove configured service credentials and common credential assignments."""
    text = str(text)
    configured = []
    for name in (
        "SECRET_KEY",
        "LOCALAI_API_KEY",
        "HERMES_BEARER_TOKEN",
        "MCP_API_KEY",
        "MFA_ENCRYPTION_KEY",
        "KAIROS_MCP_DELEGATION_KEY",
        "KAIROS_PROXY_TOKEN",
        "KAIROS_WORDPRESS_GATE_KEY",
        "PARSER_API_TOKEN",
        "AWS_SECRET_ACCESS_KEY",
        "EMAIL_HOST_PASSWORD",
    ):
        secret = getattr(settings, name, "")
        configured.append(secret)
    for database in getattr(settings, "DATABASES", {}).values():
        if isinstance(database, dict):
            configured.append(database.get("PASSWORD", ""))
    for name in ("REDIS_URL", "CELERY_BROKER_URL", "SMTP_URL"):
        value = getattr(settings, name, "")
        if isinstance(value, str):
            try:
                password = urlsplit(value).password
            except ValueError:
                password = None
            if password:
                configured.extend((password, unquote(password)))
    for principal in getattr(settings, "KAIROS_MCP_PRINCIPALS", {}).values():
        secret = principal.get("token", "") if isinstance(principal, dict) else ""
        configured.append(secret)
    for secret in sorted({value for value in configured if isinstance(value, str) and len(value) >= 8}, key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*", "Bearer [REDACTED]", text)
    return re.sub(
        r"(?i)\b(password|secret|api[_-]?key|access[_-]?token)\s*[:=]\s*[^\s,;]+",
        r"\1=[REDACTED]",
        text,
    )
