# Final Verification B — independent

Status: `PASS_WITH_DOCUMENTED_LIMITATIONS`

Reviewed revision: `398be40913b3469c5960bf5f736497c93672d200`

Operational revision: `d4478cf202cb4e3328c8f08b86b3a12a1322d50b`

Completed: 2026-08-28 UTC

Mode: independent, read-only, assuming Verification A could be wrong

## Verdict

No critical or high-severity finding was identified. The primary deployment is consistent and healthy, but it must not be represented as fully operational because the legal assistant and the external dependencies listed below remain unavailable.

## Independent evidence

- Local repository, `origin/main`, and VPS were clean at the reviewed revision. The only delta from the operational revision was the Verification A report.
- SSH passed. Nginx was active with valid configuration, and ports 80, 443, and the Kairós-only 4080 listener were present.
- From the VPS, the HTTPS home and login returned 200; WordPress and Django administrative routes redirected correctly; the legacy port redirected to canonical HTTPS.
- The certificate is valid until 2026-11-25 and HSTS is `max-age=31536000`.
- All 18 Compose services were present. Continuous services were running, health-checked services were healthy, and one-shot services had successful exits.
- Only `kairos-edge-1` published a port. The data, AI, and MCP networks were internal.
- The application administrator was active, staff/superuser, MFA-enabled, and not locked. The owner-facing name was `Vinícius`, and automated coverage included the accented application identifier.
- WordPress was canonical on HTTPS, retained nine primary-menu items, and routed “Entrar” to `/app/entrar`.
- The latest health report had all probes passing, Celery queue depth zero, failed ingestions zero, and alert count zero.
- Unexpected critical-log matches were zero. Two Hermes context errors matched the documented compatibility limitation.
- The real legal corpus remained empty. The policy code returned zero confidence and no citations before model invocation when no evidence existed.
- The newest local encrypted backup existed with mode `0600` and valid checksum. Health and backup timers were enabled and active.
- Initial public connection refusals were isolated to the reviewer's local probe network. SSH and probes originating on the VPS confirmed the public HTTPS service with HTTP 200.

## Findings and limitations

- **Medium, high confidence — legal assistant unavailable:** Hermes requires a minimum 64k context. The hardware-safe Qwen3 1.7B model supports 32k natively and is deployed at 8,192. The Hermes container health endpoint does not mean the assistant is functionally available; Kairós correctly fails closed instead.
- **Medium, high confidence — external dependencies:** SMTP, approved legal sources, DataJud/INLABS credentials, and off-host backup storage are absent. External password-reset delivery, real legal ingestion, and recovery after total VPS loss are not operational.
- **Low, high confidence — WordPress identifier:** the WordPress technical login is `vinicius`, with `Vinícius` as the display name. The accented application-login alias does not change the WordPress technical username.
- **Independent-evidence gap:** restore verification and the no-touch comparator were not rerun in B because they create temporary artifacts and B was explicitly read-only. B verified the existing backups, health data, snapshots, and recorded A results; A had already passed isolated restore and `PREEXISTING_RESOURCES_MODIFIED=0`.

Any later implementation or deployment change invalidates this result and requires both final verifications to restart.
