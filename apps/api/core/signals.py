from django.contrib.auth.signals import user_logged_out
from django.dispatch import receiver

from .audit import record_audit


@receiver(user_logged_out)
def audit_logout(sender, request, user, **kwargs):
    if user:
        record_audit("auth.logout", actor=user, request=request, target=user)
