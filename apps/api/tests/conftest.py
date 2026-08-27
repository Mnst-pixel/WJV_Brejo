import pytest
from django.core.management import call_command
from rest_framework.test import APIClient

from core.models import Role, User, UserRole


@pytest.fixture(autouse=True)
def roles(db):
    call_command("bootstrap_roles", verbosity=0)


@pytest.fixture
def student(db):
    user = User.objects.create_user(username="aluna", password="Strong-passphrase-123", display_name="Aluna")
    UserRole.objects.create(user=user, role=Role.objects.get(slug="aluno"), granted_by=user)
    return user


@pytest.fixture
def other_student(db):
    user = User.objects.create_user(username="outra", password="Strong-passphrase-456", display_name="Outra")
    UserRole.objects.create(user=user, role=Role.objects.get(slug="aluno"), granted_by=user)
    return user


@pytest.fixture
def reviewer(db):
    user = User.objects.create_user(username="revisor", password="Strong-passphrase-789", is_staff=True)
    UserRole.objects.create(user=user, role=Role.objects.get(slug="revisor-juridico"), granted_by=user)
    return user


@pytest.fixture
def client_for():
    def factory(user):
        client = APIClient()
        client.force_login(user)
        session = client.session
        session["user_session_version"] = user.session_version
        session["mfa_verified"] = user.is_staff
        session.save()
        return client

    return factory
