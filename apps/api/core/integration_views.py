from django.conf import settings
from rest_framework.response import Response
from rest_framework.views import APIView

from .permissions import CanStudy


class IntegrationStatusView(APIView):
    permission_classes = [CanStudy]

    def get(self, request):
        configured = {"smtp": bool(settings.SMTP_URL), "inlabs": getattr(settings, "KAIROS_INLABS_CONFIGURED", False),
                      "datajud": getattr(settings, "KAIROS_DATAJUD_CONFIGURED", False), "offhost": getattr(settings, "KAIROS_OFFHOST_CONFIGURED", False)}
        return Response({key: {"state": "configured_unverified" if value else "unconfigured", "external_blocker": not value}
                         for key, value in configured.items()}, headers={"Cache-Control": "private, no-store"})
