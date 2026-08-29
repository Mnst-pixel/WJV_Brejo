# Deployment

Deployment is intentionally gated.

1. Capture a fresh read-only snapshot with `scripts/vps-snapshot.sh` and verify the target host and free port.
2. Verify artifact hashes and the repository secret scan.
3. Create only `/opt/kairos` and `/srv/kairos` subdirectories with restrictive ownership.
4. Generate independent service credentials into `/opt/kairos/secrets/.env` with mode `0600`.
5. Build Kairós-owned images under `COMPOSE_PROJECT_NAME=kairos`.
6. Validate the rendered Compose model and resource names before starting anything.
7. Start data services, run health checks and migrations, then start application, WordPress, MCP, AI, and edge tiers in dependency order.
8. Provision every owner-approved human administrator in both the Kairós application and WordPress without printing or committing passwords. Application administrators must enroll their own MFA factor before administrative access.
9. Run smoke, persistence, authorization, upload, RAG, MCP, AI, backup, and restore checks.
10. Capture the post-deploy snapshot and run the no-touch comparator.
11. Run one encrypted backup, run its isolated restore verification, and run `scripts/health-report.sh` manually.
12. Install and enable only `kairos-backup.timer` and `kairos-health.timer` after those manual checks pass.
13. Confirm both timer unit names, next run times, and the latest health report without modifying any unrelated unit.
14. Run Verification A and independent Verification B from the beginning.

The owner explicitly authorized the public integration. The host Nginx contains one isolated Kairós virtual host for `kairos.2-24-215-183.sslip.io`, proxying to the Kairós-only port 4080 with TLS managed by Certbot. Existing virtual hosts and firewall rules remain out of scope and must not be changed. Direct legacy access on port 4080 redirects application traffic to the canonical HTTPS hostname; `/healthz` remains locally probeable.
