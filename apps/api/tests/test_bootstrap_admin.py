from django.core.management import call_command

from core.models import Role, User, UserRole


def test_bootstrap_admin_reconciles_profile_without_resetting_password(db, monkeypatch):
    monkeypatch.setenv("KAIROS_ADMIN_USERNAME", "vinicius")
    monkeypatch.setenv("KAIROS_ADMIN_PASSWORD", "Initial-passphrase-123")
    monkeypatch.setenv("KAIROS_ADMIN_DISPLAY_NAME", "Vinícius")
    monkeypatch.setenv("KAIROS_ADMIN_EMAIL", "first@example.test")

    call_command("bootstrap_admin", verbosity=0)
    user = User.objects.get(username="vinicius")
    assert user.check_password("Initial-passphrase-123")

    user.is_staff = False
    user.is_superuser = False
    user.is_active = False
    user.save(update_fields=["is_staff", "is_superuser", "is_active"])
    monkeypatch.setenv("KAIROS_ADMIN_PASSWORD", "Must-not-replace-password-456")
    monkeypatch.setenv("KAIROS_ADMIN_EMAIL", "updated@example.test")

    call_command("bootstrap_admin", verbosity=0)
    user.refresh_from_db()

    assert user.email == "updated@example.test"
    assert user.display_name == "Vinícius"
    assert user.is_staff and user.is_superuser and user.is_active
    assert user.check_password("Initial-passphrase-123")
    assert not user.check_password("Must-not-replace-password-456")
    assert UserRole.objects.filter(user=user, role=Role.objects.get(slug="superadministrador")).exists()
