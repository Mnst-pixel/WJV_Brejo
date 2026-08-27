# Operations runbook

## Daily checks

- Confirm every Kairós health endpoint and container state.
- Confirm disk, memory, swap, queue depth, database availability, and backup status.
- Confirm that no legal-ingestion job bypassed human review.
- Review authentication lockouts, administrative actions, AI tool invocations, and failed uploads.

## Safe restart

Operate only from `/opt/kairos/current/infra/compose` with project name `kairos`. Name the exact Kairós service. Never use system-wide Docker restart, daemon restart, prune, or host service commands.

## Incidents

If resource pressure threatens unrelated workloads, stop only the responsible Kairós AI service first. Learning functions are designed to degrade safely. Preserve logs and audit records before remediation.


## Automated health report

`kairos-health.timer` runs every five minutes and writes the current result to `/srv/kairos/observability/latest.status`, with 30 days of timestamped reports. It checks all Kairós container states, health, restarts and OOM events; host memory and disk; per-container CPU/RAM/PIDs; the edge, API, web, WordPress, PostgreSQL, Redis, MariaDB, MinIO and Celery worker; queue depth; failed corpus updates; and backup freshness/result.

Any failed probe, service outage, OOM, suspected crash loop, disk use at or above 85%, queue depth at or above 100, failed corpus update in the last 24 hours, or missing/stale/failed backup makes the unit fail and records a precise `alert.*` line. Inspect with:

- `systemctl status kairos-health.service`
- `journalctl -u kairos-health.service --since today`
- `sed -n '1,240p' /srv/kairos/observability/latest.status`
If the no-touch comparator reports a pre-existing resource change, halt acceptance, remove only the Kairós-introduced change, investigate, and invalidate both final verifications.

