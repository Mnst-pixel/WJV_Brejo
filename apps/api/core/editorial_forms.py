"""Human editorial input. Technical identifiers and provenance stay server-side."""
from django import forms

from core.models import Content, ContentVersion, Subject, Topic


class SubjectForm(forms.Form):
    name = forms.CharField(label="Nome da disciplina", max_length=160)
    description = forms.CharField(label="Descrição", required=False, widget=forms.Textarea(attrs={"rows": 3}), max_length=5000)


class TopicChoice(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.subject.name} / {obj.name}"


class TopicForm(forms.Form):
    subject = forms.ModelChoiceField(label="Disciplina", queryset=Subject.objects.all())
    parent = TopicChoice(label="Tema principal", queryset=Topic.objects.filter(parent=None).select_related("subject"), required=False,
                        help_text="Deixe vazio para criar um tema; selecione um tema para criar um subtema.")
    name = forms.CharField(label="Nome", max_length=200)
    description = forms.CharField(label="Descrição", max_length=5000, required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def clean(self):
        data = super().clean()
        if data.get("parent") and data["parent"].subject_id != getattr(data.get("subject"), "pk", None):
            self.add_error("parent", "O tema deve pertencer à disciplina selecionada.")
        return data


class RevisionForm(forms.Form):
    title = forms.CharField(label="Título", max_length=300)
    body = forms.CharField(label="Texto", max_length=100_000, widget=forms.Textarea(attrs={"rows": 18}),
                           help_text="Escreva em texto simples. A prévia preserva os parágrafos; código HTML não será executado.")
    source_url = forms.URLField(label="Link da fonte consultada", max_length=1000,
                               help_text="Informe uma referência HTTPS. O revisor verificará a fonte antes da publicação.")
    reference_date = forms.DateField(label="Data de referência", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    valid_from = forms.DateField(label="Vigente desde", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    valid_to = forms.DateField(label="Vigente até", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    changes_summary = forms.CharField(label="O que foi alterado?", max_length=5000, required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def clean_source_url(self):
        from urllib.parse import urlsplit
        value = self.cleaned_data["source_url"]
        parsed = urlsplit(value)
        if parsed.scheme != "https" or parsed.username or parsed.password:
            raise forms.ValidationError("Use um link HTTPS sem credenciais.")
        return value

    def clean(self):
        data = super().clean()
        if data.get("valid_from") and data.get("valid_to") and data["valid_to"] < data["valid_from"]:
            self.add_error("valid_to", "A data final deve ser igual ou posterior à data inicial.")
        return data


class ContentForm(RevisionForm):
    subject = forms.ModelChoiceField(label="Disciplina", queryset=Subject.objects.all())
    kind = forms.ChoiceField(label="Formato", choices=[("lesson", "Aula"), ("summary", "Resumo"), ("article", "Artigo"), ("material", "Material de apoio")])
    field_order = ["subject", "kind", "title", "body", "source_url", "reference_date", "valid_from", "valid_to", "changes_summary"]


class TransitionForm(forms.Form):
    state = forms.CharField(widget=forms.HiddenInput)
    justification = forms.CharField(label="Comentário da decisão", min_length=8, max_length=2000, widget=forms.Textarea(attrs={"rows": 3}))
    legal_status = forms.ChoiceField(label="Situação jurídica verificada", choices=ContentVersion.LegalStatus.choices[1:], required=False)

    def __init__(self, *args, state, **kwargs):
        super().__init__(*args, **kwargs)
        self.expected_state = state
        self.fields["state"].initial = state
        if state != "approved":
            del self.fields["legal_status"]
        else:
            self.fields["legal_status"].required = True

    def clean_state(self):
        value = self.cleaned_data["state"]
        if value != self.expected_state:
            raise forms.ValidationError("A situação mudou. Atualize a página antes de decidir novamente.")
        return value


class FilterForm(forms.Form):
    q = forms.CharField(label="Buscar título", max_length=200, required=False)
    subject = forms.ModelChoiceField(label="Disciplina", queryset=Subject.objects.all(), required=False, empty_label="Todas as disciplinas")
    state = forms.ChoiceField(label="Situação", required=False, choices=[("", "Todas as situações"), *Content.Status.choices])


class LegacyForm(forms.Form):
    dataset = forms.ChoiceField(label="Acervo do protótipo", choices=[("questions", "Questões antigas"), ("oab", "Resumos OAB antigos")])
    subject_id = forms.ModelChoiceField(label="Disciplina de destino", queryset=Subject.objects.all())
