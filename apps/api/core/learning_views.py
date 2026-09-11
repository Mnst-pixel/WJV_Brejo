"""Published reading and deterministic, owned learning summaries."""
from datetime import timedelta

from django.db import transaction
from django.db.models import Case, Count, F, Q, Sum, Value, When
from django.db.models.functions import TruncDate
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from core.content_workflow import published_content
from core.exceptions import Conflict
from core.models import Attempt, AttemptAnswer, Goal
from core.permissions import CanStudy, lock_study_user
from core.second_phase_models import WrittenSubmission
from core.serializers import ContentSerializer
from core.services.attempts import ensure_results_unlocked
from core.study_models import ReadingHistory, StudyActivity, StudyProgress


class ReadingView(APIView):
    permission_classes = [CanStudy]

    def get(self, request, content_id):
        content = get_object_or_404(published_content().select_related("subject", "current_version__workflow__approval").prefetch_related("topics"), pk=content_id)
        progress = StudyProgress.objects.filter(owner=request.user, target_kind="content", target_id=content.pk).first()
        current = bool(progress and progress.content_version_id == content.current_version_id)
        history = list(ReadingHistory.objects.filter(owner=request.user, content_version__content=content).order_by("-recorded_at").values("content_version_id", "content_version__version_number", "percent", "recorded_at")[:20])
        return Response({"content": ContentSerializer(content).data, "subject_name": content.subject.name, "history": history,
            "progress": {"version": progress.version if progress else 0, "percent": progress.percent if current else 0,
                "previous_percent": progress.percent if progress else 0, "current_publication": current,
                "needs_review": bool(progress and not current), "position": progress.position if current else 0}})


class LearningDashboardView(APIView):
    permission_classes = [CanStudy]

    @transaction.atomic
    def get(self, request):
        lock_study_user(request.user)
        days = serializers.ChoiceField(choices=[7, 30, 90]).run_validation(request.query_params.get("days", "7"))
        today = timezone.localdate()
        start = today - timedelta(days=days - 1)
        active_written = WrittenSubmission.objects.filter(owner=request.user, status="active").annotate(priority=Case(When(mode="formal", then=Value(0)), default=Value(1))).order_by("priority", "-started_at").first()
        formal = Q(frozen_definition__mode="formal") | Q(frozen_definition={}, simulation__mode="formal")
        active_objective = Attempt.objects.filter(owner=request.user, status="active").annotate(priority=Case(When(formal, then=Value(0)), default=Value(1))).order_by("priority", "-started_at").first()
        def resume():
            if active_written and (active_written.mode == "formal" or not active_objective or active_objective.priority != 0):
                return {"kind": "written", "title": active_written.frozen_definition.get("payload", {}).get("title", "Prova escrita em andamento"), "reason": "Retome sua peça e as discursivas salvas.", "href": f"/segunda-fase?submissao={active_written.pk}"}
            if active_objective:
                return {"kind": "simulation", "title": active_objective.frozen_definition.get("title", "Simulado em andamento"), "reason": "Continue com as respostas confirmadas no servidor.", "href": f"/simulados?tentativa={active_objective.pk}"}
            return None
        try:
            ensure_results_unlocked(request.user)
        except Conflict:
            return Response({"formal_active": True, "next_step": resume(), "days": days, "metrics": None})
        answers = AttemptAnswer.objects.filter(attempt__owner=request.user, attempt__status__in=["submitted", "graded"],
            attempt__submitted_at__date__gte=start, is_correct__isnull=False, selected_alternative__isnull=False)
        totals = answers.aggregate(answered=Count("pk"), correct=Count("pk", filter=Q(is_correct=True)))
        totals["accuracy"] = round(totals["correct"] * 100 / totals["answered"], 1) if totals["answered"] else None
        daily = {row["day"]: row for row in answers.annotate(day=TruncDate("attempt__submitted_at")).values("day").annotate(answered=Count("pk"), correct=Count("pk", filter=Q(is_correct=True)))}
        timeline = [{"date": str(day), "answered": daily.get(day, {}).get("answered", 0), "correct": daily.get(day, {}).get("correct", 0)} for day in (start + timedelta(days=i) for i in range(days))]
        subjects = list(answers.values("question__subject_id", "question__subject__name").annotate(answered=Count("pk"), correct=Count("pk", filter=Q(is_correct=True))).order_by("question__subject__name")[:100])
        subject_metrics = [{"id": str(row["question__subject_id"]), "name": row["question__subject__name"], "answered": row["answered"], "correct": row["correct"], "accuracy": round(100 * row["correct"] / row["answered"], 1)} for row in subjects]
        topic_metrics = [{"id": str(row["question__topic_id"]) if row["question__topic_id"] else None, "name": row["question__topic__name"] or "Sem tema informado", "answered": row["answered"], "correct": row["correct"]}
            for row in answers.values("question__topic_id", "question__topic__name").annotate(answered=Count("pk"), correct=Count("pk", filter=Q(is_correct=True))).order_by("question__topic__name")[:100]]
        activity = StudyActivity.objects.filter(owner=request.user, occurred_at__date__gte=start)
        registered_seconds = activity.aggregate(total=Sum("duration_seconds"))["total"] or 0
        known_days = {row["date"] for row in timeline if row["answered"]} | {str(day) for day in activity.annotate(day=TruncDate("occurred_at")).values_list("day", flat=True)}
        known_days |= {str(day) for day in WrittenSubmission.objects.filter(owner=request.user, status="submitted", submitted_at__date__gte=start).annotate(day=TruncDate("submitted_at")).values_list("day", flat=True)}
        streak = 0
        cursor = today if str(today) in known_days else today - timedelta(days=1)
        while str(cursor) in known_days:
            streak += 1
            cursor -= timedelta(days=1)
        completed = StudyProgress.objects.filter(owner=request.user, target_kind="content", percent=100,
            content_version_id__in=published_content().values("current_version_id"))
        goal = Goal.objects.filter(owner=request.user, progress__lt=100).order_by(F("target_date").asc(nulls_last=True), "created_at").first()
        next_step = resume()
        if not next_step and goal and goal.target_date and goal.target_date <= today:
            next_step = {"kind": "goal", "title": goal.title, "reason": "Sua meta tem prazo próximo ou já chegou à data planejada.", "href": "/metas"}
        weak = sorted([row for row in subject_metrics if row["answered"] >= 5], key=lambda row: (row["accuracy"], -row["answered"]))
        if not next_step and weak and weak[0]["accuracy"] < 70:
            next_step = {"kind": "practice", "title": f"Revisar {weak[0]['name']}", "reason": "Esta disciplina concentra oportunidades de revisão nas respostas recentes.", "href": f"/questoes?subject={weak[0]['id']}&mode=wrong"}
        if not next_step:
            content = published_content().exclude(pk__in=completed.values("target_id")).select_related("current_version").order_by("subject__order", "created_at", "pk").first()
            if content:
                publication = ContentSerializer(content).data
                next_step = {"kind": "reading", "title": publication["current_version"]["title"], "reason": "Continue a leitura de uma publicação ainda não concluída nesta versão.", "href": f"/estudar?conteudo={content.pk}"}
        if not next_step:
            next_step = {"kind": "practice", "title": "Praticar questões", "reason": "Escolha uma disciplina e revise os fundamentos de cada resposta.", "href": "/questoes"}
        return Response({"formal_active": False, "days": days, "next_step": next_step, "metrics": {**totals, "daily": timeline, "subjects": subject_metrics, "topics": topic_metrics,
            "registered_seconds": registered_seconds, "study_streak_in_period": streak, "completed_contents": completed.count(), "published_contents": published_content().count(),
            "submitted_simulations": Attempt.objects.filter(owner=request.user, status__in=["submitted", "graded"], submitted_at__date__gte=start).exclude(idempotency_key__startswith="practice:").count(),
            "submitted_written": WrittenSubmission.objects.filter(owner=request.user, status="submitted", submitted_at__date__gte=start).count()}})
