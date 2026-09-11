import hashlib
import unicodedata
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.cache import cache
from django.core.mail import send_mail
from django.db import connection, transaction
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django.utils.decorators import method_decorator
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .audit import record_audit
from .mfa import begin_enrollment, clear_enrollment, decrypt_secret, enrollment_user, provisioning_uri, verify_totp
from .models import (
    Attempt,
    AuditLog,
    Bookmark,
    Content,
    Conversation,
    CoverageRecord,
    FileAsset,
    Flashcard,
    Goal,
    IngestionRun,
    LoginEvent,
    Question,
    Simulation,
    SourceDocumentVersion,
    StudyNote,
    StudySession,
    Subject,
    User,
    UserSession,
)
from .permissions import CanAudit, CanStudy, CanUpdateCorpus, HasKairosPermission, is_service_account, user_requires_mfa
from .serializers import (
    AttemptSerializer,
    AuditLogSerializer,
    BookmarkSerializer,
    ContentSerializer,
    ConversationSerializer,
    CoverageRecordSerializer,
    FileAssetSerializer,
    FlashcardSerializer,
    GoalSerializer,
    IngestionRunSerializer,
    QuestionSerializer,
    SimulationSerializer,
    SourceDocumentVersionSerializer,
    StudyNoteSerializer,
    StudySessionSerializer,
    SubjectSerializer,
    UserSerializer,
)
from .services.ai import answer_consultation
from .services.attempts import attempt_results, autosave_attempt, submit_attempt
from .services.documents import transition_document_version
from .tasks import run_ingestion


def _client_ip(request):
    from .client_address import client_address
    return client_address(request)


@api_view(["GET"])
@permission_classes([AllowAny])
def health_live(request):
    return Response({"status": "ok", "service": "kairos-api"})


@api_view(["GET"])
@permission_classes([AllowAny])
def health_ready(request):
    checks = {}
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            checks["postgres"] = cursor.fetchone()[0] == 1
    except Exception:
        checks["postgres"] = False
    try:
        cache.set("kairos-ready", "1", 5)
        checks["redis"] = cache.get("kairos-ready") == "1"
    except Exception:
        checks["redis"] = False
    return Response({"status": "ok" if all(checks.values()) else "degraded", "checks": checks}, status=200 if all(checks.values()) else 503)


@ensure_csrf_cookie
@api_view(["GET"])
@permission_classes([AllowAny])
def csrf_token(request):
    return Response({"csrfToken": get_token(request)})


def _login_event(request, username, outcome, user=None):
    LoginEvent.objects.create(
        user=user,
        username_attempted=username[:150],
        outcome=outcome,
        ip_address=_client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:512],
    )


def _resolve_login_identifier(value: str):
    raw = value.strip()
    canonical = raw.casefold()
    candidate = User.objects.filter(username__iexact=canonical).first()
    if not candidate and "@" in canonical:
        candidate = User.objects.filter(email__iexact=canonical).first()
    if not candidate:
        folded = "".join(
            character
            for character in unicodedata.normalize("NFKD", canonical)
            if not unicodedata.combining(character)
        )
        candidate = User.objects.filter(username__iexact=folded).first()
    return candidate, candidate.username if candidate else canonical


def _establish_session(request, user, *, mfa_verified=False):
    login(request, user)
    request.session["user_session_version"] = user.session_version
    request.session["mfa_verified"] = mfa_verified
    request.session.save()
    key_hash = hashlib.sha256(request.session.session_key.encode()).hexdigest()
    UserSession.objects.update_or_create(
        session_key_hash=key_hash,
        defaults={
            "user": user,
            "ip_address": _client_ip(request),
            "user_agent": request.META.get("HTTP_USER_AGENT", "")[:512],
            "expires_at": timezone.now() + timedelta(seconds=settings.SESSION_COOKIE_AGE),
        },
    )


@method_decorator(csrf_protect, name="dispatch")
class SessionLoginView(APIView):
    permission_classes = [AllowAny]

    @transaction.atomic
    def post(self, request):
        candidate, username = _resolve_login_identifier(str(request.data.get("username", "")))
        password = str(request.data.get("password", ""))
        code = str(request.data.get("totp", ""))
        throttle_key = f"login:{hashlib.sha256(f'{_client_ip(request)}:{username}'.encode()).hexdigest()}"
        failures = cache.get(throttle_key, 0)
        if failures >= 12:
            _login_event(request, username, LoginEvent.Outcome.LOCKED)
            return Response({"detail": "Muitas tentativas. Tente novamente mais tarde."}, status=429)

        if candidate and candidate.locked_until and candidate.locked_until > timezone.now():
            cache.set(throttle_key, failures + 1, 3600)
            _login_event(request, username, LoginEvent.Outcome.LOCKED, candidate)
            return Response({"detail": "Credenciais inválidas ou acesso temporariamente bloqueado."}, status=401)

        user = authenticate(request, username=username, password=password)
        if not user:
            cache.set(throttle_key, failures + 1, 900)
            if candidate:
                candidate.failed_login_count += 1
                if candidate.failed_login_count >= 5:
                    seconds = min(3600, 60 * (2 ** min(candidate.failed_login_count - 5, 6)))
                    candidate.locked_until = timezone.now() + timedelta(seconds=seconds)
                candidate.save(update_fields=["failed_login_count", "locked_until", "updated_at"])
            _login_event(request, username, LoginEvent.Outcome.FAILED, candidate)
            return Response({"detail": "Credenciais inválidas ou acesso temporariamente bloqueado."}, status=401)

        password_proof = user.get_session_auth_hash()
        user = User.objects.select_for_update().filter(pk=user.pk, is_active=True).first()
        if user is None or not constant_time_compare(password_proof, user.get_session_auth_hash()):
            return Response({"detail": "Credenciais inválidas ou acesso temporariamente bloqueado."}, status=401)

        if is_service_account(user):
            return Response({"detail": "Credenciais inválidas ou acesso temporariamente bloqueado."}, status=401)
        if user_requires_mfa(user) and not user.mfa_enabled:
            begin_enrollment(request, user)
            return Response({"detail": "Configuração MFA obrigatória.", "mfa_setup_required": True}, status=428)
        if user_requires_mfa(user) and not verify_totp(user, code):
            _login_event(request, username, LoginEvent.Outcome.MFA_FAILED, user)
            return Response({"detail": "Código MFA obrigatório ou inválido.", "mfa_required": True}, status=428)

        user.failed_login_count = 0
        user.locked_until = None
        user.save(update_fields=["failed_login_count", "locked_until", "updated_at"])
        cache.delete(throttle_key)
        _establish_session(request, user, mfa_verified=user_requires_mfa(user))
        _login_event(request, username, LoginEvent.Outcome.SUCCESS, user)
        record_audit("auth.login", actor=user, request=request, target=user)
        return Response(UserSerializer(user).data)


@method_decorator(csrf_protect, name="dispatch")
class MFASetupView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        user, pending = enrollment_user(request)
        secret = decrypt_secret(pending["secret"])
        return Response({"secret": secret, "provisioning_uri": provisioning_uri(user, secret)})


@method_decorator(csrf_protect, name="dispatch")
class MFAVerifyView(APIView):
    permission_classes = [AllowAny]

    @transaction.atomic
    def post(self, request):
        user, pending = enrollment_user(request, lock=True)
        if not verify_totp(user, str(request.data.get("totp", "")), encrypted_secret=pending["secret"]):
            _login_event(request, user.username, LoginEvent.Outcome.MFA_FAILED, user)
            return Response({"detail": "Código MFA inválido."}, status=400)
        user.mfa_enabled = True
        user.mfa_secret_encrypted = pending["secret"]
        user.session_version += 1
        user.save(update_fields=["mfa_enabled", "mfa_secret_encrypted", "session_version", "updated_at"])
        clear_enrollment(request)
        _establish_session(request, user, mfa_verified=True)
        record_audit("auth.mfa.enabled", actor=user, request=request, target=user)
        return Response(UserSerializer(user).data)


class SessionLogoutView(APIView):
    def post(self, request):
        if request.session.session_key:
            key_hash = hashlib.sha256(request.session.session_key.encode()).hexdigest()
            UserSession.objects.filter(session_key_hash=key_hash).update(revoked_at=timezone.now())
        logout(request)
        return Response(status=204)


class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = str(request.data.get("email", "")).strip().lower()
        from core.recovery_policy import allow_recovery_delivery
        response = {"detail": "Se a conta existir e o e-mail estiver configurado, as instruções serão enviadas."}
        if not email or len(email) > 254 or not allow_recovery_delivery(request, email):
            return Response(response, status=202)
        user = User.objects.filter(email__iexact=email, is_active=True).first()
        if user and settings.SMTP_URL:
            from smtplib import SMTPException
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            link = f"{settings.KAIROS_BASE_URL}/app/redefinir-senha?uid={uid}&token={token}"
            try:
                sent = send_mail("Redefinição de senha do Kairós", f"Use este link uma única vez: {link}", settings.DEFAULT_FROM_EMAIL, [user.email])
            except (OSError, SMTPException):
                sent = 0
            record_audit("auth.password_reset.requested" if sent else "auth.password_reset.delivery_failed", request=request, target=user)
        return Response(response, status=202)


class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]

    @transaction.atomic
    def post(self, request):
        from django.core.exceptions import ValidationError as PasswordValidationError
        try:
            user = User.objects.select_for_update().get(pk=force_str(urlsafe_base64_decode(request.data.get("uid", ""))), is_active=True)
        except (User.DoesNotExist, ValueError, TypeError, OverflowError, UnicodeError, PasswordValidationError):
            return Response({"detail": "Token inválido."}, status=400)
        token = str(request.data.get("token", ""))
        password = str(request.data.get("new_password", ""))
        if not default_token_generator.check_token(user, token):
            return Response({"detail": "Token inválido ou expirado."}, status=400)
        try:
            validate_password(password, user=user)
        except PasswordValidationError as exc:
            raise ValidationError({"new_password": exc.messages}) from None
        user.set_password(password)
        user.session_version += 1
        user.save(update_fields=["password", "session_version", "updated_at"])
        UserSession.objects.filter(user=user, revoked_at__isnull=True).update(revoked_at=timezone.now())
        record_audit("auth.password_reset.completed", actor=user, request=request, target=user)
        return Response(status=204)


class MeView(APIView):
    def get(self, request):
        return Response(UserSerializer(request.user).data)

    @transaction.atomic
    def patch(self, request):
        user = User.objects.select_for_update().get(pk=request.user.pk)
        if not user.is_active or user.session_version != request.session.get("user_session_version"):
            raise PermissionDenied("A sessão foi revogada. Entre novamente.")
        serializer = UserSerializer(user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        record_audit("user.profile.updated", actor=user, request=request, target=user)
        return Response(serializer.data)


class OwnedViewSet(viewsets.ModelViewSet):
    permission_classes = [CanStudy]

    def get_queryset(self):
        return self.queryset.filter(owner=self.request.user).order_by("-created_at", "id")

    @transaction.atomic
    def perform_create(self, serializer):
        from .permissions import lock_study_user
        lock_study_user(self.request.user)
        serializer.save(owner=self.request.user)

    @transaction.atomic
    def perform_update(self, serializer):
        from django.shortcuts import get_object_or_404
        from .permissions import lock_study_user
        lock_study_user(self.request.user)
        serializer.instance = get_object_or_404(self.get_queryset().select_for_update(), pk=serializer.instance.pk)
        serializer.save()

    @transaction.atomic
    def perform_destroy(self, instance):
        from django.shortcuts import get_object_or_404
        from .permissions import lock_study_user
        lock_study_user(self.request.user)
        instance = get_object_or_404(self.get_queryset().select_for_update(), pk=instance.pk)
        record_audit(f"{instance._meta.label_lower}.deleted", actor=self.request.user, request=self.request, target=instance)
        instance.delete()


class GoalViewSet(OwnedViewSet):
    queryset = Goal.objects.all()
    serializer_class = GoalSerializer


class StudyNoteViewSet(OwnedViewSet):
    queryset = StudyNote.objects.all()
    serializer_class = StudyNoteSerializer


class FlashcardViewSet(OwnedViewSet):
    queryset = Flashcard.objects.all()
    serializer_class = FlashcardSerializer


class BookmarkViewSet(OwnedViewSet):
    queryset = Bookmark.objects.all()
    serializer_class = BookmarkSerializer


class StudySessionViewSet(OwnedViewSet):
    queryset = StudySession.objects.all()
    serializer_class = StudySessionSerializer


class SubjectViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [CanStudy]
    queryset = Subject.objects.prefetch_related("topics").all()
    serializer_class = SubjectSerializer


class ContentViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [CanStudy]
    queryset = Content.objects.none()
    serializer_class = ContentSerializer

    def get_queryset(self):
        from .content_workflow import published_content
        query = published_content().select_related("current_version__workflow__approval").prefetch_related("topics").order_by("subject__order", "current_version__title", "pk")
        for field in ("subject", "topics"):
            if self.request.query_params.get(field):
                query = query.filter(**{field: serializers.UUIDField().run_validation(self.request.query_params[field])})
        if self.request.query_params.get("q"):
            query = query.filter(current_version__title__icontains=self.request.query_params["q"][:200])
        return query.distinct()


class QuestionViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [CanStudy]
    queryset = Question.objects.none()
    serializer_class = QuestionSerializer

    def get_queryset(self):
        from .question_workflow import package_queryset, published_questions
        from .practice_views import filter_questions
        query = package_queryset(published_questions()).order_by("exam_phase", "number", "pk")
        return filter_questions(query, self.request.query_params, self.request.user)


class SimulationViewSet(OwnedViewSet):
    queryset = Simulation.objects.all()
    serializer_class = SimulationSerializer


class AttemptViewSet(viewsets.ModelViewSet):
    permission_classes = [CanStudy]
    serializer_class = AttemptSerializer
    # Mutations go through locked commands; generic updates can save stale
    # model fields and reopen a submitted attempt. Historical attempts persist.
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        query = Attempt.objects.filter(owner=self.request.user).select_related("simulation").prefetch_related("answers").order_by("-started_at", "pk")
        if self.request.query_params.get("purpose") == "simulation":
            query = query.exclude(idempotency_key__startswith="practice:")
        return query

    def perform_create(self, serializer):
        simulation = serializer.validated_data["simulation"]
        if simulation.owner_id != self.request.user.id:
            raise PermissionDenied("Simulado de outro usuário.")
        serializer.save(owner=self.request.user)

    @action(detail=True, methods=["post"])
    def autosave(self, request, pk=None):
        attempt = autosave_attempt(
            attempt_id=pk,
            owner=request.user,
            expected_version=request.data.get("version"),
            answers=request.data.get("answers"),
            elapsed_seconds=request.data.get("elapsed_seconds"),
        )
        return Response(AttemptSerializer(attempt).data)

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        attempt = submit_attempt(attempt_id=pk, owner=request.user)
        record_audit("attempt.submitted", actor=request.user, request=request, target=attempt)
        return Response(AttemptSerializer(attempt).data)

    @action(detail=True, methods=["get"])
    def results(self, request, pk=None):
        return Response(attempt_results(attempt_id=pk, owner=request.user))


class FileAssetViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    permission_classes = [CanStudy]
    serializer_class = FileAssetSerializer
    parser_classes = [MultiPartParser, FormParser]

    def get_throttles(self):
        from .upload_throttling import PrivateFileThrottle
        return [PrivateFileThrottle()]

    def get_queryset(self):
        return FileAsset.objects.filter(owner=self.request.user).exclude(processing_status__in=["deleted", "delete_pending"]).order_by("-created_at", "id")

    @action(detail=False, methods=["post"])
    def upload(self, request):
        from .services.uploads import create_upload
        asset = create_upload(owner=request.user, upload=request.FILES.get("file"), request=request)
        return Response(FileAssetSerializer(asset).data, status=202)

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        from .services.uploads import download_upload
        return Response(download_upload(owner=request.user, asset_id=self.get_object().id))

    @action(detail=True, methods=["get"])
    def content(self, request, pk=None):
        from .services.uploads import open_download
        return open_download(owner=request.user, asset_id=self.get_object().id)

    def perform_destroy(self, instance):
        from .services.uploads import delete_upload
        delete_upload(owner=self.request.user, asset_id=instance.id, request=self.request)


class ConversationViewSet(OwnedViewSet):
    queryset = Conversation.objects.all()
    serializer_class = ConversationSerializer


class ConsultView(APIView):
    permission_classes = [IsAuthenticated, HasKairosPermission]
    permission_codename = "ai.consult"

    def post(self, request):
        context = request.data.get("context", {})
        if not isinstance(context, dict):
            raise ValidationError({"context": "Contexto deve ser um objeto."})
        # The shared policy validates context, ownership and formal mode before retrieval.
        conversation = None
        if request.data.get("conversation_id"):
            conversation_id = serializers.UUIDField().run_validation(request.data["conversation_id"])
            conversation = get_object_or_404(Conversation, pk=conversation_id, owner=request.user)
        result = answer_consultation(
            user=request.user,
            question=str(request.data.get("question", "")),
            action=str(request.data.get("action", "consult")),
            context=context,
            conversation=conversation,
            request=request,
        )
        return Response(result)


class IngestionRunViewSet(viewsets.ModelViewSet):
    permission_classes = [CanUpdateCorpus]
    queryset = IngestionRun.objects.select_related("requested_by").all()
    serializer_class = IngestionRunSerializer
    http_method_names = ["get", "post", "head", "options"]

    def perform_create(self, serializer):
        run = serializer.save(requested_by=self.request.user)
        record_audit("corpus.ingestion.created", actor=self.request.user, request=self.request, target=run)

    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        run = self.get_object()
        if run.status != "queued":
            raise ValidationError("A execução não está na fila.")
        run_ingestion.delay(str(run.id))
        return Response({"status": "queued"}, status=202)


class SourceDocumentVersionViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [HasKairosPermission]
    permission_codename = "corpus.read"
    queryset = SourceDocumentVersion.objects.select_related("document", "approved_by").all()
    serializer_class = SourceDocumentVersionSerializer

    @action(detail=True, methods=["post"])
    def transition(self, request, pk=None):
        version = transition_document_version(
            version_id=pk,
            actor=request.user,
            next_state=str(request.data.get("state", "")),
            justification=str(request.data.get("justification", "")),
            request=request,
        )
        return Response(self.get_serializer(version).data)


class CoverageRecordViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    queryset = CoverageRecord.objects.select_related("source_registry").all()
    serializer_class = CoverageRecordSerializer


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [CanAudit]
    queryset = AuditLog.objects.select_related("actor").all()
    serializer_class = AuditLogSerializer
