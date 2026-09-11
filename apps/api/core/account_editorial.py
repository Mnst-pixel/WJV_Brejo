from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from core.account_commands import change_account, create_account, protected_target, request_account_access
from core.account_forms import AccountActionForm, AccountFilterForm, AccountProfileForm, AccountRolesForm, CreateAccountForm, ROLE_NAMES
from core.editorial_views import context, editorial_access
from core.models import AuditLog, User, UserSession
from core.permissions import active_role_slugs, request_has_permission
from core.rbac_views import assign_user_roles


def can_manage(request, target):
    if not request_has_permission(request, "users.manage"):
        return False
    try:
        protected_target(request, target)
        return True
    except PermissionDenied:
        return False


@editorial_access("users.read")
def account_list(request):
    form = AccountFilterForm(request.GET)
    query = User.objects.prefetch_related("role_assignments__role").order_by("display_name", "username", "pk")
    if form.is_valid():
        value = form.cleaned_data
        if value["q"]:
            query = query.filter(Q(display_name__icontains=value["q"]) | Q(username__icontains=value["q"]) | Q(email__icontains=value["q"]))
        if value["active"]:
            query = query.filter(is_active=value["active"] == "yes")
        if value["role"]:
            condition = Q(role_assignments__role__slug=value["role"])
            if value["role"] == "superadministrador":
                condition |= Q(is_superuser=True)
            query = query.filter(condition).distinct()
    else:
        query = query.none()
    params = request.GET.copy()
    params.pop("page", None)
    page = Paginator(query, 25).get_page(request.GET.get("page"))
    for user in page:
        user.role_labels = [ROLE_NAMES.get(grant.role.slug, "Papel de compatibilidade") for grant in user.role_assignments.all()]
        if user.is_superuser and "Superadministrador" not in user.role_labels:
            user.role_labels.append("Superadministrador")
    return render(request, "editorial/accounts.html", context(request, title="Usuários", page=page, form=form, filters=params.urlencode(), can_manage_users=request_has_permission(request, "users.manage")))


@editorial_access("users.manage")
def account_create(request):
    form = CreateAccountForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = create_account(request, **form.cleaned_data)
        messages.success(request, "Conta criada como aluno. Use Enviar instruções para que a própria pessoa defina sua senha.")
        return redirect("editorial:account", user_id=user.pk)
    return render(request, "editorial/account_form.html", context(request, title="Criar usuário", form=form, submit_label="Criar conta", smtp_configured=bool(settings.SMTP_URL)))


@editorial_access("users.read")
def account_detail(request, user_id):
    target = get_object_or_404(User.objects.prefetch_related("role_assignments__role"), pk=user_id)
    manage = can_manage(request, target)
    form = AccountActionForm(request.POST or None, initial={"expected_version": target.session_version}) if manage else None
    if request.method == "POST":
        if not form:
            raise PermissionDenied("Seu papel não permite alterar esta conta.")
        if form.is_valid():
            data = dict(form.cleaned_data)
            if data.pop("action") == "access":
                state = request_account_access(request, user_id=user_id, **data)
                text = {"sent": "Instruções enviadas ao e-mail cadastrado.", "failed": "O envio falhou. Confira a configuração de e-mail; a conta permanece preservada.", "unconfigured": "Envio indisponível: o serviço de e-mail ainda não foi configurado.", "throttled": "Aguarde antes de repetir o envio. Há um limite por destinatário e conexão; indisponibilidade temporária também preserva esse limite."}[state]
                messages.info(request, text)
            else:
                change_account(request, user_id=user_id, **form.cleaned_data)
                messages.success(request, "Alteração registrada. As sessões anteriores foram revogadas.")
            return redirect("editorial:account", user_id=user_id)
    events = AuditLog.objects.filter(target_type="core.user", target_id=str(target.pk)).select_related("actor")[:20] if request_has_permission(request, "audit.read") else []
    roles = [{"name": ROLE_NAMES.get(grant.role.slug, "Papel de compatibilidade"), "expires_at": grant.expires_at} for grant in target.role_assignments.all()]
    if target.is_superuser and not any(role["name"] == "Superadministrador" for role in roles):
        roles.append({"name": "Superadministrador", "expires_at": None})
    sessions = UserSession.objects.filter(user=target, revoked_at__isnull=True, expires_at__gt=timezone.now()).count()
    return render(request, "editorial/account.html", context(request, title=str(target), target=target, form=form, role_rows=roles, events=events, session_count=sessions,
        can_manage_account=manage, can_manage_roles=manage and request_has_permission(request, "roles.manage"), smtp_configured=bool(settings.SMTP_URL)))


@editorial_access("users.manage")
def account_edit(request, user_id):
    target = get_object_or_404(User, pk=user_id)
    protected_target(request, target)
    form = AccountProfileForm(request.POST or None, initial={"display_name": target.display_name, "email": target.email, "expected_version": target.session_version})
    if request.method == "POST" and form.is_valid():
        change_account(request, user_id=user_id, action="profile", **form.cleaned_data)
        messages.success(request, "Cadastro atualizado e sessões anteriores revogadas.")
        return redirect("editorial:account", user_id=user_id)
    return render(request, "editorial/account_form.html", context(request, title="Editar cadastro", form=form, submit_label="Salvar cadastro", target=target))


@editorial_access("roles.manage")
def account_roles(request, user_id):
    target = get_object_or_404(User, pk=user_id)
    protected_target(request, target)
    superadmin = request.user.is_superuser or "superadministrador" in active_role_slugs(request.user)
    initial_roles = set(target.role_assignments.values_list("role__slug", flat=True)) | ({"superadministrador"} if target.is_superuser else set())
    form = AccountRolesForm(request.POST or None, superadmin=superadmin, initial={"roles": list(initial_roles), "expected_version": target.session_version})
    if request.method == "POST" and form.is_valid():
        assign_user_roles(request, user_id, form.cleaned_data)
        messages.success(request, "Papéis registrados. A pessoa deverá entrar novamente; papéis administrativos exigem MFA.")
        return redirect("editorial:account", user_id=user_id)
    return render(request, "editorial/account_form.html", context(request, title="Administrar papéis", form=form, submit_label="Salvar papéis", target=target, replacing_superuser=target.is_superuser))
