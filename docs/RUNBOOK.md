# Operations runbook

## Daily checks

- Confirm every Kairós health endpoint and container state.
- Confirm disk, memory, swap, queue depth, database availability, and backup status.
- Confirm that no legal-ingestion job bypassed human review.
- Review authentication lockouts, administrative actions, AI tool invocations, and failed uploads.

## Safe restart

Operate only from `/opt/kairos/repo/infra/compose` with `COMPOSE_PROJECT_NAME=kairos`. Name the exact Kairós service. Never use system-wide Docker restart, daemon restart, prune, or host service commands.

## Incidents

If resource pressure threatens unrelated workloads, stop only the responsible Kairós AI service first. Learning functions are designed to degrade safely. Preserve logs and audit records before remediation.

If the no-touch comparator reports a pre-existing resource change, halt acceptance, remove only the Kairós-introduced change, investigate, and invalidate both final verifications.

