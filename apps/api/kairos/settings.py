import os
from pathlib import Path
from urllib.parse import quote, urlparse

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
DEBUG = env_bool("KAIROS_DEBUG")
ALLOWED_HOSTS = env_list("KAIROS_ALLOWED_HOSTS", "localhost,127.0.0.1")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "storages",
    "pgvector.django",
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.middleware.SessionVersionMiddleware",
    "core.middleware.AuditContextMiddleware",
    "core.middleware.AdminMFAMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "kairos.urls"
WSGI_APPLICATION = "kairos.wsgi.application"
ASGI_APPLICATION = "kairos.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_DB", "kairos"),
        "USER": os.getenv("POSTGRES_USER", "kairos_app"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
        "HOST": os.getenv("POSTGRES_HOST", "postgres"),
        "PORT": os.getenv("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": 60,
        "OPTIONS": {"sslmode": os.getenv("POSTGRES_SSLMODE", "prefer")},
    }
}

AUTH_USER_MODEL = "core.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "core.storage.PrivateS3Storage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
AWS_S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL", "http://minio:9000")
AWS_STORAGE_BUCKET_NAME = os.getenv("S3_BUCKET_NAME", "documents")
AWS_ACCESS_KEY_ID = os.getenv("MINIO_APP_USER", "")
AWS_SECRET_ACCESS_KEY = os.getenv("MINIO_APP_PASSWORD", "")
AWS_S3_ADDRESSING_STYLE = "path"
AWS_DEFAULT_ACL = None
AWS_QUERYSTRING_AUTH = True
AWS_QUERYSTRING_EXPIRE = 300
AWS_S3_FILE_OVERWRITE = False

TLS_ENABLED = env_bool("KAIROS_TLS_ENABLED")
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = TLS_ENABLED
SESSION_COOKIE_AGE = 43200
SESSION_SAVE_EVERY_REQUEST = True
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = TLS_ENABLED
CSRF_TRUSTED_ORIGINS = env_list("KAIROS_CSRF_TRUSTED_ORIGINS")
CORS_ALLOWED_ORIGINS = env_list("KAIROS_CORS_ORIGINS")
CORS_ALLOW_CREDENTIALS = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
X_FRAME_OPTIONS = "DENY"
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = 31536000 if TLS_ENABLED else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = TLS_ENABLED

redis_password = quote(os.getenv("REDIS_PASSWORD", ""), safe="")
redis_host = os.getenv("REDIS_HOST", "redis")
redis_port = os.getenv("REDIS_PORT", "6379")
REDIS_URL = f"redis://:{redis_password}@{redis_host}:{redis_port}/0"
CACHES = {"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": REDIS_URL}}
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_TASK_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_RESULT_SERIALIZER = "json"
CELERY_TASK_TIME_LIMIT = 300
CELERY_TASK_SOFT_TIME_LIMIT = 270
CELERY_WORKER_MAX_TASKS_PER_CHILD = 50

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 25,
    "EXCEPTION_HANDLER": "core.exceptions.api_exception_handler",
}

DATA_UPLOAD_MAX_MEMORY_SIZE = 25 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
KAIROS_MAX_UPLOAD_BYTES = int(os.getenv("KAIROS_MAX_UPLOAD_BYTES", 25 * 1024 * 1024))
KAIROS_ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "image/jpeg",
    "image/png",
    "text/plain",
}
CLAMAV_HOST = os.getenv("CLAMAV_HOST", "clamav")
CLAMAV_PORT = int(os.getenv("CLAMAV_PORT", "3310"))
MFA_ENCRYPTION_KEY = os.getenv("MFA_ENCRYPTION_KEY", "")
HERMES_BASE_URL = os.getenv("HERMES_BASE_URL", "http://hermes:8642")
HERMES_BEARER_TOKEN = os.getenv("HERMES_BEARER_TOKEN", "")
LOCALAI_BASE_URL = os.getenv("LOCALAI_BASE_URL", "http://localai:8080")
LOCALAI_API_KEY = os.getenv("LOCALAI_API_KEY", "")
LOCALAI_EMBEDDING_MODEL = os.getenv("LOCALAI_EMBEDDING_MODEL", "multilingual-e5-small")
MCP_GATEWAY_URL = os.getenv("MCP_GATEWAY_URL", "http://mcp-gateway:3000")
MCP_API_KEY = os.getenv("MCP_API_KEY", "")

SMTP_URL = os.getenv("SMTP_URL", "")
if SMTP_URL:
    smtp = urlparse(SMTP_URL)
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = smtp.hostname
    EMAIL_PORT = smtp.port or 587
    EMAIL_HOST_USER = smtp.username or ""
    EMAIL_HOST_PASSWORD = smtp.password or ""
    EMAIL_USE_TLS = smtp.scheme in {"smtp+tls", "smtps"}
    EMAIL_USE_SSL = smtp.scheme == "smtps"
else:
    EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "Kairós <no-reply@kairos.invalid>")
KAIROS_BASE_URL = os.getenv("KAIROS_BASE_URL", "http://localhost:4080")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"json": {"format": '{{"time":"{asctime}","level":"{levelname}","logger":"{name}","message":"{message}"}}', "style": "{"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "json"}},
    "root": {"handlers": ["console"], "level": os.getenv("KAIROS_LOG_LEVEL", "INFO")},
}
