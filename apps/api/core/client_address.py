from ipaddress import ip_address

from django.conf import settings
from django.utils.crypto import constant_time_compare


def client_address(request):
    """Only consume the single address overwritten by the private Kairós edge."""
    if request is None:
        return None
    values = []
    proof = getattr(settings, "KAIROS_PROXY_TOKEN", "")
    if (
        getattr(settings, "KAIROS_TRUST_PROXY_HEADERS", False)
        and len(proof) >= 32
        and constant_time_compare(request.META.get("HTTP_X_KAIROS_PROXY", ""), proof)
    ):
        values.append(request.META.get("HTTP_X_REAL_IP", ""))
    values.append(request.META.get("REMOTE_ADDR", ""))
    for value in values:
        try:
            return str(ip_address(value))
        except ValueError:
            continue
    return None
