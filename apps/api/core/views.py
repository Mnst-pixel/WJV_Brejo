import hashlib
import unicodedata
import uuid
from datetime import timedelta
from pathlib import Path

import pyotp
from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.cache import cache
from django.core.files.storage import default_storage
from django.core.mail import send_mail
from django.db import connection
from django.middleware.csrf import get_token
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import mixins, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .audit import record_audit
from .mfa import decrypt_secret, encrypt_secret, provisioning_uri, verify_totp
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
from .permissions import CanAudit, CanStudy, CanUpdateCorpus, HasKairosPermission
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
from .tasks import run_ingestion, scan_and_process_file


def _client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return (forwarded.split(",", 1)[0].strip() or request.META.get("REMOTE_ADDR")) if forwarded else request.META.get("REMOTE_ADDR")


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


class SessionLoginView(APIView):
    permission_classes = [AllowAny]

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

        if user.is_staff and not user.mfa_enabled:
            request.session["pre_mfa_user_id"] = str(user.id)
            request.session["pre_mfa_password_at"] = timezone.now().isoformat()
            return Response({"detail": "Configuração MFA obrigatória.", "mfa_setup_required": True}, status=428)
        if user.is_staff and not verify_totp(user, code):
            _login_event(request, username, LoginEvent.Outcome.MFA_FAILED, user)
            return Response({"detail": "Código MFA obrigatório ou inválido.", "mfa_required": True}, status=428)

        user.failed_login_count = 0
        user.locked_until = None
        user.save(update_fields=["failed_login_count", "locked_until", "updated_at"])
        cache.delete(throttle_key)
        _establish_session(request, user, mfa_verified=user.is_staff)
        _login_event(request, username, LoginEvent.Outcome.SUCCESS, user)
        record_audit("auth.login", actor=user, request=request, target=user)
        return Response(UserSerializer(user).data)


class MFASetupView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        user_id = request.session.get("pre_mfa_user_id")
        if not user_id:
            raise PermissionDenied("Autenticação de senha necessária.")
        user = User.objects.get(pk=user_id, is_staff=True, is_active=True)
        if user.mfa_secret_encrypted:
            secret = decrypt_secret(user.mfa_secret_encrypted)
        else:
            secret = pyotp.random_base32()
            user.mfa_secret_encrypted = encrypt_secret(secret)
            user.save(update_fields=["mfa_secret_encrypted", "updated_at"])
        return Response({"secret": secret, "provisioning_uri": provisioning_uri(user, secret)})


class MFAVerifyView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        user_id = request.session.get("pre_mfa_user_id")
        if not user_id:
            raise PermissionDenied("Autenticação de senha necessária.")
        user = User.objects.get(pk=user_id, is_staff=True, is_active=True)
        if not verify_totp(user, str(request.data.get("totp", ""))):
            _login_event(request, user.username, LoginEvent.Outcome.MFA_FAILED, user)
            return Response({"detail": "Código MFA inválido."}, status=400)
        user.mfa_enabled = True
        user.save(update_fields=["mfa_enabled", "updated_at"])
        request.session.pop("pre_mfa_user_id", None)
        request.session.pop("pre_mfa_password_at", None)
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
        user = User.objects.filter(email__iexact=email, is_active=True).first()
        if user and settings.SMTP_URL:
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            link = f"{settings.KAIROS_BASE_URL}/app/redefinir-senha?uid={uid}&token={token}"
            send_mail("Redefinição de senha do Kairós", f"Use este link uma única vez: {link}", settings.DEFAULT_FROM_EMAIL, [user.email])
            record_audit("auth.password_reset.requested", actor=user, request=request, target=user)
        return Response({"detail": "Se a conta existir e o e-mail estiver configurado, as instruções serão enviadas."}, status=202)


class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            user = User.objects.get(pk=force_str(urlsafe_base64_decode(request.data.get("uid", ""))))
        except (User.DoesNotExist, ValueError, TypeError, OverflowError):
            return Response({"detail": "Token inválido."}, status=400)
        token = str(request.data.get("token", ""))
        password = str(request.data.get("new_password", ""))
        if not default_token_generator.check_token(user, token):
            return Response({"detail": "Token inválido ou expirado."}, status=400)
        validate_password(password, user=user)
        user.set_password(password)
        user.session_version += 1
        user.save(update_fields=["password", "session_version", "updated_at"])
        UserSession.objects.filter(user=user, revoked_at__isnull=True).update(revoked_at=timezone.now())
        record_audit("auth.password_reset.completed", actor=user, request=request, target=user)
        return Response(status=204)


class MeView(APIView):
    def get(self, request):
        return Response(UserSerializer(request.user).data)

    def patch(self, request):
        serializer = UserSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        record_audit("user.profile.updated", actor=request.user, request=request, target=request.user)
        return Response(serializer.data)


class OwnedViewSet(viewsets.ModelViewSet):
    permission_classes = [CanStudy]

    def get_queryset(self):
        return self.queryset.filter(owner=self.request.user)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    def perform_destroy(self, instance):
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
    queryset = Content.objects.filter(status=Content.Status.PUBLISHED).select_related("current_version")
    serializer_class = ContentSerializer


class QuestionViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [CanStudy]
    queryset = Question.objects.filter(current_version__isnull=False).select_related("current_version").prefetch_related("current_version__alternatives")
    serializer_class = QuestionSerializer


class SimulationViewSet(OwnedViewSet):
    queryset = Simulation.objects.all()
    serializer_class = SimulationSerializer


class AttemptViewSet(viewsets.ModelViewSet):
    permission_classes = [CanStudy]
    serializer_class = AttemptSerializer

    def get_queryset(self):
        return Attempt.objects.filter(owner=self.request.user).select_related("simulation").prefetch_related("answers")

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
            expected_version=int(request.data.get("version", 0)),
            answers=list(request.data.get("answers", [])),
            elapsed_seconds=int(request.data.get("elapsed_seconds", 0)),
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

    def get_queryset(self):
        return FileAsset.objects.filter(owner=self.request.user)

    @action(detail=False, methods=["post"])
    def upload(self, request):
        import magic

        upload = request.FILES.get("file")
        if not upload:
            raise ValidationError({"file": "Arquivo obrigatório."})
        if upload.size <= 0 or upload.size > settings.KAIROS_MAX_UPLOAD_BYTES:
            raise ValidationError({"file": "Tamanho de arquivo inválido."})
        first_bytes = upload.read(8192)
        upload.seek(0)
        mime_type = magic.from_buffer(first_bytes, mime=True)
        if mime_type not in settings.KAIROS_ALLOWED_MIME_TYPES:
            raise ValidationError({"file": f"Tipo de conteúdo não permitido: {mime_type}."})
        digest = hashlib.sha256()
        for chunk in upload.chunks():
            digest.update(chunk)
        upload.seek(0)
        asset_id = uuid.uuid4()
        safe_name = Path(upload.name).name[:255]
        extension = Path(safe_name).suffix.lower()
        quarantine_key = f"quarantine/{request.user.id}/{asset_id}{extension}"
        storage_key = f"private/{request.user.id}/{asset_id}{extension}"
        default_storage.save(quarantine_key, upload)
        asset = FileAsset.objects.create(
            id=asset_id,
            owner=request.user,
            original_name=safe_name,
            storage_key=storage_key,
            quarantine_key=quarantine_key,
            mime_type=mime_type,
            size_bytes=upload.size,
            sha256=digest.hexdigest(),
        )
        scan_and_process_file.delay(str(asset.id))
        record_audit("file.uploaded", actor=request.user, request=request, target=asset, metadata={"mime": mime_type, "bytes": upload.size})
        return Response(FileAssetSerializer(asset).data, status=202)

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        asset = self.get_object()
        if asset.scan_status != FileAsset.ScanStatus.CLEAN or not default_storage.exists(asset.storage_key):
            raise PermissionDenied("O arquivo ainda não está liberado.")
        return Response({"url": default_storage.url(asset.storage_key), "expires_in": settings.AWS_QUERYSTRING_EXPIRE})

    def perform_destroy(self, instance):
        for key in (instance.storage_key, instance.quarantine_key, instance.metadata.get("text_key")):
            if key and default_storage.exists(key):
                default_storage.delete(key)
        record_audit("file.deleted", actor=self.request.user, request=self.request, target=instance)
        instance.delete()


class ConversationViewSet(OwnedViewSet):
    queryset = Conversation.objects.all()
    serializer_class = ConversationSerializer


class ConsultView(APIView):
    permission_classes = [IsAuthenticated, HasKairosPermission]
    permission_codename = "ai.use"

    def post(self, request):
        context = dict(request.data.get("context", {}))
        attempt_id = context.get("attempt_id")
        if attempt_id:
            attempt = Attempt.objects.select_related("simulation").get(pk=attempt_id, owner=request.user)
            if attempt.status == Attempt.Status.ACTIVE and attempt.simulation.mode == Simulation.Mode.FORMAL:
                raise PermissionDenied("O assistente permanece bloqueado no simulado formal até a submissão.")
            if attempt.status == Attempt.Status.ACTIVE and attempt.simulation.mode == Simulation.Mode.TRAINING and request.data.get("action") not in {"hint", "add_to_review"}:
                raise PermissionDenied("Durante o treino ativo, somente pistas e revisão são permitidas.")
        conversation = None
        if request.data.get("conversation_id"):
            conversation = Conversation.objects.get(pk=request.data["conversation_id"], owner=request.user)
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
    permission_classes = [CanUpdateCorpus]
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
