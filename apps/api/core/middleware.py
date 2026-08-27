from contextvars import ContextVar

from django.http import JsonResponse
from django.contrib.auth import logout

current_request = ContextVar("current_request", default=None)


class AuditContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = current_request.set(request)
        try:
            return self.get_response(request)
        finally:
            current_request.reset(token)


class SessionVersionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            authenticated_version = request.session.get("user_session_version")
            if authenticated_version != request.user.session_version:
                logout(request)
                return JsonResponse({"error": {"code": "session_revoked", "detail": "Sessão revogada."}}, status=401)
        return self.get_response(request)


class AdminMFAMiddleware:
    """Prevent Django admin from becoming a password-only MFA bypass."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith("/admin/") and request.user.is_authenticated and request.user.is_staff:
            if not request.session.get("mfa_verified"):
                return JsonResponse({"error": {"code": "admin_mfa_required", "detail": "Use the Kairós sign-in flow to verify MFA."}}, status=403)
        return self.get_response(request)
