from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.contrib.auth import logout
from django.core.cache import cache
from django.utils import timezone
from django.utils.crypto import constant_time_compare
import pyotp
from rest_framework.exceptions import APIException, PermissionDenied, Throttled

from .models import User
from .permissions import user_requires_mfa


class MFAUnavailable(APIException):
    status_code = 503
    default_code = "mfa_unavailable"
    default_detail = "Não foi possível verificar o segundo fator. Tente novamente em instantes."


def clear_enrollment(request):
    for key in ("mfa_enrollment", "pre_mfa_user_id", "pre_mfa_password_at"):
        request.session.pop(key, None)


def begin_enrollment(request, user):
    # A new password proof replaces the previous session/challenge. Pending keys
    # never replace the active second factor until verification succeeds.
    logout(request)
    request.session["mfa_enrollment"] = {
        "user_id": str(user.pk),
        "auth_hash": user.get_session_auth_hash(),
        "session_version": user.session_version,
        "issued_at": timezone.now().timestamp(),
        "secret": encrypt_secret(pyotp.random_base32()),
    }


def enrollment_user(request, *, lock=False):
    pending = request.session.get("mfa_enrollment")
    user = None
    if isinstance(pending, dict):
        query = User.objects.select_for_update() if lock else User.objects
        user = query.filter(pk=pending.get("user_id"), is_active=True).first()
    try:
        age = timezone.now().timestamp() - pending["issued_at"]
        valid = (
            user is not None
            and user_requires_mfa(user)
            and not user.mfa_enabled
            and 0 <= age < settings.KAIROS_MFA_ENROLLMENT_TTL_SECONDS
            and pending["session_version"] == user.session_version
            and constant_time_compare(pending["auth_hash"], user.get_session_auth_hash())
            and bool(pending["secret"])
        )
    except (KeyError, TypeError, ValueError):
        valid = False
    if not valid:
        clear_enrollment(request)
        raise PermissionDenied("Configuração MFA expirada ou inválida. Entre novamente com sua senha.")
    return user, pending


def _fernet() -> Fernet:
    if not settings.MFA_ENCRYPTION_KEY:
        raise RuntimeError("MFA_ENCRYPTION_KEY is required")
    return Fernet(settings.MFA_ENCRYPTION_KEY.encode())


def encrypt_secret(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()


def decrypt_secret(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise RuntimeError("Unable to decrypt MFA secret") from exc


def verify_totp(user, code: str, *, encrypted_secret=None) -> bool:
    # A fixed window in the key bounds a lockout even if Redis expires a key
    # between the backend's EXISTS and INCR. Retain it beyond the window to
    # avoid that boundary race normally. A new enrollment keeps the budget.
    window = int(timezone.now().timestamp()) // settings.KAIROS_MFA_WINDOW_SECONDS
    budget_key = f"kairos:mfa:attempts:{user.pk}:{window}"
    try:
        cache.add(budget_key, 0, timeout=settings.KAIROS_MFA_WINDOW_SECONDS * 2)
        attempts = cache.incr(budget_key)
    except Exception as exc:
        raise MFAUnavailable() from exc
    if attempts > settings.KAIROS_MFA_MAX_ATTEMPTS:
        raise Throttled(wait=settings.KAIROS_MFA_WINDOW_SECONDS, detail="Muitas tentativas de segundo fator.")

    token = user.mfa_secret_encrypted if encrypted_secret is None else encrypted_secret
    if not token or len(code) != 6 or not code.isascii() or not code.isdigit():
        return False
    totp = pyotp.TOTP(decrypt_secret(token))
    current_step = int(timezone.now().timestamp()) // totp.interval
    for step in (current_step, current_step - 1, current_step + 1):
        if constant_time_compare(code, totp.at(step * totp.interval)):
            try:
                unused = cache.add(f"kairos:mfa:used:{user.pk}:{step}", True, timeout=totp.interval * 3)
                if unused:
                    cache.delete(budget_key)
            except Exception as exc:
                raise MFAUnavailable() from exc
            return unused
    return False


def provisioning_uri(user, secret: str) -> str:
    label = user.email or user.username
    return pyotp.TOTP(secret).provisioning_uri(name=label, issuer_name="Kairós")
