"""Audited account commands shared by ordinary administrative forms."""
from smtplib import SMTPException
from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import PermissionDenied
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework.exceptions import ValidationError

from core.admin import locked_admin_principals
from core.audit import record_audit
from core.exceptions import Conflict
from core.models import Role, User, UserRole, UserSession
from core.permissions import active_role_slugs, is_service_account, request_has_permission
from core.rbac_policy import PRIVILEGED_ROLES


def protected_target(request, target):
    if target.pk == request.user.pk:
        raise PermissionDenied("Administre o próprio perfil pela área pessoal; não altere o próprio acesso aqui.")
    superadmin = request.user.is_superuser or "superadministrador" in active_role_slugs(request.user)
    if not superadmin and (target.is_superuser or target.role_assignments.filter(role__slug__in=PRIVILEGED_ROLES).exists()):
        raise PermissionDenied("Somente superadministrador pode alterar esta conta protegida.")


def _authorize(request, target_id=None):
    locked = locked_admin_principals(request, *([target_id] if target_id else []))
    if not request_has_permission(request, "users.manage"):
        raise PermissionDenied("Seu papel não permite administrar contas.")
    target = locked.get(target_id)
    if target_id:
        if target is None:
            raise ValidationError("Conta indisponível.")
        protected_target(request, target)
    return target


def revoke_sessions(target):
    target.session_version += 1
    UserSession.objects.filter(user=target, revoked_at__isnull=True).update(revoked_at=timezone.now())


@transaction.atomic
def create_account(request, *, username, display_name, email, justification):
    _authorize(request)
    # Provision only a human student. Elevated roles use the separate guarded command.
    role = Role.objects.get(slug="aluno")
    user = User(username=username, display_name=display_name, email=email.strip().lower())
    user.set_unusable_password()
    try:
        with transaction.atomic():
            user.save(force_insert=True)
    except IntegrityError:
        raise Conflict("Nome de acesso ou e-mail já utilizado. Confira os campos.") from None
    UserRole.objects.create(user=user, role=role, granted_by=request.user)
    record_audit("admin.user.created", actor=request.user, request=request, target=user,
        metadata={"initial_role": "aluno", "justification": justification, "access_delivery": "pending"})
    return user


@transaction.atomic
def change_account(request, *, user_id, expected_version, action, justification, display_name=None, email=None):
    target = _authorize(request, user_id)
    if target.session_version != expected_version:
        raise Conflict("A conta foi alterada. Reabra o cadastro antes de decidir.")
    changed = []
    if action == "profile":
        target.display_name = display_name
        target.email = email.strip().lower()
        changed = ["display_name", "email"]
    elif action in {"disable", "enable"}:
        target.is_active = action == "enable"
        changed = ["is_active"]
    elif action != "revoke":
        raise ValidationError("Operação de acesso inválida.")
    revoke_sessions(target)
    try:
        with transaction.atomic():
            target.save(update_fields=[*changed, "session_version", "updated_at"])
    except IntegrityError:
        raise Conflict("E-mail já associado a outra conta. Confira os dados.") from None
    record_audit("admin.user." + {"profile": "profile.changed", "disable": "disabled", "enable": "enabled", "revoke": "sessions.revoked"}[action],
        actor=request.user, request=request, target=target, metadata={"fields": changed, "justification": justification})
    return target


@transaction.atomic
def request_account_access(request, *, user_id, expected_version, justification):
    target = _authorize(request, user_id)
    if target.session_version != expected_version:
        raise Conflict("A conta foi alterada. Reabra o cadastro antes de decidir.")
    if not target.is_active or is_service_account(target) or not target.email:
        raise ValidationError("A recuperação exige conta humana ativa com e-mail cadastrado.")
    if not settings.SMTP_URL:
        record_audit("admin.user.access.requested", actor=request.user, request=request, target=target, metadata={"delivery": "unconfigured", "justification": justification})
        return "unconfigured"
    from core.recovery_policy import allow_recovery_delivery
    if not allow_recovery_delivery(request, target.email):
        return "throttled"
    uid = urlsafe_base64_encode(force_bytes(target.pk))
    token = default_token_generator.make_token(target)
    link = f"{settings.KAIROS_BASE_URL}/app/redefinir-senha?uid={uid}&token={token}"
    # Delivery is explicit operator action. Credentials never enter a page or audit log.
    try:
        sent = send_mail("Defina seu acesso ao Kairós", f"Defina uma senha pessoal neste link: {link}", settings.DEFAULT_FROM_EMAIL, [target.email])
    except (OSError, SMTPException):
        # Never log provider exceptions, which may embed connection credentials.
        sent = 0
    state = "sent" if sent else "failed"
    record_audit("admin.user.access.requested", actor=request.user, request=request, target=target,
        metadata={"delivery": state, "justification": justification})
    return state
