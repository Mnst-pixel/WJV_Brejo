"""Backend administration commands; no browser redesign and no raw policy editing."""
from uuid import UUID

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from core.audit import record_audit
from core.models import Role, User, UserRole
from core.permissions import HasKairosPermission, active_role_slugs, is_service_account
from core.rbac_policy import PRIVILEGED_ROLES, ROLES


class RoleAssignmentInput(serializers.Serializer):
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
        return Response({"user": str(target.pk), "roles": sorted(active_role_slugs(target))})

    @transaction.atomic
    def put(self, request, user_id):
        user_id = UUID(str(user_id))
        payload = RoleAssignmentInput(data=request.data)
        payload.is_valid(raise_exception=True)
        # Serialize edits to the same actor and target, including revocation of the actor.
        locked = {user.pk: user for user in User.objects.select_for_update().filter(pk__in=[request.user.pk, user_id]).order_by("pk")}
        actor = locked.get(request.user.pk)
        target = locked.get(user_id)
        if target is None:
            target = get_object_or_404(User, pk=user_id)
        request.user = actor
        self.check_permissions(request)
        if target.pk == actor.pk:
            raise PermissionDenied("Não é permitido alterar os próprios papéis.")
        previous = active_role_slugs(target)
        desired = set(payload.validated_data["roles"])
        is_super = actor.is_superuser or "superadministrador" in active_role_slugs(actor)
        if not is_super and (target.is_superuser or (previous | desired) & PRIVILEGED_ROLES):
            raise PermissionDenied("Somente superadministrador pode atribuir ou alterar papéis privilegiados.")
        if is_service_account(actor):
            raise PermissionDenied("Conta de serviço não pode conceder papéis.")
        if desired == previous:
            return Response({"user": str(target.pk), "roles": sorted(previous), "changed": False})
        role_objects = {role.slug: role for role in Role.objects.filter(slug__in=desired)}
        if set(role_objects) != desired:
            raise serializers.ValidationError("Matriz de papéis não inicializada.")
        UserRole.objects.filter(user=target).exclude(role__slug__in=desired).delete()
        for slug in sorted(desired):
            UserRole.objects.update_or_create(user=target, role=role_objects[slug], defaults={"granted_by": actor, "expires_at": None})
        target.session_version += 1
        target.save(update_fields=["session_version", "updated_at"])
        record_audit("user.roles.changed", actor=actor, request=request, target=target, metadata={
            "before": sorted(previous), "after": sorted(desired), "justification": payload.validated_data["justification"],
        })
        return Response({"user": str(target.pk), "roles": sorted(desired), "changed": True})

