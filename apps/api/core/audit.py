from typing import Any


def record_audit(action: str, *, actor=None, request=None, target=None, metadata: dict[str, Any] | None = None):
    from .models import AuditLog

    target_type = ""
    target_id = ""
    if target is not None:
        target_type = target._meta.label_lower
        target_id = str(target.pk)

    return AuditLog.objects.create(
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        action=action,
        target_type=target_type,
        target_id=target_id,
        ip_address=_client_ip(request),
        user_agent=(request.META.get("HTTP_USER_AGENT", "")[:512] if request else ""),
        request_id=(request.headers.get("X-Request-ID", "")[:128] if request else ""),
        metadata=metadata or {},
    )


def _client_ip(request):
    if not request:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return (forwarded.split(",", 1)[0].strip() or request.META.get("REMOTE_ADDR")) if forwarded else request.META.get("REMOTE_ADDR")
