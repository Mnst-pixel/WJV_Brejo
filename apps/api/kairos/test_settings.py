from .settings import *  # noqa: F403,F401

import os
from pathlib import Path
from tempfile import gettempdir
from uuid import uuid4

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
if os.environ.get("KAIROS_BROWSER_TESTS") == "1":
    # Django shares one connection across live-server threads for in-memory SQLite.
    # A disposable file gives each HTTP thread its own connection; pytest destroys it.
    DATABASES["default"]["TEST"] = {"NAME": str(Path(gettempdir()) / f"kairos-browser-{uuid4().hex}.sqlite3")}
    DATABASES["default"]["NAME"] = DATABASES["default"]["TEST"]["NAME"]
    DATABASES["default"]["OPTIONS"] = {"timeout": 20, "init_command": "PRAGMA journal_mode=WAL;"}
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
CELERY_TASK_ALWAYS_EAGER = True
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
