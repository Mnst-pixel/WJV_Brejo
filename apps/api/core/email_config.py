from urllib.parse import unquote, urlsplit


def smtp_configuration(value):
    if not value:
        return {"EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend"}
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"smtp", "smtp+tls", "smtps"} or not parsed.hostname or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
            raise ValueError
        return {"EMAIL_BACKEND": "django.core.mail.backends.smtp.EmailBackend", "EMAIL_HOST": parsed.hostname,
                "EMAIL_PORT": parsed.port or (465 if parsed.scheme == "smtps" else 587),
                "EMAIL_HOST_USER": unquote(parsed.username or ""), "EMAIL_HOST_PASSWORD": unquote(parsed.password or ""),
                "EMAIL_USE_TLS": parsed.scheme == "smtp+tls", "EMAIL_USE_SSL": parsed.scheme == "smtps", "EMAIL_TIMEOUT": 10}
    except (ValueError, TypeError):
        raise ValueError("Invalid SMTP configuration") from None
