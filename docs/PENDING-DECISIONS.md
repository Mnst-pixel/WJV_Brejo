# Pending external decisions

| Dependency | Status | Impact | Completion path |
|---|---|---|---|
| Public FQDN and TLS | `COMPLETE` | Kairós is published at `https://kairos.2-24-215-183.sslip.io`; certificate renewal is scheduled. | Replace the sslip.io hostname later only if the owner supplies a managed DNS record. |
| Existing Nginx integration | `COMPLETE_AUTHORIZED` | One isolated Kairós virtual host proxies to port 4080; unrelated virtual hosts were not modified. | Keep changes confined to the Kairós site file. |
| Elementor Pro license | `BLOCKED_EXTERNAL_DEPENDENCY` | Pro-only Popup/Theme Builder features cannot be enabled. | Owner supplies a valid license or approves a documented legitimate alternative. |
| INLABS credentials | `BLOCKED_EXTERNAL_DEPENDENCY` | INLABS remains disabled and cannot be reported operational. | Owner provides `INLABS_EMAIL` and `INLABS_PASSWORD` securely. |
| SMTP | `BLOCKED_EXTERNAL_DEPENDENCY` | Email password reset/notifications cannot be delivered externally. | Owner supplies SMTP endpoint and credential securely. |
| Off-host backup storage | `BLOCKED_EXTERNAL_DEPENDENCY` | Local backups do not survive total VPS loss. | Owner supplies S3-compatible or other external storage and retention policy. |
| MCP package redistribution rights | `BLOCKED_EXTERNAL_DEPENDENCY` | Supplied unlicensed source is not committed to the public repository. | Owner confirms ownership/right to publish or supplies a license. |
| DataJud current credential | `BLOCKED_EXTERNAL_DEPENDENCY` | DataJud cannot be declared operational until an official current key is validated. | Obtain and validate through the official source. |
| Human administrative email | `COMPLETE` | The owner-supplied address is assigned to the bootstrap administrators. | No action unless the owner changes the address. |
| Hermes/model context compatibility | `BLOCKED_HARDWARE_COMPATIBILITY` | Hermes `v2026.8.19` requires 64k context while the hardware-safe Qwen3 1.7B model supports 32k natively. The rest of Kairós remains operational. | Benchmark a hardware-safe 64k+ model or adopt a future official Hermes release with a truthful lower-context mode. |
