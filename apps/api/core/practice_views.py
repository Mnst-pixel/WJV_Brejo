"""Objective training delegates scoring to the frozen, owned attempt engine."""
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from core.exceptions import Conflict
from core.models import Attempt, AttemptAnswer, Bookmark, Simulation, StudyMark
from core.permissions import CanStudy, lock_study_user
from core.question_workflow import published_questions
from core.services.attempts import autosave_attempt, create_attempt, ensure_results_unlocked, submit_attempt


class PracticeInput(serializers.Serializer):
    question = serializers.UUIDField()
    selected_alternative = serializers.UUIDField()
    request_id = serializers.UUIDField()
    elapsed_seconds = serializers.IntegerField(min_value=0, max_value=3600, default=0)

    def validate(self, data):
        if set(self.initial_data) - set(self.fields):
            raise serializers.ValidationError("Campos não permitidos na resposta.")
        return data


class QuestionFilters(serializers.Serializer):
    subject = serializers.UUIDField(required=False)
    topic = serializers.UUIDField(required=False)
    difficulty = serializers.ChoiceField(choices=["easy", "medium", "hard"], required=False)
    year = serializers.IntegerField(min_value=1900, max_value=2200, required=False)
    q = serializers.CharField(max_length=200, required=False, allow_blank=True)
    mode = serializers.ChoiceField(choices=["all", "unseen", "answered", "wrong", "favorites", "review", "random"], default="all")


def filter_questions(query, params, owner):
    form = QuestionFilters(data=params)
    form.is_valid(raise_exception=True)
    values = form.validated_data
    for field, target in {"subject": "subject_id", "topic": "topic_id", "difficulty": "current_version__metadata__difficulty", "year": "exam_phase__exam__exam_date__year"}.items():
        if field in values:
            query = query.filter(**{target: values[field]})
    if values.get("q"):
        query = query.filter(current_version__statement__icontains=values["q"])
    answers = AttemptAnswer.objects.filter(attempt__owner=owner, attempt__status__in=["submitted", "graded"], selected_alternative__isnull=False)
    mode = values["mode"]
    if mode == "wrong":
        ensure_results_unlocked(owner)
    if mode == "unseen":
        query = query.exclude(pk__in=answers.values("question_id"))
    elif mode == "answered":
        query = query.filter(pk__in=answers.values("question_id"))
    elif mode == "wrong":
        query = query.filter(pk__in=answers.filter(is_correct=False).values("question_id"))
    elif mode == "favorites":
        query = query.filter(pk__in=Bookmark.objects.filter(owner=owner, target_type="question").values("target_id"))
    elif mode == "review":
        query = query.filter(pk__in=StudyMark.objects.filter(owner=owner, target_kind="question", kind="review").values("target_id"))
    return query.order_by("?") if mode == "random" else query


def practice_result(attempt):
    item = attempt.frozen_definition["questions"][0]
    result = attempt.result_snapshot["questions"][0]
    return {"attempt": str(attempt.pk), "question": item["question"], "statement": item["statement"],
        "submitted_at": attempt.submitted_at, "elapsed_seconds": attempt.elapsed_seconds,
        "subject_name": item.get("subject_name", ""), "topic_name": item.get("topic_name", ""),
        "source_url": item.get("source_url", ""), "reference_date": item.get("reference_date"),
        "legal_basis": item.get("legal_basis", ""), **result}


@transaction.atomic
def answer_question(*, owner, values):
    lock_study_user(owner)
    data = PracticeInput(data=values)
    data.is_valid(raise_exception=True)
    value = data.validated_data
    ensure_results_unlocked(owner)
    request_key = "practice:" + str(value["request_id"])
    previous = Attempt.objects.filter(owner=owner, idempotency_key=request_key).first()
    if previous:
        items = previous.frozen_definition.get("questions", [])
        answers = previous.result_snapshot.get("questions", [])
        if (len(items) != 1 or len(answers) != 1 or items[0]["question"] != str(value["question"]) or
                answers[0]["selected_alternative"] != str(value["selected_alternative"])):
            raise Conflict("Essa confirmação já foi usada para outra resposta.")
        return previous
    question = get_object_or_404(published_questions().select_related("exam_phase"), pk=value["question"])
    simulation = Simulation.objects.create(owner=owner, exam_phase=question.exam_phase, mode="training", title="Treino de questão",
        question_ids=[str(question.pk)], duration_minutes=60)
    attempt = create_attempt(owner=owner, simulation=simulation, idempotency_key=request_key)
    autosave_attempt(attempt_id=attempt.pk, owner=owner, expected_version=1, elapsed_seconds=value["elapsed_seconds"],
        answers=[{"question": str(question.pk), "selected_alternative": str(value["selected_alternative"])}])
    return submit_attempt(attempt_id=attempt.pk, owner=owner)


class PracticeAnswerView(APIView):
    permission_classes = [CanStudy]

    def post(self, request):
        attempt = answer_question(owner=request.user, values=request.data)
        return Response(practice_result(attempt))


class PracticeMarksView(APIView):
    permission_classes = [CanStudy]

    def get(self, request, question_id):
        get_object_or_404(published_questions(), pk=question_id)
        return Response({"favorite": Bookmark.objects.filter(owner=request.user, target_type="question", target_id=question_id).exists(),
            "review": StudyMark.objects.filter(owner=request.user, target_kind="question", target_id=question_id, locator="question", kind="review").exists()})

    @transaction.atomic
    def put(self, request, question_id):
        lock_study_user(request.user)
        get_object_or_404(published_questions(), pk=question_id)
        if not isinstance(request.data, dict) or set(request.data) != {"favorite", "review"} or any(type(value) is not bool for value in request.data.values()):
            raise serializers.ValidationError("Informe apenas as duas marcações da questão.")
        for enabled, model, lookup in [
            (request.data["favorite"], Bookmark, {"owner": request.user, "target_type": "question", "target_id": question_id}),
            (request.data["review"], StudyMark, {"owner": request.user, "target_kind": "question", "target_id": question_id, "locator": "question", "kind": "review"}),
        ]:
            if enabled:
                if not model.objects.filter(**lookup).exists() and model.objects.filter(owner=request.user).count() >= 5000:
                    raise serializers.ValidationError("Limite de marcações atingido.")
                model.objects.get_or_create(**lookup)
            else:
                model.objects.filter(**lookup).delete()
        return Response(request.data)


class PracticeHistoryView(APIView):
    permission_classes = [CanStudy]

    def get(self, request):
        ensure_results_unlocked(request.user)
        query = Attempt.objects.filter(owner=request.user, status__in=["submitted", "graded"], idempotency_key__startswith="practice:", frozen_definition__mode="training", result_snapshot__total=1).order_by("-submitted_at", "pk")
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(query, request)
        return paginator.get_paginated_response([practice_result(attempt) for attempt in page])


class LearningAccuracyView(APIView):
    permission_classes = [CanStudy]

    def get(self, request):
        ensure_results_unlocked(request.user)
        # Scalar facts are written only by deterministic submission, never supplied by the client.
        answers = AttemptAnswer.objects.filter(attempt__owner=request.user, attempt__status__in=["submitted", "graded"], is_correct__isnull=False, selected_alternative__isnull=False)
        summary = answers.aggregate(answered=Count("pk"), correct=Count("pk", filter=Q(is_correct=True)))
        summary["accuracy"] = round(100 * summary["correct"] / summary["answered"], 1) if summary["answered"] else None
        by_subject = answers.values("question__subject_id", "question__subject__name").annotate(answered=Count("pk"), correct=Count("pk", filter=Q(is_correct=True))).order_by("question__subject__name")[:100]
        summary["subjects"] = [{"id": str(row["question__subject_id"]), "name": row["question__subject__name"], "answered": row["answered"], "correct": row["correct"],
            "accuracy": round(100 * row["correct"] / row["answered"], 1)} for row in by_subject]
        summary["historical_unclassified"] = AttemptAnswer.objects.filter(attempt__owner=request.user, attempt__status__in=["submitted", "graded"], is_correct__isnull=True).count()
        return Response(summary)
