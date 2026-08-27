from django.db.models import Q
from django.utils import timezone
from rest_framework.permissions import BasePermission

from .models import Permission


def user_has_permission(user, codename: str) -> bool:
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser:
        return True
    now = timezone.now()
    return Permission.objects.filter(
        codename=codename,
        roles__user_assignments__user=user,
    ).filter(
        Q(roles__user_assignments__expires_at__isnull=True) | Q(roles__user_assignments__expires_at__gt=now)
    ).exists()


class HasKairosPermission(BasePermission):
    permission_codename = ""

    def has_permission(self, request, view):
        codename = getattr(view, "permission_codename", self.permission_codename)
        return bool(codename and user_has_permission(request.user, codename))


class CanStudy(HasKairosPermission):
    permission_codename = "study.use"


class CanReviewLegal(HasKairosPermission):
    permission_codename = "legal.review"


class CanUpdateCorpus(HasKairosPermission):
    permission_codename = "corpus.update"


class CanAudit(HasKairosPermission):
    permission_codename = "audit.read"
