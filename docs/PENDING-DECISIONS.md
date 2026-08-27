# Pending external decisions

| Dependency | Status | Impact | Completion path |
|---|---|---|---|
| Domain/FQDN and DNS | `BLOCKED_EXTERNAL_DEPENDENCY` | No definitive hostname or public TLS endpoint; temporary alternative port only. | Owner supplies hostname and DNS, then explicitly authorizes cutover/integration. |
| Existing Nginx integration | `BLOCKED_EXTERNAL_DEPENDENCY` | Kairós cannot use 80/443 without touching an existing proxy. | Owner authorizes a separately reviewed cutover; never inferred. |
| Elementor Pro license | `BLOCKED_EXTERNAL_DEPENDENCY` | Pro-only Popup/Theme Builder features cannot be enabled. | Owner supplies a valid license or approves a documented legitimate alternative. |
| INLABS credentials | `BLOCKED_EXTERNAL_DEPENDENCY` | INLABS remains disabled and cannot be reported operational. | Owner provides `INLABS_EMAIL` and `INLABS_PASSWORD` securely. |
| SMTP | `BLOCKED_EXTERNAL_DEPENDENCY` | Email password reset/notifications cannot be delivered externally. | Owner supplies SMTP endpoint and credential securely. |
| Off-host backup storage | `BLOCKED_EXTERNAL_DEPENDENCY` | Local backups do not survive total VPS loss. | Owner supplies S3-compatible or other external storage and retention policy. |
| MCP package redistribution rights | `BLOCKED_EXTERNAL_DEPENDENCY` | Supplied unlicensed source is not committed to the public repository. | Owner confirms ownership/right to publish or supplies a license. |
| DataJud current credential | `BLOCKED_EXTERNAL_DEPENDENCY` | DataJud cannot be declared operational until an official current key is validated. | Obtain and validate through the official source. |
| Human administrative email | `BLOCKED_EXTERNAL_DEPENDENCY` | Password reset and MFA recovery for the bootstrap administrator remain incomplete. | Owner supplies the intended administrative email securely. |

