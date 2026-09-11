from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect, render

from core.audit import record_audit
from core.content_workflow import authorize
from core.editorial_forms import TransitionForm
from core.editorial_views import context, editorial_access
from core.models import Exam, ExamPhase
from core.permissions import request_has_permission
from core.question_forms import ExamForm, QuestionForm
from core.question_models import QuestionWorkflow
from core.question_workflow import create_question, question_payload, revise_question, transition_question


@editorial_access("exam.create")
def exam_create(request):
    form = ExamForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                authorize(request.user, "exam.create", request)
                values = dict(form.cleaned_data)
                duration = values.pop("duration_minutes")
                exam = Exam.objects.create(created_by=request.user, **values)
                ExamPhase.objects.create(exam=exam, phase=1, duration_minutes=duration)
                record_audit("exam.created", actor=request.user, request=request, target=exam)
        except IntegrityError:
            form.add_error("edition", "Já existe uma prova dessa organizadora com a mesma edição.")
        else:
            messages.success(request, "Prova cadastrada. Agora você pode criar suas questões.")
            return redirect("editorial:questions")
    return render(request, "editorial/form.html", context(request, title="Nova prova de 1ª fase ou caderno", form=form, submit_label="Salvar prova"))


@editorial_access("question.read")
def question_list(request):
    query = QuestionWorkflow.objects.select_related("version__question__subject", "version__question__exam_phase__exam", "author").order_by("-created_at", "pk")
    search = request.GET.get("q", "")[:200]
    if search:
        query = query.filter(version__statement__icontains=search)
    state = request.GET.get("state", "")
    if state:
        query = query.filter(state=state)
    filters = request.GET.copy()
    filters.pop("page", None)
    return render(request, "editorial/questions.html", context(request, title="Questões", page=Paginator(query, 25).get_page(request.GET.get("page")),
        can_create_question=request_has_permission(request, "question.create"), can_create_exam=request_has_permission(request, "exam.create"), search=search, state=state, filters=filters.urlencode()))


@editorial_access("question.create")
def question_create(request):
    form = QuestionForm(request.POST or None, create=True)
    if request.method == "POST" and form.is_valid():
        workflow = create_question(actor=request.user, request=request, values=form.payload(),
            exam_phase_id=form.cleaned_data["exam_phase_id"].pk, subject_id=form.cleaned_data["subject_id"].pk,
            topic_id=getattr(form.cleaned_data["topic_id"], "pk", None))
        messages.success(request, "Questão salva como rascunho. Confira também as alternativas e o gabarito.")
        return redirect("editorial:question-version", workflow_id=workflow.pk)
    return render(request, "editorial/form.html", context(request, title="Nova questão", form=form, submit_label="Salvar questão como rascunho"))


@editorial_access("question.read")
def question_detail(request, workflow_id):
    workflow = get_object_or_404(QuestionWorkflow.objects.select_related("version__metadata", "version__question__subject", "version__question__exam_phase__exam",
        "answer_key_version__correct_alternative", "author", "approval__reviewer"), pk=workflow_id)
    actions = {"draft": ("review", "Enviar questão para revisão", "question.edit"), "review": ("approved", "Aprovar questão", "question.approve"),
               "approved": ("published", "Publicar questão", "publication.publish"), "published": ("archived", "Arquivar questão", "publication.publish")}
    action = actions.get(workflow.state)
    form = TransitionForm(request.POST or None, state=action[0]) if action and request_has_permission(request, action[2]) else None
    if request.method == "POST":
        if not form:
            raise PermissionDenied("Seu papel não permite essa decisão.")
        if form.is_valid():
            result = transition_question(actor=request.user, request=request, workflow_id=workflow.pk, **form.cleaned_data)
            messages.success(request, "Decisão registrada para questão, alternativas, gabarito e metadados.")
            return redirect("editorial:question-version", workflow_id=result.pk)
    return render(request, "editorial/question.html", context(request, title=f"Questão {workflow.version.question.number}", workflow=workflow,
        alternatives=workflow.version.alternatives.all(), form=form, submit_label=action[1] if action else "",
        can_revise_question=request_has_permission(request, "question.edit")))


@editorial_access("question.edit")
def question_revise(request, workflow_id):
    base = get_object_or_404(QuestionWorkflow.objects.select_related("version__metadata", "answer_key_version__correct_alternative"), pk=workflow_id)
    initial = question_payload(base)
    initial["tags"] = ", ".join(initial["tags"])
    for row in initial.pop("alternatives"):
        initial["alternative_" + row["label"]] = row["text"]
    form = QuestionForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        workflow = revise_question(actor=request.user, workflow_id=base.pk, values=form.payload(), request=request)
        messages.success(request, "Nova revisão criada. A publicação anterior foi preservada.")
        return redirect("editorial:question-version", workflow_id=workflow.pk)
    return render(request, "editorial/form.html", context(request, title="Revisar questão", form=form, submit_label="Salvar nova versão da questão"))
