import pytest

from core.exceptions import Conflict
from core.models import User
from core.serializers import UserSerializer

pytestmark = pytest.mark.django_db


def test_stale_profile_cannot_restore_revoked_session(student):
    serializer = UserSerializer(student, data={"display_name": "Changed"}, partial=True)
    assert serializer.is_valid()
    User.objects.filter(pk=student.pk).update(session_version=student.session_version + 1)
    with pytest.raises(Conflict):
        serializer.save()
    student.refresh_from_db()
    assert student.session_version == 2 and student.display_name != "Changed"


def test_profile_patch_only_updates_allowed_fields_and_merges_preferences(student, client_for):
    client = client_for(student)
    assert client.patch("/api/auth/me", {"preferences": {"reduced_motion": True}, "is_superuser": True}, format="json").status_code == 200
    assert client.patch("/api/auth/me", {"preferences": {"comfortable_reading": False}}, format="json").status_code == 200
    student.refresh_from_db()
    assert student.preferences == {"reduced_motion": True, "comfortable_reading": False}
    assert not student.is_superuser


@pytest.mark.parametrize("value", [{"unknown": True}, {"reduced_motion": "yes"}, [], {"reduced_motion": {"nested": True}}])
def test_invalid_preferences_rejected(student, client_for, value):
    assert client_for(student).patch("/api/auth/me", {"preferences": value}, format="json").status_code == 400
