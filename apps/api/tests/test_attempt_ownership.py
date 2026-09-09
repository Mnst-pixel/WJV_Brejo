import pytest
from django.utils import timezone

from core.models import Attempt, Exam, ExamPhase, Simulation


@pytest.fixture
def simulation_factory(student):
    exam = Exam.objects.create(title="Prova teste", edition="P0", exam_date=timezone.localdate(), official_source_url="https://example.invalid/exam", created_by=student)
    phase = ExamPhase.objects.create(exam=exam, phase=1)

    def create(owner, title):
        return Simulation.objects.create(owner=owner, title=title, exam_phase=phase, mode="formal")

    return create


@pytest.mark.django_db
@pytest.mark.parametrize("method", ["patch", "put"])
def test_attempt_cannot_be_relinked_to_another_user(student, other_student, client_for, method, simulation_factory):
    own = simulation_factory(student, "Próprio")
    foreign = simulation_factory(other_student, "Privado")
    attempt = Attempt.objects.create(owner=student, simulation=own)
    response = getattr(client_for(student), method)(f"/api/attempts/{attempt.id}/", {"simulation": str(foreign.id)}, format="json")
    assert response.status_code in {400, 403}
    attempt.refresh_from_db()
    assert attempt.simulation_id == own.id


@pytest.mark.django_db
def test_attempt_simulation_is_immutable_even_for_same_owner(student, client_for, simulation_factory):
    own = simulation_factory(student, "Original")
    another = simulation_factory(student, "Outro")
    attempt = Attempt.objects.create(owner=student, simulation=own)
    response = client_for(student).patch(f"/api/attempts/{attempt.id}/", {"simulation": str(another.id)}, format="json")
    assert response.status_code == 400
    attempt.refresh_from_db()
    assert attempt.simulation_id == own.id


@pytest.mark.django_db
def test_attempt_create_accepts_own_and_rejects_foreign_simulation(student, other_student, client_for, simulation_factory):
    own = simulation_factory(student, "Próprio")
    foreign = simulation_factory(other_student, "Privado")
    client = client_for(student)
    assert client.post("/api/attempts/", {"simulation": str(own.id)}, format="json").status_code == 201
    assert client.post("/api/attempts/", {"simulation": str(foreign.id)}, format="json").status_code in {400, 403}
    assert Attempt.objects.filter(owner=student).count() == 1
