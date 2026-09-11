"""Backend administration commands; no browser redesign and no raw policy editing."""
from uuid import UUID

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from core.audit import record_audit
from core.models import Role, User, UserRole, UserSession
from core.permissions import HasKairosPermission, active_role_slugs, is_service_account, request_has_permission
from core.rbac_policy import PRIVILEGED_ROLES, ROLES


class RoleAssignmentInput(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)
    roles = serializers.ListField(child=serializers.ChoiceField(choices=tuple(ROLES)), allow_empty=False, max_length=12)
    justification = serializers.CharField(min_length=8, max_length=1000)

    def validate_roles(self, value):
        if len(value) != len(set(value)):
            raise serializers.ValidationError("Papéis duplicados.")
        if "conta-de-servico" in value and len(value) != 1:
            raise serializers.ValidationError("Conta de serviço não pode acumular papéis humanos.")
        return value


class RoleCatalogView(APIView):
    permission_classes = [HasKairosPermission]
    permission_codename = "roles.read"

    def get(self, request):
        return Response({"roles": [{"slug": slug, "permissions": sorted(permissions)} for slug, permissions in ROLES.items()]})


class UserRolesView(APIView):
    permission_classes = [HasKairosPermission]
    permission_codename = "roles.manage"

    def get(self, request, user_id):
        target = get_object_or_404(User, pk=user_id)
        roles = active_role_slugs(target) | ({"superadministrador"} if target.is_superuser else set())
        return Response({"user": str(target.pk), "roles": sorted(roles), "version": target.session_version})

    def put(self, request, user_id):
        return Response(assign_user_roles(request, user_id, request.data))


@transaction.atomic
def assign_user_roles(request, user_id, data):
    """One backend command for API and human forms; neither accepts policy grants."""
    user_id = UUID(str(user_id))
    payload = RoleAssignmentInput(data=data)
    payload.is_valid(raise_exception=True)
    locked = {user.pk: user for user in User.objects.select_for_update().filter(pk__in=[request.user.pk, user_id]).order_by("pk")}
    actor = locked.get(request.user.pk)
    target = locked.get(user_id)
    if target is None:
        target = get_object_or_404(User, pk=user_id)
    request.user = actor
    if not request_has_permission(request, "roles.manage"):
        raise PermissionDenied("A autoridade para alterar papéis foi revogada.")
    if target.pk == actor.pk:
        raise PermissionDenied("Não é permitido alterar os próprios papéis.")
    if payload.validated_data["expected_version"] != target.session_version:
        from core.exceptions import Conflict
        raise Conflict("A conta foi alterada. Confira os papéis atuais antes de salvar.")
    legacy_superuser = target.is_superuser
    previous = active_role_slugs(target) | ({"superadministrador"} if legacy_superuser else set())
    # Persisted assignments protect disabled accounts and expired privileged grants.
    assigned = set(target.role_assignments.values_list("role__slug", flat=True))
    desired = set(payload.validated_data["roles"])
    is_super = actor.is_superuser or "superadministrador" in active_role_slugs(actor)
    if not is_super and (target.is_superuser or (assigned | desired) & PRIVILEGED_ROLES):
        raise PermissionDenied("Somente superadministrador pode atribuir ou alterar papéis privilegiados.")
    if is_service_account(actor):
        raise PermissionDenied("Conta de serviço não pode conceder papéis.")
    if desired == previous and not legacy_superuser:
        return {"user": str(target.pk), "roles": sorted(previous), "changed": False, "version": target.session_version}
    role_objects = {role.slug: role for role in Role.objects.filter(slug__in=desired)}
    if set(role_objects) != desired:
        raise serializers.ValidationError("Matriz de papéis não inicializada.")
    UserRole.objects.filter(user=target).exclude(role__slug__in=desired).delete()
    for slug in sorted(desired):
        UserRole.objects.update_or_create(user=target, role=role_objects[slug], defaults={"granted_by": actor, "expires_at": None})
    target.session_version += 1
    target.is_superuser = False  # Explicit operator decision replaces legacy bypass with selected roles.
    target.save(update_fields=["is_superuser", "session_version", "updated_at"])
    from django.utils import timezone
    UserSession.objects.filter(user=target, revoked_at__isnull=True).update(revoked_at=timezone.now())
    record_audit("user.roles.changed", actor=actor, request=request, target=target, metadata={
        "before": sorted(previous), "after": sorted(desired), "justification": payload.validated_data["justification"],
        "legacy_superuser_replaced": legacy_superuser,
    })
    return {"user": str(target.pk), "roles": sorted(desired), "changed": True, "version": target.session_version}

