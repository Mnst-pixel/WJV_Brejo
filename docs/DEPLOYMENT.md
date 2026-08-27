# Deployment

Deployment is intentionally gated.

1. Capture a fresh read-only snapshot with `scripts/vps-snapshot.sh` and verify the target host and free port.
2. Verify artifact hashes and the repository secret scan.
3. Create only `/opt/kairos` and `/srv/kairos` subdirectories with restrictive ownership.
4. Generate independent service credentials into `/opt/kairos/secrets/.env` with mode `0600`.
5. Build Kairós-owned images under `COMPOSE_PROJECT_NAME=kairos`.
6. Validate the rendered Compose model and resource names before starting anything.
7. Start data services, run health checks and migrations, then start application, WordPress, MCP, AI, and edge tiers in dependency order.
8. Bootstrap the two human administrator identities without printing their passwords.
9. Run smoke, persistence, authorization, upload, RAG, MCP, AI, backup, and restore checks.
10. Capture the post-deploy snapshot and run the no-touch comparator.
11. Run Verification A and independent Verification B from the beginning.

The host Nginx and firewall are out of scope and must not be edited or reloaded. Because 80/443 are occupied, Kairós uses a documented alternative port until a domain and explicit cutover authorization exist.

