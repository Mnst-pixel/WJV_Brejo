from django.db.models import Q
from django.utils import timezone
from rest_framework.permissions import BasePermission

from .models import Permission
from .rbac_policy import ADMIN_PERMISSIONS, MACHINE_PERMISSIONS, PERMISSIONS, ROLES


def lock_study_user(user):
    """Caller owns a transaction: user first, then owned object, as RBAC revocation."""
    from rest_framework.exceptions import PermissionDenied
    from .models import User
    current = User.objects.select_for_update().filter(pk=user.pk).first()
    if (current is None or not current.is_active or current.session_version != user.session_version
            or not user_has_permission(current, "study.use")):
        raise PermissionDenied("O acesso foi revogado durante a operação de estudo.")
    return current


def active_role_slugs(user):
    if not user or not user.is_authenticated or not user.is_active:
        return set()
    return set(user.role_assignments.filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())
    ).values_list("role__slug", flat=True))


def is_service_account(user):
    # Identity classification survives expiry/inactivation. Only its effective
    # grant expires; accidental human flags can never convert it to an admin.
    return bool(user and user.is_authenticated and user.pk and
                user.role_assignments.filter(role__slug="conta-de-servico").exists())


def user_requires_mfa(user):
    roles = active_role_slugs(user)
    if is_service_account(user):
        return False
    return bool(user and user.is_authenticated and user.is_active and (
        user.is_staff or user.is_superuser or any(ROLES.get(role, set()) & ADMIN_PERMISSIONS for role in roles)
    ))


def user_has_permission(user, codename: str) -> bool:
    if codename not in PERMISSIONS or not user or not user.is_authenticated or not user.is_active:
        return False
    roles = active_role_slugs(user)
    if is_service_account(user):
        # A machine principal is never a human administrator, even with accidental extra roles.
        roles &= {"conta-de-servico"}
    elif user.is_superuser:
        return codename not in MACHINE_PERMISSIONS
    eligible = [role for role in roles if codename in ROLES.get(role, set())]
    return bool(eligible) and Permission.objects.filter(codename=codename, roles__slug__in=eligible).exists()


def request_has_permission(request, codename):
    if not user_has_permission(request.user, codename):
        return False
    if is_service_account(request.user):
        # Populated exclusively by the trusted machine authentication backend, never request.data.
        auth = getattr(request, "auth", None)
        return isinstance(auth, dict) and auth.get("principal_type") == "service" and codename in auth.get("scopes", ())
    if codename in ADMIN_PERMISSIONS:
        return bool(request.session.get("mfa_verified") is True and
                    request.session.get("user_session_version") == request.user.session_version)
    return True


class HasKairosPermission(BasePermission):
    permission_codename = ""

    def has_permission(self, request, view):
        codename = getattr(view, "permission_codename", self.permission_codename)
        return bool(codename and request_has_permission(request, codename))


class CanStudy(HasKairosPermission):
    permission_codename = "study.use"


class CanReviewLegal(HasKairosPermission):
    permission_codename = "legal.review"


class CanUpdateCorpus(HasKairosPermission):
    permission_codename = "corpus.update"


class CanAudit(HasKairosPermission):
    permission_codename = "audit.read"

