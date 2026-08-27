from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
import pyotp


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


def verify_totp(user, code: str) -> bool:
    if not user.mfa_secret_encrypted or not code:
        return False
    return pyotp.TOTP(decrypt_secret(user.mfa_secret_encrypted)).verify(code, valid_window=1)


def provisioning_uri(user, secret: str) -> str:
    label = user.email or user.username
    return pyotp.TOTP(secret).provisioning_uri(name=label, issuer_name="Kairós")
