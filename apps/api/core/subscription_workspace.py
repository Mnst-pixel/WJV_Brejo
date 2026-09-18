"""Human forms over the existing plans, enrollment and private upload limits."""
from uuid import uuid4

from django import forms
from django.conf import settings
from django.contrib import messages
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError as ModelValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify
from rest_framework.exceptions import ValidationError

from core.account_commands import protected_target
from core.admin import locked_admin_principals
from core.audit import record_audit
from core.editorial_views import context, editorial_access
from core.exceptions import Conflict
from core.models import FileAsset, Permission, User
from core.permissions import active_role_slugs, is_service_account, request_has_permission
from core.rbac_policy import PRIVILEGED_ROLES
from core.upload_admin import MIB, PlanForm, UploadPolicyForm
from core.upload_models import Enrollment, Plan, UploadPolicy

SALT = "kairos.subscription.form.v1"


def snapshot(obj):
    if obj is None:
        return None
    return {field.attname: str(getattr(obj, field.attname)) for field in obj._meta.concrete_fields}


def token(request, kind, target, obj):
    return signing.dumps({"actor": str(request.user.pk), "kind": kind, "target": str(target), "snapshot": snapshot(obj)}, salt=SALT)


def check_token(request, value, kind, target, obj):
    try:
        expected = signing.loads(value, salt=SALT, max_age=3600)
    except signing.BadSignature:
        raise Conflict("Formulário expirado ou inválido. Reabra a página antes de salvar.") from None
    if expected != {"actor": str(request.user.pk), "kind": kind, "target": str(target), "snapshot": snapshot(obj)}:
        raise Conflict("Os dados mudaram durante a edição. Reabra a página para conferir a situação atual.")


class DecisionFields(forms.Form):
    expected_state = forms.CharField(widget=forms.HiddenInput, max_length=6000)
    justification = forms.CharField(label="Motivo da alteração", min_length=10, max_length=1000, widget=forms.Textarea(attrs={"rows": 3}))


class FriendlyPlanForm(PlanForm, DecisionFields):
    creation_id = forms.UUIDField(required=False, widget=forms.HiddenInput)

    class Meta(PlanForm.Meta):
        fields = ("name", "active")

    def clean(self):
        data = super().clean()
        if self.instance._state.adding and not data.get("creation_id"):
            self.add_error("creation_id", "Reabra o formulário para criar o plano.")
        return data


class FriendlyPolicyForm(UploadPolicyForm, DecisionFields):
    pass


class EnrollmentForm(DecisionFields):
    plan = forms.ModelChoiceField(label="Plano", queryset=Plan.objects.none(), empty_label="Escolha um plano")
    status = forms.ChoiceField(label="Estado da matrícula", choices=Enrollment._meta.get_field("status").choices)
    valid_from = forms.DateTimeField(label="Início da validade", widget=forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}))
    valid_to = forms.DateTimeField(label="Fim da validade", required=False, widget=forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}), help_text="Deixe em branco para validade sem data final.")

    def __init__(self, *args, current=None, **kwargs):
        super().__init__(*args, **kwargs)
        condition = Q(active=True)
        if current:
            condition |= Q(pk=current.plan_id)
        self.fields["plan"].queryset = Plan.objects.filter(condition).order_by("name", "pk")

    def clean(self):
        data = super().clean()
        if data.get("valid_from") and data.get("valid_to") and data["valid_to"] <= data["valid_from"]:
            self.add_error("valid_to", "O fim da validade deve ser posterior ao início.")
        return data


def authorize_settings(request, owner_id=None):
    locked = locked_admin_principals(request, *([owner_id] if owner_id else []))
    if not request_has_permission(request, "settings.manage"):
        raise PermissionDenied("Seu papel não permite administrar planos e limites.")
    if owner_id:
        owner = locked.get(owner_id)
        if owner is None or is_service_account(owner):
            raise PermissionDenied("Matrículas são destinadas a contas pessoais.")
        protected_target(request, owner)
    # Same lock order and mutex as the existing settings admin.
    Permission.objects.select_for_update().get(codename="settings.manage")


def enrollment_authority(request):
    return request_has_permission(request, "settings.manage"), request.user.is_superuser or "superadministrador" in active_role_slugs(request.user)


def can_manage_enrollment(request, owner, authority=None):
    # Display only; commands independently recheck fresh rows inside the lock.
    allowed, superadmin = authority if authority is not None else enrollment_authority(request)
    roles = {grant.role.slug for grant in owner.role_assignments.all()}
    return bool(allowed and owner.pk != request.user.pk and "conta-de-servico" not in roles and
        (superadmin or (not owner.is_superuser and not roles.intersection(PRIVILEGED_ROLES))))


def validate_and_save(obj):
    try:
        if isinstance(obj, (Plan, UploadPolicy)) and obj.max_upload_bytes > settings.KAIROS_MAX_UPLOAD_BYTES:
            raise ModelValidationError("unsafe upload maximum")
        obj.full_clean()
    except ModelValidationError:
        raise ValidationError("Os dados são incompatíveis. Confira os limites e a validade.") from None
    obj.save()


@transaction.atomic
def save_plan(request, plan_id, values):
    authorize_settings(request)
    target_id = plan_id or values["creation_id"]
    current = Plan.objects.select_for_update().filter(pk=target_id).first()
    check_token(request, values["expected_state"], "plan", target_id, current)
    obj = current or Plan(id=target_id, code=(slugify(values["name"])[:25] or "plano") + "-" + uuid4().hex)
    for name in ("name", "active"):
        setattr(obj, name, values[name])
    obj.max_upload_bytes = values["max_upload_mib"] * MIB
    obj.storage_quota_bytes = values["storage_quota_mib"] * MIB
    validate_and_save(obj)
    record_audit("admin.plan.changed", actor=request.user, request=request, target=obj,
        metadata={"justification": values["justification"], "fields": ["name", "active", "max_upload_bytes", "storage_quota_bytes"]})
    return obj


@transaction.atomic
def save_policy(request, values):
    authorize_settings(request)
    current = UploadPolicy.objects.select_for_update().first()
    check_token(request, values["expected_state"], "policy", "global", current)
    obj = current or UploadPolicy()
    obj.enabled = values["enabled"]
    obj.max_upload_bytes = values["max_upload_mib"] * MIB
    obj.default_storage_quota_bytes = values["storage_quota_mib"] * MIB
    validate_and_save(obj)
    record_audit("admin.upload_settings.changed", actor=request.user, request=request, target=obj,
        metadata={"justification": values["justification"], "fields": ["enabled", "max_upload_bytes", "default_storage_quota_bytes"]})


@transaction.atomic
def save_enrollment(request, owner_id, values):
    authorize_settings(request, owner_id)
    plan = Plan.objects.select_for_update().get(pk=values["plan"].pk)
    current = Enrollment.objects.select_for_update().filter(owner_id=owner_id).first()
    check_token(request, values["expected_state"], "enrollment", owner_id, current)
    if not plan.active and (current is None or current.plan_id != plan.pk):
        raise Conflict("O plano foi desativado. Escolha um plano disponível.")
    obj = current or Enrollment(owner_id=owner_id)
    obj.plan = plan
    for name in ("status", "valid_from", "valid_to"):
        setattr(obj, name, values[name])
    validate_and_save(obj)
    record_audit("admin.enrollment.changed", actor=request.user, request=request, target=obj,
        metadata={"justification": values["justification"], "fields": ["plan", "status", "valid_from", "valid_to"]})
    return obj


@editorial_access("settings.read")
def subscriptions(request):
    search = str(request.GET.get("q", ""))[:150].strip()
    plans = Plan.objects.annotate(enrollment_count=Count("enrollment")).order_by("name", "pk")
    enrollments = Enrollment.objects.select_related("owner", "plan").prefetch_related("owner__role_assignments__role").order_by("-updated_at", "pk")
    if search:
        enrollments = enrollments.filter(Q(owner__display_name__icontains=search) | Q(owner__username__icontains=search) | Q(plan__name__icontains=search))
    page = Paginator(enrollments, 25).get_page(request.GET.get("page"))
    now = timezone.now()
    authority = enrollment_authority(request)
    for item in page:
        item.available = item.status == "active" and item.plan.active and item.valid_from <= now and (item.valid_to is None or item.valid_to > now)
        item.can_manage = can_manage_enrollment(request, item.owner, authority)
    return render(request, "editorial/subscriptions.html", context(request, title="Assinaturas e planos", plans=plans, page=page, search=search, can_manage_settings=request_has_permission(request, "settings.manage")))


@editorial_access("settings.manage")
def plan_edit(request, plan_id=None):
    current = get_object_or_404(Plan, pk=plan_id) if plan_id else None
    target_id = plan_id or uuid4()
    form = FriendlyPlanForm(request.POST or None, instance=current, initial={"expected_state": token(request, "plan", target_id, current), "creation_id": target_id})
    if request.method == "POST" and form.is_valid():
        save_plan(request, plan_id, form.cleaned_data)
        messages.success(request, "Plano salvo. Os limites serão verificados nos próximos uploads; arquivos existentes permanecem preservados.")
        return redirect("editorial:subscriptions")
    return render(request, "editorial/subscription_form.html", context(request, title="Editar plano" if current else "Criar plano", form=form, submit_label="Salvar plano", scope="plan"))


@editorial_access("settings.manage")
def policy_edit(request):
    current = UploadPolicy.objects.first()
    form = FriendlyPolicyForm(request.POST or None, instance=current, initial={"expected_state": token(request, "policy", "global", current)})
    if request.method == "POST" and form.is_valid():
        save_policy(request, form.cleaned_data)
        messages.success(request, "Limites gerais salvos. Arquivos existentes permanecem preservados.")
        return redirect("editorial:subscriptions")
    return render(request, "editorial/subscription_form.html", context(request, title="Limites gerais de arquivos", form=form, submit_label="Salvar limites", scope="policy"))


@editorial_access("settings.manage")
def enrollment_edit(request, user_id):
    owner = get_object_or_404(User, pk=user_id)
    protected_target(request, owner)
    if is_service_account(owner):
        raise PermissionDenied("Matrículas são destinadas a contas pessoais.")
    current = Enrollment.objects.select_related("plan").filter(owner=owner).first()
    initial = {name: getattr(current, name) for name in ("plan", "status", "valid_from", "valid_to")} if current else {"status": "active", "valid_from": timezone.now()}
    initial["expected_state"] = token(request, "enrollment", user_id, current)
    form = EnrollmentForm(request.POST or None, current=current, initial=initial)
    if request.method == "POST" and form.is_valid():
        save_enrollment(request, user_id, form.cleaned_data)
        messages.success(request, "Matrícula salva. A titularidade e os arquivos existentes foram preservados.")
        return redirect("editorial:enrollment", user_id=user_id)
    used = FileAsset.objects.filter(owner=owner).exclude(processing_status="deleted").aggregate(total=Sum("size_bytes"))["total"] or 0
    return render(request, "editorial/subscription_form.html", context(request, title="Administrar plano da pessoa", form=form, submit_label="Salvar matrícula", scope="enrollment", owner=owner, used_mib=round(used / MIB, 2), local_timezone=timezone.get_current_timezone_name()))
