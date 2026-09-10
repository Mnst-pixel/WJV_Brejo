import pytest
from django.test import RequestFactory, override_settings

from core.client_address import client_address


@pytest.mark.parametrize("spoof", ["1.2.3.4", "invalid", "1.2.3.4, 5.6.7.8"])
def test_untrusted_forwarding_does_not_control_audit_address(spoof):
    request = RequestFactory().get("/", REMOTE_ADDR="192.0.2.20", HTTP_X_FORWARDED_FOR=spoof, HTTP_X_REAL_IP=spoof)
    with override_settings(KAIROS_TRUST_PROXY_HEADERS=False):
        assert client_address(request) == "192.0.2.20"


@override_settings(KAIROS_TRUST_PROXY_HEADERS=True, KAIROS_PROXY_TOKEN="p" * 48)
def test_private_edge_header_and_invalid_fallback():
    request = RequestFactory().get("/", REMOTE_ADDR="192.0.2.20", HTTP_X_FORWARDED_FOR="spoof", HTTP_X_REAL_IP="2001:db8::1", HTTP_X_KAIROS_PROXY="p" * 48)
    assert client_address(request) == "2001:db8::1"
    request.META["HTTP_X_REAL_IP"] = "invalid"
    assert client_address(request) == "192.0.2.20"


@pytest.mark.parametrize("token", ["", "x" * 48])
@override_settings(KAIROS_TRUST_PROXY_HEADERS=True, KAIROS_PROXY_TOKEN="p" * 48)
def test_internal_service_cannot_spoof_edge_identity(token):
    request = RequestFactory().get("/", REMOTE_ADDR="192.0.2.20", HTTP_X_REAL_IP="1.2.3.4", HTTP_X_KAIROS_PROXY=token)
    assert client_address(request) == "192.0.2.20"
