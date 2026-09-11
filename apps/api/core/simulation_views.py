"""Student simulation preparation from published, reviewed objective questions."""
from django.db import transaction
from django.db.models import Count
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from core.content_workflow import fingerprint
from core.exceptions import Conflict
from core.models import Attempt, Simulation
from core.permissions import CanStudy, lock_study_user
from core.question_workflow import published_questions
from core.serializers import AttemptSerializer
from core.services.attempts import create_attempt, ensure_results_unlocked


class SimulationInput(serializers.Serializer):
    exam_phase = serializers.UUIDField()
    title = serializers.CharField(max_length=255, default="Meu simulado")
    mode = serializers.ChoiceField(choices=["formal", "training"], default="formal")
    quantity = serializers.IntegerField(min_value=1, max_value=200)
    duration_minutes = serializers.IntegerField(min_value=1, max_value=1440)
    subjects = serializers.ListField(child=serializers.UUIDField(), max_length=50, default=list)
    difficulty = serializers.ChoiceField(choices=["", "easy", "medium", "hard"], default="")
    randomize = serializers.BooleanField(default=True)
    request_id = serializers.UUIDField()

    def validate(self, values):
        if set(self.initial_data) - set(self.fields):
            raise serializers.ValidationError("Campos de configuração não permitidos.")
        return values


class SimulationCatalogView(APIView):
    permission_classes = [CanStudy]

    def get(self, request):
        query = published_questions().filter(exam_phase__phase=1).values("exam_phase_id", "exam_phase__exam__title", "exam_phase__exam__edition",
            "exam_phase__exam__exam_date", "exam_phase__duration_minutes").annotate(available=Count("pk")).order_by("-exam_phase__exam__exam_date", "exam_phase_id")
        return Response({"results": [{"id": str(row["exam_phase_id"]), "title": row["exam_phase__exam__title"], "edition": row["exam_phase__exam__edition"],
            "date": row["exam_phase__exam__exam_date"], "duration_minutes": row["exam_phase__duration_minutes"], "available": row["available"]} for row in query[:500]]})


@transaction.atomic
def start_simulation(*, owner, data):
    lock_study_user(owner)
    form = SimulationInput(data=data)
    form.is_valid(raise_exception=True)
    values = form.validated_data
    digest = fingerprint({key: value for key, value in values.items() if key != "request_id"})
    key = "simulation:" + str(values["request_id"])
    previous = Attempt.objects.filter(owner=owner, idempotency_key=key).first()
    if previous:
        if previous.frozen_definition.get("selection_config", {}).get("request_sha256") != digest:
            raise Conflict("Esta confirmação já foi usada para outra configuração.")
        return previous
    ensure_results_unlocked(owner)
    query = published_questions().filter(exam_phase_id=values["exam_phase"], exam_phase__phase=1)
    if values["subjects"]:
        query = query.filter(subject_id__in=values["subjects"])
    if values["difficulty"]:
        query = query.filter(current_version__metadata__difficulty=values["difficulty"])
    ordered = query.order_by("?") if values["randomize"] else query.order_by("number", "pk")
    selected = list(ordered.values_list("pk", flat=True)[:values["quantity"]])
    if len(selected) < values["quantity"]:
        raise serializers.ValidationError(f"Há {len(selected)} questões publicadas nessa seleção. Reduza a quantidade ou amplie os filtros.")
    simulation = Simulation.objects.create(owner=owner, exam_phase_id=values["exam_phase"], title=values["title"], mode=values["mode"],
        question_ids=[str(item) for item in selected], duration_minutes=values["duration_minutes"],
        selection_config={"request_sha256": digest, "quantity": values["quantity"], "subjects": [str(item) for item in values["subjects"]],
                          "difficulty": values["difficulty"], "randomize": values["randomize"]})
    return create_attempt(owner=owner, simulation=simulation, idempotency_key=key)


class SimulationStartView(APIView):
    permission_classes = [CanStudy]

    def post(self, request):
        return Response(AttemptSerializer(start_simulation(owner=request.user, data=request.data)).data, status=201)
