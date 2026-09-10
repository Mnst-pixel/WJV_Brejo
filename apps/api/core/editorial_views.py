"""Server-rendered editorial workspace backed by the existing command services."""
import hashlib
from functools import wraps
from uuid import uuid4

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.http import HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.text import slugify
from rest_framework.exceptions import APIException, ValidationError

from core.audit import record_audit
from core.content_models import ContentWorkflow, LegacyContentImport
from core.content_workflow import _legacy_dataset, authorize, confirm_legacy, create_revision, preview_legacy, transition_content
from core.editorial_forms import ContentForm, FilterForm, LegacyForm, RevisionForm, SubjectForm, TopicForm, TransitionForm
from core.models import Content, ContentVersion, Subject, Topic
from core.permissions import is_service_account, request_has_permission


def editorial_access(permission):
    def decorate(view):
        @wraps(view)
        def guarded(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect("/app/entrar/?editorial=1")
            if (not request.user.mfa_enabled or is_service_account(request.user) or
                    not request_has_permission(request, permission)):
                raise PermissionDenied("Esta área exige um papel autorizado e autenticação em duas etapas.")
            if request.method not in {"GET", "POST"}:
                return HttpResponseNotAllowed(["GET", "POST"])
            try:
                return view(request, *args, **kwargs)
            except APIException as exc:
                # Domain errors remain readable, escaped and free of raw database details.
                return render(request, "editorial/error.html", {"title": "A operação não foi concluída", "detail": exc.detail}, status=exc.status_code)
        return guarded
    return decorate


def context(request, **values):
    return {"can_create": request_has_permission(request, "content.create"),
            "can_edit": request_has_permission(request, "content.edit"), **values}


def revision_values(cleaned):
    values = {name: cleaned.get(name) for name in RevisionForm.base_fields}
    # This digest authenticates authored text, never claims the linked website was fetched.
    values["source_hash"] = hashlib.sha256(values["body"].encode()).hexdigest()
    values["structured_data"] = {"provenance": {"kind": "human_authored", "hash_kind": "authored_text_sha256", "source_fetched": False}}
    return values


@editorial_access("content.read")
def dashboard(request):
    counts = [(label, ContentWorkflow.objects.filter(state=state).count()) for state, label in Content.Status.choices]
    return render(request, "editorial/dashboard.html", context(request, title="Painel editorial", counts=counts,
        subject_count=Subject.objects.count(), content_count=Content.objects.count()))


@editorial_access("content.read")
def content_list(request):
    form = FilterForm(request.GET)
    query = Content.objects.select_related("subject", "current_version").order_by("-updated_at", "pk")
    if form.is_valid():
        data = form.cleaned_data
        if data.get("q"):
            query = query.filter(versions__title__icontains=data["q"]).distinct()
        if data.get("subject"):
            query = query.filter(subject=data["subject"])
        if data.get("state"):
            query = query.filter(versions__workflow__state=data["state"]).distinct()
    else:
        query = query.none()
    params = request.GET.copy()
    params.pop("page", None)
    return render(request, "editorial/list.html", context(request, title="Conteúdo", form=form,
        page=Paginator(query, 25).get_page(request.GET.get("page")), filters=params.urlencode()))


@editorial_access("content.create")
def content_create(request):
    form = ContentForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            authorize(request.user, "content.create", request)
            data = form.cleaned_data
            content = Content.objects.create(subject=data["subject"], kind=data["kind"], created_by=request.user,
                slug=(slugify(data["title"])[:120] or "conteudo") + "-" + uuid4().hex)
            version = create_revision(actor=request.user, content_id=content.pk, values=revision_values(data), request=request)
        messages.success(request, "Rascunho salvo. Confira a prévia e envie para revisão quando estiver pronto.")
        return redirect("editorial:version", version_id=version.pk)
    return render(request, "editorial/form.html", context(request, title="Novo conteúdo", form=form, submit_label="Salvar rascunho"))


@editorial_access("content.read")
def content_detail(request, content_id):
    content = get_object_or_404(Content.objects.select_related("subject", "current_version"), pk=content_id)
    versions = content.versions.filter(workflow__isnull=False).select_related("workflow", "workflow__author", "approved_by").order_by("-version_number")
    return render(request, "editorial/history.html", context(request, title="Histórico do conteúdo", content=content,
        page=Paginator(versions, 25).get_page(request.GET.get("page"))))


@editorial_access("content.read")
def version_detail(request, version_id):
    version = get_object_or_404(ContentVersion.objects.select_related("content__subject", "workflow", "workflow__author", "approved_by", "supersedes"), pk=version_id, workflow__isnull=False)
    states = {"draft": ("review", "Enviar para revisão", "content.edit"),
              "review": ("approved", "Aprovar revisão", "content.approve"),
              "approved": ("published", "Publicar", "publication.publish"),
              "published": ("archived", "Arquivar publicação", "publication.publish")}
    next_action = states.get(version.workflow.state)
    form = None
    if next_action and request_has_permission(request, next_action[2]):
        form = TransitionForm(request.POST or None, state=next_action[0])
    if request.method == "POST":
        if not form:
            raise PermissionDenied("Seu papel não permite esta decisão.")
        if form.is_valid():
            result = transition_content(actor=request.user, version_id=version.pk, request=request, **form.cleaned_data)
            messages.success(request, "Decisão registrada no histórico.")
            return redirect("editorial:version", version_id=result.pk)
    return render(request, "editorial/version.html", context(request, title=version.title, version=version,
        state_label=dict(Content.Status.choices)[version.workflow.state], form=form,
        submit_label=next_action[1] if next_action else "", previous=version.supersedes))


@editorial_access("content.edit")
def revision_create(request, version_id):
    base = get_object_or_404(ContentVersion, pk=version_id, workflow__isnull=False)
    initial = {name: getattr(base, name) for name in RevisionForm.base_fields}
    initial["changes_summary"] = f"Revisão baseada na versão {base.version_number}."
    form = RevisionForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        values = revision_values(form.cleaned_data)
        values["structured_data"]["provenance"]["restored_from_version"] = str(base.pk)
        version = create_revision(actor=request.user, content_id=base.content_id, values=values, request=request)
        messages.success(request, "Nova versão salva como rascunho. A versão publicada continua disponível até nova aprovação.")
        return redirect("editorial:version", version_id=version.pk)
    return render(request, "editorial/form.html", context(request, title=f"Revisar a versão {base.version_number}", form=form, submit_label="Salvar nova versão"))


@editorial_access("content.read")
def taxonomy(request):
    query = Subject.objects.prefetch_related("topics__parent").order_by("name", "pk")
    return render(request, "editorial/taxonomy.html", context(request, title="Disciplinas e temas", page=Paginator(query, 25).get_page(request.GET.get("page"))))


@editorial_access("content.create")
def taxonomy_create(request, kind):
    form = (SubjectForm if kind == "subject" else TopicForm)(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            authorize(request.user, "content.create", request)
            data = form.cleaned_data
            model = Subject if kind == "subject" else Topic
            if kind == "topic" and data.get("parent"):
                parent = Topic.objects.select_for_update().get(pk=data["parent"].pk)
                if parent.subject_id != data["subject"].pk or parent.parent_id is not None:
                    raise ValidationError("O tema principal mudou. Confira a disciplina e escolha novamente.")
                data["parent"] = parent
            slug_limit = model._meta.get_field("slug").max_length - 33
            obj = model.objects.create(**data, slug=(slugify(data["name"])[:slug_limit] or "tema") + "-" + uuid4().hex)
            record_audit("content.taxonomy.created", actor=request.user, request=request, target=obj)
        messages.success(request, "Cadastro salvo.")
        return redirect("editorial:taxonomy")
    return render(request, "editorial/form.html", context(request, title="Nova disciplina" if kind == "subject" else "Novo tema ou subtema", form=form, submit_label="Salvar"))


@editorial_access("content.create")
def legacy_import(request):
    form = LegacyForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        batch, _ = preview_legacy(actor=request.user, dataset=form.cleaned_data["dataset"], subject_id=form.cleaned_data["subject_id"].pk, request=request)
        return redirect("editorial:legacy-preview", batch_id=batch.pk)
    return render(request, "editorial/form.html", context(request, title="Importar acervo antigo para revisão", form=form, submit_label="Preparar prévia"))


@editorial_access("content.create")
def legacy_preview(request, batch_id):
    batch = get_object_or_404(LegacyContentImport.objects.select_related("subject"), pk=batch_id, actor=request.user)
    if request.method == "POST":
        confirm_legacy(actor=request.user, batch_id=batch.pk, expected_hash=batch.preview_sha256, request=request)
        messages.success(request, "Acervo importado para revisão. Nenhum item foi publicado.")
        return redirect(reverse("editorial:contents") + "?state=review")
    source_hash, items = _legacy_dataset(batch.dataset)
    if source_hash != batch.source_sha256:
        raise ValidationError("O acervo mudou. Prepare uma nova prévia antes de importar.")
    return render(request, "editorial/legacy.html", context(request, title="Conferir importação", batch=batch,
        page=Paginator(items, 25).get_page(request.GET.get("page"))))
