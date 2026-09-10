from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Permission, Role
from core.rbac_policy import PERMISSIONS, ROLES


class Command(BaseCommand):
    help = "Idempotently reconciles the reviewed RBAC matrix without changing user assignments."

    @transaction.atomic
    def handle(self, *args, **options):
        permissions = {}
        for codename, description in PERMISSIONS.items():
            permissions[codename], _ = Permission.objects.update_or_create(codename=codename, defaults={"description": description})
        for slug, codenames in ROLES.items():
            role, _ = Role.objects.update_or_create(slug=slug, defaults={"name": slug.replace("-", " ").title(), "is_system": True})
            role.kairos_permissions.set([permissions[codename] for codename in sorted(codenames)])
        self.stdout.write("RBAC_BOOTSTRAP=PASS")
