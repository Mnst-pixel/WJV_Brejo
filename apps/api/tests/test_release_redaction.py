from django.test import override_settings

from core.services.ai_policy import redact


@override_settings(KAIROS_PROXY_TOKEN="p" * 48, KAIROS_MCP_DELEGATION_KEY="d" * 48,
                   KAIROS_MCP_PRINCIPALS={"tool-client": {"token": "t" * 48}})
def test_new_service_proofs_are_redacted_from_untrusted_text():
    value = " ".join(letter * 48 for letter in "pdt")
    assert redact(value) == "[REDACTED] [REDACTED] [REDACTED]"
