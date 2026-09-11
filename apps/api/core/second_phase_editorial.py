from django.contrib import messages
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect, render
from rest_framework.exceptions import APIException

from core.audit import record_audit
from core.content_workflow import authorize
from core.editorial_views import context, editorial_access
from core.models import Exam, ExamPhase
from core.permissions import request_has_permission
from core.question_forms import ExamForm
from core.second_phase_forms import AreaForm, CaseForm, CaseTransitionForm, CriterionFormSet, DiscursiveFormSet, LIST_FIELDS, formset_payload
from core.second_phase_models import SecondPhaseArea, SecondPhaseWorkflow
from core.second_phase_workflow import CaseInput, case_payload, create_case_revision, loaded_versions, transition_case


@editorial_access("case.read")
def case_list(request):
    query = SecondPhaseWorkflow.objects.select_related("version__educational_metadata__area", "author").order_by("-created_at", "pk")
    search = request.GET.get("q", "")[:200]
    if search:
        query = query.filter(version__educational_metadata__title__icontains=search)
    return render(request, "editorial/phase2_list.html", context(request, title="Segunda fase", page=Paginator(query, 25).get_page(request.GET.get("page")), search=search,
        can_create_case=request_has_permission(request, "case.create")))


@editorial_access("case.create")
def area_create(request):
    form = AreaForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                authorize(request.user, "case.create", request)
                area = SecondPhaseArea.objects.create(**form.cleaned_data)
                record_audit("phase2.area.create", actor=request.user, request=request, target=area)
            messages.success(request, "Área criada. Você já pode selecioná-la no caso.")
            return redirect("editorial:phase2")
        except IntegrityError:
            form.add_error("name", "Já existe uma área com esse nome.")
    return render(request, "editorial/form.html", context(request, title="Criar área da segunda fase", form=form, submit_label="Criar área"))


@editorial_access("exam.create")
def exam_create(request):
    form = ExamForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                authorize(request.user, "exam.create", request)
                exam = Exam.objects.create(created_by=request.user, **{key: value for key, value in form.cleaned_data.items() if key != "duration_minutes"})
                phase = ExamPhase.objects.create(exam=exam, phase=2, duration_minutes=form.cleaned_data["duration_minutes"])
                record_audit("phase2.exam.create", actor=request.user, request=request, target=phase)
        except IntegrityError:
            form.add_error("edition", "Já existe uma prova dessa organizadora com a mesma edição.")
        else:
            messages.success(request, "Caderno da segunda fase criado.")
            return redirect("editorial:phase2")
    return render(request, "editorial/form.html", context(request, title="Criar prova ou caderno da segunda fase", form=form, submit_label="Criar caderno"))


@editorial_access("case.create")
def case_edit(request, workflow_id=None):
    previous = get_object_or_404(SecondPhaseWorkflow, pk=workflow_id) if workflow_id else None
    initial = case_payload(previous.version) if previous else {}
    questions_initial = initial.pop("questions", [])
    criteria_initial = initial.pop("criteria", [])
    for name in LIST_FIELDS:
        if name in initial:
            initial[name] = "\n".join(initial[name])
    for row in criteria_initial:
        row["acceptable_answers"] = "\n".join(row["acceptable_answers"])
    bound = request.POST if request.method == "POST" else None
    choices = [(row["code"], f"{row['code']} — {row['title']}") for row in criteria_initial]
    if bound is not None:
        choices = [(bound.get(f"criteria-{i}-code", "")[:32], bound.get(f"criteria-{i}-title", "")[:255]) for i in range(110) if bound.get(f"criteria-{i}-code")]
    form = CaseForm(bound, create=previous is None, initial=initial)
    questions = DiscursiveFormSet(bound, prefix="questions", initial=questions_initial)
    criteria = CriterionFormSet(bound, prefix="criteria", initial=criteria_initial, form_kwargs={"dependency_choices": choices})
    if request.method == "POST" and all([form.is_valid(), questions.is_valid(), criteria.is_valid()]):
        values = form.payload() | {"questions": formset_payload(questions), "criteria": formset_payload(criteria, criteria=True)}
        validated = CaseInput(data=values)
        if validated.is_valid():
            try:
                workflow = create_case_revision(actor=request.user, values=values, request=request,
                    case_id=previous.version.practical_case_id if previous else None,
                    exam_phase_id=form.cleaned_data["exam_phase_id"].pk if previous is None else None)
                messages.success(request, "Nova versão salva como rascunho. A publicação anterior permanece preservada.")
                return redirect("editorial:phase2-case", workflow_id=workflow.pk)
            except APIException as exc:
                form.add_error(None, str(exc.detail))
        else:
            form.add_error(None, "Confira fontes HTTPS, datas, referências únicas, vínculos e dependências de critérios anteriores.")
    return render(request, "editorial/phase2_form.html", context(request, title="Nova revisão do caso" if previous else "Criar caso e espelho", form=form, questions=questions, criteria=criteria))


@editorial_access("case.read")
def case_detail(request, workflow_id):
    workflow = get_object_or_404(SecondPhaseWorkflow.objects.select_related("author", "approval__reviewer"), pk=workflow_id)
    workflow.version = get_object_or_404(loaded_versions(), pk=workflow.version_id)
    choices = []
    for target, permission in [("review", "case.edit"), ("approved", "case.approve"), ("published", "publication.publish"), ("archived", "publication.publish")]:
        allowed = {"draft": ["review", "archived"], "review": ["approved", "archived"], "approved": ["published", "archived"], "published": ["archived"]}.get(workflow.state, [])
        if target in allowed and request_has_permission(request, permission):
            choices.append((target, dict(SecondPhaseWorkflow._meta.get_field("state").choices)[target]))
    form = CaseTransitionForm(request.POST or None, initial={"expected_state": workflow.state}) if choices else None
    if form:
        form.fields["target_state"].choices = choices
    if request.method == "POST":
        if not form:
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied("Ação editorial não autorizada.")
        if form.is_valid():
            result = transition_case(actor=request.user, request=request, workflow_id=workflow.pk, expected_state=form.cleaned_data["expected_state"],
                state=form.cleaned_data["target_state"], justification=form.cleaned_data["justification"], legal_status=form.cleaned_data.get("legal_status"))
            messages.success(request, "Decisão registrada no histórico editorial.")
            return redirect("editorial:phase2-case", workflow_id=result.pk)
    labels = {"temporal_marker": "Marco temporal", "jurisdiction": "Competência", "addressee": "Endereçamento", "standing": "Legitimidade", "deadline": "Prazo",
        "facts": "Fatos", "distractors": "Distratores", "preliminary_matters": "Preliminares e prejudiciais", "merits": "Teses e fundamentos", "requests": "Pedidos", "changes_summary": "Alterações nesta versão"}
    sections = [(label, "\n".join(getattr(workflow.version, field)) if field in LIST_FIELDS else getattr(workflow.version, field)) for field, label in labels.items()]
    return render(request, "editorial/phase2_case.html", context(request, title=workflow.version.educational_metadata.title, workflow=workflow, reserved_sections=sections,
        form=form, can_revise_case=request_has_permission(request, "case.edit"),
        history=SecondPhaseWorkflow.objects.filter(version__practical_case_id=workflow.version.practical_case_id).select_related("version").order_by("-created_at", "pk")))
