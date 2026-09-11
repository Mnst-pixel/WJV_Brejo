from urllib.parse import urlsplit

from django import forms

from core.editorial_forms import TopicChoice
from core.models import ExamPhase, Subject, Topic


class PhaseChoice(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.exam.title} · {obj.exam.edition} · {obj.exam.exam_date.year}"


class ExamForm(forms.Form):
    title = forms.CharField(label="Nome da prova ou caderno", max_length=255)
    organizer = forms.CharField(label="Organizadora ou autoria", max_length=120, initial="FGV")
    edition = forms.CharField(label="Edição ou identificação do caderno", max_length=80)
    exam_date = forms.DateField(label="Data da prova ou referência do caderno", widget=forms.DateInput(attrs={"type": "date"}))
    official_source_url = forms.URLField(label="Fonte da prova ou da autoria", max_length=1000)
    duration_minutes = forms.IntegerField(label="Duração em minutos", min_value=1, max_value=1440, initial=300)

    def clean_official_source_url(self):
        value = self.cleaned_data["official_source_url"]
        parsed = urlsplit(value)
        if parsed.scheme != "https" or parsed.username or parsed.password:
            raise forms.ValidationError("Informe uma fonte HTTPS sem credenciais.")
        return value


class QuestionForm(forms.Form):
    statement = forms.CharField(label="Enunciado", max_length=100_000, widget=forms.Textarea(attrs={"rows": 8}))
    explanation = forms.CharField(label="Explicação do gabarito", max_length=30_000, widget=forms.Textarea(attrs={"rows": 5}))
    difficulty = forms.ChoiceField(label="Dificuldade", choices=[("easy", "Fácil"), ("medium", "Intermediária"), ("hard", "Difícil")])
    origin = forms.ChoiceField(label="Origem", choices=[("official", "Oficial"), ("authored", "Autoral"), ("adapted", "Adaptada")])
    source_url = forms.URLField(label="Fonte consultada", max_length=1000)
    legal_basis = forms.CharField(label="Fundamento jurídico", required=False, max_length=20_000, widget=forms.Textarea(attrs={"rows": 3}))
    reference_date = forms.DateField(label="Data de referência jurídica", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    valid_from = forms.DateField(label="Vigente desde", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    valid_to = forms.DateField(label="Vigente até", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    subtopic_id = TopicChoice(label="Subtema", required=False, queryset=Topic.objects.filter(parent__isnull=False).select_related("subject"))
    correct_label = forms.ChoiceField(label="Alternativa correta", choices=[(letter, letter) for letter in "ABCDEFGH"])
    tags = forms.CharField(label="Etiquetas", max_length=800, required=False, help_text="Separe por vírgula. Até 20 etiquetas de 40 caracteres.")
    observations = forms.CharField(label="Observações editoriais", max_length=5000, required=False, widget=forms.Textarea(attrs={"rows": 3}))
    changes_summary = forms.CharField(label="Comentário desta versão", max_length=5000, required=False, widget=forms.Textarea(attrs={"rows": 3}))
    annulled = forms.BooleanField(label="Questão anulada", required=False)
    answer_changed = forms.BooleanField(label="Gabarito alterado em relação à versão anterior", required=False)

    def __init__(self, *args, create=False, **kwargs):
        super().__init__(*args, **kwargs)
        taxonomy = []
        if create:
            self.fields["exam_phase_id"] = PhaseChoice(label="Prova ou caderno", queryset=ExamPhase.objects.filter(phase=1).select_related("exam"))
            self.fields["subject_id"] = forms.ModelChoiceField(label="Disciplina", queryset=Subject.objects.all())
            self.fields["topic_id"] = TopicChoice(label="Tema", queryset=Topic.objects.filter(parent=None).select_related("subject"), required=False)
            taxonomy = ["exam_phase_id", "subject_id", "topic_id"]
        alternatives = []
        for letter in "ABCDEFGH":
            key = "alternative_" + letter
            self.fields[key] = forms.CharField(label=f"Alternativa {letter}", max_length=10_000, required=letter in "AB",
                widget=forms.Textarea(attrs={"rows": 2}), help_text="Deixe vazia se não for utilizada." if letter not in "AB" else "")
            alternatives.append(key)
        self.order_fields([*taxonomy, "statement", *alternatives, "correct_label", "explanation", "difficulty", "origin", "subtopic_id"])

    def payload(self):
        from core.question_workflow import QuestionRevisionInput
        values = {name: self.cleaned_data.get(name) for name in QuestionRevisionInput().fields if name != "alternatives"}
        values["subtopic_id"] = getattr(values["subtopic_id"], "pk", None)
        values["tags"] = [tag.strip() for tag in values["tags"].split(",") if tag.strip()]
        values["alternatives"] = [{"label": letter, "text": self.cleaned_data["alternative_" + letter]} for letter in "ABCDEFGH" if self.cleaned_data["alternative_" + letter]]
        return values

    def clean(self):
        from core.question_workflow import QuestionRevisionInput
        values = super().clean()
        if self.errors:
            return values
        validated = QuestionRevisionInput(data=self.payload())
        if not validated.is_valid():
            raise forms.ValidationError("Confira alternativas consecutivas, gabarito, fonte HTTPS, etiquetas e datas.")
        topic = values.get("topic_id")
        if topic and topic.subject_id != values["subject_id"].pk:
            self.add_error("topic_id", "O tema deve pertencer à disciplina escolhida.")
        return values
