from decimal import Decimal

from django import forms
from django.forms import BaseFormSet, formset_factory

from core.models import ExamPhase
from core.question_forms import PhaseChoice
from core.second_phase_models import SecondPhaseArea
from core.second_phase_workflow import CASE_FIELDS


LIST_FIELDS = ("facts", "distractors", "preliminary_matters", "merits", "requests")


class AreaForm(forms.Form):
    name = forms.CharField(label="Nome da área", max_length=120)
    description = forms.CharField(label="Descrição", required=False, widget=forms.Textarea(attrs={"rows": 3}), max_length=5000)


class CaseTransitionForm(forms.Form):
    target_state = forms.ChoiceField(label="Decisão")
    expected_state = forms.CharField(widget=forms.HiddenInput)
    justification = forms.CharField(label="Comentário da decisão", min_length=8, max_length=2000, widget=forms.Textarea(attrs={"rows": 3}))
    legal_status = forms.ChoiceField(label="Situação jurídica conferida (ao aprovar)", required=False, choices=[("", "Selecione ao aprovar"), ("current", "Vigente"), ("historical", "Histórica")])


class CaseForm(forms.Form):
    area_id = forms.ModelChoiceField(label="Área da segunda fase", queryset=SecondPhaseArea.objects.order_by("name"))
    title = forms.CharField(label="Título do caso", max_length=255)
    piece_name = forms.CharField(label="Peça cabível — somente no espelho", max_length=200)
    prompt = forms.CharField(label="Enunciado apresentado ao aluno", max_length=100_000, widget=forms.Textarea(attrs={"rows": 10}))
    duration_minutes = forms.IntegerField(label="Duração em minutos", min_value=1, max_value=1440, initial=300)
    total_points = forms.DecimalField(label="Pontuação total do espelho", max_digits=6, decimal_places=2, min_value=Decimal("0.01"), max_value=100, initial=10)
    source_url = forms.URLField(label="Fonte consultada", max_length=1000)
    provenance = forms.ChoiceField(label="Origem do material", choices=[("human_authored", "Autoral"), ("official", "Oficial"), ("legacy_unverified", "Legado não verificado")])
    reference_date = forms.DateField(label="Data de referência jurídica", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    valid_from = forms.DateField(label="Vigente desde", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    valid_to = forms.DateField(label="Vigente até", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    temporal_marker = forms.CharField(label="Marco temporal", max_length=255, required=False)
    jurisdiction = forms.CharField(label="Competência", max_length=255, required=False)
    addressee = forms.CharField(label="Endereçamento", max_length=255, required=False)
    standing = forms.CharField(label="Legitimidade", max_length=10_000, required=False, widget=forms.Textarea(attrs={"rows": 2}))
    deadline = forms.CharField(label="Prazo aplicável", max_length=255, required=False)
    changes_summary = forms.CharField(label="Comentário desta versão", max_length=5000, required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, create=False, **kwargs):
        super().__init__(*args, **kwargs)
        if create:
            self.fields["exam_phase_id"] = PhaseChoice(label="Prova ou caderno", queryset=ExamPhase.objects.filter(phase=2).select_related("exam"))
            self.order_fields(["exam_phase_id", "area_id", "title"])
        for key, label in [("facts", "Fatos relevantes"), ("distractors", "Distratores"), ("preliminary_matters", "Preliminares e prejudiciais"), ("merits", "Teses e fundamentos"), ("requests", "Pedidos")]:
            self.fields[key] = forms.CharField(label=label, required=False, max_length=150_000, help_text="Um item por linha; estes campos integram o espelho reservado.", widget=forms.Textarea(attrs={"rows": 3}))

    def payload(self):
        values = {name: self.cleaned_data[name] for name in (*CASE_FIELDS, "area_id", "title", "piece_name", "duration_minutes", "total_points", "provenance")}
        values["area_id"] = values["area_id"].pk
        for name in LIST_FIELDS:
            values[name] = [line.strip() for line in values[name].splitlines() if line.strip()]
        return values


class DiscursiveForm(forms.Form):
    code = forms.ChoiceField(label="Questão", choices=[(f"Q{i}", f"Questão {i}") for i in range(1, 11)])
    prompt = forms.CharField(label="Enunciado", max_length=30_000, widget=forms.Textarea(attrs={"rows": 4}))
    expected_answer = forms.CharField(label="Padrão de resposta reservado", max_length=30_000, widget=forms.Textarea(attrs={"rows": 4}))


class CriterionForm(forms.Form):
    code = forms.RegexField(r"^[A-Za-z0-9_-]{1,32}$", label="Referência curta do critério", help_text="Exemplo: P1, P2, D1. Não repita referências.")
    group = forms.CharField(label="Grupo do espelho", max_length=120)
    target_code = forms.ChoiceField(label="Resposta avaliada", choices=[("piece", "Peça profissional"), *((f"Q{i}", f"Questão discursiva {i}") for i in range(1, 11))])
    title = forms.CharField(label="Nome do critério", max_length=255)
    description = forms.CharField(label="O que deve ser avaliado", max_length=10_000, widget=forms.Textarea(attrs={"rows": 3}))
    max_points = forms.DecimalField(label="Pontos máximos", max_digits=6, decimal_places=2, min_value=Decimal("0.01"), max_value=100)
    legal_basis = forms.CharField(label="Fundamento jurídico", required=False, max_length=10_000, widget=forms.Textarea(attrs={"rows": 2}))
    acceptable_answers = forms.CharField(label="Respostas equivalentes", required=False, max_length=50_000, help_text="Uma formulação por linha.", widget=forms.Textarea(attrs={"rows": 3}))
    dependencies = forms.MultipleChoiceField(label="Depende de critérios anteriores", required=False)
    required = forms.BooleanField(label="Critério obrigatório", required=False)
    severe_error = forms.BooleanField(label="Erro impeditivo quando aplicável", required=False)

    def __init__(self, *args, dependency_choices=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["dependencies"].choices = dependency_choices


class EditorialFormSet(BaseFormSet):
    def add_fields(self, form, index):
        super().add_fields(form, index)
        form.fields["ORDER"].label = "Posição"
        form.fields["DELETE"].label = "Remover deste rascunho"


DiscursiveFormSet = formset_factory(DiscursiveForm, formset=EditorialFormSet, extra=0, can_delete=True, can_order=True, max_num=10, validate_max=True, absolute_max=20)
CriterionFormSet = formset_factory(CriterionForm, formset=EditorialFormSet, extra=0, can_delete=True, can_order=True, max_num=100, validate_max=True, absolute_max=110)


def formset_payload(formset, *, criteria=False):
    result = []
    for form in formset.ordered_forms:
        row = {key: value for key, value in form.cleaned_data.items() if key not in {"ORDER", "DELETE"}}
        if criteria:
            row["acceptable_answers"] = [line.strip() for line in row["acceptable_answers"].splitlines() if line.strip()]
        result.append(row)
    return result
