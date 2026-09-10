import pytest
from django.test import override_settings

from core.email_config import smtp_configuration


@pytest.mark.parametrize("url,tls,ssl,port", [("smtps://user:synthetic@localhost", False, True, 465), ("smtp+tls://localhost", True, False, 587), ("smtp://localhost:2525", False, False, 2525)])
def test_smtp_transport_modes_are_exclusive(url, tls, ssl, port):
    config = smtp_configuration(url)
    assert config["EMAIL_USE_TLS"] == tls and config["EMAIL_USE_SSL"] == ssl
    assert config["EMAIL_PORT"] == port and config["EMAIL_TIMEOUT"] == 10


def test_unconfigured_smtp_and_invalid_url():
    assert smtp_configuration("")["EMAIL_BACKEND"].endswith("locmem.EmailBackend")
    with pytest.raises(ValueError, match="Invalid SMTP configuration"):
        smtp_configuration("https://user:synthetic@localhost")


@pytest.mark.django_db
@override_settings(SMTP_URL="smtp+tls://user:synthetic-hidden@localhost")
def test_status_has_no_secrets_and_never_claims_external_operation(student, client_for):
    response = client_for(student).get("/api/integrations/status/")
    assert response.status_code == 200
    assert response.json()["smtp"]["state"] == "configured_unverified"
    assert response.json()["offhost"]["external_blocker"] is True
    assert b"synthetic-hidden" not in response.content
    assert response["Cache-Control"] == "private, no-store"
