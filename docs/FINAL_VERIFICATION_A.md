# Final Verification A — implementation

Status: `PASS_WITH_DOCUMENTED_EXTERNAL_AND_HARDWARE_LIMITATIONS`

Reviewed revision: `6d509d25a7022fbcf481da5cdecfb9e83904966d`

Operational revision: `d4478cf202cb4e3328c8f08b86b3a12a1322d50b`

Completed: 2026-08-29 UTC (2026-08-28 America/Sao_Paulo)

Scope: administrator identity provisioning on the unchanged operational revision

## Evidence

- Repository, `origin/main`, and VPS were synchronized at the reviewed revision before this documentation-only update. Both worktrees were clean.
- API: Ruff passed without cache, and all 15 pytest cases passed in an ephemeral verification container using a non-production test key. The six warnings only reported the intentionally absent static directory on the read-only verification mount.
- Web: ESLint passed with zero warnings, TypeScript passed, and the Next.js 16.3.3 production build completed.
- All 18 Compose services were accounted for. Continuous services were running, health-checked services were healthy, one-shot bootstrap services had successful exits, restart counts were zero, and no Kairós container was OOM-killed.
- Only `kairos-edge-1` published a host port. Data, AI, and MCP networks remained Docker-internal.
- WordPress, the app login, WordPress admin, and Django admin responded on the canonical HTTPS hostname. HSTS, secure CSRF cookies, a certificate valid for more than 30 days, Certbot scheduling, valid Nginx configuration, and the legacy HTTP/IP redirect all passed.
- The application has three active, unlocked staff/superuser accounts with the `superadministrador` role: `vinicius`, `joao_ribeiro`, and `wanderson`. The two new passwords were accepted through the public HTTPS login, which correctly returned `428 mfa_setup_required`; Vinícius retained his already-enabled independent MFA factor.
- WordPress has the same three technical usernames with the `administrator` role. The two new credentials completed real public WordPress authentication and landed on `/wp-admin/` with HTTP 200.
- WordPress retained its canonical HTTPS response and administrative redirect. No page, menu, media, theme, plugin, or visual-setting operation was executed by the identity change.
- RAG, LocalAI, MCP, upload processing, and the accepted desktop/mobile visual state were outside this identity-only scope and were not re-executed. Their earlier evidence belongs to the unchanged operational revision and is not used to prove this administrator change.
- Unexpected critical-log matches were zero in the 90-minute operation window outside the documented Hermes compatibility limitation.
- The final encrypted backup `kairos-20260829T005804Z.tar.gz.enc` passed checksum and isolated restore verification for PostgreSQL, MariaDB, MinIO, WordPress, and Hermes data; temporary restore resources were removed.
- The fresh health report passed with 18 services accounted for, queue depth zero, failed ingestions zero, alert count zero, and the final backup recognized as latest. `kairos-backup.timer` and `kairos-health.timer` remained enabled and active.
- A symmetric before/after comparison around the idempotent administrator reconciliation reported zero changes in containers, container identities, networks, volumes, images, listeners, services, Nginx, Compose, cron, certificates, iptables, ip6tables, and nftables: `ADMIN_CHANGE_WINDOW_MODIFIED_RESOURCES=0`.
- The historical comparison against the original 2026-08-27 pre-deploy baseline detected later changes in unrelated Ortotrópico, Jurisprudêncio Central, and `mcp-brasil` resources. Their recorded start times precede this administrator request. They were not touched or attributed to Kairós, and the historical zero-change result is not inherited by this verification.

## Documented limitations

- Hermes Agent `v2026.8.19` requires a 64k context window while the hardware-safe Qwen3 1.7B deployment supports 32k natively and is limited to 8,192 tokens on this VPS. The legal assistant remains safely unavailable rather than misrepresenting model capacity or risking other workloads.
- SMTP delivery, off-host backup storage, INLABS/DataJud credentials, approved legal-source adapters/data, and any licensed Elementor Pro capability require owner-supplied external resources.
- Local encrypted backups are operational, but they do not protect against total VPS loss until off-host storage is supplied.

No later implementation or deployment change may inherit this result; such a change requires Verification A to restart from the beginning.
