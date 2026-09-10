"""Separate fixed-window budgets for private-file routes; fail closed on Redis loss."""
import time

from django.core.cache import cache
from rest_framework.exceptions import APIException, Throttled
from rest_framework.throttling import BaseThrottle


class FileServiceUnavailable(APIException):
    status_code = 503
    default_code = "file_service_unavailable"
    default_detail = "Arquivos temporariamente indisponíveis. Tente novamente em instantes."


class PrivateFileThrottle(BaseThrottle):
    LIMITS = {"upload": (12, 120), "download": (30, 120), "metadata": (300, 1200)}

    def allow_request(self, request, view):
        if not request.user.is_authenticated:
            return False
        kind = "upload" if view.action == "upload" else "download" if view.action == "content" else "metadata"
        bucket = int(time.time()) // 60
        for scope, maximum in zip((str(request.user.pk), "global"), self.LIMITS[kind], strict=True):
            key = f"kairos:files:{kind}:{scope}:{bucket}"
            try:
                cache.add(key, 0, timeout=120)
                count = cache.incr(key)
            except Exception:
                raise FileServiceUnavailable() from None
            if count > maximum:
                raise Throttled(wait=60, detail="Limite temporário de operações com arquivos atingido.")
        return True
