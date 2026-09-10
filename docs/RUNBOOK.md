# Operations runbook

## Daily checks

- Confirm every Kairós health endpoint and container state.
- Confirm disk, memory, swap, queue depth, database availability, and backup status.
- Confirm that no legal-ingestion job bypassed human review.
- Review authentication lockouts, administrative actions, AI tool invocations, and failed uploads.

## Safe restart

After canonical release activation, operate through `scripts/kairos-compose.py` with project `kairos`, a verified descriptor and explicit service names. Never execute historical Compose alone: it can recreate an older API or bootstrap. Until that activation, preserve the effective image/override documented in [P0-P2-ENTREGA.md](P0-P2-ENTREGA.md); restarting an existing identified container is different from recreating it from the historical checkout. Never use system-wide Docker restart, daemon restart, prune, or host service commands.

The September 10 candidate has not changed live timers yet. New backup/health behavior documented in this branch must first pass its manual isolated verification. `configured_unverified` and `unconfigured` integration states are not service readiness. Missing external credentials belong in the external-blocker register, not in a fabricated successful health result.

## Incidents

If resource pressure threatens unrelated workloads, stop only the responsible Kairós AI service first. Learning functions are designed to degrade safely. Preserve logs and audit records before remediation.


## Automated health report

`kairos-health.timer` runs every five minutes and writes the current result to `/srv/kairos/observability/latest.status`, with 30 days of timestamped reports. It checks all Kairós container states, health, restarts and OOM events; host memory and disk; per-container CPU/RAM/PIDs; the edge, API, web, WordPress, PostgreSQL, Redis, MariaDB, MinIO and Celery worker; queue depth; failed corpus updates; and backup freshness/result.

Any failed probe, service outage, OOM, suspected crash loop, disk use at or above 85%, queue depth at or above 100, failed corpus update in the last 24 hours, or missing/stale/failed backup makes the unit fail and records a precise `alert.*` line. Inspect with:

- `systemctl status kairos-health.service`
- `journalctl -u kairos-health.service --since today`
- `sed -n '1,240p' /srv/kairos/observability/latest.status`
If the no-touch comparator reports a pre-existing resource change, halt acceptance, remove only the Kairós-introduced change, investigate, and invalidate both final verifications.
