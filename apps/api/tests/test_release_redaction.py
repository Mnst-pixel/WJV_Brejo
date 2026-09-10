from django.test import override_settings

from core.services.ai_policy import redact


@override_settings(KAIROS_PROXY_TOKEN="p" * 48, KAIROS_MCP_DELEGATION_KEY="d" * 48,
                   KAIROS_MCP_PRINCIPALS={"tool-client": {"token": "t" * 48}})
def test_new_service_proofs_are_redacted_from_untrusted_text():
    value = " ".join(letter * 48 for letter in "pdt")
    assert redact(value) == "[REDACTED] [REDACTED] [REDACTED]"


@override_settings(KAIROS_WORDPRESS_GATE_KEY="wordpress-signing-fixture-key",
                   DATABASES={"default": {"PASSWORD": "database-fixture-password"}},
                   REDIS_URL="redis://cache:cache%2Ffixture%2Fpassword@redis:6379/0",
                   CELERY_BROKER_URL="redis://broker:broker-fixture-password@redis:6379/1",
                   EMAIL_HOST_PASSWORD="smtp-fixture-password")
def test_scoped_runtime_credentials_are_removed_even_without_assignment_labels():
    values = ["wordpress-signing-fixture-key", "database-fixture-password", "cache/fixture/password",
              "cache%2Ffixture%2Fpassword", "broker-fixture-password", "smtp-fixture-password"]
    assert redact(" | ".join(values)) == " | ".join(["[REDACTED]"] * len(values))
