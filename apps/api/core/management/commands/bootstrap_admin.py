import os

from django.core.management.base import BaseCommand, CommandError

from core.models import Role, User, UserRole


class Command(BaseCommand):
    help = "Creates the initial human superadministrator without changing an existing account."

    def handle(self, *args, **options):
        username = os.getenv("KAIROS_ADMIN_USERNAME", "vinicius").strip().lower()
        password = os.getenv("KAIROS_ADMIN_PASSWORD", "")
        if not password:
            raise CommandError("KAIROS_ADMIN_PASSWORD must exist in the protected environment")
        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                "display_name": os.getenv("KAIROS_ADMIN_DISPLAY_NAME", "Vinícius"),
                "email": os.getenv("KAIROS_ADMIN_EMAIL", ""),
                "is_staff": True,
                "is_superuser": True,
            },
        )
        if created:
            user.set_password(password)
            user.save(update_fields=["password"])
        role = Role.objects.get(slug="superadministrador")
        UserRole.objects.get_or_create(user=user, role=role, defaults={"granted_by": user})
        self.stdout.write(f"ADMIN_BOOTSTRAP={'CREATED' if created else 'EXISTS'}")
