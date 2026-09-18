from django import forms

from core.models import User
from core.rbac_policy import PRIVILEGED_ROLES, ROLES

ROLE_NAMES = {"superadministrador": "Superadministrador", "administrador": "Administrador", "administrador-de-conteudo": "Administrador de conteúdo", "editor": "Editor", "revisor-juridico": "Revisor jurídico", "professor": "Professor / autor", "suporte": "Suporte", "aluno": "Aluno", "conta-de-servico": "Conta de serviço", "gestor-de-usuarios": "Gestor de usuários", "curador": "Curador", "auditor": "Auditor"}


class JustificationForm(forms.Form):
    justification = forms.CharField(label="Motivo da alteração", min_length=8, max_length=1000, widget=forms.Textarea(attrs={"rows": 3}))


class CreateAccountForm(JustificationForm):
    username = forms.CharField(label="Nome de acesso", max_length=150, validators=User._meta.get_field("username").validators)
    display_name = forms.CharField(label="Nome da pessoa", max_length=180)
    email = forms.EmailField(label="E-mail para acesso", max_length=254)
    field_order = ["display_name", "username", "email", "justification"]

    def clean_email(self):
        value = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise forms.ValidationError("Este e-mail já está associado a uma conta.")
        return value

    def clean_username(self):
        value = self.cleaned_data["username"]
        if User.objects.filter(username=value).exists():
            raise forms.ValidationError("Este nome de acesso já está em uso.")
        return value


class AccountActionForm(JustificationForm):
    expected_version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    action = forms.ChoiceField(label="Ação", choices=[("revoke", "Revogar todas as sessões"), ("disable", "Suspender ou bloquear acesso"), ("enable", "Reativar acesso"), ("access", "Enviar instruções para definir senha")])
    field_order = ["action", "justification", "expected_version"]


class AccountProfileForm(JustificationForm):
    display_name = forms.CharField(label="Nome da pessoa", max_length=180)
    email = forms.EmailField(label="E-mail para acesso", max_length=254, required=False)
    expected_version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    field_order = ["display_name", "email", "justification", "expected_version"]


class AccountRolesForm(JustificationForm):
    roles = forms.MultipleChoiceField(label="Papéis de acesso", widget=forms.CheckboxSelectMultiple)
    expected_version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    field_order = ["roles", "justification", "expected_version"]

    def __init__(self, *args, superadmin=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["roles"].choices = [(slug, ROLE_NAMES[slug]) for slug in ROLES if superadmin or slug not in PRIVILEGED_ROLES]


class AccountFilterForm(forms.Form):
    q = forms.CharField(label="Buscar pessoa, nome de acesso ou e-mail", max_length=150, required=False)
    active = forms.ChoiceField(label="Acesso", required=False, choices=[("", "Todos"), ("yes", "Ativo"), ("no", "Suspenso ou bloqueado")])
    role = forms.ChoiceField(label="Papel", required=False, choices=[("", "Todos os papéis"), *ROLE_NAMES.items()])
