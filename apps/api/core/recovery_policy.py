"""Shared delivery limits with opaque identifiers and fail-closed cache handling."""
from django.core.cache import cache
from django.utils.crypto import salted_hmac

from core.client_address import client_address


def allow_recovery_delivery(request, email):
    email_key = "kairos:recovery:email:" + salted_hmac("recovery-email", email.strip().lower()).hexdigest()
    ip_key = "kairos:recovery:ip:" + salted_hmac("recovery-ip", client_address(request) or "unknown").hexdigest()
    try:
        cache.add(ip_key, 0, timeout=900)
        if cache.incr(ip_key) > 15:
            return False
        return cache.add(email_key, 1, timeout=60)
    except Exception:
        # A failed limiter must not send unlimited email or expose provider errors.
        return False
